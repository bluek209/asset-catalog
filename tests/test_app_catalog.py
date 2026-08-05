from dataclasses import replace

import pytest

from asset_catalog.app_catalog import (
    AppCatalogProjectionError,
    AppCatalogRecord,
    parse_excluded_ids,
    project_record,
    project_records,
    validate_projected_drop,
)
from asset_catalog.models import InstrumentRecord, InstrumentStatus, InstrumentType


def instrument(
    record_id: str,
    name: str,
    exchange: str,
    provider_symbol: str,
    *,
    status: InstrumentStatus = InstrumentStatus.ACTIVE,
) -> InstrumentRecord:
    market, symbol = record_id.split(":", 1)
    return InstrumentRecord(
        id=record_id,
        symbol=symbol,
        name=name,
        english_name=name if market == "US" else None,
        market=market,
        exchange=exchange,
        currency="USD" if market == "US" else "KRW",
        instrument_type=InstrumentType.COMMON_STOCK,
        status=status,
        provider_id="yahoo",
        provider_symbol=provider_symbol,
        aliases=(name, symbol),
        source_updated_date="2026-08-05",
    )


@pytest.mark.parametrize(
    ("record_id", "exchange", "provider_symbol", "expected"),
    [
        ("KR:005930", "KOSPI", "005930.KS", "KS:005930"),
        ("KR:035900", "KOSDAQ", "035900.KQ", "KQ:035900"),
        ("US:AAPL", "NASDAQ", "AAPL", "Q:AAPL"),
        ("US:BRK.B", "NYSE", "BRK-B", "N:BRK-B"),
        ("US:ABC", "NYSE_AMERICAN", "ABC", "A:ABC"),
        ("US:SPY", "NYSE_ARCA", "SPY", "P:SPY"),
        ("US:BZX", "CBOE", "BZX", "Z:BZX"),
        ("US:IEXS", "IEX", "IEXS", "V:IEXS"),
    ],
)
def test_projects_supported_venue_to_compact_identity(
    record_id: str,
    exchange: str,
    provider_symbol: str,
    expected: str,
) -> None:
    result = project_record(instrument(record_id, "Name", exchange, provider_symbol))

    assert result.i == expected
    assert result.to_dict() == {"i": expected, "n": "Name"}


def test_projection_strips_us_common_stock_suffix() -> None:
    source = instrument("US:AAPL", "Apple Inc. - Common Stock", "NASDAQ", "AAPL")

    assert project_record(source) == AppCatalogRecord("Q:AAPL", "Apple Inc.")


def test_projection_omits_inactive_and_configured_ids_then_sorts() -> None:
    records = [
        instrument("US:QQQ", "QQQ", "NASDAQ", "QQQ"),
        instrument("KR:035900", "JYP Ent.", "KOSDAQ", "035900.KQ"),
        replace(instrument("US:OLD", "Old", "NASDAQ", "OLD"), status=InstrumentStatus.INACTIVE),
    ]

    assert project_records(records, excluded_ids={"Q:QQQ"}) == [
        AppCatalogRecord("KQ:035900", "JYP Ent."),
    ]


def test_excluded_ids_are_parsed_without_logging_or_domain_specific_defaults() -> None:
    assert parse_excluded_ids(" Q:PRIVATE, KQ:000000 ,,Q:PRIVATE ") == {
        "Q:PRIVATE",
        "KQ:000000",
    }
    assert parse_excluded_ids("") == set()


def test_projection_rejects_unknown_exchange_and_duplicate_identity() -> None:
    with pytest.raises(AppCatalogProjectionError, match="unsupported exchange"):
        project_record(instrument("US:ABC", "ABC", "UNKNOWN", "ABC"))
    with pytest.raises(AppCatalogProjectionError, match="duplicate app catalog id"):
        project_records(
            [
                instrument("US:ABC", "First", "NASDAQ", "ABC"),
                instrument("US:ABC2", "Second", "NASDAQ", "ABC"),
            ],
        )


def test_projected_market_drop_over_policy_is_rejected() -> None:
    previous = [AppCatalogRecord(f"Q:X{index}", f"X{index}") for index in range(10)]
    current = previous[:8]

    with pytest.raises(AppCatalogProjectionError, match="Q count dropped from 10 to 8"):
        validate_projected_drop(current, previous, max_drop_ratio=0.10)
