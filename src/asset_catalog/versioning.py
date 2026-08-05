from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .canonical import canonical_bytes
from .models import InstrumentRecord, InstrumentStatus


class DeltaApplicationError(RuntimeError):
    pass


class DeltaReconstructionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CatalogDelta:
    from_version: str
    to_version: str
    added: tuple[InstrumentRecord, ...]
    updated: tuple[InstrumentRecord, ...]
    deactivated: tuple[InstrumentRecord, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "fromVersion": self.from_version,
            "toVersion": self.to_version,
            "added": [record.to_dict() for record in self.added],
            "updated": [record.to_dict() for record in self.updated],
            "deactivated": [record.to_dict() for record in self.deactivated],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CatalogDelta:
        return cls(
            schema_version=int(value["schemaVersion"]),
            from_version=str(value["fromVersion"]),
            to_version=str(value["toVersion"]),
            added=tuple(InstrumentRecord.from_dict(item) for item in value.get("added", [])),
            updated=tuple(InstrumentRecord.from_dict(item) for item in value.get("updated", [])),
            deactivated=tuple(
                InstrumentRecord.from_dict(item) for item in value.get("deactivated", [])
            ),
        )


def reconcile_snapshot(
    previous: list[InstrumentRecord],
    collected_active: list[InstrumentRecord],
) -> list[InstrumentRecord]:
    previous_by_id = {record.id: record for record in previous}
    collected_by_id = {
        record.id: record.with_status(InstrumentStatus.ACTIVE)
        for record in collected_active
    }
    reconciled = dict(collected_by_id)
    for record_id, old_record in previous_by_id.items():
        if record_id in collected_by_id:
            continue
        if old_record.status is InstrumentStatus.ACTIVE:
            status = InstrumentStatus.INACTIVE
        else:
            status = InstrumentStatus.DELISTED
        reconciled[record_id] = old_record.with_status(status)
    return sorted(reconciled.values(), key=lambda record: record.id)


def build_delta(
    from_version: str,
    previous: list[InstrumentRecord],
    to_version: str,
    current: list[InstrumentRecord],
) -> CatalogDelta:
    previous_by_id = {record.id: record for record in previous}
    current_by_id = {record.id: record for record in current}
    missing_ids = previous_by_id.keys() - current_by_id.keys()
    if missing_ids:
        raise DeltaApplicationError(
            "current snapshot must retain every previous identity: " + ", ".join(sorted(missing_ids)),
        )

    added: list[InstrumentRecord] = []
    updated: list[InstrumentRecord] = []
    deactivated: list[InstrumentRecord] = []
    for record_id, current_record in current_by_id.items():
        previous_record = previous_by_id.get(record_id)
        if previous_record is None:
            added.append(current_record)
        elif previous_record.content_dict() != current_record.content_dict():
            if current_record.status is InstrumentStatus.ACTIVE:
                updated.append(current_record)
            else:
                deactivated.append(current_record)

    return CatalogDelta(
        from_version=from_version,
        to_version=to_version,
        added=tuple(sorted(added, key=lambda record: record.id)),
        updated=tuple(sorted(updated, key=lambda record: record.id)),
        deactivated=tuple(sorted(deactivated, key=lambda record: record.id)),
    )


def apply_delta(
    previous: list[InstrumentRecord],
    delta: CatalogDelta,
    *,
    base_version: str,
) -> list[InstrumentRecord]:
    if base_version != delta.from_version:
        raise DeltaApplicationError(
            f"delta expected {delta.from_version}, received {base_version}",
        )
    records = {record.id: record for record in previous}
    changes = (
        ("added", delta.added),
        ("updated", delta.updated),
        ("deactivated", delta.deactivated),
    )
    changed_ids = [record.id for _, group in changes for record in group]
    if len(changed_ids) != len(set(changed_ids)):
        raise DeltaApplicationError("delta contains duplicate instrument changes")

    for record in delta.added:
        if record.id in records:
            raise DeltaApplicationError(f"delta adds existing instrument {record.id}")
        records[record.id] = record
    for group in (delta.updated, delta.deactivated):
        for record in group:
            if record.id not in records:
                raise DeltaApplicationError(f"delta changes unknown instrument {record.id}")
            records[record.id] = record
    return sorted(records.values(), key=lambda record: record.id)


def verify_reconstruction(
    previous: list[InstrumentRecord],
    delta: CatalogDelta,
    expected: list[InstrumentRecord],
    *,
    base_version: str,
) -> bool:
    reconstructed = apply_delta(previous, delta, base_version=base_version)
    if canonical_bytes(reconstructed) != canonical_bytes(expected):
        raise DeltaReconstructionError("delta reconstruction does not match current snapshot")
    return True


def compose_deltas(first: CatalogDelta, second: CatalogDelta) -> CatalogDelta:
    if first.to_version != second.from_version:
        raise DeltaApplicationError(
            f"delta edge is disconnected: {first.to_version} != {second.from_version}",
        )
    operations: dict[str, tuple[str, InstrumentRecord]] = {}
    for operation, records in (
        ("added", first.added),
        ("updated", first.updated),
        ("deactivated", first.deactivated),
    ):
        for record in records:
            operations[record.id] = (operation, record)

    for next_operation, records in (
        ("added", second.added),
        ("updated", second.updated),
        ("deactivated", second.deactivated),
    ):
        for record in records:
            prior = operations.get(record.id)
            if prior is None:
                operations[record.id] = (next_operation, record)
                continue
            prior_operation, _ = prior
            if prior_operation == "added" and next_operation == "deactivated":
                del operations[record.id]
            elif prior_operation == "added":
                operations[record.id] = ("added", record)
            elif next_operation == "deactivated":
                operations[record.id] = ("deactivated", record)
            else:
                operations[record.id] = ("updated", record)

    def records_for(operation: str) -> tuple[InstrumentRecord, ...]:
        return tuple(
            record
            for _, record in sorted(
                (record_id, value[1])
                for record_id, value in operations.items()
                if value[0] == operation
            )
        )

    return CatalogDelta(
        from_version=first.from_version,
        to_version=second.to_version,
        added=records_for("added"),
        updated=records_for("updated"),
        deactivated=records_for("deactivated"),
    )
