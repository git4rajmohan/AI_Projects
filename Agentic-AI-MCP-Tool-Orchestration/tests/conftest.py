"""Pytest configuration and shared fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ on the path so tests can import mcp_app without installation
_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
