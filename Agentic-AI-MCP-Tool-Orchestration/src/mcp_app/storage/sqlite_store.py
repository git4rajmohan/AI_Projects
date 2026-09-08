"""SQLite-backed store – stub placeholder (not implemented)."""
from __future__ import annotations


class SQLiteStore:
    """
    Placeholder for a future SQLite-backed session store.

    Not implemented in Milestone 1. Raises NotImplementedError on all calls.
    """

    def __init__(self, db_path: str) -> None:
        raise NotImplementedError(
            "SQLiteStore is not yet implemented. Use JSONLStore instead."
        )
