from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from .crypto_models import ASSET_PATTERN, CryptoMarket, CryptoVenue


class CryptoCatalogProjectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CryptoCatalogRecord:
    i: str
    k: str
    e: str

    def __post_init__(self) -> None:
        provider_symbol_for(self.i)
        if not self.k.strip() or not self.e.strip():
            raise CryptoCatalogProjectionError("crypto catalog record has empty fields")
        if self.k != " ".join(self.k.split()) or self.e != " ".join(self.e.split()):
            raise CryptoCatalogProjectionError("crypto catalog record names are not canonical")

    def to_dict(self) -> dict[str, str]:
        return {"i": self.i, "k": self.k, "e": self.e}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CryptoCatalogRecord:
        if set(value) != {"i", "k", "e"}:
            raise CryptoCatalogProjectionError("crypto catalog record has invalid fields")
        return cls(str(value["i"]), str(value["k"]), str(value["e"]))


def _identity_parts(identity: str) -> tuple[CryptoVenue, str, str]:
    try:
        prefix, pair = identity.split(":", 1)
        base, quote = pair.rsplit("-", 1)
        venue = CryptoVenue(prefix)
    except (ValueError, TypeError) as error:
        raise CryptoCatalogProjectionError("crypto catalog id is invalid") from error
    if ASSET_PATTERN.fullmatch(base) is None or ASSET_PATTERN.fullmatch(quote) is None:
        raise CryptoCatalogProjectionError("crypto catalog id has an invalid asset")
    expected_quote = "USDT" if venue is CryptoVenue.BINANCE else "KRW"
    if quote != expected_quote:
        raise CryptoCatalogProjectionError("crypto catalog id has an invalid quote")
    return venue, base, quote


def provider_symbol_for(identity: str) -> str:
    venue, base, quote = _identity_parts(identity)
    if venue in {CryptoVenue.UPBIT, CryptoVenue.BITHUMB}:
        return f"{quote}-{base}"
    return f"{base}{quote}"


def _is_target(market: CryptoMarket) -> bool:
    if not market.tradable or market.warning:
        return False
    if market.venue in {CryptoVenue.UPBIT, CryptoVenue.BITHUMB}:
        return market.quote == "KRW"
    return market.quote == "USDT"


def project_crypto_records(
    markets: list[CryptoMarket],
    *,
    excluded_ids: set[str] | None = None,
) -> list[CryptoCatalogRecord]:
    excluded = excluded_ids or set()
    eligible = [market for market in markets if _is_target(market)]
    names_by_base: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for market in eligible:
        if market.korean_name is not None:
            names_by_base[market.base].add(
                (" ".join(market.korean_name.split()), " ".join(market.english_name.split())),
            )

    projected: dict[str, CryptoCatalogRecord] = {}
    for market in eligible:
        identity = f"{market.venue.value}:{market.base}-{market.quote}"
        if provider_symbol_for(identity) != market.provider_symbol:
            raise CryptoCatalogProjectionError(f"provider symbol does not match crypto catalog id: {identity}")
        if market.korean_name is not None:
            korean_name = " ".join(market.korean_name.split())
            english_name = " ".join(market.english_name.split())
        else:
            candidates = names_by_base.get(market.base, set())
            korean_name, english_name = next(iter(candidates)) if len(candidates) == 1 else (market.base, market.base)
        item = CryptoCatalogRecord(identity, korean_name, english_name)
        if identity in projected:
            raise CryptoCatalogProjectionError(f"duplicate crypto catalog id: {identity}")
        if identity not in excluded:
            projected[identity] = item
    return [projected[identity] for identity in sorted(projected)]


def validate_crypto_drop(
    current: list[CryptoCatalogRecord],
    previous: list[CryptoCatalogRecord],
    *,
    max_drop_ratio: float,
) -> None:
    if not 0 <= max_drop_ratio < 1:
        raise ValueError("max_drop_ratio must be between 0 and 1")
    old_counts = Counter(record.i.split(":", 1)[0] for record in previous)
    new_counts = Counter(record.i.split(":", 1)[0] for record in current)
    for venue, old_count in sorted(old_counts.items()):
        new_count = new_counts[venue]
        if (old_count - new_count) / old_count > max_drop_ratio:
            raise CryptoCatalogProjectionError(f"{venue} count dropped from {old_count} to {new_count}")
