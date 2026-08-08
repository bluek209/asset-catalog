from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from asset_catalog.app_catalog import AppCatalogRecord
from asset_catalog.crypto_catalog import CryptoCatalogRecord
from asset_catalog.cli import main
from asset_catalog.site_pipeline import CatalogPartResult, SuitePipelineResult, publish_catalog_suite
from asset_catalog.sources.binance import BinanceSourceError
from asset_catalog.sources.data_go_kr import KoreanSourceError

from test_pipeline import record


class SuccessfulPipeline:
    def run(self, site_root: Path, generated_at: datetime) -> SuitePipelineResult:
        result = publish_catalog_suite(
            site_root,
            [AppCatalogRecord("Q:AAPL", "Apple")],
            [CryptoCatalogRecord("UP:BTC-KRW", "비트코인", "Bitcoin")],
            generated_at.astimezone(UTC),
        )
        return SuitePipelineResult(
            CatalogPartResult(result.stock.changed, result.stock.version, 1),
            CatalogPartResult(result.crypto.changed, result.crypto.version, 1),
        )


def test_cli_reports_success_without_network(tmp_path: Path, capsys) -> None:
    exit_code = main(
        ["--site-root", str(tmp_path / "docs"), "--generated-at", "2026-08-05T00:00:00Z"],
        environ={"DATA_GO_KR_SERVICE_KEY": "secret"},
        pipeline_factory=lambda key, ratio, excluded: SuccessfulPipeline(),
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "stock=" in output and "/1" in output
    assert "crypto=" in output


def test_cli_writes_pretty_history_from_verified_site(tmp_path: Path, capsys) -> None:
    site = tmp_path / "site"
    history_catalog = tmp_path / "history" / "catalog.json"
    history_manifest = tmp_path / "history" / "manifest.json"

    exit_code = main(
        [
            "--site-root",
            str(site),
            "--history-output",
            str(history_catalog),
            "--history-manifest-output",
            str(history_manifest),
            "--generated-at",
            "2026-08-05T00:00:00Z",
        ],
        environ={"DATA_GO_KR_SERVICE_KEY": "secret"},
        pipeline_factory=lambda key, ratio, excluded: SuccessfulPipeline(),
    )
    deployed_manifest = json.loads((site / "manifest.json").read_text(encoding="utf-8"))
    deployed_catalog = json.loads(
        gzip.decompress((site / deployed_manifest["f"]["p"]).read_bytes()),
    )

    assert exit_code == 0
    assert history_catalog.read_bytes().endswith(b"\n")
    assert history_manifest.read_bytes().endswith(b"\n")
    assert json.loads(history_catalog.read_text(encoding="utf-8")) == deployed_catalog
    assert json.loads(history_manifest.read_text(encoding="utf-8")) == deployed_manifest
    assert '  "f": {' in history_manifest.read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert "stock=" in output and "crypto=" in output


def test_cli_writes_history_when_catalog_is_unchanged(tmp_path: Path) -> None:
    site = tmp_path / "site"
    history = tmp_path / "catalog.json"
    history_manifest = tmp_path / "manifest.json"
    common = ["--site-root", str(site), "--generated-at", "2026-08-05T00:00:00Z"]
    factory = lambda key, ratio, excluded: SuccessfulPipeline()

    assert main(
        common,
        environ={"DATA_GO_KR_SERVICE_KEY": "secret"},
        pipeline_factory=factory,
    ) == 0
    assert main(
        [
            *common,
            "--history-output",
            str(history),
            "--history-manifest-output",
            str(history_manifest),
        ],
        environ={"DATA_GO_KR_SERVICE_KEY": "secret"},
        pipeline_factory=factory,
    ) == 0

    assert history.is_file()
    assert history_manifest.is_file()


def test_cli_redacts_secret_from_known_source_failure(tmp_path: Path, capsys) -> None:
    secret = "secret/value+with-special"

    class FailingPipeline:
        def run(self, site_root: Path, generated_at: datetime) -> SuitePipelineResult:
            del site_root, generated_at
            raise KoreanSourceError(f"failed with {secret}")

    exit_code = main(
        ["--site-root", str(tmp_path / "docs")],
        environ={"DATA_GO_KR_SERVICE_KEY": secret},
        pipeline_factory=lambda key, ratio, excluded: FailingPipeline(),
    )
    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert exit_code == 2
    assert secret not in output
    assert "secret%2Fvalue%2Bwith-special" not in output
    assert "catalog build failed: source or validation" in output


def test_cli_redacts_crypto_source_failure(tmp_path: Path, capsys) -> None:
    secret = "private-binance-response"

    class FailingPipeline:
        def run(self, site_root: Path, generated_at: datetime) -> SuitePipelineResult:
            del site_root, generated_at
            raise BinanceSourceError(secret)

    exit_code = main(
        ["--site-root", str(tmp_path / "site")],
        environ={"DATA_GO_KR_SERVICE_KEY": "configured"},
        pipeline_factory=lambda key, ratio, excluded: FailingPipeline(),
    )
    output = capsys.readouterr().err

    assert exit_code == 2
    assert secret not in output
    assert output.strip() == "catalog build failed: source or validation"


def test_verify_only_does_not_require_service_key(tmp_path: Path, capsys) -> None:
    site = tmp_path / "docs"
    publish_catalog_suite(
        site,
        [AppCatalogRecord("Q:AAPL", "Apple")],
        [CryptoCatalogRecord("UP:BTC-KRW", "비트코인", "Bitcoin")],
        datetime(2026, 8, 5, tzinfo=UTC),
    )

    exit_code = main(["--site-root", str(site), "--verify-only"], environ={})

    assert exit_code == 0
    assert "catalog verified" in capsys.readouterr().out


def test_verify_only_rejects_site_without_crypto_catalog(tmp_path: Path, capsys) -> None:
    site = tmp_path / "docs"
    from asset_catalog.app_publishing import publish_catalog

    publish_catalog(site, [AppCatalogRecord("Q:AAPL", "Apple")], datetime(2026, 8, 5, tzinfo=UTC))

    assert main(["--site-root", str(site), "--verify-only"], environ={}) == 3
    assert capsys.readouterr().err.strip() == "catalog verification failed"


def test_cli_hydrates_before_build_and_passes_secret_exclusions(tmp_path: Path) -> None:
    events: list[str] = []
    captured_exclusions: set[str] = set()

    class OrderedPipeline(SuccessfulPipeline):
        def run(self, site_root: Path, generated_at: datetime) -> SuitePipelineResult:
            events.append("build")
            return super().run(site_root, generated_at)

    def factory(key: str, ratio: float, excluded: set[str]) -> OrderedPipeline:
        nonlocal captured_exclusions
        captured_exclusions = excluded
        return OrderedPipeline()

    exit_code = main(
        [
            "--site-root",
            str(tmp_path / "site"),
            "--hydrate-url",
            "https://example.test/catalog/",
            "--generated-at",
            "2026-08-05T00:00:00Z",
        ],
        environ={
            "DATA_GO_KR_SERVICE_KEY": "secret",
            "EXCLUDED_ASSET_IDS": "Q:PRIVATE,KQ:000000",
        },
        pipeline_factory=factory,
        hydrator=lambda url, site: events.append("hydrate") or False,
    )

    assert exit_code == 0
    assert events == ["hydrate", "build"]
    assert captured_exclusions == {"Q:PRIVATE", "KQ:000000"}
