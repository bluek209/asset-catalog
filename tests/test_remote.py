from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError

import pytest

from asset_catalog.app_catalog import AppCatalogRecord
from asset_catalog.app_publishing import publish_catalog
from asset_catalog.remote import RemoteStateError, hydrate_site


def site_payloads(tmp_path: Path) -> dict[str, bytes]:
    site = tmp_path / "origin"
    publish_catalog(site, [AppCatalogRecord("Q:AAPL", "Apple")], datetime(2026, 8, 5, tzinfo=UTC))
    return {path.relative_to(site).as_posix(): path.read_bytes() for path in site.rglob("*") if path.is_file()}


def test_hydrate_downloads_and_verifies_manifest_references(tmp_path: Path) -> None:
    payloads = site_payloads(tmp_path)

    hydrated = hydrate_site(
        "https://example.test/catalog/",
        tmp_path / "site",
        opener=lambda url, timeout: payloads[url.removeprefix("https://example.test/catalog/")],
    )

    assert hydrated is True
    assert (tmp_path / "site" / "manifest.json").read_bytes() == payloads["manifest.json"]


def test_first_deploy_manifest_404_is_empty_state(tmp_path: Path) -> None:
    def missing(url: str, timeout: float) -> bytes:
        raise HTTPError(url, 404, "Not Found", {}, None)

    assert hydrate_site("https://example.test/", tmp_path / "site", opener=missing) is False
    assert not (tmp_path / "site").exists()


def test_non_404_or_tampered_remote_aborts(tmp_path: Path) -> None:
    def unavailable(url: str, timeout: float) -> bytes:
        raise HTTPError(url, 503, "Unavailable", {}, None)

    with pytest.raises(RemoteStateError, match="could not be downloaded"):
        hydrate_site("https://example.test/", tmp_path / "site", opener=unavailable)

    payloads = site_payloads(tmp_path)
    full_path = next(path for path in payloads if path.startswith("f/"))
    payloads[full_path] += b"tampered"
    with pytest.raises(RemoteStateError, match="verification failed"):
        hydrate_site(
            "https://example.test/",
            tmp_path / "tampered",
            opener=lambda url, timeout: payloads[url.removeprefix("https://example.test/")],
        )
