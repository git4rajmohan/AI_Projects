#!/usr/bin/env python3
"""AgilePoint Documentation MCP Server.

Searches https://documentation.agilepoint.com using a crawler-based approach:
  - On first use, builds an index by crawling known section pages and their
    DC.relation links (no external search engines needed)
  - Keyword-matches the index against the search query
  - Returns matching doc URLs; use fetch_page to get full content

Tools:
  search_docs(query, max_results?)  -- search and get matching results with URLs
  fetch_page(url)                   -- get full text content of a doc page
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL = "https://documentation.agilepoint.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Seed pages used to build the documentation index.
# Each page is fetched once; its <a href> and DC.relation links are collected.
# These cover the major sections: App Builder, Form Controls, Portal, Startup, Release Notes.
_INDEX_SEED_PAGES: list[str] = [
    # Root / main portal -- 68 links covering all major sections
    f"{BASE_URL}/",
    # App Builder section index
    f"{BASE_URL}/9000/appbuilder/index.html",
    # Form Controls overview -> links to Basic / Advanced / Kendo sub-sections
    f"{BASE_URL}/9000/appbuilder/cloudformControls.html",
    # Basic form controls (25 controls including Subform)
    f"{BASE_URL}/9000/appbuilder/cloudformControlsBasic.html",
    # Advanced form controls (25+ controls)
    f"{BASE_URL}/9000/appbuilder/cloudformControlsAdvanced.html",
    # Telerik/Kendo form controls
    f"{BASE_URL}/9000/appbuilder/cloudformControlsKendo.html",
    # Process Builder section
    f"{BASE_URL}/9000/appbuilder/wlcloudappProcessBuilder.html",
    # Data Entities section
    f"{BASE_URL}/9000/appbuilder/wlcloudappDataEntities.html",
    # NX Portal section index
    f"{BASE_URL}/9000/portal/index.html",
    # Get Started / Startup section index
    f"{BASE_URL}/9000/startup/index.html",
    # Release Notes section index
    f"{BASE_URL}/9011/releaseNotes/index.html",
]

# Human-readable section labels derived from URL path segments
_SECTION_MAP: dict[str, str] = {
    "startup": "Get Started / Concepts",
    "appbuilder": "App Builder",
    "admin": "Administration",
    "developer": "Developers / API",
    "portal": "NX Portal",
    "installation": "Installation",
    "troubleshooting": "Troubleshooting",
    "releasenotes": "Release Notes",
    "mobile": "Mobile Apps",
    "sharepoint": "SharePoint Integration",
    "salesforce": "Salesforce App",
    "analytics": "Analytics Center",
}

# Stop words to strip from search queries
_STOP_WORDS: frozenset[str] = frozenset({
    "how", "to", "a", "an", "the", "what", "is", "are", "in", "for",
    "and", "or", "of", "with", "can", "do", "does", "use", "using",
    "get", "then", "fetch", "please", "show", "me", "i", "my",
    "this", "that", "these", "those", "which", "where", "when", "why",
    "list", "all", "find", "search", "page", "result", "content",
})

# ── Global Index (built lazily once, then cached) ─────────────────────────────

_DOC_INDEX: list[dict[str, str]] | None = None  # [{url, title, section}, ...]


# ── HTML Parsers ──────────────────────────────────────────────────────────────


class _PageTextExtractor(HTMLParser):
    """Extract readable text from a documentation HTML page."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.text_blocks: list[str] = []
        self._in_title = False
        self._skip_depth = 0
        self._skip_tags = {"script", "style", "nav", "footer", "header"}
        self._heading_tags = {"h1", "h2", "h3", "h4"}
        self._in_heading = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._skip_tags:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag in self._heading_tags:
            self._flush_buf()
            self._in_heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag == "title":
            self._in_title = False
        if tag in self._heading_tags:
            heading = "".join(self._buf).strip()
            if heading:
                self.text_blocks.append(f"\n### {heading}")
            self._buf = []
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
            return
        text = data.strip()
        if text:
            self._buf.append(text)
            if any(data.endswith(c) for c in (".", "!", "?", "\n")):
                self._flush_buf()

    def _flush_buf(self) -> None:
        joined = " ".join(self._buf).strip()
        if joined:
            self.text_blocks.append(joined)
        self._buf = []

    @property
    def text(self) -> str:
        self._flush_buf()
        return "\n".join(self.text_blocks)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _section_from_url(url: str) -> str:
    """Derive a human-readable section label from a documentation URL."""
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    for part in parts:
        if part.lower() in _SECTION_MAP:
            return _SECTION_MAP[part.lower()]
    return "Documentation"


def _url_to_title(url: str) -> str:
    """Derive a readable title from the URL filename using camelCase splitting."""
    filename = url.split("/")[-1].replace(".html", "")
    if not filename or filename == "index":
        return _section_from_url(url) + " Overview"

    # Strip common doc filename prefixes (order matters -- longer first)
    prefixes = [
        "cloudformControlsKendo",
        "cloudformControls",
        "cloudenvInstructions",
        "cloudportalScreens",
        "cloudform",
        "cloudenv",
        "cloudportal",
        "wlcloudapp",
        "wladmin",
        "wlportal",
        "wlstartup",
        "wlrn",
        "wl",
        "accesstoken",
        "cloudglossary",
        "cloud",
        "example",
    ]
    low = filename.lower()
    for prefix in prefixes:
        if low.startswith(prefix.lower()):
            remainder = filename[len(prefix):]
            if remainder:
                filename = remainder
            break

    # Split camelCase: "SubFormControlV8" -> "Sub Form Control V8"
    title = re.sub(r"([a-z])([A-Z])", r"\1 \2", filename)
    title = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", title)
    # Remove trailing version tags like "V8", "V7"
    title = re.sub(r"\s+V\d+\s*$", "", title, flags=re.IGNORECASE).strip()
    return title or filename


def _decompose_url(url: str) -> str:
    """Return the lowercased URL path for substring keyword matching."""
    parsed = urlparse(url)
    return parsed.path.lower().replace(".html", "").replace("/", " ").replace("-", " ")


def _score_entry(entry: dict[str, str], query_words: list[str]) -> float:
    """Score an index entry against query keywords."""
    url_text = _decompose_url(entry["url"])       # lowercased full path
    title_text = entry.get("title", "").lower()
    score = 0.0
    for word in query_words:
        wl = word.lower()
        # Strong match: word appears in URL path (filename or section)
        if wl in url_text:
            score += 3.0
        # Good match: word appears in derived title
        if wl in title_text:
            score += 2.0
        # Partial match: query word is a prefix of a URL segment or vice versa
        for segment in url_text.split():
            if len(segment) > 2 and (segment.startswith(wl) or wl.startswith(segment)):
                score += 0.5
                break
    return score


def _collect_links_from_html(html: str, base_url: str) -> list[str]:
    """
    Collect all AgilePoint documentation URLs from an HTML page.

    Extracts both:
      - ``<meta name="DC.relation" content="...">`` (OxygenXML WebHelp TOC links)
      - Regular ``<a href="...html">`` links
    """
    links: list[str] = []

    # DC.relation meta tags -- these encode the OxygenXML WebHelp TOC hierarchy
    for rel in re.findall(r'<meta\s+name="DC\.relation"\s+content="([^"]+)"', html):
        full = urljoin(base_url, rel)
        if "documentation.agilepoint.com" in full and ".html" in full:
            links.append(full)

    # Regular anchor links
    for href in re.findall(r'<a\s[^>]*href="([^"#][^"]*\.html)"', html):
        if href.startswith("javascript"):
            continue
        full = urljoin(base_url, href)
        if "documentation.agilepoint.com" in full:
            links.append(full)

    return links


def _build_doc_index() -> list[dict[str, str]]:
    """
    Build the documentation URL index by crawling seed pages.

    Fetches each seed page once and collects all linked AgilePoint documentation
    URLs (via <a href> and DC.relation meta tags).  Deduplicates and assigns
    a derived title and section label to each entry.  Typically runs in < 5 s.
    """
    seen: set[str] = set()
    entries: list[dict[str, str]] = []

    with httpx.Client(timeout=12.0, follow_redirects=True, headers=HEADERS) as client:
        for seed_url in _INDEX_SEED_PAGES:
            try:
                resp = client.get(seed_url)
            except Exception:
                continue

            if resp.status_code != 200 or len(resp.text) < 500:
                continue

            # Add the seed page itself
            if seed_url not in seen:
                seen.add(seed_url)
                title_m = re.search(r"<title>([^<]+)</title>", resp.text)
                real_title = title_m.group(1).strip() if title_m else _url_to_title(seed_url)
                # Strip trailing "| AgilePoint Documentation" suffix
                real_title = re.sub(r"\s*[|–-].*AgilePoint.*$", "", real_title).strip()
                entries.append({
                    "url": seed_url,
                    "title": real_title or _url_to_title(seed_url),
                    "section": _section_from_url(seed_url),
                })

            # Collect all linked URLs from this page
            for link_url in _collect_links_from_html(resp.text, seed_url):
                if link_url not in seen:
                    seen.add(link_url)
                    entries.append({
                        "url": link_url,
                        "title": _url_to_title(link_url),
                        "section": _section_from_url(link_url),
                    })

    return entries


def search_agilepoint_docs(query: str, max_results: int = 5) -> dict[str, Any]:
    """
    Search the AgilePoint documentation index.

    On the first call the index is built by crawling known section pages (takes
    a few seconds).  Subsequent calls use the cached index immediately.
    """
    global _DOC_INDEX
    if _DOC_INDEX is None:
        _DOC_INDEX = _build_doc_index()

    # Parse query into meaningful keywords
    query_words: list[str] = [
        w for w in re.split(r"[\s_\-]+", query.lower())
        if w and w not in _STOP_WORDS and len(w) > 2
    ]

    if not query_words:
        return {
            "error": (
                "Query is too vague after removing common words. "
                "Try specific terms like 'subform', 'process builder', or 'REST API'."
            ),
            "results": [],
        }

    # Score every index entry
    scored: list[tuple[float, dict[str, str]]] = []
    seen_urls: set[str] = set()
    for entry in _DOC_INDEX:
        url = entry["url"]
        if url in seen_urls:
            continue
        score = _score_entry(entry, query_words)
        if score > 0.0:
            seen_urls.add(url)
            scored.append((score, entry))

    # Sort descending by score
    scored.sort(key=lambda x: -x[0])
    top = scored[:max_results]

    results: list[dict[str, Any]] = [
        {
            "rank": i + 1,
            "title": e["title"],
            "url": e["url"],
            "section": e["section"],
            "snippet": f"Documentation page in the {e['section']} section.",
        }
        for i, (_, e) in enumerate(top)
    ]

    result_data: dict[str, Any] = {
        "query": query,
        "keywords_used": query_words,
        "total_found": len(scored),
        "results": results,
        "search_tip": (
            "Use 'fetch_page' with a result URL to get the full page content."
        ),
    }

    if not results:
        result_data["message"] = (
            f"No results found for '{query}' (keywords: {query_words}). "
            f"The index covers {len(_DOC_INDEX)} pages. "
            "Try shorter, more specific terms. "
            "For example, search 'subform' instead of 'how to use subform control'."
        )

    return result_data


def fetch_page_content(url: str) -> dict[str, Any]:
    """Fetch and extract readable content from an AgilePoint documentation page."""
    parsed = urlparse(url)
    if parsed.netloc not in (
        "documentation.agilepoint.com",
        "helpdesk.agilepoint.com",
    ):
        return {
            "error": (
                f"Only AgilePoint documentation URLs are allowed. "
                f"Got: {parsed.netloc}"
            )
        }

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers=HEADERS)
            resp.raise_for_status()
            html_content = resp.text
    except httpx.TimeoutException:
        return {"error": f"Page fetch timed out: {url}"}
    except httpx.HTTPError as e:
        return {"error": f"Failed to fetch page {url}: {e}"}

    extractor = _PageTextExtractor()
    extractor.feed(html_content)
    full_text = extractor.text

    # Trim to a sensible length (LLM context limit)
    if len(full_text) > 6000:
        full_text = full_text[:6000] + "\n\n...[content truncated, page has more]"

    return {
        "url": url,
        "title": extractor.title.strip(),
        "section": _section_from_url(url),
        "content": full_text,
        "content_length": len(extractor.text),
    }


# ── MCP JSON-RPC Protocol ─────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_docs",
        "description": (
            "Search the AgilePoint NX product documentation at "
            "https://documentation.agilepoint.com. "
            "Returns matching documentation pages with URLs, titles and section labels. "
            "Always call this first for any AgilePoint question, then use fetch_page "
            "on a result URL to read the actual content."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search terms, e.g. 'subform control', 'process builder', "
                        "'REST API authentication', 'data grid form control'"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (1-10, default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": (
            "Fetch the full text content of a specific AgilePoint documentation page. "
            "Use this after search_docs to get detailed information from a result URL. "
            "Only works with documentation.agilepoint.com URLs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL of an AgilePoint documentation page",
                },
            },
            "required": ["url"],
        },
    },
]


def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _text_content(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _format_search_result(r: dict) -> str:
    """Format search results as clean text for the LLM."""
    if "error" in r:
        return f"Search error: {r['error']}"

    lines: list[str] = [
        f'AgilePoint Documentation Search: "{r["query"]}"',
        f"Keywords used: {r.get('keywords_used', [])}",
        f"Found {r['total_found']} result(s)\n",
    ]

    if r.get("results"):
        lines.append("**Results:**")
        for res in r["results"]:
            lines.append(f"\n{res['rank']}. [{res['section']}] {res['title']}")
            lines.append(f"   URL: {res['url']}")
            if res.get("snippet"):
                lines.append(f"   {res['snippet']}")
    else:
        lines.append(r.get("message", "No results found."))

    if r.get("search_tip"):
        lines.append(f"\nTip: {r['search_tip']}")

    return "\n".join(lines)


def _handle(request: dict) -> dict | None:
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "agilepoint-docs",
                "version": "2.0.0",
                "description": "Search AgilePoint NX documentation (crawler-based index)",
            },
        })

    if method == "notifications/initialized":
        return None  # fire-and-forget

    if method == "tools/list":
        return _ok(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "search_docs":
            query = arguments.get("query", "").strip()
            if not query:
                return _err(req_id, -32602, "query parameter is required")
            max_results = min(max(int(arguments.get("max_results", 5)), 1), 10)
            result = search_agilepoint_docs(query, max_results)
            text = _format_search_result(result)
            return _ok(req_id, _text_content(text))

        if tool_name == "fetch_page":
            url = arguments.get("url", "").strip()
            if not url:
                return _err(req_id, -32602, "url parameter is required")
            result = fetch_page_content(url)
            if "error" in result:
                text = f"Error: {result['error']}"
            else:
                text = (
                    f"# {result['title']}\n"
                    f"Section: {result['section']}\n"
                    f"URL: {result['url']}\n\n"
                    f"{result['content']}"
                )
            return _ok(req_id, _text_content(text))

        return _err(req_id, -32601, f"Tool not found: {tool_name}")

    return _err(req_id, -32601, f"Method not found: {method}")


# ── Entry Point ───────────────────────────────────────────────────────────────

def main() -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            resp = _err(None, -32700, f"Parse error: {exc}")
            print(json.dumps(resp), flush=True)
            continue

        response = _handle(request)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
