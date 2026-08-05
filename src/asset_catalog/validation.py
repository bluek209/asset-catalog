from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .models import InstrumentRecord, InstrumentStatus, InstrumentType


class CatalogValidationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Sentinel:
    id: str
    provider_symbol: str


@dataclass(frozen=True, slots=True)
class RequiredCategory:
    label: str
    market: str
    types: tuple[InstrumentType, ...]


DEFAULT_SENTINELS = (
    Sentinel("KR:005930", "005930.KS"),
    Sentinel("KR:035900", "035900.KQ"),
    Sentinel("KR:367380", "367380.KS"),
    Sentinel("US:AAPL", "AAPL"),
    Sentinel("US:QQQ", "QQQ"),
)

STOCK_TYPES_KR = (
    InstrumentType.COMMON_STOCK,
    InstrumentType.PREFERRED_STOCK,
    InstrumentType.REIT,
    InstrumentType.SPAC,
)
STOCK_TYPES_US = (
    InstrumentType.COMMON_STOCK,
    InstrumentType.PREFERRED_STOCK,
    InstrumentType.ADR,
    InstrumentType.REIT,
)
DEFAULT_REQUIRED_CATEGORIES = (
    RequiredCategory("KR stock", "KR", STOCK_TYPES_KR),
    RequiredCategory("KR ETF", "KR", (InstrumentType.ETF,)),
    RequiredCategory("KR ETN", "KR", (InstrumentType.ETN,)),
    RequiredCategory("US stock", "US", STOCK_TYPES_US),
    RequiredCategory("US ETF", "US", (InstrumentType.ETF,)),
    RequiredCategory("US ETN", "US", (InstrumentType.ETN,)),
)


@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    max_drop_ratio: float = 0.10
    sentinels: tuple[Sentinel, ...] = DEFAULT_SENTINELS
    required_categories: tuple[RequiredCategory, ...] = DEFAULT_REQUIRED_CATEGORIES

    def __post_init__(self) -> None:
        if not 0 <= self.max_drop_ratio < 1:
            raise ValueError("max_drop_ratio must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    total_count: int
    active_count: int
    group_counts: dict[str, int]
    sentinel_ids: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalCount": self.total_count,
            "activeCount": self.active_count,
            "groupCounts": dict(sorted(self.group_counts.items())),
            "sentinelIds": list(self.sentinel_ids),
            "warnings": list(self.warnings),
        }


def _active_counts(records: list[InstrumentRecord]) -> Counter[tuple[str, InstrumentType]]:
    return Counter(
        (record.market, record.instrument_type)
        for record in records
        if record.status is InstrumentStatus.ACTIVE
    )


def validate_catalog(
    records: list[InstrumentRecord],
    *,
    previous: list[InstrumentRecord] | None = None,
    policy: ValidationPolicy = ValidationPolicy(),
) -> ValidationReport:
    by_id: dict[str, InstrumentRecord] = {}
    market_symbols: set[tuple[str, str]] = set()
    for record in records:
        if record.id in by_id:
            raise CatalogValidationError(f"duplicate instrument id: {record.id}")
        by_id[record.id] = record
        market_symbol = (record.market, record.symbol.upper())
        if market_symbol in market_symbols:
            raise CatalogValidationError(
                f"duplicate market symbol: {record.market}:{record.symbol}",
            )
        market_symbols.add(market_symbol)
        if not all(
            value.strip()
            for value in (
                record.id,
                record.symbol,
                record.name,
                record.market,
                record.exchange,
                record.currency,
                record.provider_id,
                record.provider_symbol,
                record.source_updated_date,
            )
        ):
            raise CatalogValidationError(f"instrument {record.id} is missing required fields")

    active_counts = _active_counts(records)
    for category in policy.required_categories:
        count = sum(active_counts[(category.market, item_type)] for item_type in category.types)
        if count == 0:
            raise CatalogValidationError(f"required category {category.label} is empty")

    if previous is not None:
        previous_counts = _active_counts(previous)
        for (market, item_type), previous_count in sorted(
            previous_counts.items(),
            key=lambda item: (item[0][0], item[0][1].value),
        ):
            if previous_count <= 0:
                continue
            current_count = active_counts[(market, item_type)]
            drop_ratio = (previous_count - current_count) / previous_count
            if drop_ratio > policy.max_drop_ratio:
                raise CatalogValidationError(
                    f"{market} {item_type.value.replace('_', ' ')} count dropped "
                    f"from {previous_count} to {current_count}",
                )

    sentinel_ids: list[str] = []
    for sentinel in policy.sentinels:
        record = by_id.get(sentinel.id)
        if record is None or record.status is not InstrumentStatus.ACTIVE:
            raise CatalogValidationError(f"sentinel {sentinel.id} is missing")
        if record.provider_symbol != sentinel.provider_symbol:
            raise CatalogValidationError(
                f"sentinel {sentinel.id} provider symbol is invalid",
            )
        sentinel_ids.append(sentinel.id)

    group_counts = {
        f"{market}:{item_type.value}": count
        for (market, item_type), count in active_counts.items()
    }
    return ValidationReport(
        total_count=len(records),
        active_count=sum(active_counts.values()),
        group_counts=dict(sorted(group_counts.items())),
        sentinel_ids=tuple(sentinel_ids),
    )
