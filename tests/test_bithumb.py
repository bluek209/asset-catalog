from pathlib import Path

import pytest

from asset_catalog.crypto_models import CryptoMarket, CryptoVenue
from asset_catalog.sources.bithumb import BITHUMB_MARKETS_URL, BithumbClient, BithumbSourceError, parse_bithumb_markets


FIXTURE = Path(__file__).parent / "fixtures" / "bithumb_markets.json"


def test_bithumb_normalizes_its_warning_contract_independently() -> None:
    rows = parse_bithumb_markets(FIXTURE.read_bytes())

    assert rows == [
        CryptoMarket(CryptoVenue.BITHUMB, "BTC", "KRW", "KRW-BTC", "비트코인", "Bitcoin", True, False),
        CryptoMarket(CryptoVenue.BITHUMB, "ETH", "KRW", "KRW-ETH", "이더리움", "Ethereum", True, True),
    ]


def test_bithumb_client_uses_fixed_public_endpoint_and_timeout() -> None:
    requested: list[tuple[str, float]] = []

    def opener(url: str, timeout: float) -> bytes:
        requested.append((url, timeout))
        return FIXTURE.read_bytes()

    rows = BithumbClient(opener=opener, timeout=9.0).collect()

    assert requested == [(BITHUMB_MARKETS_URL, 9.0)]
    assert rows[0].venue is CryptoVenue.BITHUMB


def test_bithumb_rejects_unknown_warning_without_echoing_body() -> None:
    payload = b'[{"market":"KRW-BTC","korean_name":"x","english_name":"x","market_warning":"SECRET"}]'

    with pytest.raises(BithumbSourceError) as raised:
        parse_bithumb_markets(payload)

    assert "SECRET" not in str(raised.value)
