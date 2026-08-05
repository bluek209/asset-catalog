from datetime import UTC, datetime
from pathlib import Path

import pytest

from asset_catalog.models import (
    InstrumentRecord,
    InstrumentStatus,
    InstrumentType,
)
from asset_catalog.app_publishing import load_published_catalog, publish_catalog
from asset_catalog.app_catalog import AppCatalogRecord
from asset_catalog.pipeline import CatalogPipeline
from asset_catalog.sources.data_go_kr import KoreanSourceError
from asset_catalog.validation import ValidationPolicy


def record(record_id: str) -> InstrumentRecord:
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
        instrument_type=InstrumentType.COMMON_STOCK,
        status=InstrumentStatus.ACTIVE,
        provider_id="yahoo",
        provider_symbol=f"{symbol}.KS" if korean else symbol,
        aliases=(symbol,),
        source_updated_date="2026-08-05",
    )


class FakeSource:
    def __init__(self, records: list[InstrumentRecord]) -> None:
        self.records = records
        self.calls = 0

    def collect_all(self) -> list[InstrumentRecord]:
        self.calls += 1
        return self.records

    def collect(self) -> list[InstrumentRecord]:
        self.calls += 1
        return self.records


def policy() -> ValidationPolicy:
    return ValidationPolicy(sentinels=(), required_categories=(), max_drop_ratio=0.5)


def test_pipeline_collects_validates_reconciles_and_publishes(tmp_path: Path) -> None:
    korean = FakeSource([record("KR:005930")])
    us = FakeSource([record("US:AAPL")])
    pipeline = CatalogPipeline(korean, us, validation_policy=policy())

    result = pipeline.run(tmp_path / "docs", datetime(2026, 8, 5, tzinfo=UTC))

    assert result.changed is True
    assert result.record_count == 2
    assert korean.calls == 1
    assert us.calls == 1


def test_source_failure_does_not_modify_existing_manifest(tmp_path: Path) -> None:
    site = tmp_path / "docs"
    publish_catalog(site, [AppCatalogRecord("Q:AAPL", "AAPL")], datetime(2026, 8, 4, tzinfo=UTC))
    before = {path.relative_to(site): path.read_bytes() for path in site.rglob("*") if path.is_file()}

    class FailingKoreanSource:
        def collect_all(self) -> list[InstrumentRecord]:
            raise KoreanSourceError("source failed")

    failing = FailingKoreanSource()
    sleeps: list[float] = []
    pipeline = CatalogPipeline(
        failing,
        FakeSource([record("US:AAPL")]),
        validation_policy=policy(),
        sleeper=sleeps.append,
    )

    with pytest.raises(KoreanSourceError, match="source failed"):
        pipeline.run(site, datetime(2026, 8, 5, tzinfo=UTC))

    assert sleeps == [1.0, 2.0]
    assert {path.relative_to(site): path.read_bytes() for path in site.rglob("*") if path.is_file()} == before


def test_pipeline_retries_each_source_until_third_attempt(tmp_path: Path) -> None:
    class FlakyKoreanSource:
        def __init__(self) -> None:
            self.calls = 0

        def collect_all(self) -> list[InstrumentRecord]:
            self.calls += 1
            if self.calls < 3:
                raise KoreanSourceError("temporary")
            return [record("KR:005930")]

    korean = FlakyKoreanSource()
    sleeps: list[float] = []
    pipeline = CatalogPipeline(
        korean,
        FakeSource([record("US:AAPL")]),
        validation_policy=policy(),
        sleeper=sleeps.append,
    )

    result = pipeline.run(tmp_path / "site", datetime(2026, 8, 5, tzinfo=UTC))

    assert result.changed is True
    assert korean.calls == 3
    assert sleeps == [1.0, 2.0]


def test_pipeline_excludes_configured_compact_ids_from_publication(tmp_path: Path) -> None:
    site = tmp_path / "site"
    pipeline = CatalogPipeline(
        FakeSource([record("KR:005930")]),
        FakeSource([record("US:AAPL"), record("US:PRIVATE")]),
        validation_policy=policy(),
        excluded_ids={"Q:PRIVATE"},
    )

    pipeline.run(site, datetime(2026, 8, 5, tzinfo=UTC))

    assert [item.i for item in load_published_catalog(site).records] == ["KS:005930", "Q:AAPL"]
