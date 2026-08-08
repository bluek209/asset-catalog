import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from asset_catalog.crypto_catalog import CryptoCatalogRecord
from asset_catalog.crypto_publishing import (
    CryptoPublicationVerificationError,
    load_published_crypto_catalog,
    publish_crypto_catalog,
    verify_crypto_site,
)


def record(identity: str, korean: str | None = None, english: str | None = None) -> CryptoCatalogRecord:
    symbol = identity.split(":", 1)[1].rsplit("-", 1)[0]
    return CryptoCatalogRecord(identity, korean or symbol, english or symbol)


def tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_first_crypto_publish_creates_minimal_verified_tree(tmp_path: Path) -> None:
    site = tmp_path / "crypto"
    result = publish_crypto_catalog(
        site,
        [
            record("UP:BTC-KRW", "비트코인", "Bitcoin"),
            record("BN:BTC-USDT", "비트코인", "Bitcoin"),
        ],
        datetime(2026, 8, 8, tzinfo=UTC),
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
            {"i": "BN:BTC-USDT", "k": "비트코인", "e": "Bitcoin"},
            {"i": "UP:BTC-KRW", "k": "비트코인", "e": "Bitcoin"},
        ],
    }
    assert result.manifest_path == site / "manifest.json"
    verify_crypto_site(site)


def test_unchanged_crypto_content_does_not_touch_tree(tmp_path: Path) -> None:
    site = tmp_path / "crypto"
    records = [record("UP:BTC-KRW")]
    first = publish_crypto_catalog(site, records, datetime(2026, 8, 8, tzinfo=UTC))
    before = tree(site)

    second = publish_crypto_catalog(site, records, datetime(2026, 8, 9, tzinfo=UTC))

    assert second.changed is False
    assert second.version == first.version
    assert tree(site) == before


def test_changed_crypto_content_creates_cumulative_delta(tmp_path: Path) -> None:
    site = tmp_path / "crypto"
    initial = [record(f"UP:X{index:03d}-KRW", f"코인 {index}", f"Coin {index}") for index in range(100)]
    second_records = [*initial, record("BT:NEW-KRW", "신규", "New")]
    second_records[0] = record("UP:X000-KRW", "첫 변경", "Changed once")
    third_records = [item for item in second_records if item.i != "BT:NEW-KRW"]
    third_records[0] = record("UP:X000-KRW", "두번째 변경", "Changed twice")
    third_records.append(record("BN:BTC-USDT", "비트코인", "Bitcoin"))

    first = publish_crypto_catalog(site, initial, datetime(2026, 8, 8, tzinfo=UTC))
    second = publish_crypto_catalog(site, second_records, datetime(2026, 8, 9, tzinfo=UTC))
    third = publish_crypto_catalog(site, third_records, datetime(2026, 8, 10, tzinfo=UTC))
    published = load_published_crypto_catalog(site)

    assert published.version == third.version
    assert set(published.manifest["d"]) == {first.version, second.version}
    assert list((site / "f").glob("*.json.gz")) == [site / published.manifest["f"]["p"]]
    verify_crypto_site(site)


def test_large_crypto_delta_is_omitted_for_full_fallback(tmp_path: Path) -> None:
    site = tmp_path / "crypto"
    first = publish_crypto_catalog(site, [record("UP:BTC-KRW")], datetime(2026, 8, 8, tzinfo=UTC))

    publish_crypto_catalog(
        site,
        [record("BN:ETH-USDT")],
        datetime(2026, 8, 9, tzinfo=UTC),
        max_delta_ratio=0,
    )

    assert first.version not in load_published_crypto_catalog(site).manifest["d"]


def test_crypto_verify_rejects_tampered_artifact_and_unsafe_path(tmp_path: Path) -> None:
    site = tmp_path / "crypto"
    publish_crypto_catalog(site, [record("UP:BTC-KRW")], datetime(2026, 8, 8, tzinfo=UTC))
    published = load_published_crypto_catalog(site)
    full_path = site / published.manifest["f"]["p"]
    data = bytearray(full_path.read_bytes())
    data[-1] ^= 1
    full_path.write_bytes(data)

    with pytest.raises(CryptoPublicationVerificationError, match="checksum"):
        verify_crypto_site(site)

    published.manifest["f"]["p"] = "../secret"
    (site / "manifest.json").write_text(json.dumps(published.manifest))
    with pytest.raises(CryptoPublicationVerificationError, match="unsafe"):
        verify_crypto_site(site)
