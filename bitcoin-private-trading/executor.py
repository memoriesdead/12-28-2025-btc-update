"""
Real Order Executor - Places actual trades on exchanges via CCXT.
"""
import ccxt
from typing import Dict, Optional
from .credentials import get_exchange_client


class OrderExecutor:
    """Execute real orders on exchanges."""

    def __init__(self):
        self.clients: Dict[str, ccxt.Exchange] = {}

    def _get_client(self, exchange: str) -> ccxt.Exchange:
        """Get or create exchange client."""
        if exchange not in self.clients:
            self.clients[exchange] = get_exchange_client(exchange)
        return self.clients[exchange]

    def _get_symbol(self, exchange: str, instrument: str) -> str:
        """Get trading symbol for exchange/instrument."""
        # Default BTC/USDT for most exchanges
        instrument = instrument.lower()

        if instrument in ('spot', 'margin'):
            return 'BTC/USDT'
        elif instrument in ('perpetual', 'perp'):
            return 'BTC/USDT:USDT'  # CCXT perpetual format
        elif instrument == 'futures':
            return 'BTC/USDT:USDT'  # Same as perp for most exchanges
        elif instrument == 'inverse':
            return 'BTC/USD:BTC'  # Inverse perpetual
        elif instrument == 'options':
            return 'BTC/USDT:USDT'  # Options vary by exchange
        elif instrument == 'leveraged_token':
            return 'BTC3L/USDT'  # 3x leveraged token
        else:
            return 'BTC/USDT'

    def execute_short(self, exchange: str, instrument: str, size_btc: float) -> dict:
        """Place SHORT order on exchange."""
        try:
            client = self._get_client(exchange)
            symbol = self._get_symbol(exchange, instrument)

            # For perpetual/futures, we need to set position mode
            if instrument.lower() in ('perpetual', 'perp', 'futures', 'inverse'):
                # Set leverage if supported
                try:
                    client.set_leverage(125, symbol)
                except Exception:
                    pass  # Not all exchanges support this

                # Create short position (sell to open)
                order = client.create_market_sell_order(
                    symbol,
                    size_btc,
                    params={'reduceOnly': False}  # Open new position
                )
            else:
                # Spot/margin - regular market sell
                order = client.create_market_sell_order(symbol, size_btc)

            return {
                'order_id': order.get('id', 'unknown'),
                'exchange': exchange,
                'instrument': instrument,
                'side': 'sell',
                'size': size_btc,
                'price': order.get('average') or order.get('price'),
                'status': order.get('status', 'unknown'),
                'raw': order
            }

        except Exception as e:
            return {
                'order_id': None,
                'exchange': exchange,
                'instrument': instrument,
                'side': 'sell',
                'size': size_btc,
                'price': None,
                'status': 'failed',
                'error': str(e)
            }

    def execute_long(self, exchange: str, instrument: str, size_btc: float) -> dict:
        """Place LONG order on exchange."""
        try:
            client = self._get_client(exchange)
            symbol = self._get_symbol(exchange, instrument)

            # For perpetual/futures, set leverage
            if instrument.lower() in ('perpetual', 'perp', 'futures', 'inverse'):
                try:
                    client.set_leverage(125, symbol)
                except Exception:
                    pass

                order = client.create_market_buy_order(
                    symbol,
                    size_btc,
                    params={'reduceOnly': False}
                )
            else:
                order = client.create_market_buy_order(symbol, size_btc)

            return {
                'order_id': order.get('id', 'unknown'),
                'exchange': exchange,
                'instrument': instrument,
                'side': 'buy',
                'size': size_btc,
                'price': order.get('average') or order.get('price'),
                'status': order.get('status', 'unknown'),
                'raw': order
            }

        except Exception as e:
            return {
                'order_id': None,
                'exchange': exchange,
                'instrument': instrument,
                'side': 'buy',
                'size': size_btc,
                'price': None,
                'status': 'failed',
                'error': str(e)
            }

    def close_position(self, exchange: str, instrument: str, side: str, size_btc: float) -> dict:
        """Close an open position."""
        try:
            client = self._get_client(exchange)
            symbol = self._get_symbol(exchange, instrument)

            # Close by trading opposite direction with reduceOnly
            if side == 'sell':  # Was short, buy to close
                order = client.create_market_buy_order(
                    symbol,
                    size_btc,
                    params={'reduceOnly': True}
                )
            else:  # Was long, sell to close
                order = client.create_market_sell_order(
                    symbol,
                    size_btc,
                    params={'reduceOnly': True}
                )

            return {
                'order_id': order.get('id', 'unknown'),
                'exchange': exchange,
                'instrument': instrument,
                'side': 'buy' if side == 'sell' else 'sell',
                'size': size_btc,
                'price': order.get('average') or order.get('price'),
                'status': order.get('status', 'unknown'),
                'raw': order
            }

        except Exception as e:
            return {
                'order_id': None,
                'exchange': exchange,
                'instrument': instrument,
                'side': 'close',
                'size': size_btc,
                'price': None,
                'status': 'failed',
                'error': str(e)
            }

    def get_balance(self, exchange: str) -> dict:
        """Get account balance."""
        try:
            client = self._get_client(exchange)
            balance = client.fetch_balance()
            return {
                'exchange': exchange,
                'usdt': balance.get('USDT', {}).get('free', 0),
                'btc': balance.get('BTC', {}).get('free', 0),
                'total_usdt': balance.get('USDT', {}).get('total', 0),
                'status': 'success'
            }
        except Exception as e:
            return {
                'exchange': exchange,
                'usdt': 0,
                'btc': 0,
                'total_usdt': 0,
                'status': 'failed',
                'error': str(e)
            }

    def get_positions(self, exchange: str) -> list:
        """Get open positions."""
        try:
            client = self._get_client(exchange)
            positions = client.fetch_positions()
            return [p for p in positions if float(p.get('contracts', 0)) != 0]
        except Exception as e:
            return []
