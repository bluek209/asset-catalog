from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.request import urlopen

from ..crypto_models import ASSET_PATTERN, CryptoMarket, CryptoVenue


UPBIT_MARKETS_URL = "https://api.upbit.com/v1/market/all?is_details=true"


class UpbitSourceError(RuntimeError):
    pass


OpenBytes = Callable[[str, float], bytes]


def _download(url: str, timeout: float) -> bytes:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS origin
        return response.read()


def _name(item: dict[str, Any], key: str) -> str:
    value = " ".join(str(item.get(key, "")).split())
    if not value:
        raise UpbitSourceError("Upbit market has an invalid name")
    return value


def parse_upbit_markets(data: bytes) -> list[CryptoMarket]:
    try:
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, list):
            raise UpbitSourceError("Upbit market payload has an invalid root")
        records: list[CryptoMarket] = []
        for item in payload:
            if not isinstance(item, dict):
                raise UpbitSourceError("Upbit market payload has an invalid row")
            market = str(item.get("market", "")).strip().upper()
            parts = market.split("-")
            if len(parts) != 2 or any(ASSET_PATTERN.fullmatch(part) is None for part in parts):
                raise UpbitSourceError("Upbit market has an invalid symbol")
            quote, base = parts
            event = item.get("market_event")
            if not isinstance(event, dict) or not isinstance(event.get("warning"), bool):
                raise UpbitSourceError("Upbit market has an invalid event")
            records.append(
                CryptoMarket(
                    venue=CryptoVenue.UPBIT,
                    base=base,
                    quote=quote,
                    provider_symbol=market,
                    korean_name=_name(item, "korean_name"),
                    english_name=_name(item, "english_name"),
                    tradable=True,
                    warning=event["warning"],
                ),
            )
        return sorted(records, key=lambda record: record.provider_symbol)
    except UpbitSourceError:
        raise
    except Exception as error:
        raise UpbitSourceError("Upbit markets could not be read") from error


class UpbitClient:
    def __init__(self, *, opener: OpenBytes = _download, timeout: float = 30.0) -> None:
        self._opener = opener
        self._timeout = timeout

    def collect(self) -> list[CryptoMarket]:
        try:
            return parse_upbit_markets(self._opener(UPBIT_MARKETS_URL, self._timeout))
        except UpbitSourceError:
            raise
        except Exception as error:
            raise UpbitSourceError("Upbit markets could not be read") from error
