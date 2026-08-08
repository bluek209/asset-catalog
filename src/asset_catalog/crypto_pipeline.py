from __future__ import annotations

from collections.abc import Callable
from time import sleep
from typing import Protocol

from .crypto_catalog import CryptoCatalogRecord, project_crypto_records, validate_crypto_drop
from .crypto_models import CryptoMarket


class CryptoCatalogSource(Protocol):
    def collect(self) -> list[CryptoMarket]: ...


class CryptoCatalogPipeline:
    def __init__(
        self,
        upbit_source: CryptoCatalogSource,
        bithumb_source: CryptoCatalogSource,
        binance_source: CryptoCatalogSource,
        *,
        max_drop_ratio: float = 0.10,
        excluded_ids: set[str] | None = None,
        attempts: int = 3,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        if attempts <= 0:
            raise ValueError("attempts must be positive")
        if not 0 <= max_drop_ratio < 1:
            raise ValueError("max_drop_ratio must be between 0 and 1")
        self._sources = (upbit_source, bithumb_source, binance_source)
        self._max_drop_ratio = max_drop_ratio
        self._excluded_ids = excluded_ids or set()
        self._attempts = attempts
        self._sleeper = sleeper

    def _retry(self, operation: Callable[[], list[CryptoMarket]]) -> list[CryptoMarket]:
        for attempt in range(self._attempts):
            try:
                return operation()
            except Exception:
                if attempt == self._attempts - 1:
                    raise
                self._sleeper(float(2**attempt))
        raise RuntimeError("unreachable")

    def collect_and_project(
        self,
        previous: list[CryptoCatalogRecord] | None = None,
    ) -> list[CryptoCatalogRecord]:
        markets: list[CryptoMarket] = []
        for source in self._sources:
            markets.extend(self._retry(source.collect))
        projected = project_crypto_records(markets, excluded_ids=self._excluded_ids)
        if previous is not None:
            validate_crypto_drop(projected, previous, max_drop_ratio=self._max_drop_ratio)
        return projected
