from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .app_catalog import AppCatalogProjectionError, parse_excluded_ids
from .app_publishing import PublicationVerificationError, load_published_catalog, verify_site
from .app_versioning import DeltaApplicationError
from .catalog_serialization import write_pretty_catalog
from .pipeline import CatalogPipeline, PipelineResult
from .remote import RemoteStateError, hydrate_site
from .sources.data_go_kr import KoreanPublicDataClient, KoreanSourceError
from .sources.nasdaq_trader import NasdaqTraderClient, NasdaqTraderSourceError
from .validation import CatalogValidationError, ValidationPolicy


class RunnablePipeline(Protocol):
    def run(self, site_root: Path, generated_at: datetime) -> PipelineResult: ...


PipelineFactory = Callable[[str, float, set[str]], RunnablePipeline]
Hydrator = Callable[[str, Path], bool]


def _default_pipeline(
    service_key: str,
    max_drop_ratio: float,
    excluded_ids: set[str],
) -> CatalogPipeline:
    return CatalogPipeline(
        KoreanPublicDataClient(service_key),
        NasdaqTraderClient(),
        validation_policy=ValidationPolicy(max_drop_ratio=max_drop_ratio),
        excluded_ids=excluded_ids,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the Asset Catalog")
    parser.add_argument("--site-root", type=Path, default=Path("docs"))
    parser.add_argument("--generated-at")
    parser.add_argument("--max-drop-ratio", type=float, default=0.10)
    parser.add_argument("--hydrate-url")
    parser.add_argument("--history-output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def _parse_instant(raw: str | None) -> datetime:
    if raw is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("generated-at must include a timezone")
    return parsed.astimezone(UTC)


def main(
    args: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    pipeline_factory: PipelineFactory = _default_pipeline,
    hydrator: Hydrator = hydrate_site,
) -> int:
    options = _parser().parse_args(args)
    environment = os.environ if environ is None else environ
    if options.verify_only:
        try:
            verify_site(options.site_root)
            print(f"catalog verified: {options.site_root}")
            return 0
        except PublicationVerificationError:
            print("catalog verification failed", file=sys.stderr)
            return 3

    service_key = environment.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not service_key:
        print("catalog build failed: configuration", file=sys.stderr)
        return 2
    try:
        generated_at = _parse_instant(options.generated_at)
        if options.hydrate_url:
            hydrator(options.hydrate_url, options.site_root)
        excluded_ids = parse_excluded_ids(environment.get("EXCLUDED_ASSET_IDS", ""))
        pipeline = pipeline_factory(service_key, options.max_drop_ratio, excluded_ids)
        result = pipeline.run(options.site_root, generated_at)
        if options.history_output is not None:
            published = load_published_catalog(options.site_root)
            write_pretty_catalog(options.history_output, published.records)
        state = "updated" if result.changed else "unchanged"
        print(f"catalog {state}: version={result.version} records={result.record_count}")
        return 0
    except (
        KoreanSourceError,
        NasdaqTraderSourceError,
        CatalogValidationError,
        AppCatalogProjectionError,
        ValueError,
    ):
        print("catalog build failed: source or validation", file=sys.stderr)
        return 2
    except (
        PublicationVerificationError,
        DeltaApplicationError,
        RemoteStateError,
        OSError,
    ):
        print("catalog build failed: publication verification", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
