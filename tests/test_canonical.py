from datetime import date
from dataclasses import replace

from asset_catalog.canonical import canonical_bytes, content_version
from asset_catalog.models import (
    InstrumentRecord,
    InstrumentStatus,
    InstrumentType,
)


def record(record_id: str, symbol: str) -> InstrumentRecord:
    is_korean = record_id.startswith("KR:")
    return InstrumentRecord(
        id=record_id,
        symbol=symbol,
        name=symbol,
        english_name=None,
        market="KR" if is_korean else "US",
        exchange="KOSPI" if is_korean else "NASDAQ",
        currency="KRW" if is_korean else "USD",
        instrument_type=InstrumentType.COMMON_STOCK,
        status=InstrumentStatus.ACTIVE,
        provider_id="yahoo",
        provider_symbol=f"{symbol}.KS" if is_korean else symbol,
        aliases=(symbol,),
        source_updated_date="2026-08-05",
    )


def test_canonical_content_is_order_independent() -> None:
    samsung = record("KR:005930", "005930")
    apple = record("US:AAPL", "AAPL")

    assert canonical_bytes([samsung, apple]) == canonical_bytes([apple, samsung])


def test_version_uses_date_and_canonical_content_hash() -> None:
    records = [record("US:AAPL", "AAPL")]

    version = content_version(records, date(2026, 8, 5))

    assert version.startswith("20260805-")
    assert version == content_version(list(reversed(records)), date(2026, 8, 5))


def test_source_observation_date_does_not_change_business_content_version() -> None:
    original = record("US:AAPL", "AAPL")
    observed_next_day = replace(original, source_updated_date="2026-08-06")

    assert canonical_bytes([original]) == canonical_bytes([observed_next_day])
