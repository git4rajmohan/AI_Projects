"""
SQLite database layer for the Appointment Scheduler Bot.

Stores bookings and SMS records in a local SQLite file.
Seeds 10 pre-existing appointment records on first run.
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Database path ─────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent.parent / "data" / "appointments.db"


def _get_conn() -> sqlite3.Connection:
    """Get a SQLite connection. Creates the data directory if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── Schema initialization ─────────────────────────────────────────────────────
def init_db():
    """Create tables if they don't exist and seed initial data."""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                datetime TEXT NOT NULL,
                patient_name TEXT NOT NULL,
                department TEXT NOT NULL,
                contact_phone TEXT DEFAULT '',
                sms_sid TEXT DEFAULT '',
                booked_at TEXT NOT NULL,
                is_pre_existing INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS sms_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sid TEXT NOT NULL,
                to_number TEXT DEFAULT '',
                body TEXT NOT NULL,
                mode TEXT DEFAULT 'mock',
                sent_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_bookings_datetime ON bookings(datetime);
            CREATE INDEX IF NOT EXISTS idx_sms_sent_at ON sms_records(sent_at);
        """)
        conn.commit()

        # Clean up any error rows from failed Twilio attempts
        _cleanup_error_rows(conn)

        # Seed 10 pre-existing appointment records if the table is empty
        count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        if count == 0:
            _seed_bookings(conn)
            logger.info(f"DB: seeded 10 pre-existing appointment records")

    finally:
        conn.close()


def _cleanup_error_rows(conn: sqlite3.Connection):
    """Remove bookings and SMS records that resulted from errors (failed Twilio sends)."""
    b_del = conn.execute("DELETE FROM bookings WHERE sms_sid LIKE 'ERROR_%'").rowcount
    s_del = conn.execute("DELETE FROM sms_records WHERE sid LIKE 'ERROR_%' OR mode = 'error'").rowcount
    if b_del or s_del:
        conn.commit()
        logger.info(f"DB: cleaned up {b_del} error bookings, {s_del} error SMS records")


def _seed_bookings(conn: sqlite3.Connection):
    """Insert 10 pre-existing appointment records into the database."""
    # Generate 10 records across different departments and dates
    # Use dates in September 2026 (the current month in the app context)
    base_date = datetime(2026, 9, 1)
    seed_data = [
        ("2026-09-01T09:00:00", "Alice Johnson",     "cardiology",        "15551234001", "SEED_SMS_001"),
        ("2026-09-02T10:00:00", "Bob Smith",         "dermatology",       "15551234002", "SEED_SMS_002"),
        ("2026-09-03T14:00:00", "Carol Williams",    "orthopedics",       "15551234003", "SEED_SMS_003"),
        ("2026-09-04T11:00:00", "David Brown",       "general medicine",  "15551234004", "SEED_SMS_004"),
        ("2026-09-07T09:00:00", "Eva Davis",         "neurology",         "15551234005", "SEED_SMS_005"),
        ("2026-09-08T10:00:00", "Frank Miller",      "gastroenterology",  "15551234006", "SEED_SMS_006"),
        ("2026-09-09T15:00:00", "Grace Wilson",      "ent",               "15551234007", "SEED_SMS_007"),
        ("2026-09-10T09:00:00", "Henry Taylor",      "ophthalmology",     "15551234008", "SEED_SMS_008"),
        ("2026-09-11T13:00:00", "Ivy Anderson",      "psychiatry",        "15551234009", "SEED_SMS_009"),
        ("2026-09-14T14:00:00", "Jack Thomas",       "dental",            "15551234010", "SEED_SMS_010"),
    ]

    now_iso = datetime.now().isoformat()
    for dt_str, name, dept, phone, sms_sid in seed_data:
        conn.execute(
            """INSERT INTO bookings (datetime, patient_name, department, contact_phone, sms_sid, booked_at, is_pre_existing)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (dt_str, name, dept, phone, sms_sid, now_iso)
        )

    # Also seed corresponding SMS records
    for dt_str, name, dept, phone, sms_sid in seed_data:
        body = f"Appointment confirmed for {name} with {dept} on {dt_str}. Reply YES to confirm."
        conn.execute(
            """INSERT INTO sms_records (sid, to_number, body, mode, sent_at)
               VALUES (?, ?, ?, 'seed', ?)""",
            (sms_sid, phone, body, now_iso)
        )

    conn.commit()


# ── Booking operations ────────────────────────────────────────────────────────
def add_booking(
    dt: datetime,
    patient_name: str,
    department: str,
    contact_phone: str,
    sms_sid: str,
) -> dict:
    """Insert a new booking and return it as a dict."""
    iso_dt = dt.strftime("%Y-%m-%dT%H:00:00")
    booked_at = datetime.now().isoformat()
    conn = _get_conn()
    try:
        cursor = conn.execute(
            """INSERT INTO bookings (datetime, patient_name, department, contact_phone, sms_sid, booked_at, is_pre_existing)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (iso_dt, patient_name or "Unknown", department or "General",
             contact_phone or "", sms_sid, booked_at)
        )
        conn.commit()
        booking_id = cursor.lastrowid
        logger.info(f"DB: booked {iso_dt} for {patient_name} (id={booking_id})")
        return {
            "id": booking_id,
            "datetime": iso_dt,
            "patient_name": patient_name or "Unknown",
            "department": department or "General",
            "contact_phone": contact_phone or "",
            "sms_sid": sms_sid,
            "booked_at": booked_at,
            "is_pre_existing": 0,
        }
    finally:
        conn.close()


def get_all_bookings() -> list[dict]:
    """Return all bookings as list of dicts, ordered by datetime."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM bookings ORDER BY datetime ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_booked_datetimes() -> set[str]:
    """Return a set of all booked datetime strings (for availability checks)."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT datetime FROM bookings").fetchall()
        return {r["datetime"] for r in rows}
    finally:
        conn.close()


def find_bookings_by_name(patient_name: str) -> list[dict]:
    """Find all non-pre-existing bookings matching a patient name (case-insensitive)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE LOWER(patient_name) = LOWER(?) AND is_pre_existing = 0 ORDER BY datetime ASC",
            (patient_name.strip(),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_booking_datetime(booking_id: int, new_dt: datetime) -> bool:
    """Update a booking's datetime. Returns True if a row was updated."""
    iso_dt = new_dt.strftime("%Y-%m-%dT%H:00:00")
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "UPDATE bookings SET datetime = ? WHERE id = ? AND is_pre_existing = 0",
            (iso_dt, booking_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_booking(booking_id: int) -> bool:
    """Delete a booking by ID. Returns True if a row was deleted."""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM bookings WHERE id = ? AND is_pre_existing = 0",
            (booking_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_pre_existing_slots() -> set[str]:
    """Return pre-existing busy slots as 'YYYY-MM-DD HH:MM' format strings."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT datetime FROM bookings WHERE is_pre_existing = 1"
        ).fetchall()
        slots = set()
        for r in rows:
            dt = datetime.fromisoformat(r["datetime"])
            slots.add(dt.strftime("%Y-%m-%d %H:%M"))
        return slots
    finally:
        conn.close()


# ── SMS operations ────────────────────────────────────────────────────────────
def add_sms_record(sid: str, to_number: str, body: str, mode: str) -> dict:
    """Insert a new SMS record and return it as a dict."""
    sent_at = datetime.now().isoformat()
    conn = _get_conn()
    try:
        cursor = conn.execute(
            """INSERT INTO sms_records (sid, to_number, body, mode, sent_at)
               VALUES (?, ?, ?, ?, ?)""",
            (sid, to_number or "", body, mode, sent_at)
        )
        conn.commit()
        return {
            "id": cursor.lastrowid,
            "sid": sid,
            "to_number": to_number or "",
            "body": body,
            "mode": mode,
            "sent_at": sent_at,
        }
    finally:
        conn.close()


def get_all_sms_records() -> list[dict]:
    """Return all SMS records as list of dicts, ordered by sent_at DESC."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM sms_records ORDER BY sent_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Initialize on import ──────────────────────────────────────────────────────
init_db()