from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from asset_catalog.models import InstrumentType
from asset_catalog.sources.data_go_kr import (
    IncompleteSourceError,
    KoreanKind,
    KoreanPublicDataClient,
    parse_korean_items,
)


FIXTURES = Path(__file__).parent / "fixtures"


def fixture_body(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["response"]["body"]


def test_stock_parser_maps_kospi_and_kosdaq_symbols() -> None:
    records = parse_korean_items(KoreanKind.STOCK, fixture_body("kr_stock_page.json")["items"]["item"])
    by_symbol = {record.symbol: record for record in records}

    assert by_symbol["005930"].provider_symbol == "005930.KS"
    assert by_symbol["035900"].provider_symbol == "035900.KQ"
    assert by_symbol["035900"].name == "JYP Ent."
    assert by_symbol["005935"].instrument_type is InstrumentType.PREFERRED_STOCK


def test_endpoint_kind_controls_fund_type() -> None:
    etf_item = dict(fixture_body("kr_etf_page.json")["items"]["item"][0])
    etn_item = dict(fixture_body("kr_etn_page.json")["items"]["item"][0])
    etf_item.pop("mrktCtg")
    etn_item.pop("mrktCtg")

    etf = parse_korean_items(KoreanKind.ETF, [etf_item])[0]
    etn = parse_korean_items(KoreanKind.ETN, [etn_item])[0]

    assert etf.instrument_type is InstrumentType.ETF
    assert etf.provider_symbol == "367380.KS"
    assert etn.instrument_type is InstrumentType.ETN
    assert etn.provider_symbol == "530036.KS"


def test_stock_parser_accepts_new_alphanumeric_short_codes() -> None:
    item = dict(fixture_body("kr_stock_page.json")["items"]["item"][1])
    item.update({"srtnCd": "0001A0", "itmsNm": "덕양에너젠"})

    record = parse_korean_items(KoreanKind.STOCK, [item])[0]

    assert record.symbol == "0001A0"
    assert record.provider_symbol == "0001A0.KQ"


def test_parser_excludes_konex_without_guessing_a_yahoo_suffix() -> None:
    item = dict(fixture_body("kr_stock_page.json")["items"]["item"][0])
    item.update({"srtnCd": "999999", "itmsNm": "코넥스예시", "mrktCtg": "KONEX"})

    assert parse_korean_items(KoreanKind.STOCK, [item]) == []


def test_client_collects_every_declared_page() -> None:
    requested_pages: list[int] = []

    def opener(url: str, timeout: float) -> bytes:
        del timeout
        page = int(parse_qs(urlparse(url).query)["pageNo"][0])
        requested_pages.append(page)
        items = fixture_body("kr_stock_page.json")["items"]["item"]
        selected = items[:2] if page == 1 else items[2:]
        payload = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {
                    "numOfRows": 2,
                    "pageNo": page,
                    "totalCount": 3,
                    "items": {"item": selected},
                },
            },
        }
        return json.dumps(payload).encode()

    records = KoreanPublicDataClient("secret", opener=opener, page_size=2).collect(KoreanKind.STOCK)

    assert requested_pages == [1, 2]
    assert [record.symbol for record in records] == ["005930", "035900", "005935"]


def test_client_does_not_double_encode_an_encoded_service_key() -> None:
    requested_url = ""

    def opener(url: str, timeout: float) -> bytes:
        nonlocal requested_url
        del timeout
        requested_url = url
        payload = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {
                    "numOfRows": 1000,
                    "pageNo": 1,
                    "totalCount": 0,
                    "items": {"item": []},
                },
            },
        }
        return json.dumps(payload).encode()

    KoreanPublicDataClient("fake%2Bencoded%2Fkey", opener=opener).collect(KoreanKind.STOCK)

    assert "serviceKey=fake%2Bencoded%2Fkey" in requested_url
    assert "%252B" not in requested_url


def test_collect_all_uses_latest_common_trading_date() -> None:
    requested: list[tuple[str, str]] = []

    def opener(url: str, timeout: float) -> bytes:
        del timeout
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        base_date = query["basDt"][0]
        if "getStockPriceInfo" in parsed.path:
            kind = "stock"
        elif "getETFPriceInfo" in parsed.path:
            kind = "etf"
        else:
            kind = "etn"
        requested.append((kind, base_date))

        if base_date in {"20260805", "20260804"} and kind == "etn":
            body = {
                "numOfRows": 1000,
                "pageNo": 1,
                "totalCount": 0,
                "items": {"item": []},
            }
        else:
            body = fixture_body(f"kr_{kind}_page.json")
        payload = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": body,
            },
        }
        return json.dumps(payload).encode()

    records = KoreanPublicDataClient(
        "secret",
        opener=opener,
        today_provider=lambda: date(2026, 8, 5),
    ).collect_all()

    assert requested == [
        ("stock", "20260805"),
        ("etf", "20260805"),
        ("etn", "20260805"),
        ("stock", "20260804"),
        ("etf", "20260804"),
        ("etn", "20260804"),
        ("stock", "20260803"),
        ("etf", "20260803"),
        ("etn", "20260803"),
    ]
    assert {record.symbol for record in records} == {"005930", "035900", "005935", "367380", "530036"}


def test_client_rejects_incomplete_source_without_leaking_secret() -> None:
    def opener(url: str, timeout: float) -> bytes:
        del url, timeout
        payload = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {
                    "numOfRows": 1000,
                    "pageNo": 1,
                    "totalCount": 3,
                    "items": {"item": fixture_body("kr_stock_page.json")["items"]["item"][:2]},
                },
            },
        }
        return json.dumps(payload).encode()

    with pytest.raises(IncompleteSourceError, match="Korean STOCK source is incomplete") as caught:
        KoreanPublicDataClient("secret-value", opener=opener).collect(KoreanKind.STOCK)

    assert "secret-value" not in str(caught.value)
