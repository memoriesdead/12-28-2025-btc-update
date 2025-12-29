# Frankfurt Proxy Configuration

## Proxy Details
- **IP**: 141.147.58.130
- **Port**: 8888
- **Protocol**: HTTP
- **Region**: EU Frankfurt (Oracle Cloud)

## Usage

### Environment Variable
```bash
export HTTP_PROXY=http://141.147.58.130:8888
export HTTPS_PROXY=http://141.147.58.130:8888
```

### Python requests
```python
proxy = {
    'http': 'http://141.147.58.130:8888',
    'https': 'http://141.147.58.130:8888'
}
requests.get(url, proxies=proxy)
```

### curl
```bash
curl --proxy http://141.147.58.130:8888 https://api.binance.com/api/v3/ticker/price
```

### C++ (libcurl)
```cpp
curl_easy_setopt(curl, CURLOPT_PROXY, "http://141.147.58.130:8888");
```

## SSH Access
```bash
ssh ubuntu@141.147.58.130
```

## Verified Working Exchanges
- Binance
- Bybit
- OKX
- HTX (Huobi)
- KuCoin
- Gate.io
- MEXC

## Cost
FREE (Oracle Cloud Always Free Tier)
- 1 OCPU ARM
- 6 GB RAM
