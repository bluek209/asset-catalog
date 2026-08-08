from pathlib import Path

import pytest

from asset_catalog.crypto_models import CryptoMarket, CryptoVenue
from asset_catalog.sources.upbit import UPBIT_MARKETS_URL, UpbitClient, UpbitSourceError, parse_upbit_markets


FIXTURE = Path(__file__).parent / "fixtures" / "upbit_markets.json"


def test_upbit_normalizes_pair_names_and_warning_state() -> None:
    rows = parse_upbit_markets(FIXTURE.read_bytes())

    assert rows == [
        CryptoMarket(CryptoVenue.UPBIT, "BTC", "KRW", "KRW-BTC", "비트코인", "Bitcoin", True, False),
        CryptoMarket(CryptoVenue.UPBIT, "ETH", "KRW", "KRW-ETH", "이더리움", "Ethereum", True, True),
    ]


def test_upbit_client_uses_fixed_public_endpoint_and_timeout() -> None:
    requested: list[tuple[str, float]] = []

    def opener(url: str, timeout: float) -> bytes:
        requested.append((url, timeout))
        return FIXTURE.read_bytes()

    rows = UpbitClient(opener=opener, timeout=12.0).collect()

    assert requested == [(UPBIT_MARKETS_URL, 12.0)]
    assert rows[0].provider_symbol == "KRW-BTC"


def test_upbit_rejects_malformed_payload_without_echoing_body() -> None:
    secret = "private-response-value"

    with pytest.raises(UpbitSourceError) as raised:
        parse_upbit_markets(f'{{"unexpected":"{secret}"}}'.encode())

    assert secret not in str(raised.value)
