from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


ASSET_PATTERN = re.compile(r"[^\W_]{1,20}", flags=re.UNICODE)


class CryptoVenue(StrEnum):
    UPBIT = "UP"
    BITHUMB = "BT"
    BINANCE = "BN"


@dataclass(frozen=True, slots=True)
class CryptoMarket:
    venue: CryptoVenue
    base: str
    quote: str
    provider_symbol: str
    korean_name: str | None
    english_name: str | None
    tradable: bool
    warning: bool

    def __post_init__(self) -> None:
        if ASSET_PATTERN.fullmatch(self.base) is None or ASSET_PATTERN.fullmatch(self.quote) is None:
            raise ValueError("crypto market has an invalid asset")
        if not self.provider_symbol or self.provider_symbol != self.provider_symbol.upper():
            raise ValueError("crypto market has an invalid provider symbol")
        if (self.korean_name is None) != (self.english_name is None):
            raise ValueError("crypto market names must both be present or absent")
        if self.korean_name is not None and (not self.korean_name.strip() or not self.english_name.strip()):
            raise ValueError("crypto market has an empty name")
