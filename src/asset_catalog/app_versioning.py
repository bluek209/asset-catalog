from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .app_catalog import AppCatalogRecord


class DeltaApplicationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AppCatalogDelta:
    from_version: str
    to_version: str
    added: tuple[AppCatalogRecord, ...]
    updated: tuple[AppCatalogRecord, ...]
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
    def from_dict(cls, value: dict[str, Any]) -> AppCatalogDelta:
        if int(value.get("v", 0)) != 1:
            raise DeltaApplicationError("unsupported delta schema")
        try:
            return cls(
                str(value["f"]),
                str(value["t"]),
                tuple(AppCatalogRecord.from_dict(item) for item in value.get("a", [])),
                tuple(AppCatalogRecord.from_dict(item) for item in value.get("u", [])),
                tuple(str(identity) for identity in value.get("d", [])),
            )
        except Exception as error:
            raise DeltaApplicationError("delta payload is invalid") from error


def _by_id(records: list[AppCatalogRecord]) -> dict[str, AppCatalogRecord]:
    result: dict[str, AppCatalogRecord] = {}
    for record in records:
        if record.i in result:
            raise DeltaApplicationError(f"duplicate catalog identity: {record.i}")
        result[record.i] = record
    return result


def build_delta(
    from_version: str,
    previous: list[AppCatalogRecord],
    to_version: str,
    current: list[AppCatalogRecord],
) -> AppCatalogDelta:
    old = _by_id(previous)
    new = _by_id(current)
    return AppCatalogDelta(
        from_version,
        to_version,
        tuple(new[identity] for identity in sorted(new.keys() - old.keys())),
        tuple(
            new[identity]
            for identity in sorted(new.keys() & old.keys())
            if new[identity] != old[identity]
        ),
        tuple(sorted(old.keys() - new.keys())),
    )


def apply_delta(
    previous: list[AppCatalogRecord],
    delta: AppCatalogDelta,
    *,
    base_version: str,
) -> list[AppCatalogRecord]:
    if base_version != delta.from_version:
        raise DeltaApplicationError(f"delta expected {delta.from_version}, received {base_version}")
    records = _by_id(previous)
    changed = [
        *(record.i for record in delta.added),
        *(record.i for record in delta.updated),
        *delta.deleted,
    ]
    if len(changed) != len(set(changed)):
        raise DeltaApplicationError("delta contains duplicate operations")
    for record in delta.added:
        if record.i in records:
            raise DeltaApplicationError(f"delta adds existing record {record.i}")
        records[record.i] = record
    for record in delta.updated:
        if record.i not in records:
            raise DeltaApplicationError(f"delta updates unknown record {record.i}")
        records[record.i] = record
    for identity in delta.deleted:
        if identity not in records:
            raise DeltaApplicationError(f"delta deletes unknown record {identity}")
        del records[identity]
    return [records[identity] for identity in sorted(records)]


def compose_deltas(first: AppCatalogDelta, second: AppCatalogDelta) -> AppCatalogDelta:
    if first.to_version != second.from_version:
        raise DeltaApplicationError(
            f"delta edge is disconnected: {first.to_version} != {second.from_version}",
        )
    operations: dict[str, tuple[str, AppCatalogRecord | None]] = {}
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
        raise DeltaApplicationError("delta contains duplicate operations")
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

    def records_for(operation: str) -> tuple[AppCatalogRecord, ...]:
        return tuple(
            value
            for _, (current, value) in sorted(operations.items())
            if current == operation and value is not None
        )

    return AppCatalogDelta(
        first.from_version,
        second.to_version,
        records_for("a"),
        records_for("u"),
        tuple(identity for identity, (op, _) in sorted(operations.items()) if op == "d"),
    )
