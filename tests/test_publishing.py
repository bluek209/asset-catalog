from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from asset_catalog.models import (
    InstrumentRecord,
    InstrumentStatus,
    InstrumentType,
)
from asset_catalog.publishing import (
    PublicationVerificationError,
    load_published_catalog,
    publish_catalog,
    verify_site,
)


def record(record_id: str, name: str | None = None) -> InstrumentRecord:
    market, symbol = record_id.split(":", 1)
    korean = market == "KR"
    return InstrumentRecord(
        id=record_id,
        symbol=symbol,
        name=name or symbol,
        english_name=None if korean else (name or symbol),
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


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_first_publication_creates_full_snapshot_without_delta(tmp_path: Path) -> None:
    site = tmp_path / "docs"

    result = publish_catalog(site, [record("US:AAPL")], datetime(2026, 8, 5, tzinfo=UTC))
    published = load_published_catalog(site)

    assert result.changed is True
    assert published.version == result.version
    assert [item.id for item in published.records] == ["US:AAPL"]
    assert published.manifest["deltas"] == []
    assert published.manifest["cumulativeDeltas"] == []
    verify_site(site)


def test_identical_content_does_not_modify_any_artifact(tmp_path: Path) -> None:
    site = tmp_path / "docs"
    records = [record("US:AAPL")]
    publish_catalog(site, records, datetime(2026, 8, 5, tzinfo=UTC))
    before = tree_bytes(site)

    result = publish_catalog(site, records, datetime(2026, 8, 6, tzinfo=UTC))

    assert result.changed is False
    assert tree_bytes(site) == before


def test_changed_publication_creates_adjacent_and_single_file_cumulative_delta(tmp_path: Path) -> None:
    site = tmp_path / "docs"
    first = publish_catalog(site, [record("US:AAPL")], datetime(2026, 8, 5, tzinfo=UTC))
    second = publish_catalog(
        site,
        [record("US:AAPL", "Apple"), record("US:QQQ")],
        datetime(2026, 8, 6, tzinfo=UTC),
    )
    third = publish_catalog(
        site,
        [record("US:AAPL", "Apple Inc"), record("US:QQQ"), record("US:SPY")],
        datetime(2026, 8, 7, tzinfo=UTC),
    )
    published = load_published_catalog(site)

    assert len(published.manifest["deltas"]) == 2
    cumulative = {entry["from"]: entry for entry in published.manifest["cumulativeDeltas"]}
    assert first.version in cumulative
    assert second.version in cumulative
    assert all(entry["to"] == third.version for entry in cumulative.values())
    verify_site(site)


def test_retention_keeps_latest_three_fulls_and_drops_delta_older_than_90_days(tmp_path: Path) -> None:
    site = tmp_path / "docs"
    start = datetime(2026, 1, 1, tzinfo=UTC)
    versions: list[str] = []
    records: list[InstrumentRecord] = []
    for index, days in enumerate((0, 100, 101, 102)):
        records = records + [record(f"US:X{index}")]
        versions.append(publish_catalog(site, records, start + timedelta(days=days)).version)

    manifest = load_published_catalog(site).manifest

    assert [entry["version"] for entry in manifest["fullSnapshots"]] == versions[-3:]
    assert all(entry["from"] != versions[0] for entry in manifest["deltas"])
    assert all(entry["from"] != versions[0] for entry in manifest["cumulativeDeltas"])
    verify_site(site)


def test_verify_rejects_tampered_artifact(tmp_path: Path) -> None:
    site = tmp_path / "docs"
    publish_catalog(site, [record("US:AAPL")], datetime(2026, 8, 5, tzinfo=UTC))
    published = load_published_catalog(site)
    full_path = site / published.manifest["full"]["url"]
    tampered = bytearray(full_path.read_bytes())
    tampered[-1] ^= 0x01
    full_path.write_bytes(tampered)

    with pytest.raises(PublicationVerificationError, match="checksum"):
        verify_site(site)
