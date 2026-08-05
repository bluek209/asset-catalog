from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from ..models import InstrumentRecord, InstrumentStatus, InstrumentType


BASE_URL = "https://apis.data.go.kr/1160100/service"


class KoreanKind(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"
    ETN = "ETN"


ENDPOINTS = {
    KoreanKind.STOCK: "GetStockSecuritiesInfoService/getStockPriceInfo",
    KoreanKind.ETF: "GetSecuritiesProductInfoService/getETFPriceInfo",
    KoreanKind.ETN: "GetSecuritiesProductInfoService/getETNPriceInfo",
}


class KoreanSourceError(RuntimeError):
    pass


class IncompleteSourceError(KoreanSourceError):
    pass


OpenBytes = Callable[[str, float], bytes]
TodayProvider = Callable[[], date]


def _download(url: str, timeout: float) -> bytes:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS origin
        return response.read()


def _today_in_korea() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _source_date(raw: object) -> str:
    value = str(raw or "").strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    raise KoreanSourceError("Korean source contains an invalid base date")


def _stock_type(name: str) -> InstrumentType:
    compact = re.sub(r"\s+", "", name)
    if "스팩" in compact:
        return InstrumentType.SPAC
    if "리츠" in compact:
        return InstrumentType.REIT
    if re.search(r"우(?:B|C)?$", compact, re.IGNORECASE):
        return InstrumentType.PREFERRED_STOCK
    return InstrumentType.COMMON_STOCK


def _instrument_type(kind: KoreanKind, name: str) -> InstrumentType:
    if kind is KoreanKind.ETF:
        return InstrumentType.ETF
    if kind is KoreanKind.ETN:
        return InstrumentType.ETN
    return _stock_type(name)


def parse_korean_items(kind: KoreanKind, items: Iterable[dict[str, Any]]) -> list[InstrumentRecord]:
    records: list[InstrumentRecord] = []
    for item in items:
        symbol = str(item.get("srtnCd", "")).strip()
        name = " ".join(str(item.get("itmsNm", "")).split())
        market_category = str(item.get("mrktCtg", "")).strip().upper()
        if not re.fullmatch(r"[0-9A-Z]{6}", symbol) or not name:
            raise KoreanSourceError("Korean source contains an invalid symbol or name")
        if kind in {KoreanKind.ETF, KoreanKind.ETN} and market_category in {"", "KOSPI"}:
            exchange = "KOSPI"
            suffix = ".KS"
        elif market_category == "KONEX":
            continue
        elif market_category == "KOSPI":
            exchange = "KOSPI"
            suffix = ".KS"
        elif market_category == "KOSDAQ":
            exchange = "KOSDAQ"
            suffix = ".KQ"
        else:
            raise KoreanSourceError("Korean source contains an unsupported market")

        corporation = " ".join(str(item.get("corpNm", "")).split())
        aliases = tuple(value for value in (name, corporation, symbol) if value)
        records.append(
            InstrumentRecord(
                id=f"KR:{symbol}",
                symbol=symbol,
                name=name,
                english_name=None,
                market="KR",
                exchange=exchange,
                currency="KRW",
                instrument_type=_instrument_type(kind, name),
                status=InstrumentStatus.ACTIVE,
                provider_id="yahoo",
                provider_symbol=f"{symbol}{suffix}",
                aliases=aliases,
                source_updated_date=_source_date(item.get("basDt")),
            ),
        )
    return records


class KoreanPublicDataClient:
    def __init__(
        self,
        service_key: str,
        *,
        opener: OpenBytes = _download,
        page_size: int = 1000,
        timeout: float = 30.0,
        today_provider: TodayProvider = _today_in_korea,
        max_lookback_days: int = 14,
    ) -> None:
        if not service_key.strip():
            raise ValueError("Korean public-data service key is required")
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        if max_lookback_days <= 0:
            raise ValueError("max_lookback_days must be positive")
        self._service_key = service_key
        self._opener = opener
        self._page_size = page_size
        self._timeout = timeout
        self._today_provider = today_provider
        self._max_lookback_days = max_lookback_days

    def collect_all(self) -> list[InstrumentRecord]:
        for days_ago in range(self._max_lookback_days):
            base_date = self._today_provider() - timedelta(days=days_ago)
            first_pages = {kind: self._load_page(kind, 1, base_date) for kind in KoreanKind}
            if all(int(body.get("totalCount", 0)) > 0 for body in first_pages.values()):
                records: list[InstrumentRecord] = []
                for kind in KoreanKind:
                    records.extend(self.collect(kind, base_date=base_date, first_body=first_pages[kind]))
                return records
        raise KoreanSourceError("Korean sources have no common trading date in the lookback window")

    def collect(
        self,
        kind: KoreanKind,
        *,
        base_date: date | None = None,
        first_body: dict[str, Any] | None = None,
    ) -> list[InstrumentRecord]:
        raw_items: list[dict[str, Any]] = []
        page = 1
        total_count: int | None = None
        while total_count is None or len(raw_items) < total_count:
            body = first_body if page == 1 and first_body is not None else self._load_page(kind, page, base_date)
            declared_total = int(body.get("totalCount", 0))
            if total_count is None:
                total_count = declared_total
            elif total_count != declared_total:
                raise IncompleteSourceError(f"Korean {kind.value} source changed during pagination")

            page_items = body.get("items", {}).get("item", [])
            if isinstance(page_items, dict):
                page_items = [page_items]
            if not isinstance(page_items, list):
                raise KoreanSourceError(f"Korean {kind.value} source has an invalid items field")
            raw_items.extend(item for item in page_items if isinstance(item, dict))
            if len(raw_items) >= declared_total:
                break
            if not page_items:
                break
            page += 1

        if total_count is None or len(raw_items) != total_count:
            raise IncompleteSourceError(
                f"Korean {kind.value} source is incomplete: expected {total_count or 0}, received {len(raw_items)}",
            )
        return parse_korean_items(kind, raw_items)

    def _load_page(self, kind: KoreanKind, page: int, base_date: date | None = None) -> dict[str, Any]:
        parameters: dict[str, object] = {
            "serviceKey": self._service_key,
            "resultType": "json",
            "numOfRows": self._page_size,
            "pageNo": page,
        }
        if base_date is not None:
            parameters["basDt"] = base_date.strftime("%Y%m%d")
        query = urlencode(parameters, safe="%")
        try:
            payload = json.loads(
                self._opener(f"{BASE_URL}/{ENDPOINTS[kind]}?{query}", self._timeout).decode("utf-8"),
            )
            response = payload["response"]
            header = response["header"]
            if str(header.get("resultCode")) not in {"0", "00"}:
                raise KoreanSourceError(f"Korean {kind.value} source rejected the request")
            body = response["body"]
            if not isinstance(body, dict):
                raise TypeError("body")
            return body
        except KoreanSourceError:
            raise
        except Exception as error:
            raise KoreanSourceError(f"Korean {kind.value} source could not be read") from error
