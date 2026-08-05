import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from asset_catalog.app_catalog import AppCatalogRecord
from asset_catalog.app_publishing import (
    PublicationVerificationError,
    load_published_catalog,
    publish_catalog,
    verify_site,
)


def record(identity: str, name: str | None = None) -> AppCatalogRecord:
    return AppCatalogRecord(identity, name or identity)


def tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_first_publish_creates_minimal_verified_site(tmp_path: Path) -> None:
    site = tmp_path / "site"
    result = publish_catalog(
        site,
        [record("Q:AAPL", "Apple Inc."), record("KQ:035900", "JYP Ent.")],
        datetime(2026, 8, 5, tzinfo=UTC),
    )
    manifest = json.loads((site / "manifest.json").read_text())
    full_bytes = (site / manifest["f"]["p"]).read_bytes()

    assert set(manifest) == {"v", "l", "f", "d"}
    assert manifest["l"] == result.version
    assert manifest["d"] == {}
    assert manifest["f"] == {
        "p": f"f/{result.version}.json.gz",
        "b": len(full_bytes),
        "h": hashlib.sha256(full_bytes).hexdigest(),
        "n": 2,
    }
    assert json.loads(gzip.decompress(full_bytes)) == {
        "v": 1,
        "r": [
            {"i": "KQ:035900", "n": "JYP Ent."},
            {"i": "Q:AAPL", "n": "Apple Inc."},
        ],
    }
    verify_site(site)


def test_unchanged_content_does_not_touch_site(tmp_path: Path) -> None:
    site = tmp_path / "site"
    records = [record("Q:AAPL")]
    first = publish_catalog(site, records, datetime(2026, 8, 5, tzinfo=UTC))
    before = tree(site)

    second = publish_catalog(site, records, datetime(2026, 8, 6, tzinfo=UTC))

    assert second.changed is False
    assert second.version == first.version
    assert tree(site) == before


def test_changed_content_creates_cumulative_delta_and_prunes_old_full(tmp_path: Path) -> None:
    site = tmp_path / "site"
    initial = [record(f"Q:X{index:03d}") for index in range(100)]
    second_records = [*initial, record("Q:NEW")]
    second_records[0] = record("Q:X000", "Changed once")
    third_records = [item for item in second_records if item.i != "Q:NEW"]
    third_records[0] = record("Q:X000", "Changed twice")
    third_records.append(record("Q:SPY"))
    first = publish_catalog(site, initial, datetime(2026, 8, 5, tzinfo=UTC))
    second = publish_catalog(
        site,
        second_records,
        datetime(2026, 8, 6, tzinfo=UTC),
    )
    third = publish_catalog(
        site,
        third_records,
        datetime(2026, 8, 7, tzinfo=UTC),
    )
    manifest = load_published_catalog(site).manifest

    assert manifest["l"] == third.version
    assert set(manifest["d"]) == {first.version, second.version}
    assert list((site / "f").glob("*.json.gz")) == [site / manifest["f"]["p"]]
    verify_site(site)


def test_large_delta_is_omitted_for_full_fallback(tmp_path: Path) -> None:
    site = tmp_path / "site"
    first = publish_catalog(site, [record("Q:AAPL")], datetime(2026, 8, 5, tzinfo=UTC))

    publish_catalog(
        site,
        [record("Q:QQQ")],
        datetime(2026, 8, 6, tzinfo=UTC),
        max_delta_ratio=0,
    )

    assert first.version not in load_published_catalog(site).manifest["d"]


def test_verify_rejects_tampered_artifact(tmp_path: Path) -> None:
    site = tmp_path / "site"
    publish_catalog(site, [record("Q:AAPL")], datetime(2026, 8, 5, tzinfo=UTC))
    published = load_published_catalog(site)
    full_path = site / published.manifest["f"]["p"]
    data = bytearray(full_path.read_bytes())
    data[-1] ^= 1
    full_path.write_bytes(data)

    with pytest.raises(PublicationVerificationError, match="checksum"):
        verify_site(site)
