from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_catalog_build_stops_after_first_successful_retry(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    attempts_file = tmp_path / "attempts"
    arguments_file = tmp_path / "arguments"
    fake_catalog = bin_dir / "asset-catalog"
    fake_catalog.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" > "$ARGUMENTS_FILE"
attempts=0
if [[ -f "$ATTEMPTS_FILE" ]]; then
  attempts="$(cat "$ATTEMPTS_FILE")"
fi
attempts=$((attempts + 1))
printf '%s' "$attempts" > "$ATTEMPTS_FILE"
if (( attempts < 2 )); then
  echo "failed attempt output"
  echo "temporary source failure" >&2
  exit 2
fi
echo "catalog unchanged: stock=test/1 crypto=test/1"
""",
        encoding="utf-8",
    )
    fake_catalog.chmod(0o755)
    environment = os.environ | {
        "ARGUMENTS_FILE": str(arguments_file),
        "ATTEMPTS_FILE": str(attempts_file),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["bash", str(ROOT / "scripts/retry_catalog_build.sh"), "0", "0"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert attempts_file.read_text(encoding="utf-8") == "2"
    assert arguments_file.read_text(encoding="utf-8").splitlines() == [
        "--site-root",
        "site",
        "--history-output",
        "catalog.json",
        "--history-manifest-output",
        "manifest.json",
        "--crypto-history-output",
        "crypto/catalog.json",
        "--crypto-history-manifest-output",
        "crypto/manifest.json",
        "--hydrate-url",
        "https://bluek209.github.io/asset-catalog/",
    ]
    assert result.stdout.strip() == "catalog unchanged: stock=test/1 crypto=test/1"


def test_catalog_build_returns_last_failure_after_three_attempts(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    attempts_file = tmp_path / "attempts"
    fake_catalog = bin_dir / "asset-catalog"
    fake_catalog.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
attempts=0
if [[ -f "$ATTEMPTS_FILE" ]]; then
  attempts="$(cat "$ATTEMPTS_FILE")"
fi
printf '%s' "$((attempts + 1))" > "$ATTEMPTS_FILE"
echo "temporary source failure" >&2
exit 7
""",
        encoding="utf-8",
    )
    fake_catalog.chmod(0o755)
    environment = os.environ | {
        "ATTEMPTS_FILE": str(attempts_file),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["bash", str(ROOT / "scripts/retry_catalog_build.sh"), "0", "0"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 7
    assert attempts_file.read_text(encoding="utf-8") == "3"
    assert result.stdout == ""


def test_publish_workflow_uses_long_catalog_retry_window() -> None:
    workflow = (ROOT / ".github/workflows/publish-catalog.yml").read_text(encoding="utf-8")

    assert "timeout-minutes: 30" in workflow
    assert 'catalog_output="$(scripts/retry_catalog_build.sh 300 600)"' in workflow
