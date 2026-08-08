from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeVar

from .app_catalog import AppCatalogRecord
from .app_publishing import (
    PublicationVerificationError,
    PublishResult,
    load_published_catalog,
    publish_catalog,
    verify_site,
)
from .crypto_catalog import CryptoCatalogRecord
from .crypto_publishing import (
    CryptoPublicationVerificationError,
    load_published_crypto_catalog,
    publish_crypto_catalog,
    verify_crypto_site,
)


class SitePublicationError(RuntimeError):
    pass


RecordT = TypeVar("RecordT")


class ProjectionPipeline(Protocol[RecordT]):
    def collect_and_project(self, previous: list[RecordT] | None = None) -> list[RecordT]: ...


@dataclass(frozen=True, slots=True)
class SuitePublishResult:
    stock: PublishResult
    crypto: PublishResult

    @property
    def changed(self) -> bool:
        return self.stock.changed or self.crypto.changed


@dataclass(frozen=True, slots=True)
class CatalogPartResult:
    changed: bool
    version: str
    record_count: int


@dataclass(frozen=True, slots=True)
class SuitePipelineResult:
    stock: CatalogPartResult
    crypto: CatalogPartResult

    @property
    def changed(self) -> bool:
        return self.stock.changed or self.crypto.changed


SuitePublisher = Callable[
    [Path, list[AppCatalogRecord], list[CryptoCatalogRecord], datetime],
    SuitePublishResult,
]


def _copy_child(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _replace_tree(staging: Path, destination: Path) -> None:
    backup = destination.parent / f".{destination.name}-suite-backup"
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


def publish_catalog_suite(
    site_root: Path,
    stock_records: list[AppCatalogRecord],
    crypto_records: list[CryptoCatalogRecord],
    generated_at: datetime,
) -> SuitePublishResult:
    site_root.parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=f".{site_root.name}-suite-", dir=site_root.parent))
    try:
        stock_root = workspace / "stock"
        crypto_root = workspace / "crypto"
        stock_root.mkdir()
        if site_root.exists():
            for child in site_root.iterdir():
                if child.name != "crypto":
                    _copy_child(child, stock_root / child.name)
            if (site_root / "crypto").exists():
                shutil.copytree(site_root / "crypto", crypto_root)

        stock_result = publish_catalog(stock_root, stock_records, generated_at)
        crypto_result = publish_crypto_catalog(crypto_root, crypto_records, generated_at)
        result = SuitePublishResult(
            PublishResult(stock_result.changed, stock_result.version, site_root / "manifest.json"),
            PublishResult(crypto_result.changed, crypto_result.version, site_root / "crypto" / "manifest.json"),
        )
        if not result.changed:
            return result

        assembled = workspace / "assembled"
        shutil.copytree(stock_root, assembled)
        shutil.copytree(crypto_root, assembled / "crypto")
        verify_site(assembled)
        verify_crypto_site(assembled / "crypto")
        _replace_tree(assembled, site_root)
        return result
    except (PublicationVerificationError, CryptoPublicationVerificationError, OSError) as error:
        raise SitePublicationError("catalog suite could not be published") from error
    finally:
        if workspace.exists():
            shutil.rmtree(workspace)


class CatalogSuitePipeline:
    def __init__(
        self,
        *,
        stock: ProjectionPipeline[AppCatalogRecord],
        crypto: ProjectionPipeline[CryptoCatalogRecord],
        publisher: SuitePublisher = publish_catalog_suite,
    ) -> None:
        self._stock = stock
        self._crypto = crypto
        self._publisher = publisher

    def run(self, site_root: Path, generated_at: datetime) -> SuitePipelineResult:
        previous_stock = load_published_catalog(site_root).records if (site_root / "manifest.json").exists() else None
        previous_crypto = (
            load_published_crypto_catalog(site_root / "crypto").records
            if (site_root / "crypto" / "manifest.json").exists()
            else None
        )
        stock_records = self._stock.collect_and_project(previous_stock)
        crypto_records = self._crypto.collect_and_project(previous_crypto)
        published = self._publisher(site_root, stock_records, crypto_records, generated_at)
        return SuitePipelineResult(
            CatalogPartResult(published.stock.changed, published.stock.version, len(stock_records)),
            CatalogPartResult(published.crypto.changed, published.crypto.version, len(crypto_records)),
        )
