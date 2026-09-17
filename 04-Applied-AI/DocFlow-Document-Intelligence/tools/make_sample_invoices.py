"""Generate sample invoice PDFs + ground-truth JSON for every demo scenario.

Usage: .venv/Scripts/python.exe tools/make_sample_invoices.py
"""
import json
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "invoices"
OUT.mkdir(parents=True, exist_ok=True)

# line_amount = quantity * unit_price
SAMPLES = {
    # Demo 1 — normal: PO-12345 total 850,000 → should pass everything
    "d1_normal": {
        "vendor_name": "ABC Supplier", "vendor_id": "V-10025", "invoice_number": "INV-10026",
        "invoice_date": "2026-09-10", "po_number": "PO-12345", "currency": "JPY",
        "bank_account": "XXXX1234", "tax": 0,
        "lines": [
            {"description": "Product A", "quantity": 100, "unit_price": 1000},
            {"description": "Product B", "quantity": 150, "unit_price": 5000},
        ],
    },
    # Demo 2 — quantity mismatch: 150 vs PO 100
    "d2_qty_mismatch": {
        "vendor_name": "ABC Supplier", "vendor_id": "V-10025", "invoice_number": "INV-10027",
        "invoice_date": "2026-09-10", "po_number": "PO-12345", "currency": "JPY",
        "bank_account": "XXXX1234", "tax": 0,
        "lines": [
            {"description": "Product A", "quantity": 150, "unit_price": 1000},
            {"description": "Product B", "quantity": 150, "unit_price": 5000},
        ],
    },
    # Demo 3 — duplicate invoice number (INV-10025 already paid in seed)
    "d3_duplicate": {
        "vendor_name": "ABC Supplier", "vendor_id": "V-10025", "invoice_number": "INV-10025",
        "invoice_date": "2026-09-11", "po_number": "PO-12345", "currency": "JPY",
        "bank_account": "XXXX1234", "tax": 0,
        "lines": [
            {"description": "Product A", "quantity": 100, "unit_price": 1000},
        ],
    },
    # Demo 4 — changed bank account (master: XXXX1234)
    "d4_bank_change": {
        "vendor_name": "ABC Supplier", "vendor_id": "V-10025", "invoice_number": "INV-10028",
        "invoice_date": "2026-09-10", "po_number": "PO-12345", "currency": "JPY",
        "bank_account": "XXXX9876", "tax": 0,
        "lines": [
            {"description": "Product A", "quantity": 100, "unit_price": 1000},
            {"description": "Product B", "quantity": 150, "unit_price": 5000},
        ],
    },
    # Demo 5 — missing PO
    "d5_missing_po": {
        "vendor_name": "ABC Supplier", "vendor_id": "V-10025", "invoice_number": "INV-10033",
        "invoice_date": "2026-09-10", "po_number": "PO-99999", "currency": "JPY",
        "bank_account": "XXXX1234", "tax": 0,
        "lines": [
            {"description": "Product A", "quantity": 100, "unit_price": 1000},
        ],
    },
    # Demo 6 — poor quality (garbled, low-confidence extraction expected)
    "d6_low_confidence": {
        "vendor_name": "Delta Components", "vendor_id": "V-10026", "invoice_number": "INV-10029",
        "invoice_date": "2026-09-12", "po_number": "PO-20001", "currency": "JPY",
        "bank_account": "XXXX5566", "tax": 0, "degraded": True,
        "lines": [
            {"description": "Widget", "quantity": 50, "unit_price": 800},
        ],
    },
    # Demo 7 — high value: 1,200,000 → finance review
    "d7_high_value": {
        "vendor_name": "ABC Supplier", "vendor_id": "V-10025", "invoice_number": "INV-10030",
        "invoice_date": "2026-09-12", "po_number": "PO-20003", "currency": "JPY",
        "bank_account": "XXXX1234", "tax": 0,
        "lines": [
            {"description": "Service X", "quantity": 4, "unit_price": 300000},
        ],
    },
    # Demo 8 — currency mismatch (USD invoice against JPY PO-12345)
    "d8_currency_mismatch": {
        "vendor_name": "ABC Supplier", "vendor_id": "V-10025", "invoice_number": "INV-10031",
        "invoice_date": "2026-09-12", "po_number": "PO-12345", "currency": "USD",
        "bank_account": "XXXX1234", "tax": 0,
        "lines": [
            {"description": "Product A", "quantity": 100, "unit_price": 1000},
            {"description": "Product B", "quantity": 150, "unit_price": 5000},
        ],
    },
    # Demo 9 — small invoice: under the auto-approve limit → end-to-end AUTO_APPROVED
    "d9_small": {
        "vendor_name": "Delta Components", "vendor_id": "V-10026", "invoice_number": "INV-10032",
        "invoice_date": "2026-09-12", "po_number": "PO-20004", "currency": "JPY",
        "bank_account": "XXXX5566", "tax": 0,
        "lines": [
            {"description": "Gadget", "quantity": 20, "unit_price": 3000},
        ],
    },
    # Demo 10 — image-only scan (no text layer): same vendor/PO as d1, own invoice
    # number; OCR must recover the content → manager review just like d1.
    "d10_scanned": {
        "vendor_name": "ABC Supplier", "vendor_id": "V-10025", "invoice_number": "INV-10034",
        "invoice_date": "2026-09-10", "po_number": "PO-12345", "currency": "JPY",
        "bank_account": "XXXX1234", "tax": 0, "image_only": True,
        "lines": [
            {"description": "Product A", "quantity": 100, "unit_price": 1000},
            {"description": "Product B", "quantity": 150, "unit_price": 5000},
        ],
    },
}


def render(path: Path, inv: dict) -> None:
    doc = fitz.open()
    if inv.get("image_only"):
        # Image-only scan (§3/§19): text rendered to a bitmap page — zero text
        # layer, OCR (Phase 14) is the only way to read it.
        tmp = fitz.open()
        src = tmp.new_page(width=612, height=792)  # US Letter in points
        src.insert_text((72, 72), _invoice_text(inv), fontname="cour", fontsize=9)
        pix = src.get_pixmap(dpi=150)
        doc.new_page(width=612, height=792).insert_image(fitz.Rect(0, 0, 612, 792),
                                                         pixmap=pix)
        tmp.close()
    else:
        doc.new_page().insert_text((72, 72), _invoice_text(inv), fontname="cour",
                                   fontsize=9)
    doc.save(path)
    doc.close()


def _invoice_text(inv: dict) -> str:
    body = inv["lines"]
    subtotal = sum(l["quantity"] * l["unit_price"] for l in body)
    total = subtotal + inv["tax"]
    text = "\n".join([
        "INVOICE",
        f"Vendor:    {inv['vendor_name']} ({inv['vendor_id']})",
        f"Invoice #: {inv['invoice_number']}",
        f"Date:      {inv['invoice_date']}",
        f"PO Number: {inv['po_number']}",
        f"Currency:  {inv['currency']}",
        f"Bank Acc:  {inv['bank_account']}",
        "",
        "Item              Qty    Unit Price    Amount",
        *[f"{l['description']:<16}{l['quantity']:>6}{l['unit_price']:>12,}{l['quantity'] * l['unit_price']:>12,}" for l in body],
        "",
        f"Subtotal: {subtotal:,}",
        f"Tax:      {inv['tax']:,}",
        f"TOTAL:    {total:,}",
    ])
    if inv.get("degraded"):
        # Simulate a poor scan: garble most characters, keep a few recognizable
        return "".join(c if c in " \n" or i % 7 == 0 else "▒" for i, c in enumerate(text))
    return text


def ground_truth(inv: dict) -> dict:
    lines = inv["lines"]
    subtotal = sum(l["quantity"] * l["unit_price"] for l in lines)
    return {
        "vendor_name": inv["vendor_name"], "vendor_id": inv["vendor_id"],
        "invoice_number": inv["invoice_number"], "invoice_date": inv["invoice_date"],
        "po_number": inv["po_number"], "currency": inv["currency"],
        "bank_account": inv["bank_account"],
        "line_items": [
            {"description": l["description"], "quantity": l["quantity"],
             "unit_price": l["unit_price"], "amount": l["quantity"] * l["unit_price"]}
            for l in lines
        ],
        "subtotal": subtotal, "tax": inv["tax"], "total_amount": subtotal + inv["tax"],
    }


def main() -> None:
    for name, inv in SAMPLES.items():
        render(OUT / f"{name}.pdf", inv)
        (OUT / f"{name}_ground_truth.json").write_text(
            json.dumps(ground_truth(inv), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {len(SAMPLES)} sample invoices written to {OUT}")


if __name__ == "__main__":
    main()