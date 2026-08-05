from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .canonical import content_digest, content_version, gzip_bytes, json_bytes
from .models import InstrumentRecord, InstrumentStatus
from .versioning import (
    CatalogDelta,
    build_delta,
    compose_deltas,
    verify_reconstruction,
)


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
    records: list[InstrumentRecord]

    @property
    def version(self) -> str:
        return str(self.manifest["latestVersion"])


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_gzip_artifact(site: Path, relative: str, payload: Any) -> dict[str, Any]:
    data = gzip_bytes(payload)
    path = site / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"url": relative, "size": len(data), "sha256": _sha256(data)}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_gzip(path: Path) -> Any:
    return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))


def load_published_catalog(site_root: Path) -> PublishedCatalog:
    manifest_path = site_root / "manifest.json"
    if not manifest_path.exists():
        raise PublicationVerificationError("published manifest does not exist")
    try:
        manifest = _read_json(manifest_path)
        payload = _read_gzip(site_root / manifest["full"]["url"])
        records = [InstrumentRecord.from_dict(item) for item in payload["records"]]
        return PublishedCatalog(manifest=manifest, records=records)
    except PublicationVerificationError:
        raise
    except Exception as error:
        raise PublicationVerificationError("published catalog could not be loaded") from error


def _entry_date(version: str) -> datetime:
    try:
        return datetime.strptime(version[:8], "%Y%m%d").replace(tzinfo=UTC)
    except ValueError as error:
        raise PublicationVerificationError(f"invalid catalog version: {version}") from error


def _artifact_entry(
    artifact: dict[str, Any],
    *,
    version: str | None = None,
    from_version: str | None = None,
    to_version: str | None = None,
    created_at: datetime,
    record_count: int | None = None,
) -> dict[str, Any]:
    entry = dict(artifact)
    entry["createdAt"] = created_at.isoformat().replace("+00:00", "Z")
    if version is not None:
        entry["version"] = version
    if from_version is not None:
        entry["from"] = from_version
    if to_version is not None:
        entry["to"] = to_version
    if record_count is not None:
        entry["recordCount"] = record_count
    return entry


def _active_group_counts(records: list[InstrumentRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        if record.status is not InstrumentStatus.ACTIVE:
            continue
        key = f"{record.market}:{record.instrument_type.value}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def publish_catalog(
    site_root: Path,
    records: list[InstrumentRecord],
    generated_at: datetime,
) -> PublishResult:
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    generated_at = generated_at.astimezone(UTC)
    previous = load_published_catalog(site_root) if (site_root / "manifest.json").exists() else None
    current_digest = content_digest(records)
    if previous is not None and previous.manifest.get("contentSha256") == current_digest:
        return PublishResult(False, previous.version, site_root / "manifest.json")

    version = content_version(records, generated_at.date())
    staging = Path(tempfile.mkdtemp(prefix=f".{site_root.name}-publish-", dir=site_root.parent))
    try:
        if site_root.exists():
            shutil.copytree(site_root, staging, dirs_exist_ok=True)

        full_relative = f"catalog/full/catalog-{version}.json.gz"
        full_artifact = _write_gzip_artifact(
            staging,
            full_relative,
            {
                "schemaVersion": 1,
                "version": version,
                "records": [record.to_dict() for record in sorted(records, key=lambda item: item.id)],
            },
        )
        full_entry = _artifact_entry(
            full_artifact,
            version=version,
            created_at=generated_at,
            record_count=len(records),
        )

        prior_manifest = previous.manifest if previous is not None else {}
        full_snapshots = [*prior_manifest.get("fullSnapshots", []), full_entry][-3:]
        deltas: list[dict[str, Any]] = list(prior_manifest.get("deltas", []))
        cumulative_entries: list[dict[str, Any]] = []

        if previous is not None:
            adjacent = build_delta(previous.version, previous.records, version, records)
            verify_reconstruction(previous.records, adjacent, records, base_version=previous.version)
            adjacent_relative = f"catalog/delta/{previous.version}--{version}.json.gz"
            adjacent_artifact = _write_gzip_artifact(staging, adjacent_relative, adjacent.to_dict())
            adjacent_entry = _artifact_entry(
                adjacent_artifact,
                from_version=previous.version,
                to_version=version,
                created_at=generated_at,
            )
            deltas.append(adjacent_entry)

            cutoff = generated_at - timedelta(days=90)
            deltas = [
                entry
                for entry in deltas
                if _entry_date(str(entry["from"])) >= cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
            ]

            for entry in prior_manifest.get("cumulativeDeltas", []):
                from_version = str(entry["from"])
                if _entry_date(from_version) < cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
                    continue
                previous_cumulative = CatalogDelta.from_dict(_read_gzip(staging / entry["url"]))
                cumulative = compose_deltas(previous_cumulative, adjacent)
                relative = f"catalog/cumulative/{from_version}--{version}.json.gz"
                artifact = _write_gzip_artifact(staging, relative, cumulative.to_dict())
                cumulative_entries.append(
                    _artifact_entry(
                        artifact,
                        from_version=from_version,
                        to_version=version,
                        created_at=generated_at,
                    ),
                )
            cumulative_entries.append(dict(adjacent_entry))

        manifest = {
            "schemaVersion": 1,
            "latestVersion": version,
            "generatedAt": generated_at.isoformat().replace("+00:00", "Z"),
            "contentSha256": current_digest,
            "full": full_entry,
            "fullSnapshots": full_snapshots,
            "deltas": deltas,
            "cumulativeDeltas": cumulative_entries,
            "counts": _active_group_counts(records),
        }

        _prune_artifacts(staging, manifest)
        report_path = staging / "reports/latest-summary.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_bytes(
            json_bytes(
                {
                    "version": version,
                    "generatedAt": manifest["generatedAt"],
                    "recordCount": len(records),
                    "activeRecordCount": sum(manifest["counts"].values()),
                    "counts": manifest["counts"],
                },
            ),
        )
        (staging / "manifest.json").write_bytes(json_bytes(manifest))
        verify_site(staging)
        _replace_tree(staging, site_root)
        return PublishResult(True, version, site_root / "manifest.json")
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _referenced_urls(manifest: dict[str, Any]) -> set[str]:
    entries = [
        *manifest.get("fullSnapshots", []),
        *manifest.get("deltas", []),
        *manifest.get("cumulativeDeltas", []),
    ]
    return {str(entry["url"]) for entry in entries}


def _prune_artifacts(site: Path, manifest: dict[str, Any]) -> None:
    referenced = _referenced_urls(manifest)
    catalog_root = site / "catalog"
    if not catalog_root.exists():
        return
    for path in catalog_root.rglob("*.json.gz"):
        if path.relative_to(site).as_posix() not in referenced:
            path.unlink()


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


def verify_site(site_root: Path) -> None:
    manifest_path = site_root / "manifest.json"
    if not manifest_path.exists():
        raise PublicationVerificationError("published manifest does not exist")
    try:
        manifest = _read_json(manifest_path)
    except Exception as error:
        raise PublicationVerificationError("published manifest is invalid") from error
    if int(manifest.get("schemaVersion", 0)) != 1:
        raise PublicationVerificationError("unsupported manifest schema")
    for entry in [
        *manifest.get("fullSnapshots", []),
        *manifest.get("deltas", []),
        *manifest.get("cumulativeDeltas", []),
    ]:
        path = site_root / str(entry["url"])
        if not path.exists():
            raise PublicationVerificationError(f"referenced artifact is missing: {entry['url']}")
        data = path.read_bytes()
        if len(data) != int(entry["size"]):
            raise PublicationVerificationError(f"artifact size is invalid: {entry['url']}")
        if _sha256(data) != str(entry["sha256"]):
            raise PublicationVerificationError(f"artifact checksum is invalid: {entry['url']}")
        try:
            gzip.decompress(data)
        except Exception as error:
            raise PublicationVerificationError(f"artifact compression is invalid: {entry['url']}") from error

    published = load_published_catalog(site_root)
    if manifest["full"]["url"] not in _referenced_urls(manifest):
        raise PublicationVerificationError("current full snapshot is not retained")
    if content_digest(published.records) != manifest.get("contentSha256"):
        raise PublicationVerificationError("full snapshot content hash is invalid")
    if published.version != manifest["full"]["version"]:
        raise PublicationVerificationError("full snapshot version is invalid")
