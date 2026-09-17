"""Launcher for the Streamlit UI.

This module provides the ``mcpapp-ui`` console-script entry point.
It starts ``streamlit run`` pointing at ``app.py`` in this package,
forwarding any extra CLI arguments straight to Streamlit.

Usage:
    mcpapp-ui                     # opens on http://localhost:8501
    mcpapp-ui --server.port 8080  # custom port
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:  # pragma: no cover
    app_path = Path(__file__).with_name("app.py")
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path)] + sys.argv[1:]
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
