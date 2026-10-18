"""SQLite-backed dedupe store with a 7-day TTL.

Keeps a hash per seen item plus ``first_seen`` and a ``notified`` flag so the
same contest is never alerted twice. Entries older than 7 days are pruned so
a recurring contest can alert again after the window.

The clock is injectable (``now`` callable) so tests can control time without
patching :mod:`time`.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable

from hotline.sources import Item

TTL_SECONDS = 604800  # 7 days

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_items (
    hash        TEXT PRIMARY KEY,
    first_seen  REAL NOT NULL,
    notified    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_seen_items_first_seen ON seen_items(first_seen);
"""


def _normalize(value: str) -> str:
    """Lowercase, strip, and collapse internal whitespace."""
    return " ".join(value.strip().lower().split())


def item_hash(item: Item) -> str:
    """Return a stable sha256 hash for ``item``.

    The hash is computed over the normalized title, raw URL, and normalized
    text joined by newlines, so re-polls of the same item produce the same
    hash.

    Args:
        item: The item to hash.

    Returns:
        A hex sha256 digest.
    """
    payload = "\n".join([_normalize(item.title), item.url, _normalize(item.text)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Store:
    """Dedupe store over a SQLite database.

    Args:
        db_path: Database path. Use ``":memory:"`` for an ephemeral store.
        now: Injectable clock returning epoch seconds. Defaults to
            :func:`time.time`.
    """

    def __init__(self, db_path: str, now: Callable[[], float] = time.time) -> None:
        self._conn = sqlite3.connect(db_path)
        self._now = now
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    def seen(self, hash_: str) -> bool:
        """Return whether ``hash_`` has been recorded."""
        row = self._conn.execute("SELECT 1 FROM seen_items WHERE hash = ?", (hash_,)).fetchone()
        return row is not None

    def record(self, hash_: str) -> None:
        """Record ``hash_`` with ``first_seen=now`` if not already present."""
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_items (hash, first_seen, notified) VALUES (?, ?, 0)",
            (hash_, self._now()),
        )
        self._conn.commit()

    def mark_notified(self, hash_: str) -> None:
        """Mark ``hash_`` as notified, recording it first if unseen."""
        self.record(hash_)
        self._conn.execute("UPDATE seen_items SET notified = 1 WHERE hash = ?", (hash_,))
        self._conn.commit()

    def should_notify(self, item_or_hash: Item | str) -> bool:
        """Return whether an item/hash should trigger a notification.

        True when the hash is absent, or present with ``notified=0`` and not
        older than the 7-day TTL. False when already notified or expired.

        Args:
            item_or_hash: An :class:`Item` (hashed here) or a precomputed hash.
        """
        hash_ = item_or_hash if isinstance(item_or_hash, str) else item_hash(item_or_hash)
        row = self._conn.execute(
            "SELECT first_seen, notified FROM seen_items WHERE hash = ?", (hash_,)
        ).fetchone()
        if row is None:
            return True
        first_seen, notified = row
        if notified:
            return False
        return first_seen >= self._now() - TTL_SECONDS

    def prune(self, now: float | None = None) -> int:
        """Delete entries older than the 7-day TTL.

        Args:
            now: Reference epoch seconds. Defaults to the store's clock.

        Returns:
            The number of rows deleted.
        """
        reference = self._now() if now is None else now
        cursor = self._conn.execute(
            "DELETE FROM seen_items WHERE first_seen < ?", (reference - TTL_SECONDS,)
        )
        self._conn.commit()
        return cursor.rowcount
