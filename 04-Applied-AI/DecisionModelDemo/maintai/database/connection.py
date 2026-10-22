# SQLite connection (spec1 §11). DATABASE_URL comes from config/settings.py;
# only the sqlite:/// scheme is supported — that is the spec's database.

import sqlite3
from pathlib import Path

from config import settings  # live-reading: tests monkeypatch DATABASE_URL here

_SCHEMA = Path(__file__).parent / "schema.sql"


def db_path() -> Path:
    url = settings.DATABASE_URL
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError(f"Only sqlite:/// DATABASE_URL is supported, got: {url}")
    return Path(url[len(prefix):])


def get_conn() -> sqlite3.Connection:
    """Open a connection with row access by column name. Caller owns it:
    use `with conn:` for a transaction or close() when done."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> None:
    """Create the schema if missing, then add columns newer dbs lack. Idempotent."""
    own = conn is None
    conn = conn or get_conn()
    conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(machines)")}
    if "team" not in cols:  # migration for databases created before Phase 11
        conn.execute("ALTER TABLE machines ADD COLUMN team TEXT NOT NULL DEFAULT ''")
    if own:
        conn.commit()
        conn.close()