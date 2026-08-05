from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from .models import InstrumentRecord


def json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_payload(records: Sequence[InstrumentRecord]) -> list[dict[str, Any]]:
    return [record.content_dict() for record in sorted(records, key=lambda item: item.id)]


def canonical_bytes(records: Sequence[InstrumentRecord]) -> bytes:
    return json_bytes(canonical_payload(records))


def content_digest(records: Sequence[InstrumentRecord]) -> str:
    return hashlib.sha256(canonical_bytes(records)).hexdigest()


def content_version(records: Sequence[InstrumentRecord], generated_date: date) -> str:
    return f"{generated_date:%Y%m%d}-{content_digest(records)[:8]}"


def gzip_bytes(payload: Any) -> bytes:
    return gzip.compress(json_bytes(payload), compresslevel=9, mtime=0)


def write_gzip_json(path: Path, payload: Any) -> bytes:
    compressed = gzip_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compressed)
    return compressed


def read_gzip_json(path: Path) -> Any:
    return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
