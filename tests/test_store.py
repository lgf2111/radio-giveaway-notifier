"""Tests for hotline.store."""

from __future__ import annotations

from hotline.sources import Item
from hotline.store import TTL_SECONDS, Store, item_hash


def _item() -> Item:
    return Item(
        title="Win Tickets",
        url="https://example.test/win",
        text="call now to win tickets",
        published=None,
        source="web",
    )


def test_item_hash_stable_and_normalized() -> None:
    a = Item("Win  Tickets", "https://example.test/win", "Call Now ", None, "web")
    b = Item("win tickets", "https://example.test/win", "call now", None, "web")
    assert item_hash(a) == item_hash(b)


def test_seen_record_flow() -> None:
    store = Store(":memory:")
    h = item_hash(_item())
    assert store.seen(h) is False
    store.record(h)
    assert store.seen(h) is True


def test_should_notify_flow() -> None:
    store = Store(":memory:")
    item = _item()
    h = item_hash(item)
    # Unseen -> should notify.
    assert store.should_notify(item) is True
    store.record(h)
    # Seen but not notified and fresh -> should still notify.
    assert store.should_notify(h) is True
    store.mark_notified(h)
    # Notified -> never notify again.
    assert store.should_notify(item) is False
    assert store.should_notify(h) is False


def test_same_hash_not_notified_twice() -> None:
    store = Store(":memory:")
    h = item_hash(_item())
    store.mark_notified(h)
    assert store.should_notify(h) is False


def test_prune_removes_back_dated_entry() -> None:
    clock = {"now": 1_000_000.0}
    store = Store(":memory:", now=lambda: clock["now"])
    h = item_hash(_item())
    store.record(h)
    assert store.seen(h) is True
    # Advance well beyond the TTL and prune.
    clock["now"] += TTL_SECONDS + 10
    deleted = store.prune()
    assert deleted == 1
    assert store.seen(h) is False


def test_prune_keeps_fresh_entry() -> None:
    clock = {"now": 1_000_000.0}
    store = Store(":memory:", now=lambda: clock["now"])
    h = item_hash(_item())
    store.record(h)
    clock["now"] += 10
    assert store.prune() == 0
    assert store.seen(h) is True


def test_expired_unnotified_entry_not_notified() -> None:
    clock = {"now": 1_000_000.0}
    store = Store(":memory:", now=lambda: clock["now"])
    h = item_hash(_item())
    store.record(h)
    clock["now"] += TTL_SECONDS + 10
    assert store.should_notify(h) is False
