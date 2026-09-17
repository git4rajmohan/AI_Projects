"""Export the Cognee knowledge graph to an interactive HTML visualization.

Uses cognee 1.4.2's built-in ``cognee.api.v1.visualize.visualize_graph`` — a
self-contained HTML page (nodes colored by type, click to inspect, zoom/pan).
Default renders a BOUNDED subgraph (seeds = highest-degree nodes, 2-hop
neighborhood, 500-node cap) which loads fast and stays readable; pass
``--full`` to render the entire graph (legacy whole-graph render).

Usage (Streamlit MUST be stopped first — Ladybug .lbug file lock, Error 33):
    .\\.venv\\Scripts\\python.exe scripts\\visualize_graph.py          # bounded subgraph
    .\\.venv\\Scripts\\python.exe scripts\\visualize_graph.py --full    # entire graph

Output: data/graph_visualization.html (opened in the default browser).
Read-only: never touches Qdrant, the ledger, or document state.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import get_settings  # noqa: E402
from app.knowledge.cognee_manager import CognifyManager, configure  # noqa: E402

OUTPUT_PATH = PROJECT_ROOT / "data" / "graph_visualization.html"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the knowledge graph to interactive HTML")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Render the ENTIRE graph instead of the bounded 500-node subgraph",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the HTML in the browser after export",
    )
    args = parser.parse_args()

    # configure() MUST run before any cognee import/config access in the
    # process, or cognee resolves storage to site-packages and dies with
    # "sqlite3.OperationalError: unable to open database file" (Phase 9/11 gotcha).
    settings = get_settings()
    CognifyManager(settings)  # triggers configure()

    import cognee

    print(f"Exporting {'FULL graph' if args.full else 'bounded subgraph (500-node cap)'}...")
    html_path = asyncio_run_export(full=args.full)
    print(f"✅ HTML written: {html_path}")

    # Real sanity check: cognee reports the same path — never fabricate success.
    assert Path(html_path).is_file(), f"cognee reported {html_path} but the file is missing"
    size_kb = Path(html_path).stat().st_size / 1024
    print(f"   size: {size_kb:.0f} KB")

    if not args.no_open:
        webbrowser.open(f"file:///{html_path.as_posix()}")
        print("Opened in default browser.")
    print("Done. cognee version:", cognee.__version__)
    return 0


def asyncio_run_export(full: bool) -> str:
    """Call visualize_graph with the project's dataset; returns the written path."""
    import asyncio

    async def _export() -> str:
        from cognee.api.v1.visualize import visualize_graph

        # visualize_graph resolves the dataset (by name), enters the per-dataset
        # Ladybug context, and writes the self-contained HTML itself.
        return await visualize_graph(
            destination_file_path=str(OUTPUT_PATH),
            dataset="main_dataset",
            full=full,
        )

    return asyncio.run(_export())


if __name__ == "__main__":
    raise SystemExit(main())