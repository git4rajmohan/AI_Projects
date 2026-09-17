import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def samples():
    """Regenerate sample PDFs + ground truth once per test session."""
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_sample_invoices.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr