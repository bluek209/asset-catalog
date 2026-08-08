from datetime import UTC, datetime
from pathlib import Path

import pytest

from asset_catalog.app_catalog import AppCatalogRecord
from asset_catalog.app_publishing import load_published_catalog
from asset_catalog.crypto_catalog import CryptoCatalogRecord
from asset_catalog.crypto_publishing import load_published_crypto_catalog
from asset_catalog.site_pipeline import CatalogSuitePipeline, SitePublicationError, publish_catalog_suite


def tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


class Projection:
    def __init__(self, records: list, events: list[str], name: str, failure: Exception | None = None) -> None:
        self.records = records
        self.events = events
        self.name = name
        self.failure = failure

    def collect_and_project(self, previous: list | None = None) -> list:
        del previous
        self.events.append(self.name)
        if self.failure is not None:
            raise self.failure
        return self.records


def stock_records(name: str = "Apple") -> list[AppCatalogRecord]:
    return [AppCatalogRecord("Q:AAPL", name)]


def crypto_records(name: str = "비트코인") -> list[CryptoCatalogRecord]:
    return [CryptoCatalogRecord("UP:BTC-KRW", name, "Bitcoin")]


def test_suite_publication_builds_root_stock_and_nested_crypto_atomically(tmp_path: Path) -> None:
    site = tmp_path / "site"

    result = publish_catalog_suite(site, stock_records(), crypto_records(), datetime(2026, 8, 8, tzinfo=UTC))

    assert result.stock.changed is True
    assert result.crypto.changed is True
    assert load_published_catalog(site).records == stock_records()
    assert load_published_crypto_catalog(site / "crypto").records == crypto_records()
    assert not (site / "crypto" / "crypto").exists()


def test_source_failure_before_publication_keeps_entire_site_unchanged(tmp_path: Path) -> None:
    site = tmp_path / "site"
    publish_catalog_suite(site, stock_records(), crypto_records(), datetime(2026, 8, 8, tzinfo=UTC))
    before = tree(site)
    events: list[str] = []
    suite = CatalogSuitePipeline(
        stock=Projection(stock_records("Changed"), events, "stock"),
        crypto=Projection(crypto_records(), events, "crypto", RuntimeError("source failed")),
    )

    with pytest.raises(RuntimeError, match="source failed"):
        suite.run(site, datetime(2026, 8, 9, tzinfo=UTC))

    assert events == ["stock", "crypto"]
    assert tree(site) == before


def test_publication_failure_keeps_entire_site_unchanged(tmp_path: Path) -> None:
    site = tmp_path / "site"
    publish_catalog_suite(site, stock_records(), crypto_records(), datetime(2026, 8, 8, tzinfo=UTC))
    before = tree(site)
    events: list[str] = []

    def failing_publisher(*args, **kwargs):
        del args, kwargs
        raise SitePublicationError("verification failed")

    suite = CatalogSuitePipeline(
        stock=Projection(stock_records("Changed"), events, "stock"),
        crypto=Projection(crypto_records("변경"), events, "crypto"),
        publisher=failing_publisher,
    )

    with pytest.raises(SitePublicationError, match="verification failed"):
        suite.run(site, datetime(2026, 8, 9, tzinfo=UTC))

    assert events == ["stock", "crypto"]
    assert tree(site) == before


def test_unchanged_suite_does_not_touch_existing_tree(tmp_path: Path) -> None:
    site = tmp_path / "site"
    first = publish_catalog_suite(site, stock_records(), crypto_records(), datetime(2026, 8, 8, tzinfo=UTC))
    before = tree(site)

    second = publish_catalog_suite(site, stock_records(), crypto_records(), datetime(2026, 8, 9, tzinfo=UTC))

    assert first.changed is True
    assert second.changed is False
    assert second.stock.manifest_path == site / "manifest.json"
    assert second.crypto.manifest_path == site / "crypto" / "manifest.json"
    assert tree(site) == before
