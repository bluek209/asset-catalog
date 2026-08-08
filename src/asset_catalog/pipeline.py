from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import sleep
from collections.abc import Callable
from typing import Protocol

from .app_catalog import AppCatalogRecord, project_records, validate_projected_drop
from .app_publishing import PublishResult, load_published_catalog, publish_catalog
from .models import InstrumentRecord
from .validation import ValidationPolicy, validate_catalog


class KoreanCatalogSource(Protocol):
    def collect_all(self) -> list[InstrumentRecord]: ...


class UsCatalogSource(Protocol):
    def collect(self) -> list[InstrumentRecord]: ...


@dataclass(frozen=True, slots=True)
class PipelineResult:
    changed: bool
    version: str
    record_count: int


class CatalogPipeline:
    def __init__(
        self,
        korean_source: KoreanCatalogSource,
        us_source: UsCatalogSource,
        *,
        validation_policy: ValidationPolicy = ValidationPolicy(),
        excluded_ids: set[str] | None = None,
        attempts: int = 3,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        if attempts <= 0:
            raise ValueError("attempts must be positive")
        self._korean_source = korean_source
        self._us_source = us_source
        self._validation_policy = validation_policy
        self._excluded_ids = excluded_ids or set()
        self._attempts = attempts
        self._sleeper = sleeper

    def _retry(self, operation: Callable[[], list[InstrumentRecord]]) -> list[InstrumentRecord]:
        for attempt in range(self._attempts):
            try:
                return operation()
            except Exception:
                if attempt == self._attempts - 1:
                    raise
                self._sleeper(float(2**attempt))
        raise RuntimeError("unreachable")

    def run(self, site_root: Path, generated_at: datetime) -> PipelineResult:
        previous = load_published_catalog(site_root) if (site_root / "manifest.json").exists() else None
        projected = self.collect_and_project(previous.records if previous is not None else None)
        publish_result: PublishResult = publish_catalog(
            site_root,
            projected,
            generated_at,
        )
        return PipelineResult(
            changed=publish_result.changed,
            version=publish_result.version,
            record_count=len(projected),
        )

    def collect_and_project(
        self,
        previous: list[AppCatalogRecord] | None = None,
    ) -> list[AppCatalogRecord]:
        collected = [
            *self._retry(self._korean_source.collect_all),
            *self._retry(self._us_source.collect),
        ]
        validate_catalog(
            collected,
            policy=self._validation_policy,
        )
        projected = project_records(collected, excluded_ids=self._excluded_ids)
        if previous is not None:
            validate_projected_drop(
                projected,
                previous,
                max_drop_ratio=self._validation_policy.max_drop_ratio,
            )
        return projected
