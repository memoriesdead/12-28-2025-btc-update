#!/usr/bin/env python3
"""
DEPTH CALCULATOR - Pure Mathematical Price Impact
==================================================

100% DETERMINISTIC - No probability, only math.

Given:
    - Deposit size (from blockchain)
    - Order book depth (from exchange)

Calculate:
    - Exact price impact
    - VWAP (Volume-Weighted Average Price)
    - Cumulative depth at each level
    - Expected profit (after fees)

MULTI-INSTRUMENT SUPPORT:
    Each of the 7 instrument types has its own impact profile:
    - SPOT: Simple volume impact, no amplification
    - MARGIN: Leveraged impact, liquidation cascades
    - PERPETUAL: Standard implementation
    - FUTURES: Impact plus basis consideration
    - OPTIONS: Delta-adjusted exposure impact
    - INVERSE: Calculate in BTC terms, convert to USD
    - LEVERAGED_TOKEN: Impact on underlying * leverage
"""

from typing import List, Tuple, Dict, Optional, Any
from dataclasses import dataclass, field

from .config import InstrumentType


@dataclass
class PriceImpact:
    """
    Result of price impact calculation - supports ALL 7 instrument types.

    INSTRUMENT-SPECIFIC FIELDS:
    - basis_adjustment: For FUTURES (mark - spot)
    - contracts_affected: For INVERSE (number of contracts)
    - leveraged_move: For LEVERAGED_TOKEN (amplified move)
    - delta_adjusted: For OPTIONS (delta-weighted impact)
    - liquidation_cascade: For MARGIN (additional cascade impact)
    """
    start_price: float      # Best bid before sell
    end_price: float        # Price after all volume eaten
    vwap: float             # Volume-weighted average execution price
    price_drop_pct: float   # Percentage drop (start to end)
    volume_filled: float    # BTC that can be filled
    volume_remaining: float # BTC that couldn't be filled (if any)
    levels_eaten: int       # Number of price levels consumed
    total_cost: float       # Total USD received from sell

    # NEW: Instrument type (default PERPETUAL for backward compatibility)
    instrument_type: InstrumentType = InstrumentType.PERPETUAL

    # FUTURES specific: Basis adjustment
    basis_adjustment: float = 0.0

    # INVERSE specific: Contract count affected
    contracts_affected: float = 0.0

    # LEVERAGED_TOKEN specific: Amplified move
    leveraged_move: float = 0.0

    # OPTIONS specific: Delta-adjusted impact
    delta_adjusted_impact: float = 0.0

    # MARGIN specific: Liquidation cascade effect
    liquidation_cascade_pct: float = 0.0

    @property
    def slippage_pct(self) -> float:
        """Slippage from best bid to VWAP."""
        if self.start_price == 0:
            return 0.0
        return (self.start_price - self.vwap) / self.start_price * 100

    def is_profitable(self, fees_pct: float, safety_multiple: float = 2.0) -> bool:
        """Check if trade is profitable after fees with safety margin."""
        return self.price_drop_pct > (fees_pct * safety_multiple)

    def expected_profit_pct(self, fees_pct: float) -> float:
        """Calculate expected profit percentage after fees."""
        return self.price_drop_pct - fees_pct

    @property
    def effective_impact(self) -> float:
        """Get the effective impact based on instrument type."""
        if self.instrument_type == InstrumentType.LEVERAGED_TOKEN:
            return self.leveraged_move if self.leveraged_move else self.price_drop_pct
        elif self.instrument_type == InstrumentType.OPTIONS:
            return self.delta_adjusted_impact if self.delta_adjusted_impact else self.price_drop_pct
        elif self.instrument_type == InstrumentType.MARGIN:
            return self.price_drop_pct + self.liquidation_cascade_pct
        return self.price_drop_pct


def calculate_vwap(levels: List[Tuple[float, float]], volume: float) -> float:
    """
    Calculate Volume-Weighted Average Price for a given volume.

    This is the ACTUAL average price we'll receive when selling.

    Example:
        Selling 10 BTC across multiple bid levels:
        - 5 BTC @ $87,000 = $435,000
        - 5 BTC @ $86,950 = $434,750
        - VWAP = $869,750 / 10 = $86,975

    Args:
        levels: List of (price, volume) tuples, sorted by price descending
        volume: Amount to sell

    Returns:
        Volume-weighted average execution price
    """
    if not levels or volume <= 0:
        return 0.0

    remaining = volume
    total_cost = 0.0
    total_volume = 0.0

    for level in levels:
        if remaining <= 0:
            break
        price = level[0]
        level_volume = level[1]
        fill = min(remaining, level_volume)
        total_cost += price * fill
        total_volume += fill
        remaining -= fill

    if total_volume == 0:
        return levels[0][0]  # Best price if no fill

    return total_cost / total_volume


def calculate_cumulative_depth(levels: List[Tuple[float, float]]) -> List[Dict]:
    """
    Calculate cumulative depth at each price level.

    This shows how much total volume is available at or above each price.

    Args:
        levels: List of (price, volume) tuples, sorted by price descending

    Returns:
        List of dicts with price, volume, cumulative, and pct_drop

    Example:
        [
            {'price': 87000, 'volume': 2, 'cumulative': 2, 'pct_drop': 0.0},
            {'price': 86950, 'volume': 3, 'cumulative': 5, 'pct_drop': 0.057},
            {'price': 86900, 'volume': 5, 'cumulative': 10, 'pct_drop': 0.115},
        ]
    """
    if not levels:
        return []

    start_price = levels[0][0]
    cumulative = 0.0
    result = []

    for level in levels:
        price = level[0]
        volume = level[1]
        cumulative += volume
        pct_drop = (start_price - price) / start_price * 100 if start_price > 0 else 0.0
        result.append({
            'price': price,
            'volume': volume,
            'cumulative': cumulative,
            'pct_drop': pct_drop
        })

    return result


def calculate_price_impact(sell_btc: float, bids: List[Tuple[float, float]]) -> PriceImpact:
    """
    Calculate exact price impact of a market sell order.

    This is the core deterministic calculation:
    - Given deposit size and order book, we KNOW exactly what price impact will be.

    Args:
        sell_btc: Amount being sold (from blockchain deposit detection)
        bids: List of (price, volume) tuples, sorted by price descending

    Returns:
        PriceImpact with all calculated values

    Example:
        Deposit: 50 BTC to Binance
        Order Book Bids:
            $87,000: 10 BTC
            $86,950: 15 BTC
            $86,900: 20 BTC
            $86,850: 25 BTC

        Calculation:
            50 BTC eats: 10 + 15 + 20 + 5 = 50 BTC
            Start: $87,000
            End: $86,850
            Impact: 0.172%
            VWAP: $86,925
    """
    if not bids or sell_btc <= 0:
        return PriceImpact(
            start_price=0.0,
            end_price=0.0,
            vwap=0.0,
            price_drop_pct=0.0,
            volume_filled=0.0,
            volume_remaining=sell_btc,
            levels_eaten=0,
            total_cost=0.0
        )

    remaining = sell_btc
    start_price = bids[0][0]
    end_price = start_price
    levels_eaten = 0
    total_cost = 0.0
    total_filled = 0.0

    for level in bids:
        if remaining <= 0:
            break

        # Handle different order book formats (some have 2 elements, some have more)
        price = level[0]
        volume = level[1]

        fill = min(remaining, volume)
        total_cost += price * fill
        total_filled += fill
        remaining -= fill
        end_price = price
        levels_eaten += 1

    # Calculate metrics
    price_drop_pct = (start_price - end_price) / start_price * 100 if start_price > 0 else 0.0
    vwap = total_cost / total_filled if total_filled > 0 else start_price

    return PriceImpact(
        start_price=start_price,
        end_price=end_price,
        vwap=vwap,
        price_drop_pct=price_drop_pct,
        volume_filled=total_filled,
        volume_remaining=remaining,
        levels_eaten=levels_eaten,
        total_cost=total_cost
    )


def calculate_buy_impact(buy_btc: float, asks: List[Tuple[float, float]]) -> PriceImpact:
    """
    Calculate exact price impact of a market buy order.

    Same as sell impact but for LONG signals (withdrawal detected).

    Args:
        buy_btc: Amount being bought
        asks: List of (price, volume) tuples, sorted by price ascending

    Returns:
        PriceImpact with price_rise instead of price_drop
    """
    if not asks or buy_btc <= 0:
        return PriceImpact(
            start_price=0.0,
            end_price=0.0,
            vwap=0.0,
            price_drop_pct=0.0,  # Will be negative for rise
            volume_filled=0.0,
            volume_remaining=buy_btc,
            levels_eaten=0,
            total_cost=0.0
        )

    remaining = buy_btc
    start_price = asks[0][0]
    end_price = start_price
    levels_eaten = 0
    total_cost = 0.0
    total_filled = 0.0

    for price, volume in asks:
        if remaining <= 0:
            break

        fill = min(remaining, volume)
        total_cost += price * fill
        total_filled += fill
        remaining -= fill
        end_price = price
        levels_eaten += 1

    # For buys, price rises (negative drop)
    price_rise_pct = (end_price - start_price) / start_price * 100 if start_price > 0 else 0.0
    vwap = total_cost / total_filled if total_filled > 0 else start_price

    return PriceImpact(
        start_price=start_price,
        end_price=end_price,
        vwap=vwap,
        price_drop_pct=-price_rise_pct,  # Negative = price rise
        volume_filled=total_filled,
        volume_remaining=remaining,
        levels_eaten=levels_eaten,
        total_cost=total_cost
    )


def calculate_exit_price(entry_price: float, impact: PriceImpact,
                         direction: str, take_profit_pct: float = 0.8) -> float:
    """
    Calculate deterministic exit price based on order book math.

    We KNOW price will move to impact.end_price when the order executes.
    We take 80% of the expected move as our target (safety margin).

    Args:
        entry_price: Our entry price
        impact: The calculated price impact
        direction: 'SHORT' or 'LONG'
        take_profit_pct: How much of the expected move to capture (default 80%)

    Returns:
        Target exit price
    """
    if direction == 'SHORT':
        # Price will drop - we exit at 80% of expected drop
        target_drop_pct = impact.price_drop_pct * take_profit_pct
        exit_price = entry_price * (1 - target_drop_pct / 100)
    else:
        # LONG - price will rise
        target_rise_pct = abs(impact.price_drop_pct) * take_profit_pct
        exit_price = entry_price * (1 + target_rise_pct / 100)

    return exit_price


def calculate_position_size(capital: float, leverage: int, entry_price: float,
                           exit_price: float, fees_pct: float) -> Dict:
    """
    Calculate optimal position size based on expected profit.

    Args:
        capital: Available trading capital
        leverage: Maximum leverage to use
        entry_price: Entry price
        exit_price: Target exit price
        fees_pct: Total round-trip fees

    Returns:
        Dict with position details
    """
    if entry_price <= 0 or exit_price <= 0:
        return {'position_size': 0, 'expected_profit': 0, 'risk': 0}

    # Calculate expected profit per unit
    price_change_pct = abs(entry_price - exit_price) / entry_price * 100
    net_profit_pct = price_change_pct - fees_pct

    if net_profit_pct <= 0:
        return {'position_size': 0, 'expected_profit': 0, 'risk': 0}

    # Position size with leverage
    position_size = capital * leverage
    expected_profit = position_size * (net_profit_pct / 100)

    return {
        'position_size': position_size,
        'btc_amount': position_size / entry_price,
        'entry_price': entry_price,
        'exit_price': exit_price,
        'price_change_pct': price_change_pct,
        'fees_pct': fees_pct,
        'net_profit_pct': net_profit_pct,
        'expected_profit': expected_profit,
        'leverage': leverage
    }


# =============================================================================
# PER-INSTRUMENT PRICE IMPACT CALCULATIONS
# =============================================================================

def calculate_instrument_price_impact(
    flow_btc: float,
    levels: List[Tuple[float, float]],
    instrument_type: InstrumentType = InstrumentType.PERPETUAL,
    is_sell: bool = True,
    **kwargs: Any
) -> PriceImpact:
    """
    Calculate price impact based on instrument type.

    100% DETERMINISTIC - each instrument uses pure math.

    Args:
        flow_btc: Amount of BTC flow (deposit/withdrawal)
        levels: Order book levels (bids for sell, asks for buy)
        instrument_type: Type of instrument
        is_sell: True if selling (SHORT), False if buying (LONG)
        **kwargs: Instrument-specific parameters

    Returns:
        PriceImpact with instrument-specific fields populated
    """
    if instrument_type == InstrumentType.SPOT:
        return _calculate_spot_impact(flow_btc, levels, is_sell)

    elif instrument_type == InstrumentType.MARGIN:
        leverage = kwargs.get('leverage', 1)
        return _calculate_margin_impact(flow_btc, levels, is_sell, leverage)

    elif instrument_type == InstrumentType.PERPETUAL:
        # Standard implementation
        if is_sell:
            return calculate_price_impact(flow_btc, levels)
        else:
            return calculate_buy_impact(flow_btc, levels)

    elif instrument_type == InstrumentType.FUTURES:
        basis = kwargs.get('basis', 0.0)
        return _calculate_futures_impact(flow_btc, levels, is_sell, basis)

    elif instrument_type == InstrumentType.OPTIONS:
        delta = kwargs.get('delta', 0.5)
        return _calculate_options_impact(flow_btc, levels, is_sell, delta)

    elif instrument_type == InstrumentType.INVERSE:
        contract_size = kwargs.get('contract_size', 1.0)
        return _calculate_inverse_impact(flow_btc, levels, is_sell, contract_size)

    elif instrument_type == InstrumentType.LEVERAGED_TOKEN:
        target_leverage = kwargs.get('target_leverage', 3.0)
        return _calculate_leveraged_token_impact(flow_btc, levels, is_sell, target_leverage)

    # Default to perpetual
    if is_sell:
        return calculate_price_impact(flow_btc, levels)
    else:
        return calculate_buy_impact(flow_btc, levels)


def _calculate_spot_impact(
    flow_btc: float,
    levels: List[Tuple[float, float]],
    is_sell: bool
) -> PriceImpact:
    """
    SPOT: Simple order book walk-through, no amplification.

    100% DETERMINISTIC - just volume * price levels.
    """
    if is_sell:
        impact = calculate_price_impact(flow_btc, levels)
    else:
        impact = calculate_buy_impact(flow_btc, levels)

    impact.instrument_type = InstrumentType.SPOT
    return impact


def _calculate_margin_impact(
    flow_btc: float,
    levels: List[Tuple[float, float]],
    is_sell: bool,
    leverage: int
) -> PriceImpact:
    """
    MARGIN: Leveraged impact with liquidation cascade consideration.

    100% DETERMINISTIC:
    - Calculate base impact from order book
    - If impact > liquidation threshold, add cascade effect
    """
    if is_sell:
        impact = calculate_price_impact(flow_btc, levels)
    else:
        impact = calculate_buy_impact(flow_btc, levels)

    impact.instrument_type = InstrumentType.MARGIN

    # Margin can trigger liquidation cascades
    liquidation_threshold = (100 / leverage) if leverage > 0 else 100
    if impact.price_drop_pct > liquidation_threshold:
        # Add 50% cascade effect when liquidations trigger
        impact.liquidation_cascade_pct = impact.price_drop_pct * 0.5

    return impact


def _calculate_futures_impact(
    flow_btc: float,
    levels: List[Tuple[float, float]],
    is_sell: bool,
    basis: float
) -> PriceImpact:
    """
    FUTURES: Impact plus basis consideration.

    100% DETERMINISTIC:
    - Calculate base impact from order book
    - Factor in basis (mark - spot) for entry/exit pricing
    """
    if is_sell:
        impact = calculate_price_impact(flow_btc, levels)
    else:
        impact = calculate_buy_impact(flow_btc, levels)

    impact.instrument_type = InstrumentType.FUTURES
    impact.basis_adjustment = basis

    return impact


def _calculate_options_impact(
    flow_btc: float,
    levels: List[Tuple[float, float]],
    is_sell: bool,
    delta: float
) -> PriceImpact:
    """
    OPTIONS: Delta-adjusted exposure impact.

    100% DETERMINISTIC:
    - Effective exposure = flow * |delta|
    - Options don't have direct order book impact, but underlying does
    """
    # Delta-adjusted exposure
    effective_flow = flow_btc * abs(delta)

    if is_sell:
        impact = calculate_price_impact(effective_flow, levels)
    else:
        impact = calculate_buy_impact(effective_flow, levels)

    impact.instrument_type = InstrumentType.OPTIONS
    impact.delta_adjusted_impact = impact.price_drop_pct * abs(delta)

    return impact


def _calculate_inverse_impact(
    flow_btc: float,
    levels: List[Tuple[float, float]],
    is_sell: bool,
    contract_size: float
) -> PriceImpact:
    """
    INVERSE: Calculate impact in BTC terms.

    100% DETERMINISTIC:
    - Inverse contracts are denominated in BTC
    - Convert flow to contract count
    - Impact calculation is the same, but P&L is in BTC
    """
    # Convert BTC flow to contract count
    contracts = flow_btc / contract_size if contract_size > 0 else flow_btc

    if is_sell:
        impact = calculate_price_impact(flow_btc, levels)
    else:
        impact = calculate_buy_impact(flow_btc, levels)

    impact.instrument_type = InstrumentType.INVERSE
    impact.contracts_affected = contracts

    return impact


def _calculate_leveraged_token_impact(
    flow_btc: float,
    levels: List[Tuple[float, float]],
    is_sell: bool,
    target_leverage: float
) -> PriceImpact:
    """
    LEVERAGED TOKEN: Impact on underlying * leverage.

    100% DETERMINISTIC:
    - Token tracks underlying * leverage
    - A 1% underlying move = 3% token move for 3x token
    """
    if is_sell:
        impact = calculate_price_impact(flow_btc, levels)
    else:
        impact = calculate_buy_impact(flow_btc, levels)

    impact.instrument_type = InstrumentType.LEVERAGED_TOKEN
    impact.leveraged_move = impact.price_drop_pct * target_leverage

    return impact


# =============================================================================
# TESTING
# =============================================================================

def main():
    """Test the deterministic calculations."""
    print("=" * 70)
    print("DEPTH CALCULATOR - 100% DETERMINISTIC MATH")
    print("=" * 70)
    print()

    # Example order book bids
    bids = [
        (87000, 10),   # $87,000: 10 BTC
        (86950, 15),   # $86,950: 15 BTC
        (86900, 20),   # $86,900: 20 BTC
        (86850, 25),   # $86,850: 25 BTC
        (86800, 30),   # $86,800: 30 BTC
    ]

    # Example deposit
    deposit_btc = 50.0
    fees_pct = 0.10  # 0.1% round trip

    print(f"Deposit: {deposit_btc} BTC")
    print(f"Fees: {fees_pct}%")
    print()

    print("Order Book Bids:")
    for price, vol in bids:
        print(f"  ${price:,.2f}: {vol} BTC")
    print()

    # Calculate impact
    impact = calculate_price_impact(deposit_btc, bids)

    print("CALCULATION RESULTS:")
    print(f"  Start Price: ${impact.start_price:,.2f}")
    print(f"  End Price:   ${impact.end_price:,.2f}")
    print(f"  VWAP:        ${impact.vwap:,.2f}")
    print(f"  Price Drop:  {impact.price_drop_pct:.4f}%")
    print(f"  Slippage:    {impact.slippage_pct:.4f}%")
    print(f"  Levels Eaten: {impact.levels_eaten}")
    print(f"  Volume Filled: {impact.volume_filled} BTC")
    print()

    # Profitability check
    is_profitable = impact.is_profitable(fees_pct, safety_multiple=2.0)
    expected_profit = impact.expected_profit_pct(fees_pct)

    print("PROFITABILITY:")
    print(f"  Impact > 2x Fees: {is_profitable}")
    print(f"  Expected Profit:  {expected_profit:.4f}%")
    print()

    # Calculate exit price
    entry_price = impact.start_price
    exit_price = calculate_exit_price(entry_price, impact, 'SHORT', take_profit_pct=0.8)

    print("TRADE PLAN:")
    print(f"  Entry:  ${entry_price:,.2f}")
    print(f"  Exit:   ${exit_price:,.2f}")
    print(f"  Target: {(entry_price - exit_price) / entry_price * 100:.4f}% profit")
    print()

    # Position sizing
    capital = 100.0
    leverage = 125
    position = calculate_position_size(capital, leverage, entry_price, exit_price, fees_pct)

    print("POSITION:")
    print(f"  Capital:   ${capital}")
    print(f"  Leverage:  {leverage}x")
    print(f"  Size:      ${position['position_size']:,.2f}")
    print(f"  BTC:       {position['btc_amount']:.6f}")
    print(f"  Expected:  ${position['expected_profit']:.2f} profit")
    print()

    print("=" * 70)
    print("100% DETERMINISTIC - No probability, only math.")
    print("=" * 70)


if __name__ == "__main__":
    main()
