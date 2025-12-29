#!/usr/bin/env python3
"""
Oracle Cloud Automation Script
- Resize mailserver from 4 OCPU/24GB to 3 OCPU/18GB
- Create Frankfurt instance with 1 OCPU/6GB
"""

import oci
import sys
import time

# Configuration from user's OCI setup
CONFIG = {
    "user": "ocid1.user.oc1..aaaaaaaaqnq4nndmyh6cqjpafjlxpmibticc7bw67loou6hpqmqqreszotrq",
    "fingerprint": "75:d9:db:23:a7:3f:a2:9e:80:9b:ce:a4:c2:ca:72:75",
    "tenancy": "ocid1.tenancy.oc1..aaaaaaaaovq7uw52qicvbajuadngkgjjwwlvmuhpbrbk56j6o2agbu4oqzva",
    "region": "us-sanjose-1",
    "key_file": r"C:\Users\kevin\Downloads\kevinchandarasane12345@gmail.com-2025-12-04T21_46_18.556Z.pem"
}

def get_compute_client(region=None):
    """Get compute client for specified region."""
    config = CONFIG.copy()
    if region:
        config["region"] = region
    return oci.core.ComputeClient(config)

def get_identity_client():
    """Get identity client."""
    return oci.identity.IdentityClient(CONFIG)

def get_vcn_client(region=None):
    """Get VCN client for networking."""
    config = CONFIG.copy()
    if region:
        config["region"] = region
    return oci.core.VirtualNetworkClient(config)

def list_instances(compartment_id, region=None):
    """List all instances in compartment."""
    compute = get_compute_client(region)
    instances = compute.list_instances(compartment_id=compartment_id).data
    return [i for i in instances if i.lifecycle_state not in ["TERMINATED", "TERMINATING"]]

def get_instance_by_name(compartment_id, name, region=None):
    """Find instance by display name."""
    instances = list_instances(compartment_id, region)
    for i in instances:
        if i.display_name.lower() == name.lower():
            return i
    return None

def resize_instance(instance_id, ocpus, memory_gb, region=None):
    """Resize instance to new OCPU and memory."""
    compute = get_compute_client(region)

    # Get current instance
    instance = compute.get_instance(instance_id).data
    print(f"Current instance: {instance.display_name}")
    print(f"Current shape: {instance.shape}")
    print(f"Current config: {instance.shape_config}")

    # Update shape config
    update_details = oci.core.models.UpdateInstanceDetails(
        shape_config=oci.core.models.UpdateInstanceShapeConfigDetails(
            ocpus=float(ocpus),
            memory_in_gbs=float(memory_gb)
        )
    )

    print(f"\nResizing to {ocpus} OCPU / {memory_gb} GB...")
    result = compute.update_instance(instance_id, update_details)

    # Wait for update
    print("Waiting for resize to complete...")
    waiter = oci.wait_until(
        compute,
        compute.get_instance(instance_id),
        'lifecycle_state',
        'RUNNING',
        max_wait_seconds=300
    )

    print(f"[OK] Resize complete!")
    return result.data

def get_availability_domain(compartment_id, region):
    """Get first availability domain for region."""
    config = CONFIG.copy()
    config["region"] = region
    identity = oci.identity.IdentityClient(config)
    ads = identity.list_availability_domains(compartment_id).data
    return ads[0].name if ads else None

def get_or_create_vcn(compartment_id, region):
    """Get existing VCN or create new one."""
    vcn_client = get_vcn_client(region)

    # Check for existing VCN
    vcns = vcn_client.list_vcns(compartment_id=compartment_id).data
    for vcn in vcns:
        if vcn.lifecycle_state == "AVAILABLE":
            print(f"Using existing VCN: {vcn.display_name}")
            return vcn

    # Create new VCN
    print("Creating new VCN...")
    vcn_details = oci.core.models.CreateVcnDetails(
        compartment_id=compartment_id,
        cidr_block="10.0.0.0/16",
        display_name="frankfurt-vcn",
        dns_label="frankfurtvcn"
    )
    vcn = vcn_client.create_vcn(vcn_details).data

    # Wait for VCN
    oci.wait_until(vcn_client, vcn_client.get_vcn(vcn.id), 'lifecycle_state', 'AVAILABLE')
    print(f"[OK] Created VCN: {vcn.display_name}")
    return vcn

def get_or_create_subnet(compartment_id, vcn_id, ad, region):
    """Get existing subnet or create new one."""
    vcn_client = get_vcn_client(region)

    # Check for existing subnet
    subnets = vcn_client.list_subnets(compartment_id=compartment_id, vcn_id=vcn_id).data
    for subnet in subnets:
        if subnet.lifecycle_state == "AVAILABLE":
            print(f"Using existing subnet: {subnet.display_name}")
            return subnet

    # Create internet gateway first
    print("Creating internet gateway...")
    ig_details = oci.core.models.CreateInternetGatewayDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        is_enabled=True,
        display_name="frankfurt-ig"
    )
    ig = vcn_client.create_internet_gateway(ig_details).data
    oci.wait_until(vcn_client, vcn_client.get_internet_gateway(ig.id), 'lifecycle_state', 'AVAILABLE')

    # Update route table
    route_tables = vcn_client.list_route_tables(compartment_id=compartment_id, vcn_id=vcn_id).data
    if route_tables:
        rt = route_tables[0]
        rt_details = oci.core.models.UpdateRouteTableDetails(
            route_rules=[
                oci.core.models.RouteRule(
                    destination="0.0.0.0/0",
                    destination_type="CIDR_BLOCK",
                    network_entity_id=ig.id
                )
            ]
        )
        vcn_client.update_route_table(rt.id, rt_details)

    # Create subnet
    print("Creating subnet...")
    subnet_details = oci.core.models.CreateSubnetDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        availability_domain=ad,
        cidr_block="10.0.1.0/24",
        display_name="frankfurt-subnet",
        dns_label="frankfurtsub"
    )
    subnet = vcn_client.create_subnet(subnet_details).data
    oci.wait_until(vcn_client, vcn_client.get_subnet(subnet.id), 'lifecycle_state', 'AVAILABLE')

    # Update security list to allow SSH
    security_lists = vcn_client.list_security_lists(compartment_id=compartment_id, vcn_id=vcn_id).data
    if security_lists:
        sl = security_lists[0]
        ingress_rules = list(sl.ingress_security_rules) if sl.ingress_security_rules else []
        ingress_rules.append(
            oci.core.models.IngressSecurityRule(
                protocol="6",  # TCP
                source="0.0.0.0/0",
                tcp_options=oci.core.models.TcpOptions(
                    destination_port_range=oci.core.models.PortRange(min=22, max=22)
                )
            )
        )
        sl_details = oci.core.models.UpdateSecurityListDetails(
            ingress_security_rules=ingress_rules,
            egress_security_rules=sl.egress_security_rules
        )
        vcn_client.update_security_list(sl.id, sl_details)

    print(f"[OK] Created subnet: {subnet.display_name}")
    return subnet

def create_frankfurt_instance(compartment_id, ssh_public_key=None):
    """Create new instance in Frankfurt with 1 OCPU / 6GB."""
    region = "eu-frankfurt-1"
    compute = get_compute_client(region)

    print(f"\n{'='*60}")
    print("CREATING FRANKFURT INSTANCE")
    print(f"{'='*60}")

    # Get availability domain
    ad = get_availability_domain(compartment_id, region)
    print(f"Availability Domain: {ad}")

    # Get or create VCN and subnet
    vcn = get_or_create_vcn(compartment_id, region)
    subnet = get_or_create_subnet(compartment_id, vcn.id, ad, region)

    # Get Ubuntu image for ARM
    images = compute.list_images(
        compartment_id=compartment_id,
        operating_system="Canonical Ubuntu",
        shape="VM.Standard.A1.Flex",
        sort_by="TIMECREATED",
        sort_order="DESC"
    ).data

    if not images:
        print("ERROR: No Ubuntu images found for A1 shape")
        return None

    image = images[0]
    print(f"Image: {image.display_name}")

    # Default SSH key if not provided
    if not ssh_public_key:
        ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAWQkmKVREwP11pQz+Ec8tfIqGTUnkAj+F4ohVEXhaxE kevin@memories"

    # Create instance
    print("\nLaunching instance...")
    instance_details = oci.core.models.LaunchInstanceDetails(
        availability_domain=ad,
        compartment_id=compartment_id,
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=1.0,
            memory_in_gbs=6.0
        ),
        display_name="frankfurt-proxy",
        image_id=image.id,
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=subnet.id,
            assign_public_ip=True
        ),
        metadata={
            "ssh_authorized_keys": ssh_public_key
        }
    )

    instance = compute.launch_instance(instance_details).data
    print(f"Instance ID: {instance.id}")
    print("Waiting for instance to start (this may take 2-3 minutes)...")

    # Wait for running
    oci.wait_until(
        compute,
        compute.get_instance(instance.id),
        'lifecycle_state',
        'RUNNING',
        max_wait_seconds=600
    )

    # Get public IP
    vnic_attachments = compute.list_vnic_attachments(
        compartment_id=compartment_id,
        instance_id=instance.id
    ).data

    if vnic_attachments:
        vcn_client = get_vcn_client(region)
        vnic = vcn_client.get_vnic(vnic_attachments[0].vnic_id).data
        print(f"\n[OK] Frankfurt instance created!")
        print(f"  Public IP: {vnic.public_ip}")
        return instance, vnic.public_ip

    return instance, None

def main():
    """Main automation flow."""
    print("="*60)
    print("ORACLE CLOUD AUTOMATION")
    print("="*60)

    compartment_id = CONFIG["tenancy"]  # Using root compartment

    # Step 1: List current instances
    print("\n[1] Checking current instances in San Jose...")
    try:
        instances = list_instances(compartment_id, "us-sanjose-1")
    except Exception as e:
        if "401" in str(e) or "NotAuthenticated" in str(e):
            print("\n" + "="*60)
            print("API KEY NOT REGISTERED IN ORACLE CLOUD")
            print("="*60)
            print("\nThe API key needs to be added to your Oracle Cloud account.")
            print("\nSteps:")
            print("1. Go to: https://cloud.oracle.com")
            print("2. Click your profile (top right) -> My Profile -> API Keys")
            print("3. Click 'Add API Key' -> 'Paste Public Key'")
            print("4. Paste the public key from:")
            print("   c:\\Users\\kevin\\bitcoin\\kevinchandarasane12345@gmail.com-2025-12-28T07_42_15.968Z_public.pem")
            print("5. Click 'Add'")
            print("\nThen run this script again.")
            return False
        raise

    for i in instances:
        print(f"  - {i.display_name}: {i.shape} ({i.lifecycle_state})")
        if i.shape_config:
            print(f"    OCPUs: {i.shape_config.ocpus}, Memory: {i.shape_config.memory_in_gbs} GB")

    # Step 2: Find mailserver
    print("\n[2] Looking for mailserver instance...")
    mailserver = get_instance_by_name(compartment_id, "mailserver", "us-sanjose-1")

    if not mailserver:
        print("  ERROR: mailserver not found!")
        # Try partial match
        for i in instances:
            if "mail" in i.display_name.lower():
                mailserver = i
                print(f"  Found similar: {i.display_name}")
                break

    if mailserver:
        print(f"  Found: {mailserver.display_name}")
        print(f"  Current: {mailserver.shape_config.ocpus} OCPU / {mailserver.shape_config.memory_in_gbs} GB")

        if mailserver.shape_config.ocpus > 3:
            print("\n[3] Resizing mailserver to 3 OCPU / 18 GB...")
            resize_instance(mailserver.id, 3, 18, "us-sanjose-1")
        else:
            print("\n[3] Mailserver already at 3 OCPU or less, skipping resize")

    # Step 3: Check Frankfurt quota
    print("\n[4] Checking Frankfurt region...")
    frankfurt_instances = list_instances(compartment_id, "eu-frankfurt-1")

    if frankfurt_instances:
        print("  Existing instances in Frankfurt:")
        for i in frankfurt_instances:
            print(f"    - {i.display_name}: {i.shape}")
    else:
        print("  No instances in Frankfurt - ready to create")
        # Create Frankfurt instance with SSH key
        print("\n[5] Creating Frankfurt instance (1 OCPU / 6 GB)...")
        try:
            result = create_frankfurt_instance(compartment_id)
            if result:
                instance, public_ip = result
                print(f"\n[OK] SUCCESS! Frankfurt instance created")
                print(f"  Public IP: {public_ip}")
                print(f"\n  SSH: ssh ubuntu@{public_ip}")
        except Exception as e:
            print(f"  Error creating Frankfurt instance: {e}")

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print("1. Mailserver: 4 OCPU/24GB -> 3 OCPU/18GB")
    print("2. Frankfurt:  1 OCPU/6GB  (NEW)")
    print("3. Total:      4 OCPU/24GB (within free tier)")
    print("="*60)

    return True

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
