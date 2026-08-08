import pytest

from asset_catalog.crypto_catalog import CryptoCatalogRecord
from asset_catalog.crypto_versioning import (
    CryptoCatalogDelta,
    CryptoDeltaApplicationError,
    apply_crypto_delta,
    build_crypto_delta,
    compose_crypto_deltas,
)


def record(identity: str, korean: str | None = None, english: str | None = None) -> CryptoCatalogRecord:
    symbol = identity.split(":", 1)[1].rsplit("-", 1)[0]
    return CryptoCatalogRecord(identity, korean or symbol, english or symbol)


def test_crypto_delta_round_trips_add_update_delete_with_exact_fields() -> None:
    previous = [record("UP:BTC-KRW", "비트코인", "Bitcoin"), record("BN:OLD-USDT")]
    current = [record("BT:ETH-KRW", "이더리움", "Ethereum"), record("UP:BTC-KRW", "비트코인 변경", "Bitcoin Updated")]

    delta = build_crypto_delta("v1", previous, "v2", current)

    assert delta.to_dict() == {
        "v": 1,
        "f": "v1",
        "t": "v2",
        "a": [{"i": "BT:ETH-KRW", "k": "이더리움", "e": "Ethereum"}],
        "u": [{"i": "UP:BTC-KRW", "k": "비트코인 변경", "e": "Bitcoin Updated"}],
        "d": ["BN:OLD-USDT"],
    }
    assert CryptoCatalogDelta.from_dict(delta.to_dict()) == delta
    assert apply_crypto_delta(previous, delta, base_version="v1") == current


def test_crypto_delta_rejects_wrong_version_and_duplicate_operations() -> None:
    previous = [record("UP:BTC-KRW")]
    delta = CryptoCatalogDelta("v1", "v2", (), (record("UP:BTC-KRW"),), ("UP:BTC-KRW",))

    with pytest.raises(CryptoDeltaApplicationError, match="expected v1"):
        apply_crypto_delta(previous, delta, base_version="old")
    with pytest.raises(CryptoDeltaApplicationError, match="duplicate operations"):
        apply_crypto_delta(previous, delta, base_version="v1")


def test_crypto_delta_composition_handles_add_update_delete_cycles() -> None:
    first = CryptoCatalogDelta(
        "v1",
        "v2",
        (record("BN:ADDED-USDT", "추가", "Added"),),
        (),
        ("BT:RETURN-KRW",),
    )
    second = CryptoCatalogDelta(
        "v2",
        "v3",
        (record("BT:RETURN-KRW", "복귀", "Returned"),),
        (),
        ("BN:ADDED-USDT",),
    )

    cumulative = compose_crypto_deltas(first, second)

    assert cumulative.added == ()
    assert cumulative.updated == (record("BT:RETURN-KRW", "복귀", "Returned"),)
    assert cumulative.deleted == ()


def test_crypto_delta_rejects_disconnected_edges() -> None:
    with pytest.raises(CryptoDeltaApplicationError, match="disconnected"):
        compose_crypto_deltas(
            CryptoCatalogDelta("v1", "v2", (), (), ()),
            CryptoCatalogDelta("other", "v3", (), (), ()),
        )
