import pytest

from asset_catalog.app_catalog import AppCatalogRecord
from asset_catalog.app_versioning import (
    AppCatalogDelta,
    DeltaApplicationError,
    apply_delta,
    build_delta,
    compose_deltas,
)


def record(identity: str, name: str | None = None) -> AppCatalogRecord:
    return AppCatalogRecord(identity, name or identity)


def test_delta_round_trips_and_reconstructs_add_update_delete() -> None:
    previous = [record("KQ:035900", "JYP Ent."), record("Q:OLD", "Old")]
    current = [record("KQ:035900", "JYP Entertainment"), record("Q:NEW", "New")]

    delta = build_delta("v1", previous, "v2", current)
    payload = delta.to_dict()

    assert payload == {
        "v": 1,
        "f": "v1",
        "t": "v2",
        "a": [{"i": "Q:NEW", "n": "New"}],
        "u": [{"i": "KQ:035900", "n": "JYP Entertainment"}],
        "d": ["Q:OLD"],
    }
    assert AppCatalogDelta.from_dict(payload) == delta
    assert apply_delta(previous, delta, base_version="v1") == current


def test_apply_rejects_wrong_version_and_duplicate_operations() -> None:
    previous = [record("Q:AAPL")]
    delta = AppCatalogDelta("v1", "v2", (), (record("Q:AAPL"),), ("Q:AAPL",))

    with pytest.raises(DeltaApplicationError, match="expected v1"):
        apply_delta(previous, delta, base_version="old")
    with pytest.raises(DeltaApplicationError, match="duplicate operations"):
        apply_delta(previous, delta, base_version="v1")


def test_composition_handles_add_update_delete_cycles() -> None:
    first = AppCatalogDelta(
        "v1",
        "v2",
        (record("Q:ADDED", "One"),),
        (),
        ("Q:RETURN",),
    )
    second = AppCatalogDelta(
        "v2",
        "v3",
        (record("Q:RETURN", "Returned"),),
        (record("Q:ADDED", "Two"),),
        ("Q:ADDED",),
    )

    with pytest.raises(DeltaApplicationError, match="duplicate operations"):
        apply_delta([], second, base_version="v2")

    valid_second = AppCatalogDelta(
        "v2",
        "v3",
        (record("Q:RETURN", "Returned"),),
        (),
        ("Q:ADDED",),
    )
    cumulative = compose_deltas(first, valid_second)

    assert cumulative.added == ()
    assert cumulative.updated == (record("Q:RETURN", "Returned"),)
    assert cumulative.deleted == ()


def test_compose_rejects_disconnected_edges() -> None:
    with pytest.raises(DeltaApplicationError, match="disconnected"):
        compose_deltas(
            AppCatalogDelta("v1", "v2", (), (), ()),
            AppCatalogDelta("other", "v3", (), (), ()),
        )
