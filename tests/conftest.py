"""Shared pytest fixtures and helpers.

Provides access to the repo ``fixtures/`` directory and small fake-factory
helpers. No test performs network I/O; later features extend these fakes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to the repo ``fixtures/`` directory."""
    return FIXTURES_DIR


@pytest.fixture
def read_fixture():
    """Return a reader that loads a fixture file's text by name."""

    def _read(name: str) -> str:
        return (FIXTURES_DIR / name).read_text(encoding="utf-8")

    return _read
