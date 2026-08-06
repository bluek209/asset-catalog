import gzip
import json
from difflib import unified_diff
from pathlib import Path

from asset_catalog.app_catalog import AppCatalogRecord
from asset_catalog.canonical import gzip_bytes
from asset_catalog.catalog_serialization import (
    catalog_payload,
    pretty_catalog_bytes,
    pretty_json_bytes,
    write_pretty_catalog,
    write_pretty_json,
)


def test_pretty_catalog_is_sorted_utf8_and_ends_with_newline() -> None:
    records = [
        AppCatalogRecord("Q:AAPL", "Apple Inc."),
        AppCatalogRecord("KS:005930", "삼성전자"),
    ]

    rendered = pretty_catalog_bytes(records)

    assert rendered == (
        b'{\n'
        b'  "r": [\n'
        b'    {\n'
        b'      "i": "KS:005930",\n'
        b'      "n": "\xec\x82\xbc\xec\x84\xb1\xec\xa0\x84\xec\x9e\x90"\n'
        b'    },\n'
        b'    {\n'
        b'      "i": "Q:AAPL",\n'
        b'      "n": "Apple Inc."\n'
        b'    }\n'
        b'  ],\n'
        b'  "v": 1\n'
        b'}\n'
    )


def test_pretty_and_compact_gzip_decode_to_same_payload() -> None:
    records = [
        AppCatalogRecord("Q:AAPL", "Apple Inc."),
        AppCatalogRecord("KS:005930", "삼성전자"),
    ]
    payload = catalog_payload(records)

    pretty = json.loads(pretty_catalog_bytes(records))
    compact = json.loads(gzip.decompress(gzip_bytes(payload)))

    assert pretty == compact == payload


def test_pretty_catalog_is_stable_for_input_order() -> None:
    first = AppCatalogRecord("Q:AAPL", "Apple Inc.")
    second = AppCatalogRecord("KS:005930", "삼성전자")

    assert pretty_catalog_bytes([first, second]) == pretty_catalog_bytes([second, first])


def test_write_pretty_catalog_creates_parent_and_returns_bytes(tmp_path: Path) -> None:
    output = tmp_path / "history" / "catalog.json"
    records = [AppCatalogRecord("KS:005930", "삼성전자")]

    written = write_pretty_catalog(output, records)

    assert output.read_bytes() == written == pretty_catalog_bytes(records)


def test_pretty_json_is_sorted_utf8_and_ends_with_newline() -> None:
    rendered = pretty_json_bytes({"z": "한글", "a": {"b": 2, "a": 1}})

    assert rendered == (
        b'{\n'
        b'  "a": {\n'
        b'    "a": 1,\n'
        b'    "b": 2\n'
        b'  },\n'
        b'  "z": "\xed\x95\x9c\xea\xb8\x80"\n'
        b'}\n'
    )


def test_write_pretty_json_creates_parent_and_returns_bytes(tmp_path: Path) -> None:
    output = tmp_path / "history" / "manifest.json"
    payload = {"v": 1, "l": "20260806-abcdef12"}

    written = write_pretty_json(output, payload)

    assert output.read_bytes() == written == pretty_json_bytes(payload)


def test_pretty_catalog_diff_is_limited_to_changed_record() -> None:
    unchanged = AppCatalogRecord("Q:MSFT", "Microsoft")
    before = pretty_catalog_bytes(
        [AppCatalogRecord("Q:AAPL", "Apple"), unchanged],
    ).decode("utf-8")
    after = pretty_catalog_bytes(
        [AppCatalogRecord("Q:AAPL", "Apple Inc."), unchanged],
    ).decode("utf-8")

    diff = "".join(
        unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            n=0,
        ),
    )

    assert '-      "n": "Apple"' in diff
    assert '+      "n": "Apple Inc."' in diff
    assert "Q:MSFT" not in diff


def test_pretty_catalog_add_remove_diff_is_limited_to_target_record() -> None:
    apple = AppCatalogRecord("Q:AAPL", "Apple")
    google = AppCatalogRecord("Q:GOOG", "Google")
    microsoft = AppCatalogRecord("Q:MSFT", "Microsoft")
    before = pretty_catalog_bytes([apple, microsoft]).decode("utf-8")
    after = pretty_catalog_bytes([apple, google, microsoft]).decode("utf-8")

    added = "".join(
        unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            n=0,
        ),
    )
    removed = "".join(
        unified_diff(
            after.splitlines(keepends=True),
            before.splitlines(keepends=True),
            n=0,
        ),
    )

    assert '+      "i": "Q:GOOG"' in added
    assert '-      "i": "Q:GOOG"' in removed
    assert "Q:AAPL" not in added + removed
    assert "Q:MSFT" not in added + removed
