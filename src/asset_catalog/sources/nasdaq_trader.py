from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.request import urlopen

from ..models import InstrumentRecord, InstrumentStatus, InstrumentType


DIRECTORY_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
EXCHANGES = {
    "A": "NYSE_AMERICAN",
    "N": "NYSE",
    "P": "NYSE_ARCA",
    "Q": "NASDAQ",
    "V": "IEX",
    "Z": "CBOE",
}
REQUIRED_HEADERS = {
    "Nasdaq Traded",
    "Symbol",
    "Security Name",
    "Listing Exchange",
    "ETF",
    "Test Issue",
    "Financial Status",
}


class NasdaqTraderSourceError(RuntimeError):
    pass


OpenBytes = Callable[[str, float], bytes]


def _download(url: str, timeout: float) -> bytes:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS origin
        return response.read()


def _matches(value: str, pattern: str) -> bool:
    return re.search(pattern, value, flags=re.IGNORECASE) is not None


def to_yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-").replace("/", "-").replace("^", "-")


def classify_us_instrument(name: str, etf_flag: str) -> InstrumentType:
    if etf_flag.upper() == "Y":
        return InstrumentType.ETF
    if _matches(name, r"\b(ETN|EXCHANGE[ -]TRADED NOTE|INDEX[ -]LINKED NOTE)\b"):
        return InstrumentType.ETN
    if _matches(name, r"\b(ADR|ADS|DEPOSITARY (SHARE|SHARES|RECEIPT|RECEIPTS))\b"):
        return InstrumentType.ADR
    if _matches(name, r"\b(REIT|REAL ESTATE INVESTMENT TRUST)\b"):
        return InstrumentType.REIT
    if _matches(name, r"\bPREFERRED\b"):
        return InstrumentType.PREFERRED_STOCK
    return InstrumentType.COMMON_STOCK


def _is_excluded(name: str, symbol: str, instrument_type: InstrumentType) -> bool:
    if instrument_type is InstrumentType.ETN:
        return False
    if _matches(symbol, r"(?:[./^](?:W|WS|U|R))$"):
        return True
    return _matches(
        name,
        r"\b(WARRANTS?|RIGHTS?|UNITS?|BONDS?|DEBENTURES?|SENIOR NOTES?|NOTES? DUE)\b",
    )


def _source_date(lines: list[str]) -> str:
    footer = next((line for line in lines if line.startswith("File Creation Time:")), None)
    if footer is None:
        raise NasdaqTraderSourceError("Nasdaq Trader directory has no creation time")
    raw = footer.removeprefix("File Creation Time:").split("|", 1)[0].strip()
    try:
        return datetime.strptime(raw, "%m%d%Y%H:%M").date().isoformat()
    except ValueError as error:
        raise NasdaqTraderSourceError("Nasdaq Trader directory has an invalid creation time") from error


def parse_nasdaq_traded(text: str) -> list[InstrumentRecord]:
    lines = [line for line in text.splitlines() if line.strip()]
    source_updated_date = _source_date(lines)
    data_lines = [line for line in lines if not line.startswith("File Creation Time:")]
    reader = csv.DictReader(io.StringIO("\n".join(data_lines)), delimiter="|")
    if reader.fieldnames is None or not REQUIRED_HEADERS.issubset(reader.fieldnames):
        raise NasdaqTraderSourceError("Nasdaq Trader directory headers are invalid")

    records: list[InstrumentRecord] = []
    for row in reader:
        if not _supported_row(row):
            continue
        symbol = str(row["Symbol"]).strip().upper()
        name = " ".join(str(row["Security Name"]).split())
        instrument_type = classify_us_instrument(name, str(row["ETF"]))
        if not symbol or not name or _is_excluded(name, symbol, instrument_type):
            continue
        exchange = EXCHANGES[str(row["Listing Exchange"]).strip().upper()]
        simple_name = re.sub(r"\s+-\s+Common Stock$", "", name, flags=re.IGNORECASE).strip()
        records.append(
            InstrumentRecord(
                id=f"US:{symbol}",
                symbol=symbol,
                name=name,
                english_name=name,
                market="US",
                exchange=exchange,
                currency="USD",
                instrument_type=instrument_type,
                status=InstrumentStatus.ACTIVE,
                provider_id="yahoo",
                provider_symbol=to_yahoo_symbol(symbol),
                aliases=tuple({symbol, name, simple_name}),
                source_updated_date=source_updated_date,
            ),
        )
    return sorted(records, key=lambda record: record.id)


def _supported_row(row: dict[str, Any]) -> bool:
    listing_exchange = str(row.get("Listing Exchange", "")).strip().upper()
    financial_status = str(row.get("Financial Status", "")).strip().upper()
    return (
        str(row.get("Nasdaq Traded", "")).strip().upper() == "Y"
        and str(row.get("Test Issue", "")).strip().upper() == "N"
        and listing_exchange in EXCHANGES
        and financial_status in {"", "N"}
    )


class NasdaqTraderClient:
    def __init__(self, *, opener: OpenBytes = _download, timeout: float = 30.0) -> None:
        self._opener = opener
        self._timeout = timeout

    def collect(self) -> list[InstrumentRecord]:
        try:
            text = self._opener(DIRECTORY_URL, self._timeout).decode("utf-8-sig")
            return parse_nasdaq_traded(text)
        except NasdaqTraderSourceError:
            raise
        except Exception as error:
            raise NasdaqTraderSourceError("Nasdaq Trader directory could not be read") from error
