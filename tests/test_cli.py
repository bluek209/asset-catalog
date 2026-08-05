from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from asset_catalog.app_catalog import AppCatalogRecord
from asset_catalog.app_publishing import publish_catalog
from asset_catalog.cli import main
from asset_catalog.pipeline import PipelineResult
from asset_catalog.sources.data_go_kr import KoreanSourceError

from test_pipeline import record


class SuccessfulPipeline:
    def run(self, site_root: Path, generated_at: datetime) -> PipelineResult:
        result = publish_catalog(site_root, [AppCatalogRecord("Q:AAPL", "Apple")], generated_at.astimezone(UTC))
        return PipelineResult(result.changed, result.version, 1)


def test_cli_reports_success_without_network(tmp_path: Path, capsys) -> None:
    exit_code = main(
        ["--site-root", str(tmp_path / "docs"), "--generated-at", "2026-08-05T00:00:00Z"],
        environ={"DATA_GO_KR_SERVICE_KEY": "secret"},
        pipeline_factory=lambda key, ratio, excluded: SuccessfulPipeline(),
    )

    assert exit_code == 0
    assert "records=1" in capsys.readouterr().out


def test_cli_redacts_secret_from_known_source_failure(tmp_path: Path, capsys) -> None:
    secret = "secret/value+with-special"

    class FailingPipeline:
        def run(self, site_root: Path, generated_at: datetime) -> PipelineResult:
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


def test_verify_only_does_not_require_service_key(tmp_path: Path, capsys) -> None:
    site = tmp_path / "docs"
    publish_catalog(site, [AppCatalogRecord("Q:AAPL", "Apple")], datetime(2026, 8, 5, tzinfo=UTC))

    exit_code = main(["--site-root", str(site), "--verify-only"], environ={})

    assert exit_code == 0
    assert "catalog verified" in capsys.readouterr().out


def test_cli_hydrates_before_build_and_passes_secret_exclusions(tmp_path: Path) -> None:
    events: list[str] = []
    captured_exclusions: set[str] = set()

    class OrderedPipeline(SuccessfulPipeline):
        def run(self, site_root: Path, generated_at: datetime) -> PipelineResult:
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
