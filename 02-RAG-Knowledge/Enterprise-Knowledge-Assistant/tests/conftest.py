"""Pytest bootstrap: make the project importable as a plain package.

Adds the project root to ``sys.path`` so ``import app...`` works no matter
which directory pytest is invoked from (root, ``tests/``, VS Code test runner).
"""

from __future__ import annotations

import sys
from pathlib import Path

# LLM answers contain Unicode; Windows consoles default to cp1252 and crash
# on print() inside tests. Force UTF-8 before any test output happens.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: §25/§47 — phrases a grounded "not found" answer may use. Shared by the
#: unknown-question tests (test_retrieval, test_groundedness) so the two
#: modules can't drift. Includes "could not be found", which the LLM emits
#: naturally and a naive "not found" substring check misses.
NOT_FOUND_PHRASES = (
    "could not find",
    "could not be found",
    "not found",
    "no information",
    "not contain",
    "not available",
    "do not provide",
    "does not provide",
    "do not specify",
    "does not specify",
)