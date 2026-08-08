from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .crypto_catalog import CryptoCatalogRecord


class CryptoDeltaApplicationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CryptoCatalogDelta:
    from_version: str
    to_version: str
    added: tuple[CryptoCatalogRecord, ...]
    updated: tuple[CryptoCatalogRecord, ...]
    deleted: tuple[str, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.schema_version,
            "f": self.from_version,
            "t": self.to_version,
            "a": [record.to_dict() for record in self.added],
            "u": [record.to_dict() for record in self.updated],
            "d": list(self.deleted),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CryptoCatalogDelta:
        if set(value) != {"v", "f", "t", "a", "u", "d"} or int(value.get("v", 0)) != 1:
            raise CryptoDeltaApplicationError("unsupported crypto delta schema")
        try:
            return cls(
                str(value["f"]),
                str(value["t"]),
                tuple(CryptoCatalogRecord.from_dict(item) for item in value["a"]),
                tuple(CryptoCatalogRecord.from_dict(item) for item in value["u"]),
                tuple(str(identity) for identity in value["d"]),
            )
        except Exception as error:
            raise CryptoDeltaApplicationError("crypto delta payload is invalid") from error


def _by_id(records: list[CryptoCatalogRecord]) -> dict[str, CryptoCatalogRecord]:
    result: dict[str, CryptoCatalogRecord] = {}
    for record in records:
        if record.i in result:
            raise CryptoDeltaApplicationError(f"duplicate crypto catalog identity: {record.i}")
        result[record.i] = record
    return result


def build_crypto_delta(
    from_version: str,
    previous: list[CryptoCatalogRecord],
    to_version: str,
    current: list[CryptoCatalogRecord],
) -> CryptoCatalogDelta:
    old = _by_id(previous)
    new = _by_id(current)
    return CryptoCatalogDelta(
        from_version,
        to_version,
        tuple(new[identity] for identity in sorted(new.keys() - old.keys())),
        tuple(new[identity] for identity in sorted(new.keys() & old.keys()) if new[identity] != old[identity]),
        tuple(sorted(old.keys() - new.keys())),
    )


def apply_crypto_delta(
    previous: list[CryptoCatalogRecord],
    delta: CryptoCatalogDelta,
    *,
    base_version: str,
) -> list[CryptoCatalogRecord]:
    if base_version != delta.from_version:
        raise CryptoDeltaApplicationError(f"crypto delta expected {delta.from_version}, received {base_version}")
    records = _by_id(previous)
    changed = [
        *(record.i for record in delta.added),
        *(record.i for record in delta.updated),
        *delta.deleted,
    ]
    if len(changed) != len(set(changed)):
        raise CryptoDeltaApplicationError("crypto delta contains duplicate operations")
    for record in delta.added:
        if record.i in records:
            raise CryptoDeltaApplicationError(f"crypto delta adds existing record {record.i}")
        records[record.i] = record
    for record in delta.updated:
        if record.i not in records:
            raise CryptoDeltaApplicationError(f"crypto delta updates unknown record {record.i}")
        records[record.i] = record
    for identity in delta.deleted:
        if identity not in records:
            raise CryptoDeltaApplicationError(f"crypto delta deletes unknown record {identity}")
        del records[identity]
    return [records[identity] for identity in sorted(records)]


def compose_crypto_deltas(first: CryptoCatalogDelta, second: CryptoCatalogDelta) -> CryptoCatalogDelta:
    if first.to_version != second.from_version:
        raise CryptoDeltaApplicationError(
            f"crypto delta edge is disconnected: {first.to_version} != {second.from_version}",
        )
    operations: dict[str, tuple[str, CryptoCatalogRecord | None]] = {}
    for operation, records in (("a", first.added), ("u", first.updated)):
        for record in records:
            operations[record.i] = (operation, record)
    for identity in first.deleted:
        operations[identity] = ("d", None)

    following = [
        *(("a", record.i, record) for record in second.added),
        *(("u", record.i, record) for record in second.updated),
        *(("d", identity, None) for identity in second.deleted),
    ]
    following_ids = [identity for _, identity, _ in following]
    if len(following_ids) != len(set(following_ids)):
        raise CryptoDeltaApplicationError("crypto delta contains duplicate operations")
    for next_operation, identity, record in following:
        prior = operations.get(identity)
        if prior is None:
            operations[identity] = (next_operation, record)
            continue
        prior_operation, _ = prior
        if prior_operation == "a" and next_operation == "d":
            del operations[identity]
        elif prior_operation == "a":
            operations[identity] = ("a", record)
        elif prior_operation == "d" and next_operation == "a":
            operations[identity] = ("u", record)
        elif next_operation == "d":
            operations[identity] = ("d", None)
        else:
            operations[identity] = ("u", record)

    def records_for(operation: str) -> tuple[CryptoCatalogRecord, ...]:
        return tuple(
            value
            for _, (current, value) in sorted(operations.items())
            if current == operation and value is not None
        )

    return CryptoCatalogDelta(
        first.from_version,
        second.to_version,
        records_for("a"),
        records_for("u"),
        tuple(identity for identity, (operation, _) in sorted(operations.items()) if operation == "d"),
    )
