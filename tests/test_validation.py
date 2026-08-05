from dataclasses import replace

import pytest

from asset_catalog.models import (
    InstrumentRecord,
    InstrumentStatus,
    InstrumentType,
)
from asset_catalog.validation import (
    CatalogValidationError,
    Sentinel,
    ValidationPolicy,
    validate_catalog,
)


def instrument(
    record_id: str,
    *,
    instrument_type: InstrumentType,
    provider_symbol: str | None = None,
) -> InstrumentRecord:
    market, symbol = record_id.split(":", 1)
    korean = market == "KR"
    return InstrumentRecord(
        id=record_id,
        symbol=symbol,
        name=symbol,
        english_name=None if korean else symbol,
        market=market,
        exchange="KOSPI" if korean else "NASDAQ",
        currency="KRW" if korean else "USD",
        instrument_type=instrument_type,
        status=InstrumentStatus.ACTIVE,
        provider_id="yahoo",
        provider_symbol=provider_symbol if provider_symbol is not None else (f"{symbol}.KS" if korean else symbol),
        aliases=(symbol,),
        source_updated_date="2026-08-05",
    )


def complete_catalog() -> list[InstrumentRecord]:
    return [
        instrument("KR:005930", instrument_type=InstrumentType.COMMON_STOCK, provider_symbol="005930.KS"),
        instrument("KR:035900", instrument_type=InstrumentType.COMMON_STOCK, provider_symbol="035900.KQ"),
        instrument("KR:367380", instrument_type=InstrumentType.ETF, provider_symbol="367380.KS"),
        instrument("KR:530036", instrument_type=InstrumentType.ETN, provider_symbol="530036.KS"),
        instrument("US:AAPL", instrument_type=InstrumentType.COMMON_STOCK),
        instrument("US:QQQ", instrument_type=InstrumentType.ETF),
        instrument("US:VXX", instrument_type=InstrumentType.ETN),
    ]


def test_complete_catalog_returns_group_counts_and_sentinels() -> None:
    report = validate_catalog(complete_catalog())

    assert report.total_count == 7
    assert report.group_counts["KR:ETF"] == 1
    assert report.group_counts["US:COMMON_STOCK"] == 1
    assert report.sentinel_ids == (
        "KR:005930",
        "KR:035900",
        "KR:367380",
        "US:AAPL",
        "US:QQQ",
    )


def test_duplicate_ids_are_rejected() -> None:
    records = complete_catalog()

    with pytest.raises(CatalogValidationError, match="duplicate instrument id"):
        validate_catalog(records + [records[0]])


def test_missing_provider_symbol_is_rejected() -> None:
    records = complete_catalog()
    records[0] = replace(records[0], provider_symbol="")

    with pytest.raises(CatalogValidationError, match="missing required fields"):
        validate_catalog(records)


def test_market_type_count_drop_over_policy_is_rejected() -> None:
    previous = [
        instrument(f"KR:{index:06d}", instrument_type=InstrumentType.ETF)
        for index in range(100, 110)
    ]
    current = previous[:8]
    policy = ValidationPolicy(
        max_drop_ratio=0.10,
        sentinels=(),
        required_categories=(),
    )

    with pytest.raises(CatalogValidationError, match="KR ETF count dropped from 10 to 8"):
        validate_catalog(current, previous=previous, policy=policy)


def test_missing_sentinel_is_rejected() -> None:
    records = [record for record in complete_catalog() if record.id != "US:QQQ"]
    records.append(instrument("US:SPY", instrument_type=InstrumentType.ETF))

    with pytest.raises(CatalogValidationError, match="sentinel US:QQQ is missing"):
        validate_catalog(records)


def test_missing_required_korean_etn_category_is_rejected() -> None:
    records = [
        record
        for record in complete_catalog()
        if not (record.market == "KR" and record.instrument_type is InstrumentType.ETN)
    ]

    with pytest.raises(CatalogValidationError, match="required category KR ETN is empty"):
        validate_catalog(records)


def test_custom_sentinel_requires_exact_provider_symbol() -> None:
    policy = ValidationPolicy(
        sentinels=(Sentinel("US:AAPL", "AAPL"),),
        required_categories=(),
    )
    record = instrument("US:AAPL", instrument_type=InstrumentType.COMMON_STOCK, provider_symbol="WRONG")

    with pytest.raises(CatalogValidationError, match="sentinel US:AAPL provider symbol is invalid"):
        validate_catalog([record], policy=policy)
