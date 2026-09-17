"""Renderer: converts a Markdown string into an interactive markmap HTML file."""

import json
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "markmap_template.html"


def render_to_html(markdown_str: str) -> str:
    """Inject Markdown content into the markmap HTML template.

    The Markdown is JSON-escaped and placed into a JS const so markmap
    can parse it client-side.

    Args:
        markdown_str: A Markdown string with hierarchical headings.

    Returns:
        A complete standalone HTML string that renders an interactive mindmap.
    """
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    markdown_json = json.dumps(markdown_str)
    return template.replace("{{MARKDOWN_JSON}}", markdown_json)


def save_html(html_str: str, output_path: str | Path) -> Path:
    """Write the HTML string to a file.

    Args:
        html_str: Complete HTML document string.
        output_path: Path to write the file to.

    Returns:
        The Path object of the written file.
    """
    output_path = Path(output_path)
    output_path.write_text(html_str, encoding="utf-8")
    return output_path