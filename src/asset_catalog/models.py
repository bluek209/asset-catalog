from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class InstrumentType(StrEnum):
    COMMON_STOCK = "COMMON_STOCK"
    PREFERRED_STOCK = "PREFERRED_STOCK"
    ADR = "ADR"
    REIT = "REIT"
    SPAC = "SPAC"
    ETF = "ETF"
    ETN = "ETN"


class InstrumentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DELISTED = "DELISTED"


@dataclass(frozen=True, slots=True)
class InstrumentRecord:
    id: str
    symbol: str
    name: str
    english_name: str | None
    market: str
    exchange: str
    currency: str
    instrument_type: InstrumentType
    status: InstrumentStatus
    provider_id: str
    provider_symbol: str
    aliases: tuple[str, ...]
    source_updated_date: str

    def to_dict(self) -> dict[str, Any]:
        aliases = sorted({value.strip() for value in self.aliases if value.strip()})
        return {
            "id": self.id,
            "symbol": self.symbol,
            "name": self.name,
            "englishName": self.english_name,
            "market": self.market,
            "exchange": self.exchange,
            "currency": self.currency,
            "instrumentType": self.instrument_type.value,
            "status": self.status.value,
            "providerId": self.provider_id,
            "providerSymbol": self.provider_symbol,
            "aliases": aliases,
            "sourceUpdatedDate": self.source_updated_date,
        }

    def content_dict(self) -> dict[str, Any]:
        value = self.to_dict()
        del value["sourceUpdatedDate"]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> InstrumentRecord:
        return cls(
            id=str(value["id"]),
            symbol=str(value["symbol"]),
            name=str(value["name"]),
            english_name=(
                str(value["englishName"]) if value.get("englishName") is not None else None
            ),
            market=str(value["market"]),
            exchange=str(value["exchange"]),
            currency=str(value["currency"]),
            instrument_type=InstrumentType(str(value["instrumentType"])),
            status=InstrumentStatus(str(value["status"])),
            provider_id=str(value["providerId"]),
            provider_symbol=str(value["providerSymbol"]),
            aliases=tuple(str(alias) for alias in value.get("aliases", [])),
            source_updated_date=str(value["sourceUpdatedDate"]),
        )

    def with_status(self, status: InstrumentStatus) -> InstrumentRecord:
        return replace(self, status=status)
