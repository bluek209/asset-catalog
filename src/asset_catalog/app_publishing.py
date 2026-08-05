from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from .app_catalog import AppCatalogProjectionError, AppCatalogRecord
from .app_versioning import AppCatalogDelta, DeltaApplicationError, apply_delta, build_delta, compose_deltas
from .canonical import gzip_bytes, json_bytes


class PublicationVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PublishResult:
    changed: bool
    version: str
    manifest_path: Path


@dataclass(frozen=True, slots=True)
class PublishedCatalog:
    manifest: dict[str, Any]
    records: list[AppCatalogRecord]

    @property
    def version(self) -> str:
        return str(self.manifest["l"])


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_bytes(records: list[AppCatalogRecord]) -> bytes:
    return json_bytes([record.to_dict() for record in sorted(records, key=lambda item: item.i)])


def _content_version(records: list[AppCatalogRecord], instant: datetime) -> str:
    return f"{instant:%Y%m%d}-{_sha256(_record_bytes(records))[:8]}"


def _safe_relative(raw: object) -> str:
    value = str(raw)
    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
        raise PublicationVerificationError("unsafe artifact path")
    return value


def _entry(relative: str, data: bytes, count: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"p": relative, "b": len(data), "h": _sha256(data)}
    if count is not None:
        result["n"] = count
    return result


def _write(root: Path, relative: str, payload: Any) -> tuple[dict[str, Any], bytes]:
    data = gzip_bytes(payload)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _entry(relative, data), data


def _read(root: Path, entry: dict[str, Any]) -> Any:
    relative = _safe_relative(entry.get("p"))
    path = root / relative
    if not path.is_file():
        raise PublicationVerificationError(f"referenced artifact is missing: {relative}")
    data = path.read_bytes()
    if len(data) != int(entry.get("b", -1)):
        raise PublicationVerificationError(f"artifact size is invalid: {relative}")
    if _sha256(data) != str(entry.get("h", "")):
        raise PublicationVerificationError(f"artifact checksum is invalid: {relative}")
    try:
        return json.loads(gzip.decompress(data).decode("utf-8"))
    except Exception as error:
        raise PublicationVerificationError(f"artifact compression is invalid: {relative}") from error


def load_published_catalog(site_root: Path) -> PublishedCatalog:
    try:
        manifest = json.loads((site_root / "manifest.json").read_text(encoding="utf-8"))
        if set(manifest) != {"v", "l", "f", "d"} or int(manifest["v"]) != 1:
            raise PublicationVerificationError("unsupported manifest schema")
        full = _read(site_root, manifest["f"])
        if set(full) != {"v", "r"} or int(full["v"]) != 1:
            raise PublicationVerificationError("unsupported full schema")
        records = [AppCatalogRecord.from_dict(item) for item in full["r"]]
        if records != sorted(records, key=lambda item: item.i):
            raise PublicationVerificationError("full catalog is not sorted")
        if len({record.i for record in records}) != len(records):
            raise PublicationVerificationError("full catalog has duplicate identities")
        if len(records) != int(manifest["f"].get("n", -1)):
            raise PublicationVerificationError("full catalog count is invalid")
        return PublishedCatalog(manifest, records)
    except PublicationVerificationError:
        raise
    except Exception as error:
        raise PublicationVerificationError("published catalog could not be loaded") from error


def _version_date(version: str) -> datetime:
    if re.fullmatch(r"\d{8}-[0-9a-f]{8}", version) is None:
        raise PublicationVerificationError(f"invalid catalog version: {version}")
    return datetime.strptime(version[:8], "%Y%m%d").replace(tzinfo=UTC)


def _replace_tree(staging: Path, destination: Path) -> None:
    backup = destination.parent / f".{destination.name}-backup"
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        os.replace(destination, backup)
    try:
        os.replace(staging, destination)
    except Exception:
        if backup.exists():
            os.replace(backup, destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def publish_catalog(
    site_root: Path,
    records: list[AppCatalogRecord],
    generated_at: datetime,
    *,
    retention_days: int = 90,
    max_delta_ratio: float = 0.60,
) -> PublishResult:
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    if retention_days < 0 or not 0 <= max_delta_ratio <= 1:
        raise ValueError("invalid publication policy")
    generated_at = generated_at.astimezone(UTC)
    ordered = sorted(records, key=lambda item: item.i)
    if len({record.i for record in ordered}) != len(ordered):
        raise PublicationVerificationError("catalog has duplicate identities")
    previous = None
    if (site_root / "manifest.json").exists():
        verify_site(site_root)
        previous = load_published_catalog(site_root)
    version = _content_version(ordered, generated_at)
    if previous is not None and _record_bytes(previous.records) == _record_bytes(ordered):
        return PublishResult(False, previous.version, site_root / "manifest.json")

    site_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{site_root.name}-publish-", dir=site_root.parent))
    try:
        full_path = f"f/{version}.json.gz"
        full_entry, full_data = _write(
            staging,
            full_path,
            {"v": 1, "r": [record.to_dict() for record in ordered]},
        )
        full_entry["n"] = len(ordered)
        delta_entries: dict[str, dict[str, Any]] = {}
        if previous is not None:
            adjacent = build_delta(previous.version, previous.records, version, ordered)
            if apply_delta(previous.records, adjacent, base_version=previous.version) != ordered:
                raise PublicationVerificationError("adjacent delta reconstruction failed")
            cutoff = (generated_at - timedelta(days=retention_days)).replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
            candidates: list[AppCatalogDelta] = []
            if _version_date(previous.version) >= cutoff:
                candidates.append(adjacent)
            for from_version, entry in previous.manifest["d"].items():
                if _version_date(str(from_version)) >= cutoff:
                    candidates.append(compose_deltas(AppCatalogDelta.from_dict(_read(site_root, entry)), adjacent))
            for delta in candidates:
                relative = f"d/{delta.from_version}--{version}.json.gz"
                entry, data = _write(staging, relative, delta.to_dict())
                if len(data) < len(full_data) * max_delta_ratio:
                    delta_entries[delta.from_version] = entry
                else:
                    (staging / relative).unlink()
        manifest = {"v": 1, "l": version, "f": full_entry, "d": dict(sorted(delta_entries.items()))}
        (staging / "manifest.json").write_bytes(json_bytes(manifest))
        verify_site(staging)
        _replace_tree(staging, site_root)
        return PublishResult(True, version, site_root / "manifest.json")
    except (DeltaApplicationError, AppCatalogProjectionError) as error:
        raise PublicationVerificationError("catalog delta could not be published") from error
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify_site(site_root: Path) -> None:
    published = load_published_catalog(site_root)
    version = published.version
    if version.split("-", 1)[1] != _sha256(_record_bytes(published.records))[:8]:
        raise PublicationVerificationError("full snapshot version is invalid")
    _version_date(version)
    if published.manifest["f"]["p"] != f"f/{version}.json.gz":
        raise PublicationVerificationError("full snapshot path is invalid")
    for from_version, entry in published.manifest["d"].items():
        try:
            delta = AppCatalogDelta.from_dict(_read(site_root, entry))
        except DeltaApplicationError as error:
            raise PublicationVerificationError("delta payload is invalid") from error
        if delta.from_version != from_version or delta.to_version != version:
            raise PublicationVerificationError("delta edge is invalid")
        if entry["p"] != f"d/{from_version}--{version}.json.gz":
            raise PublicationVerificationError("delta path is invalid")
