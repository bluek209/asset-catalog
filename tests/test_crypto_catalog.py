from dataclasses import replace

import pytest

from asset_catalog.crypto_catalog import (
    CryptoCatalogProjectionError,
    CryptoCatalogRecord,
    project_crypto_records,
    provider_symbol_for,
    validate_crypto_drop,
)
from asset_catalog.crypto_models import CryptoMarket, CryptoVenue


def market(
    venue: CryptoVenue,
    base: str,
    quote: str,
    provider_symbol: str,
    *,
    korean_name: str | None = "비트코인",
    english_name: str | None = "Bitcoin",
    tradable: bool = True,
    warning: bool = False,
) -> CryptoMarket:
    if venue is CryptoVenue.BINANCE:
        korean_name = None
        english_name = None
    return CryptoMarket(
        venue,
        base,
        quote,
        provider_symbol,
        korean_name,
        english_name,
        tradable,
        warning,
    )


def test_public_record_has_exact_minimal_fields() -> None:
    record = CryptoCatalogRecord("UP:BTC-KRW", "비트코인", "Bitcoin")

    assert record.to_dict() == {"i": "UP:BTC-KRW", "k": "비트코인", "e": "Bitcoin"}
    with pytest.raises(CryptoCatalogProjectionError, match="invalid fields"):
        CryptoCatalogRecord.from_dict(
            {"i": "UP:BTC-KRW", "k": "비트코인", "e": "Bitcoin", "p": "KRW-BTC"},
        )


def test_projection_filters_quote_warning_and_trading_state_then_sorts() -> None:
    records = project_crypto_records(
        [
            market(CryptoVenue.UPBIT, "BTC", "KRW", "KRW-BTC"),
            market(CryptoVenue.BITHUMB, "BTC", "KRW", "KRW-BTC"),
            market(CryptoVenue.BINANCE, "BTC", "USDT", "BTCUSDT"),
            market(CryptoVenue.UPBIT, "ETH", "KRW", "KRW-ETH", warning=True),
            market(CryptoVenue.BITHUMB, "XRP", "BTC", "BTC-XRP"),
            market(CryptoVenue.BINANCE, "OLD", "USDT", "OLDUSDT", tradable=False),
            market(CryptoVenue.BINANCE, "ETH", "BTC", "ETHBTC"),
        ],
        excluded_ids=set(),
    )

    assert records == [
        CryptoCatalogRecord("BN:BTC-USDT", "비트코인", "Bitcoin"),
        CryptoCatalogRecord("BT:BTC-KRW", "비트코인", "Bitcoin"),
        CryptoCatalogRecord("UP:BTC-KRW", "비트코인", "Bitcoin"),
    ]
    assert provider_symbol_for(records[0].i) == "BTCUSDT"
    assert provider_symbol_for(records[1].i) == "KRW-BTC"


def test_binance_ambiguous_or_missing_korean_name_falls_back_to_base_symbol() -> None:
    records = project_crypto_records(
        [
            market(CryptoVenue.UPBIT, "ABC", "KRW", "KRW-ABC", korean_name="에이비씨", english_name="ABC Coin"),
            market(CryptoVenue.BITHUMB, "ABC", "KRW", "KRW-ABC", korean_name="다른코인", english_name="Other Coin"),
            market(CryptoVenue.BINANCE, "ABC", "USDT", "ABCUSDT"),
            market(CryptoVenue.BINANCE, "NONE", "USDT", "NONEUSDT"),
        ],
        excluded_ids=set(),
    )

    assert CryptoCatalogRecord("BN:ABC-USDT", "ABC", "ABC") in records
    assert CryptoCatalogRecord("BN:NONE-USDT", "NONE", "NONE") in records


def test_projection_supports_unicode_provider_asset_without_guessing_a_name() -> None:
    records = project_crypto_records(
        [market(CryptoVenue.BINANCE, "币安人生", "USDT", "币安人生USDT")],
        excluded_ids=set(),
    )

    assert records == [CryptoCatalogRecord("BN:币安人生-USDT", "币安人生", "币安人生")]
    assert provider_symbol_for(records[0].i) == "币安人生USDT"


def test_projection_rejects_provider_symbol_mismatch_and_duplicate_identity() -> None:
    valid = market(CryptoVenue.UPBIT, "BTC", "KRW", "KRW-BTC")
    with pytest.raises(CryptoCatalogProjectionError, match="provider symbol"):
        project_crypto_records([replace(valid, provider_symbol="BTC-KRW")], excluded_ids=set())
    with pytest.raises(CryptoCatalogProjectionError, match="duplicate crypto catalog id"):
        project_crypto_records([valid, valid], excluded_ids=set())


def test_projection_applies_exact_public_id_exclusions() -> None:
    records = project_crypto_records(
        [
            market(CryptoVenue.UPBIT, "BTC", "KRW", "KRW-BTC"),
            market(CryptoVenue.BITHUMB, "BTC", "KRW", "KRW-BTC"),
        ],
        excluded_ids={"UP:BTC-KRW"},
    )

    assert records == [CryptoCatalogRecord("BT:BTC-KRW", "비트코인", "Bitcoin")]


def test_venue_drop_over_policy_is_rejected() -> None:
    previous = [CryptoCatalogRecord(f"UP:X{index}-KRW", f"코인{index}", f"Coin {index}") for index in range(10)]

    with pytest.raises(CryptoCatalogProjectionError, match="UP count dropped from 10 to 8"):
        validate_crypto_drop(previous[:8], previous, max_drop_ratio=0.10)
