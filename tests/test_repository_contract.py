from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_repository_uses_asset_catalog_identity() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    previous_package = "simple" + "_rebalancing_catalog"

    assert 'name = "asset-catalog"' in project
    assert 'asset-catalog = "asset_catalog.cli:main"' in project
    assert not (ROOT / "src" / previous_package).exists()
    assert (ROOT / "src/asset_catalog/cli.py").exists()


def test_publish_workflow_records_readable_history_before_changed_only_pages_deployment() -> None:
    workflow = (ROOT / ".github/workflows/publish-catalog.yml").read_text(encoding="utf-8")

    assert 'cron: "30 23 * * *"' in workflow
    assert 'cron: "30 11 * * *"' in workflow
    assert "DATA_GO_KR_SERVICE_KEY: ${{ secrets.DATA_GO_KR_SERVICE_KEY }}" in workflow
    assert "EXCLUDED_ASSET_IDS: ${{ secrets.EXCLUDED_ASSET_IDS }}" in workflow
    assert workflow.index("pytest -q") < workflow.index("asset-catalog --site-root site")
    assert "--hydrate-url https://bluek209.github.io/asset-catalog/" in workflow
    assert "asset-catalog --site-root site --verify-only" in workflow
    assert "catalog" + "-build" not in workflow
    assert "contents: write" in workflow
    assert "--history-output catalog.json" in workflow
    assert "version: ${{ steps.build.outputs.version }}" in workflow
    assert "catalog-data" in workflow
    assert 'git -C "$history_dir" config user.name "github-actions[bot]"' in workflow
    assert 'git -C "$history_dir" add README.md catalog.json' in workflow
    assert 'git -C "$history_dir" diff --cached --quiet' in workflow
    assert 'git -C "$history_dir" commit -m "data: 카탈로그 ${CATALOG_VERSION} 갱신"' in workflow
    assert 'git -C "$history_dir" push origin HEAD:catalog-data' in workflow
    assert workflow.index("asset-catalog --site-root site --verify-only") < workflow.index(
        'git -C "$history_dir" push origin HEAD:catalog-data',
    )
    assert workflow.index('git -C "$history_dir" push origin HEAD:catalog-data') < workflow.index(
        "actions/configure-pages@v5",
    )
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "actions/configure-pages@v5" in workflow
    assert "actions/upload-pages-artifact@v4" in workflow
    assert "actions/deploy-pages@v4" in workflow
    assert "steps.build.outputs.changed == 'true'" in workflow


def test_public_repository_omits_description_and_environment_example() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert not (ROOT / "README.md").exists()
    assert not (ROOT / ".env.example").exists()
    assert "!.env.example" not in gitignore
    assert ".idea/" in gitignore
