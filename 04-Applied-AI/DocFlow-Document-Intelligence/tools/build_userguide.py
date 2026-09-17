"""Splice base64-encoded screenshots into the userguide template -> userguide.html.

Run: .venv\\Scripts\\python.exe tools/build_userguide.py
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, "tools", "userguide_template.html")
OUT = os.path.join(ROOT, "userguide.html")
SHOTS = os.path.join(ROOT, "docs", "screenshots")

PLACEHOLDERS = {
    "{{B64_ui_allinvoices}}": "ui_allinvoices.png",
    "{{B64_ui_review_mismatch}}": "ui_review_mismatch.png",
    "{{B64_ui_review_missing_po}}": "ui_review_missing_po.png",
}

html = open(TPL, encoding="utf-8").read()
for ph, fname in PLACEHOLDERS.items():
    p = os.path.join(SHOTS, fname)
    b64 = open(p + ".b64", encoding="ascii").read().strip()
    assert ph in html, f"placeholder {ph} missing from template"
    html = html.replace(ph, b64)

open(OUT, "w", encoding="utf-8").write(html)
print(f"written {OUT} ({len(html):,} chars)")