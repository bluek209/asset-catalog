from dataclasses import replace

import pytest

from asset_catalog.models import (
    InstrumentRecord,
    InstrumentStatus,
    InstrumentType,
)
from asset_catalog.versioning import (
    DeltaApplicationError,
    apply_delta,
    build_delta,
    compose_deltas,
    reconcile_snapshot,
    verify_reconstruction,
)


def record(
    record_id: str,
    *,
    name: str | None = None,
    status: InstrumentStatus = InstrumentStatus.ACTIVE,
) -> InstrumentRecord:
    market, symbol = record_id.split(":", 1)
    korean = market == "KR"
    return InstrumentRecord(
        id=record_id,
        symbol=symbol,
        name=name or symbol,
        english_name=None if korean else (name or symbol),
        market=market,
        exchange="KOSPI" if korean else "NASDAQ",
        currency="KRW" if korean else "USD",
        instrument_type=InstrumentType.COMMON_STOCK,
        status=status,
        provider_id="yahoo",
        provider_symbol=f"{symbol}.KS" if korean else symbol,
        aliases=(symbol, name or symbol),
        source_updated_date="2026-08-05",
    )


def test_reconcile_moves_missing_record_through_inactive_and_delisted() -> None:
    apple = record("US:AAPL")

    first_missing = reconcile_snapshot([apple], [])
    second_missing = reconcile_snapshot(first_missing, [])

    assert first_missing[0].status is InstrumentStatus.INACTIVE
    assert second_missing[0].status is InstrumentStatus.DELISTED
    assert reconcile_snapshot(second_missing, [apple])[0].status is InstrumentStatus.ACTIVE


def test_delta_adds_updates_and_deactivates_then_reconstructs_snapshot() -> None:
    previous = [record("KR:005930", name="삼성전자"), record("US:AAPL")]
    collected = [record("KR:005930", name="삼성전자 보통주"), record("US:QQQ")]
    current = reconcile_snapshot(previous, collected)

    delta = build_delta("v1", previous, "v2", current)

    assert [item.id for item in delta.added] == ["US:QQQ"]
    assert [item.id for item in delta.updated] == ["KR:005930"]
    assert [item.id for item in delta.deactivated] == ["US:AAPL"]
    assert delta.deactivated[0].status is InstrumentStatus.INACTIVE
    assert verify_reconstruction(previous, delta, current, base_version="v1")


def test_apply_delta_rejects_wrong_local_version() -> None:
    delta = build_delta("v1", [], "v2", [record("US:AAPL")])

    with pytest.raises(DeltaApplicationError, match="expected v1, received old"):
        apply_delta([], delta, base_version="old")


def test_cumulative_delta_coalesces_multiple_changes() -> None:
    added = record("US:NEW", name="New One")
    first = build_delta("v1", [], "v2", [added])
    second = build_delta("v2", [added], "v3", [replace(added, name="New Two")])

    cumulative = compose_deltas(first, second)

    assert cumulative.from_version == "v1"
    assert cumulative.to_version == "v3"
    assert [item.name for item in cumulative.added] == ["New Two"]
    assert not cumulative.updated


def test_cumulative_delta_removes_add_then_deactivate_cycle() -> None:
    added = record("US:NEW")
    inactive = added.with_status(InstrumentStatus.INACTIVE)
    first = build_delta("v1", [], "v2", [added])
    second = build_delta("v2", [added], "v3", [inactive])

    cumulative = compose_deltas(first, second)

    assert not cumulative.added
    assert not cumulative.updated
    assert not cumulative.deactivated
