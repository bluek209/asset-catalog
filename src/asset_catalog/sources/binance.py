from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.request import urlopen

from ..crypto_models import ASSET_PATTERN, CryptoMarket, CryptoVenue


BINANCE_MARKETS_URL = "https://data-api.binance.vision/api/v3/exchangeInfo"


class BinanceSourceError(RuntimeError):
    pass


OpenBytes = Callable[[str, float], bytes]


def _download(url: str, timeout: float) -> bytes:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS origin
        return response.read()


def _spot_allowed(item: dict[str, Any]) -> bool:
    explicit = item.get("isSpotTradingAllowed")
    if isinstance(explicit, bool):
        return explicit
    permissions = item.get("permissions", [])
    if not isinstance(permissions, list):
        raise BinanceSourceError("Binance market has invalid permissions")
    return "SPOT" in permissions


def parse_binance_markets(data: bytes) -> list[CryptoMarket]:
    try:
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
            raise BinanceSourceError("Binance market payload has an invalid root")
        records: list[CryptoMarket] = []
        for item in payload["symbols"]:
            if not isinstance(item, dict):
                raise BinanceSourceError("Binance market payload has an invalid row")
            base = str(item.get("baseAsset", "")).strip().upper()
            quote = str(item.get("quoteAsset", "")).strip().upper()
            symbol = str(item.get("symbol", "")).strip().upper()
            if (
                ASSET_PATTERN.fullmatch(base) is None
                or ASSET_PATTERN.fullmatch(quote) is None
                or symbol != f"{base}{quote}"
            ):
                raise BinanceSourceError("Binance market has an invalid symbol")
            status = str(item.get("status", "")).strip().upper()
            if not status:
                raise BinanceSourceError("Binance market has an invalid status")
            records.append(
                CryptoMarket(
                    venue=CryptoVenue.BINANCE,
                    base=base,
                    quote=quote,
                    provider_symbol=symbol,
                    korean_name=None,
                    english_name=None,
                    tradable=status == "TRADING" and _spot_allowed(item),
                    warning=False,
                ),
            )
        return sorted(records, key=lambda record: record.provider_symbol)
    except BinanceSourceError:
        raise
    except Exception as error:
        raise BinanceSourceError("Binance markets could not be read") from error


class BinanceClient:
    def __init__(self, *, opener: OpenBytes = _download, timeout: float = 30.0) -> None:
        self._opener = opener
        self._timeout = timeout

    def collect(self) -> list[CryptoMarket]:
        try:
            return parse_binance_markets(self._opener(BINANCE_MARKETS_URL, self._timeout))
        except BinanceSourceError:
            raise
        except Exception as error:
            raise BinanceSourceError("Binance markets could not be read") from error
