from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .app_catalog import AppCatalogRecord


def catalog_payload(records: Sequence[AppCatalogRecord]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda item: item.i)
    return {"v": 1, "r": [record.to_dict() for record in ordered]}


def pretty_catalog_bytes(records: Sequence[AppCatalogRecord]) -> bytes:
    rendered = json.dumps(
        catalog_payload(records),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    return f"{rendered}\n".encode("utf-8")


def write_pretty_catalog(path: Path, records: Sequence[AppCatalogRecord]) -> bytes:
    data = pretty_catalog_bytes(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data
