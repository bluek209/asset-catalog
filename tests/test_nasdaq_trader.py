from pathlib import Path

from asset_catalog.models import InstrumentType
from asset_catalog.sources.nasdaq_trader import (
    NasdaqTraderClient,
    parse_nasdaq_traded,
    to_yahoo_symbol,
)


FIXTURE = Path(__file__).parent / "fixtures" / "nasdaqtraded.txt"


def test_us_directory_filters_and_classifies_supported_instruments() -> None:
    records = parse_nasdaq_traded(FIXTURE.read_text(encoding="utf-8"))
    by_symbol = {record.symbol: record for record in records}

    assert by_symbol["AAPL"].instrument_type is InstrumentType.COMMON_STOCK
    assert by_symbol["QQQ"].instrument_type is InstrumentType.ETF
    assert by_symbol["VXX"].instrument_type is InstrumentType.ETN
    assert by_symbol["BABA"].instrument_type is InstrumentType.ADR
    assert by_symbol["O"].instrument_type is InstrumentType.REIT
    assert by_symbol["PREF.A"].instrument_type is InstrumentType.PREFERRED_STOCK
    assert "TEST" not in by_symbol
    assert "ACME.W" not in by_symbol
    assert "ACME.U" not in by_symbol
    assert "NOTE" not in by_symbol


def test_yahoo_symbol_converts_dot_classes() -> None:
    assert to_yahoo_symbol("BRK.B") == "BRK-B"


def test_client_reads_fixed_official_directory_without_leaking_url() -> None:
    requested: list[tuple[str, float]] = []

    def opener(url: str, timeout: float) -> bytes:
        requested.append((url, timeout))
        return FIXTURE.read_bytes()

    records = NasdaqTraderClient(opener=opener, timeout=12.0).collect()

    assert requested == [("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt", 12.0)]
    assert next(record for record in records if record.symbol == "BRK.B").provider_symbol == "BRK-B"
    assert {record.source_updated_date for record in records} == {"2026-08-05"}
