"""
Wiki manager  Efolder CRUD, link resolution, backlinks index, scaffold.
All path operations are validated to prevent path traversal.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import frontmatter

WIKI_SUBDIRS = ["sources", "entities", "concepts", "analyses"]
CLIPPINGS_DIR = "Clippings"
RAW_DIR = "raw"


def _effective_root(wiki_root: str) -> Path:
    """Return the folder that actually contains wiki/ and Clippings/.

    Handles the common case where the user registered the parent folder
    (e.g. RMtest07) instead of the actual wiki root (e.g. RMtest07/MyWiki).
    Scans one level of children; falls back to the given root if nothing matches.
    """
    root = Path(wiki_root)
    if (root / "wiki").exists():
        return root
    try:
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith(".") and (child / "wiki").exists():
                return child
    except (PermissionError, OSError):
        pass
    return root

AGENTS_TEMPLATE = """\
# LLM Wiki — Agent Instructions

This file is the schema and operating manual for this wiki. Read this file at the
start of every session before touching any other file.

---

## Purpose

This wiki is a persistent, LLM-maintained knowledge base. The LLM incrementally
ingests documentation articles, builds structured wiki pages, maintains
cross-references, and synthesises the growing knowledge base.

---

## Directory Structure

```
wiki/
├── index.md          ↁEMaster catalog  Eread first when answering queries
├── log.md            ↁEAppend-only activity record
├── overview.md       ↁEEvolving synthesis of the full wiki
├── sources/          ↁEOne page per ingested source
├── entities/         ↁEPages for platform components, modules, features
├── concepts/         ↁEPages for overarching ideas, patterns, approaches
└── analyses/         ↁEComparisons, investigations, answered questions
```

---

## Page Frontmatter

Every wiki page must start with YAML frontmatter:

```yaml
---
title: "Human-readable title"
type: source | entity | concept | analysis | overview | index
tags: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: <number of sources this page draws from>
---
```

---

## Ingest Workflow

1. Read the source document in full.
2. Create a source page in wiki/sources/.
3. Create or update entity pages in wiki/entities/.
4. Create or update concept pages in wiki/concepts/.
5. Update wiki/index.md.
6. Append to wiki/log.md.
7. Update wiki/overview.md if this is the 1st, 3rd, 5th, or every 5th source thereafter.

---

## Linking Style

- Use [[wiki-link]] syntax for all internal links.
- Every entity and concept name should be linked on first occurrence.

---

## Lint Workflow

1. Scan all pages for broken [[links]].
2. Find orphan pages (no inbound links).
3. Identify stale claims contradicted by newer sources.
4. Note concept gaps  Eimportant ideas without their own page.
5. Suggest new sources to fill knowledge gaps.
6. Append a lint entry to wiki/log.md.
"""

INDEX_TEMPLATE = """\
---
title: "Wiki Index"
type: index
updated: {date}
---

# Wiki Index

Master catalog of all pages.

---

## Overview

- [[overview]]  EHigh-level synthesis of the wiki's current state

---

## Sources

*No sources ingested yet.*

| Page | Description |
|------|-------------|

---

## Entities

| Page | Type | Description |
|------|------|-------------|

---

## Concepts

| Page | Type | Description |
|------|------|-------------|

---

## Analyses

| Page | Question |
|------|----------|
"""

LOG_TEMPLATE = """\
---
title: "Wiki Activity Log"
type: log
---

# Wiki Activity Log

Append-only. One entry per ingest, query filing, or lint pass.

---
"""

OVERVIEW_TEMPLATE = """\
---
title: "Wiki Overview"
type: overview
updated: {date}
sources: 0
---

# Wiki Overview

*No sources ingested yet. Overview will be generated after first ingest.*
"""


def _safe_path(base: Path, relative: str) -> Path:
    """Resolve a relative path under base, raising if it escapes base."""
    # Reject paths with invalid Windows filename characters
    invalid_chars = '<>:"|?*'
    if any(c in relative for c in invalid_chars):
        raise ValueError(f"Invalid characters in path: {relative}")
    resolved = (base / relative).resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise ValueError(f"Path traversal attempt blocked: {relative}")
    return resolved


def scaffold_wiki(root_path: str) -> None:
    """Create the full wiki project folder structure."""
    from datetime import date

    root = Path(root_path)
    root.mkdir(parents=True, exist_ok=True)

    # Clippings and raw dirs
    (root / CLIPPINGS_DIR).mkdir(exist_ok=True)
    (root / RAW_DIR / "articles").mkdir(parents=True, exist_ok=True)
    (root / RAW_DIR / "assets").mkdir(exist_ok=True)

    # Wiki dirs
    wiki = root / "wiki"
    wiki.mkdir(exist_ok=True)
    for sub in WIKI_SUBDIRS:
        (wiki / sub).mkdir(exist_ok=True)

    today = date.today().isoformat()

    # Core wiki files (only if not already present)
    _write_if_missing(wiki / "index.md", INDEX_TEMPLATE.format(date=today))
    _write_if_missing(wiki / "log.md", LOG_TEMPLATE)
    _write_if_missing(wiki / "overview.md", OVERVIEW_TEMPLATE.format(date=today))
    _write_if_missing(root / "AGENTS.md", AGENTS_TEMPLATE)


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def get_file_tree(wiki_root: str) -> dict:
    """Return a nested dict representing the wiki/ folder tree."""
    wiki = _effective_root(wiki_root) / "wiki"
    if not wiki.exists():
        return {}
    return _tree_node(wiki, wiki)


def _tree_node(path: Path, base: Path) -> dict:
    rel = path.relative_to(base)
    node: dict = {"name": path.name, "path": rel.as_posix() if str(rel) != '.' else '', "type": "dir", "children": []}
    items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    for item in items:
        if item.name.startswith("."):
            continue
        if item.is_dir():
            node["children"].append(_tree_node(item, base))
        else:
            node["children"].append({
                "name": item.name,
                "path": item.relative_to(base).as_posix(),
                "type": "file",
            })
    return node


def read_page(wiki_root: str, rel_path: str) -> Optional[dict]:
    """Read a wiki page. Returns {path, raw, frontmatter, content}."""
    wiki = _effective_root(wiki_root) / "wiki"
    full = _safe_path(wiki, rel_path)
    if not full.exists() or not full.is_file():
        return None
    raw = full.read_text(encoding="utf-8")
    try:
        post = frontmatter.loads(raw)
        return {
            "path": rel_path,
            "raw": raw,
            "frontmatter": dict(post.metadata),
            "content": post.content,
        }
    except Exception:
        return {"path": rel_path, "raw": raw, "frontmatter": {}, "content": raw}


def search_pages(wiki_root: str, query: str) -> List[dict]:
    """Full-text search across all wiki pages. Returns list of {path, snippet}."""
    wiki = _effective_root(wiki_root) / "wiki"
    results = []
    q = query.lower()
    for md_file in wiki.rglob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        if q in text.lower():
            idx = text.lower().index(q)
            snippet = text[max(0, idx - 60): idx + 120].replace("\n", " ")
            results.append({
                "path": md_file.relative_to(wiki).as_posix(),
                "snippet": snippet,
            })
    return results


def get_backlinks(wiki_root: str, slug: str) -> List[str]:
    """Return list of page paths that contain [[slug]] links pointing to slug."""
    wiki = _effective_root(wiki_root) / "wiki"
    pattern = re.compile(r"\[\[" + re.escape(slug) + r"(?:\|[^\]]+)?\]\]", re.IGNORECASE)
    matches = []
    for md_file in wiki.rglob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        if pattern.search(text):
            matches.append(md_file.relative_to(wiki).as_posix())
    return matches


def resolve_wikilink(wiki_root: str, slug: str) -> Optional[str]:
    """Resolve [[slug]] to a relative path within wiki/. Returns None if not found."""
    wiki = _effective_root(wiki_root) / "wiki"
    # Try direct path match first (handles slugs like "sources/team-calendar")
    candidate = wiki / f"{slug}.md"
    if candidate.exists():
        return candidate.relative_to(wiki).as_posix()
    # Try exact stem match (handles bare slugs like "team-calendar")
    for md_file in wiki.rglob("*.md"):
        if md_file.stem.lower() == slug.lower():
            return md_file.relative_to(wiki).as_posix()
    return None


def list_source_files(wiki_root: str) -> List[dict]:
    """List all source files in Clippings/ and raw/articles/ with ingest status."""
    root = _effective_root(wiki_root)
    ingested_slugs = _ingested_slugs(root)
    files = []

    for folder in [root / CLIPPINGS_DIR, root / RAW_DIR / "articles"]:
        if not folder.exists():
            continue
        for f in sorted(folder.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                slug = f.stem.lower().replace(" ", "-")
                files.append({
                    "name": f.name,
                    "path": f.relative_to(root).as_posix(),
                    "size": f.stat().st_size,
                    "status": "ingested" if slug in ingested_slugs else "pending",
                })
    # Deduplicate by filename  Eprevents double-listing when the same file
    # exists in both Clippings/ and raw/articles/
    seen: set[str] = set()
    unique: list[dict] = []
    for f in files:
        if f["name"] not in seen:
            seen.add(f["name"])
            unique.append(f)
    return unique


def _ingested_slugs(root: Path) -> set:
    """Parse wiki/log.md to find already-ingested source slugs."""
    log_path = root / "wiki" / "log.md"
    if not log_path.exists():
        return set()
    text = log_path.read_text(encoding="utf-8")
    # Lines like: ## [2026-04-16] ingest | AgilePoint NX Analytics Center
    matches = re.findall(r"ingest \| (.+)", text)
    return {m.strip().lower().replace(" ", "-") for m in matches}


def save_file_to_clippings(wiki_root: str, filename: str, content: bytes) -> str:
    """Save an uploaded file to Clippings/. Returns relative path."""
    root = _effective_root(wiki_root)
    clippings = root / CLIPPINGS_DIR
    clippings.mkdir(exist_ok=True)
    # Sanitize filename
    safe_name = re.sub(r"[^\w\s\-.]", "", filename).strip()
    dest = _safe_path(clippings, safe_name)
    dest.write_bytes(content)
    return dest.relative_to(root).as_posix()


def write_wiki_page(wiki_root: str, rel_path: str, content: str) -> None:
    """Write or overwrite a page under wiki/."""
    wiki = _effective_root(wiki_root) / "wiki"
    full = _safe_path(wiki, rel_path)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def append_log(wiki_root: str, entry: str) -> None:
    """Append a log entry to wiki/log.md."""
    log_path = _effective_root(wiki_root) / "wiki" / "log.md"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"\n{entry}\n")


def auto_rebuild_index(wiki_root: str) -> None:
    """Scan all wiki pages and rebuild index.md from scratch.
    Used as a fallback when the LLM doesn't output an index update."""
    from datetime import date

    wiki = _effective_root(wiki_root) / "wiki"
    if not wiki.exists():
        return

    sources = []
    entities = []
    concepts = []
    analyses = []

    for md_file in wiki.rglob("*.md"):
        rel = md_file.relative_to(wiki).as_posix()
        if rel in ("index.md", "log.md", "overview.md"):
            continue
        try:
            raw = md_file.read_text(encoding="utf-8")
            post = frontmatter.loads(raw)
            title = post.metadata.get("title", md_file.stem)
            ptype = post.metadata.get("type", "")
            tags = post.metadata.get("tags", [])
            desc = ""
            # Extract first non-heading line as description
            for line in post.content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("---"):
                    desc = line[:100]
                    break

            entry = {
                "path": rel,
                "title": title,
                "type": ptype,
                "desc": desc,
                "link": rel.replace("/", "/").replace(".md", ""),
            }

            if ptype == "source":
                sources.append(entry)
            elif ptype == "entity":
                entities.append(entry)
            elif ptype == "concept":
                concepts.append(entry)
            elif ptype == "analysis":
                analyses.append(entry)
        except Exception:
            continue

    today = date.today().isoformat()

    def _table(rows, cols):
        if not rows:
            return f"| {' | '.join(cols)} |\n|{'|'.join(['---'] * len(cols))}|\n"
        lines = [f"| {' | '.join(cols)} |", f"|{'|'.join(['---'] * len(cols))}|"]
        for r in rows:
            link = f"[[{r['link']}|{r['title']}]]"
            vals = [link] + [r.get(c.lower().replace(" ", "_"), r.get("desc", "")) for c in cols[1:]]
            lines.append(f"| {' | '.join(vals)} |")
        return "\n".join(lines) + "\n"

    index_content = f"""---
title: "Wiki Index"
type: index
updated: {today}
---

# Wiki Index

Master catalog of all pages.

---

## Overview

- [[overview]]  EHigh-level synthesis of the wiki's current state

---

## Sources

{_table(sources, ["Page", "Description"]) if sources else "*No sources ingested yet.*\\n"}

---

## Entities

{_table(entities, ["Page", "Type", "Description"])}

---

## Concepts

{_table(concepts, ["Page", "Type", "Description"])}

---

## Analyses

{_table(analyses, ["Page", "Question"])}
---
"""
    index_path = wiki / "index.md"
    index_path.write_text(index_content, encoding="utf-8")
