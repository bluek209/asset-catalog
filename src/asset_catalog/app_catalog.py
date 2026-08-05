from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .models import InstrumentRecord, InstrumentStatus


class AppCatalogProjectionError(RuntimeError):
    pass


VENUE_CODES = {
    "KOSPI": "KS",
    "KOSDAQ": "KQ",
    "NASDAQ": "Q",
    "NYSE": "N",
    "NYSE_AMERICAN": "A",
    "NYSE_ARCA": "P",
    "CBOE": "Z",
    "IEX": "V",
}


@dataclass(frozen=True, slots=True)
class AppCatalogRecord:
    i: str
    n: str

    def __post_init__(self) -> None:
        if not self.i.strip() or not self.n.strip():
            raise AppCatalogProjectionError("app catalog record has empty fields")

    def to_dict(self) -> dict[str, str]:
        return {"i": self.i, "n": self.n}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AppCatalogRecord:
        if set(value) != {"i", "n"}:
            raise AppCatalogProjectionError("app catalog record has invalid fields")
        return cls(str(value["i"]), str(value["n"]))


def parse_excluded_ids(raw: str) -> set[str]:
    return {value.strip() for value in raw.split(",") if value.strip()}


def project_record(record: InstrumentRecord) -> AppCatalogRecord:
    venue = VENUE_CODES.get(record.exchange)
    if venue is None:
        raise AppCatalogProjectionError(f"unsupported exchange: {record.exchange}")
    if record.market == "KR":
        symbol = record.provider_symbol.removesuffix(".KS").removesuffix(".KQ")
    elif record.market == "US":
        symbol = record.provider_symbol
    else:
        raise AppCatalogProjectionError(f"unsupported market: {record.market}")
    name = " ".join(record.name.split())
    if record.market == "US":
        name = re.sub(r"\s+-\s+Common Stock$", "", name, flags=re.IGNORECASE).strip()
    return AppCatalogRecord(f"{venue}:{symbol}", name)


def project_records(
    records: list[InstrumentRecord],
    *,
    excluded_ids: set[str] | None = None,
) -> list[AppCatalogRecord]:
    excluded = excluded_ids or set()
    projected: dict[str, AppCatalogRecord] = {}
    for record in records:
        if record.status is not InstrumentStatus.ACTIVE:
            continue
        item = project_record(record)
        if item.i in excluded:
            continue
        if item.i in projected:
            raise AppCatalogProjectionError(f"duplicate app catalog id: {item.i}")
        projected[item.i] = item
    return [projected[identity] for identity in sorted(projected)]


def validate_projected_drop(
    current: list[AppCatalogRecord],
    previous: list[AppCatalogRecord],
    *,
    max_drop_ratio: float,
) -> None:
    if not 0 <= max_drop_ratio < 1:
        raise ValueError("max_drop_ratio must be between 0 and 1")
    old_counts = Counter(record.i.split(":", 1)[0] for record in previous)
    new_counts = Counter(record.i.split(":", 1)[0] for record in current)
    for venue, old_count in sorted(old_counts.items()):
        new_count = new_counts[venue]
        if (old_count - new_count) / old_count > max_drop_ratio:
            raise AppCatalogProjectionError(
                f"{venue} count dropped from {old_count} to {new_count}",
            )
