import json
import sqlite3
from pathlib import Path

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors (
    vendor_id TEXT PRIMARY KEY, name TEXT NOT NULL,
    status TEXT NOT NULL,  -- active | inactive | new
    bank_account TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number TEXT PRIMARY KEY, vendor_id TEXT NOT NULL REFERENCES vendors,
    currency TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS po_line_items (
    line_id INTEGER PRIMARY KEY, po_number TEXT NOT NULL REFERENCES purchase_orders,
    description TEXT NOT NULL, quantity REAL NOT NULL,
    unit_price REAL NOT NULL, tax_rate REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS goods_receipts (
    gr_number TEXT PRIMARY KEY, po_number TEXT NOT NULL,
    line_id INTEGER REFERENCES po_line_items, quantity_received REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id TEXT PRIMARY KEY, invoice_number TEXT NOT NULL,
    vendor_id TEXT NOT NULL, invoice_date TEXT NOT NULL, po_number TEXT,
    currency TEXT NOT NULL, subtotal REAL NOT NULL, tax REAL NOT NULL,
    total REAL NOT NULL, bank_account TEXT,
    document_path TEXT, status TEXT NOT NULL DEFAULT 'received',
    extracted_json TEXT, UNIQUE(vendor_id, invoice_number)
);
CREATE TABLE IF NOT EXISTS invoice_line_items (
    invoice_id TEXT NOT NULL REFERENCES invoices, line_number INTEGER NOT NULL,
    description TEXT NOT NULL, quantity REAL NOT NULL,
    unit_price REAL NOT NULL, amount REAL NOT NULL,
    PRIMARY KEY (invoice_id, line_number)
);
CREATE TABLE IF NOT EXISTS exceptions (
    exception_id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL, type TEXT NOT NULL, severity TEXT NOT NULL,
    reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS review_actions (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL, reviewer TEXT NOT NULL, action TEXT NOT NULL,
    comments TEXT, timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL, stage TEXT NOT NULL, payload_json TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Seed data — the "systems of record" (vendor master, PO system, receipts)
SEED = {
    "vendors": [
        {"vendor_id": "V-10025", "name": "ABC Supplier", "status": "active", "bank_account": "XXXX1234"},
        {"vendor_id": "V-10026", "name": "Delta Components", "status": "active", "bank_account": "XXXX5566"},
        {"vendor_id": "V-10027", "name": "Zenith Traders", "status": "active", "bank_account": "XXXX7788"},
        {"vendor_id": "V-10028", "name": "Old Vendor Co", "status": "inactive", "bank_account": "XXXX9900"},
        {"vendor_id": "V-10029", "name": "Fresh Vendor LLC", "status": "new", "bank_account": "XXXX1122"},
    ],
    "purchase_orders": [
        {"po_number": "PO-12345", "vendor_id": "V-10025", "currency": "JPY", "status": "open",
         "lines": [
             {"line_id": 1, "description": "Product A", "quantity": 100, "unit_price": 1000},
             {"line_id": 2, "description": "Product B", "quantity": 150, "unit_price": 5000},
         ]},
        {"po_number": "PO-20001", "vendor_id": "V-10026", "currency": "JPY", "status": "open",
         "lines": [{"line_id": 3, "description": "Widget", "quantity": 50, "unit_price": 800}]},
        {"po_number": "PO-20002", "vendor_id": "V-10027", "currency": "USD", "status": "open",
         "lines": [{"line_id": 4, "description": "Consulting", "quantity": 10, "unit_price": 500}]},
        {"po_number": "PO-20003", "vendor_id": "V-10025", "currency": "JPY", "status": "open",
         "lines": [{"line_id": 5, "description": "Service X", "quantity": 4, "unit_price": 300000}]},
        {"po_number": "PO-20004", "vendor_id": "V-10026", "currency": "JPY", "status": "open",
         "lines": [{"line_id": 6, "description": "Gadget", "quantity": 20, "unit_price": 3000}]},
        {"po_number": "PO-20005", "vendor_id": "V-10027", "currency": "JPY", "status": "open",
         "lines": [{"line_id": 7, "description": "Part Z", "quantity": 80, "unit_price": 250}]},
    ],
    "goods_receipts": [
        {"gr_number": "GR-30001", "po_number": "PO-12345", "line_id": 1, "quantity_received": 100},
        {"gr_number": "GR-30002", "po_number": "PO-12345", "line_id": 2, "quantity_received": 150},
        {"gr_number": "GR-30003", "po_number": "PO-20005", "line_id": 7, "quantity_received": 80},
    ],
    "invoices": [
        {"invoice_id": "inv_seed_1", "invoice_number": "INV-10025", "vendor_id": "V-10025",
         "invoice_date": "2026-08-01", "po_number": "PO-12345", "currency": "JPY",
         "subtotal": 850000, "tax": 0, "total": 850000, "bank_account": "XXXX1234",
         "document_path": None, "status": "paid",
         "lines": [{"line_number": 1, "description": "Product A", "quantity": 100, "unit_price": 1000, "amount": 100000},
                    {"line_number": 2, "description": "Product B", "quantity": 150, "unit_price": 5000, "amount": 750000}]},
    ],
}


def get_conn(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | None = None) -> None:
    Path(path or settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    with get_conn(path) as conn:
        conn.executescript(SCHEMA)


def seed(path: str | None = None) -> None:
    init_db(path)
    with get_conn(path) as conn:
        for v in SEED["vendors"]:
            conn.execute("INSERT OR IGNORE INTO vendors VALUES (:vendor_id,:name,:status,:bank_account)", v)
        for po in SEED["purchase_orders"]:
            conn.execute("INSERT OR IGNORE INTO purchase_orders VALUES (:po_number,:vendor_id,:currency,:status)", po)
            for ln in po["lines"]:
                conn.execute("INSERT OR IGNORE INTO po_line_items VALUES (:line_id,:po_number,:description,:quantity,:unit_price,0)",
                             {"po_number": po["po_number"], **ln})
        for gr in SEED["goods_receipts"]:
            conn.execute("INSERT OR IGNORE INTO goods_receipts VALUES (:gr_number,:po_number,:line_id,:quantity_received)", gr)
        for inv in SEED["invoices"]:
            conn.execute(
                "INSERT OR IGNORE INTO invoices VALUES (:invoice_id,:invoice_number,:vendor_id,:invoice_date,:po_number,"
                ":currency,:subtotal,:tax,:total,:bank_account,:document_path,:status,NULL)", inv)
            for ln in inv["lines"]:
                conn.execute("INSERT OR IGNORE INTO invoice_line_items VALUES (:invoice_id,:line_number,:description,:quantity,:unit_price,:amount)",
                             {"invoice_id": inv["invoice_id"], **ln})


# ── Repositories ─────────────────────────────────────────────
def get_vendor(vendor_id: str, path: str | None = None) -> dict | None:
    with get_conn(path) as conn:
        row = conn.execute("SELECT * FROM vendors WHERE vendor_id=?", (vendor_id,)).fetchone()
    return dict(row) if row else None


def get_po(po_number: str, path: str | None = None) -> dict | None:
    with get_conn(path) as conn:
        row = conn.execute("SELECT * FROM purchase_orders WHERE po_number=?", (po_number,)).fetchone()
        if not row:
            return None
        po = dict(row)
        po["lines"] = [dict(r) for r in conn.execute(
            "SELECT * FROM po_line_items WHERE po_number=? ORDER BY line_id", (po_number,))]
    return po


def get_receipts_for_po(po_number: str, path: str | None = None) -> list[dict]:
    with get_conn(path) as conn:
        rows = conn.execute("SELECT * FROM goods_receipts WHERE po_number=?", (po_number,)).fetchall()
    return [dict(r) for r in rows]


def find_duplicate_invoice(vendor_id: str, invoice_number: str, path: str | None = None) -> dict | None:
    with get_conn(path) as conn:
        row = conn.execute(
            "SELECT * FROM invoices WHERE vendor_id=? AND invoice_number=?", (vendor_id, invoice_number)
        ).fetchone()
    return dict(row) if row else None


def save_audit_event(invoice_id: str, stage: str, payload: dict, path: str | None = None) -> None:
    with get_conn(path) as conn:
        conn.execute("INSERT INTO audit_events (invoice_id, stage, payload_json) VALUES (?,?,?)",
                     (invoice_id, stage, json.dumps(payload, ensure_ascii=False)))


def delete_invoice(invoice_id: str, path: str | None = None) -> bool:
    """Remove an invoice + its children (demo re-upload helper). Seed rows are
    protected — deleting those would break the duplicate-detection demo."""
    SEED_IDS = {inv["invoice_id"] for inv in SEED["invoices"]}
    if invoice_id in SEED_IDS:
        raise ValueError("cannot delete seeded invoice (demo fixture)")
    with get_conn(path) as conn:
        cur = conn.execute("SELECT 1 FROM invoices WHERE invoice_id=?", (invoice_id,))
        if not cur.fetchone():
            return False
        # children first — invoice_line_items has an FK to invoices
        for table in ("invoice_line_items", "audit_events", "exceptions",
                      "review_actions"):
            conn.execute(f"DELETE FROM {table} WHERE invoice_id=?", (invoice_id,))
        conn.execute("DELETE FROM invoices WHERE invoice_id=?", (invoice_id,))
    return True