from datetime import UTC, datetime
from pathlib import Path

import pytest

from asset_catalog.crypto_catalog import CryptoCatalogRecord
from asset_catalog.crypto_models import CryptoMarket, CryptoVenue
from asset_catalog.crypto_pipeline import CryptoCatalogPipeline
from asset_catalog.crypto_publishing import load_published_crypto_catalog, publish_crypto_catalog
from asset_catalog.sources.binance import BinanceSourceError


class FakeCryptoSource:
    def __init__(self, records: list[CryptoMarket]) -> None:
        self.records = records
        self.calls = 0

    def collect(self) -> list[CryptoMarket]:
        self.calls += 1
        return self.records


def market(venue: CryptoVenue, base: str, quote: str, symbol: str) -> CryptoMarket:
    names = (None, None) if venue is CryptoVenue.BINANCE else ("비트코인", "Bitcoin")
    return CryptoMarket(venue, base, quote, symbol, *names, True, False)


def test_crypto_pipeline_collects_three_sources_and_projects_records() -> None:
    upbit = FakeCryptoSource([market(CryptoVenue.UPBIT, "BTC", "KRW", "KRW-BTC")])
    bithumb = FakeCryptoSource([market(CryptoVenue.BITHUMB, "BTC", "KRW", "KRW-BTC")])
    binance = FakeCryptoSource([market(CryptoVenue.BINANCE, "BTC", "USDT", "BTCUSDT")])
    pipeline = CryptoCatalogPipeline(upbit, bithumb, binance, max_drop_ratio=0.5)

    records = pipeline.collect_and_project()

    assert [record.i for record in records] == ["BN:BTC-USDT", "BT:BTC-KRW", "UP:BTC-KRW"]
    assert (upbit.calls, bithumb.calls, binance.calls) == (1, 1, 1)


def test_crypto_pipeline_retries_then_preserves_previous_drop_policy(tmp_path: Path) -> None:
    previous = [CryptoCatalogRecord(f"UP:X{index}-KRW", f"코인 {index}", f"Coin {index}") for index in range(10)]
    site = tmp_path / "crypto"
    publish_crypto_catalog(site, previous, datetime(2026, 8, 7, tzinfo=UTC))

    class FlakySource(FakeCryptoSource):
        def collect(self) -> list[CryptoMarket]:
            self.calls += 1
            if self.calls < 3:
                raise BinanceSourceError("temporary")
            return self.records

    upbit = FlakySource(
        [market(CryptoVenue.UPBIT, f"X{index}", "KRW", f"KRW-X{index}") for index in range(8)],
    )
    sleeps: list[float] = []
    pipeline = CryptoCatalogPipeline(
        upbit,
        FakeCryptoSource([]),
        FakeCryptoSource([]),
        max_drop_ratio=0.5,
        sleeper=sleeps.append,
    )

    records = pipeline.collect_and_project(load_published_crypto_catalog(site).records)

    assert len(records) == 8
    assert upbit.calls == 3
    assert sleeps == [1.0, 2.0]


def test_crypto_pipeline_source_failure_bubbles_after_three_attempts() -> None:
    class FailingSource:
        calls = 0

        def collect(self) -> list[CryptoMarket]:
            self.calls += 1
            raise BinanceSourceError("failed")

    failing = FailingSource()
    sleeps: list[float] = []
    pipeline = CryptoCatalogPipeline(
        FakeCryptoSource([]),
        FakeCryptoSource([]),
        failing,
        sleeper=sleeps.append,
    )

    with pytest.raises(BinanceSourceError, match="failed"):
        pipeline.collect_and_project()

    assert failing.calls == 3
    assert sleeps == [1.0, 2.0]
