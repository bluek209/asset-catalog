from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .app_catalog import AppCatalogRecord


def catalog_payload(records: Sequence[AppCatalogRecord]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda item: item.i)
    return {"v": 1, "r": [record.to_dict() for record in ordered]}


def pretty_json_bytes(payload: Any) -> bytes:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    return f"{rendered}\n".encode("utf-8")


def write_pretty_json(path: Path, payload: Any) -> bytes:
    data = pretty_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def pretty_catalog_bytes(records: Sequence[AppCatalogRecord]) -> bytes:
    return pretty_json_bytes(catalog_payload(records))


def write_pretty_catalog(path: Path, records: Sequence[AppCatalogRecord]) -> bytes:
    return write_pretty_json(path, catalog_payload(records))
