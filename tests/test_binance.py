from pathlib import Path

import pytest

from asset_catalog.crypto_models import CryptoMarket, CryptoVenue
from asset_catalog.sources.binance import BINANCE_MARKETS_URL, BinanceClient, BinanceSourceError, parse_binance_markets


FIXTURE = Path(__file__).parent / "fixtures" / "binance_exchange_info.json"


def test_binance_normalizes_trading_and_spot_flags_without_guessing_names() -> None:
    rows = parse_binance_markets(FIXTURE.read_bytes())

    assert rows == [
        CryptoMarket(CryptoVenue.BINANCE, "BTC", "USDT", "BTCUSDT", None, None, True, False),
        CryptoMarket(CryptoVenue.BINANCE, "OLD", "USDT", "OLDUSDT", None, None, False, False),
        CryptoMarket(CryptoVenue.BINANCE, "币安人生", "USDT", "币安人生USDT", None, None, True, False),
    ]


def test_binance_client_uses_fixed_market_data_endpoint_and_timeout() -> None:
    requested: list[tuple[str, float]] = []

    def opener(url: str, timeout: float) -> bytes:
        requested.append((url, timeout))
        return FIXTURE.read_bytes()

    rows = BinanceClient(opener=opener, timeout=7.0).collect()

    assert requested == [(BINANCE_MARKETS_URL, 7.0)]
    assert rows[0].provider_symbol == "BTCUSDT"


def test_binance_rejects_symbol_that_does_not_match_base_and_quote() -> None:
    payload = b'{"symbols":[{"symbol":"WRONG","status":"TRADING","baseAsset":"BTC","quoteAsset":"USDT","isSpotTradingAllowed":true}]}'

    with pytest.raises(BinanceSourceError, match="invalid symbol"):
        parse_binance_markets(payload)
