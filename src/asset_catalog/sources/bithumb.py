from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.request import urlopen

from ..crypto_models import ASSET_PATTERN, CryptoMarket, CryptoVenue


BITHUMB_MARKETS_URL = "https://api.bithumb.com/v1/market/all?isDetails=true"
WARNING_VALUES = {"NONE": False, "CAUTION": True}


class BithumbSourceError(RuntimeError):
    pass


OpenBytes = Callable[[str, float], bytes]


def _download(url: str, timeout: float) -> bytes:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS origin
        return response.read()


def _name(item: dict[str, Any], key: str) -> str:
    value = " ".join(str(item.get(key, "")).split())
    if not value:
        raise BithumbSourceError("Bithumb market has an invalid name")
    return value


def parse_bithumb_markets(data: bytes) -> list[CryptoMarket]:
    try:
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, list):
            raise BithumbSourceError("Bithumb market payload has an invalid root")
        records: list[CryptoMarket] = []
        for item in payload:
            if not isinstance(item, dict):
                raise BithumbSourceError("Bithumb market payload has an invalid row")
            market = str(item.get("market", "")).strip().upper()
            parts = market.split("-")
            if len(parts) != 2 or any(ASSET_PATTERN.fullmatch(part) is None for part in parts):
                raise BithumbSourceError("Bithumb market has an invalid symbol")
            warning_value = str(item.get("market_warning", "")).strip().upper()
            if warning_value not in WARNING_VALUES:
                raise BithumbSourceError("Bithumb market has an invalid warning")
            quote, base = parts
            records.append(
                CryptoMarket(
                    venue=CryptoVenue.BITHUMB,
                    base=base,
                    quote=quote,
                    provider_symbol=market,
                    korean_name=_name(item, "korean_name"),
                    english_name=_name(item, "english_name"),
                    tradable=True,
                    warning=WARNING_VALUES[warning_value],
                ),
            )
        return sorted(records, key=lambda record: record.provider_symbol)
    except BithumbSourceError:
        raise
    except Exception as error:
        raise BithumbSourceError("Bithumb markets could not be read") from error


class BithumbClient:
    def __init__(self, *, opener: OpenBytes = _download, timeout: float = 30.0) -> None:
        self._opener = opener
        self._timeout = timeout

    def collect(self) -> list[CryptoMarket]:
        try:
            return parse_bithumb_markets(self._opener(BITHUMB_MARKETS_URL, self._timeout))
        except BithumbSourceError:
            raise
        except Exception as error:
            raise BithumbSourceError("Bithumb markets could not be read") from error
