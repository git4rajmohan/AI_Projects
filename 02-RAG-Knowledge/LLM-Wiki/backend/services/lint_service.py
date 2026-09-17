"""
Lint service — two-phase wiki health check.
Phase 1: Programmatic scan (broken links, orphans, no-outbound pages).
Phase 2: LLM analysis (stale claims, concept gaps, missing cross-refs, source suggestions).
Yields SSE-compatible event dicts.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import AsyncGenerator

from backend.config import LLMConfig
from backend.services import llm_service, wiki_manager

LINT_SYSTEM_PROMPT = """\
You are a wiki curator performing a health check on a structured knowledge base.
You will be given a summary of all wiki pages (titles, types, frontmatter, content excerpts).

Analyse the wiki and report on:
1. **Contradictions** — pages that make conflicting claims
2. **Stale claims** — content superseded by newer sources (use dates in frontmatter)
3. **Concept gaps** — important ideas mentioned across multiple pages but lacking their own concept page
4. **Missing cross-references** — pages that should link to each other but don't
5. **Data gaps** — areas where a web search would significantly improve coverage
6. **Suggested new sources** — specific documents, docs pages, or searches to look for

Format your response with clear ## Section headers for each category above.
Be specific — name the pages involved and explain each issue concisely.
"""


async def run_lint(
    cfg: LLMConfig, wiki_root: str
) -> AsyncGenerator[dict, None]:
    """Async generator yielding lint results as SSE events."""

    yield {"event": "progress", "message": "Scanning wiki structure..."}

    # --- Phase 1: Programmatic scan ---
    wiki = wiki_manager._effective_root(wiki_root) / "wiki"
    all_pages = list(wiki.rglob("*.md"))

    # Build slug → path map
    slug_to_path: dict[str, str] = {}
    for p in all_pages:
        slug_to_path[p.stem.lower()] = p.relative_to(wiki).as_posix()

    # Build inbound link map
    inbound: dict[str, list[str]] = {p.stem.lower(): [] for p in all_pages}
    link_pattern = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

    broken_links: list[dict] = []
    no_outbound: list[str] = []

    for p in all_pages:
        text = p.read_text(encoding="utf-8")
        found_links = link_pattern.findall(text)
        page_slug = p.stem.lower()

        outbound_count = 0
        for link in found_links:
            target = link.strip().lower()
            if target in slug_to_path:
                inbound[target].append(page_slug)
                outbound_count += 1
            else:
                broken_links.append({"page": page_slug, "link": link.strip()})

        # Pages with no outbound links (excluding index, log)
        if outbound_count == 0 and page_slug not in ("index", "log", "overview"):
            no_outbound.append(page_slug)

    orphan_pages = [slug for slug, inb in inbound.items()
                    if not inb and slug not in ("index", "log", "overview")]

    programmatic_results = {
        "broken_links": broken_links,
        "orphan_pages": orphan_pages,
        "no_outbound_pages": no_outbound,
    }

    yield {"event": "programmatic", "results": programmatic_results}
    yield {"event": "progress", "message": f"Found {len(broken_links)} broken links, {len(orphan_pages)} orphans. Running LLM analysis..."}

    # --- Phase 2: LLM analysis ---
    # Build compact wiki summary (title + type + first 300 chars of content)
    summaries = []
    for p in sorted(all_pages, key=lambda x: x.name):
        text = p.read_text(encoding="utf-8")
        excerpt = text[:400].replace("\n", " ")
        summaries.append(f"### {p.relative_to(wiki).as_posix()}\n{excerpt}\n")

    wiki_summary = "\n".join(summaries)

    messages = [
        {"role": "system", "content": LINT_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"## Wiki Page Summaries\n\n{wiki_summary}\n\n"
            f"## Programmatic Scan Results\n\n"
            f"Broken links: {broken_links}\n"
            f"Orphan pages: {orphan_pages}\n"
            f"Pages with no outbound links: {no_outbound}\n\n"
            "Perform the full health check analysis."
        )},
    ]

    llm_output_chunks = []
    async for chunk in llm_service.stream_completion(cfg, messages):
        llm_output_chunks.append(chunk)
        yield {"event": "token", "chunk": chunk}

    llm_output = "".join(llm_output_chunks)

    # Append log entry
    today = date.today().isoformat()
    wiki_manager.append_log(
        wiki_root,
        f"## [{today}] lint | {len(broken_links)} broken links, {len(orphan_pages)} orphans",
    )

    yield {"event": "done", "llm_analysis": llm_output, "programmatic": programmatic_results}
