"""Source package: pollers that yield :class:`Item` records.

The shared :class:`Item` dataclass lives here because every source (web,
social, audio) produces it. Keeping it in the source package's root avoids a
circular import between the sources and the detection module that consumes
their text.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    """A single candidate item produced by a source.

    Attributes:
        title: Human-readable title of the item.
        url: Canonical URL the item was found at (or a synthetic one).
        text: The text content to run detection against.
        published: ISO-8601 publication timestamp, or ``None`` if unknown.
        source: Short source identifier, e.g. ``"web"``, ``"social"``, ``"audio"``.
    """

    title: str
    url: str
    text: str
    published: str | None
    source: str
