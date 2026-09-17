"""
Ingest service — reads source files, calls LLM, writes wiki pages.
Yields SSE-compatible event dicts for streaming progress.
"""
from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path
from typing import AsyncGenerator

from backend.config import LLMConfig
from backend.services import llm_service, wiki_manager

INGEST_SYSTEM_PROMPT = """\
You are a technical writer creating wiki pages from a source document.

OUTPUT FORMAT:
Output each page separated by this exact marker:
===FILE: path/to/page.md===

Each page MUST have YAML frontmatter followed by markdown content.
All file paths MUST end with .md and use hyphens (no spaces).

RULES:
- Every page starts with --- frontmatter --- then content.
- Use [[wiki-link]] for cross-references.
- Be concise. Use bullet points.
- Only use information from the source document.
- Output a source page, entity pages for each component mentioned, concept pages for cross-cutting ideas, and the COMPLETE updated index.md.
- File paths are relative to wiki/ (e.g. sources/my-source.md, NOT wiki/sources/my-source.md).

COMPLETE EXAMPLE (follow this exactly):

===FILE: sources/example-doc.md===
---
title: "Example Document"
type: source
tags: [example]
created: 2026-01-01
updated: 2026-01-01
sources: 1
---
# Example Document

Summary of the document.

## Key Points
- Point one
- Point two

## Related
- [[entities/example-component]]
- [[concepts/example-pattern]]

===FILE: entities/example-component.md===
---
title: "Example Component"
type: entity
tags: [example]
created: 2026-01-01
updated: 2026-01-01
sources: 1
---
# Example Component

- What it is and what it does.

## Appears In
- [[sources/example-doc]]

===FILE: index.md===
---
title: "Wiki Index"
type: index
updated: 2026-01-01
---
# Wiki Index

## Sources
| Page | Description |
|------|-------------|
| [[sources/example-doc]] | Example document |

## Entities
| Page | Type | Description |
|------|------|-------------|
| [[entities/example-component]] | Feature | Example component |

Now produce wiki pages for the source document provided below. Start immediately with ===FILE:=== — do not output anything before the first file marker.
"""


async def ingest_files(
    cfg: LLMConfig,
    wiki_root: str,
    file_paths: list[str],
    rebuild: bool = False,
) -> AsyncGenerator[dict, None]:
    """
    Async generator that ingests source files one by one.
    Yields dicts: {event: "progress"|"file_done"|"error"|"done", ...}
    """
    root = wiki_manager._effective_root(wiki_root)
    agents_path = root / "AGENTS.md"
    agents_content = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""

    today = date.today().isoformat()

    # Read current index for context
    index_path = root / "wiki" / "index.md"
    current_index = index_path.read_text(encoding="utf-8") if index_path.exists() else ""

    total = len(file_paths)
    for i, rel_path in enumerate(file_paths):
        source_path = root / rel_path
        if not source_path.exists():
            yield {"event": "error", "file": rel_path, "message": "File not found"}
            continue

        yield {"event": "progress", "file": rel_path, "index": i + 1, "total": total,
               "message": f"Reading {source_path.name}..."}

        extracted_source_content = _read_source_file(source_path)
        source_content = extracted_source_content

        # For local CPU models (small context), use a compact prompt without AGENTS.md
        # The system prompt already contains the full schema and example
        is_local = cfg.provider == "local-cpu"
        if is_local:
            # Truncate source content to fit small model context
            max_source_chars = 8000
            if len(source_content) > max_source_chars:
                source_content = source_content[:max_source_chars] + "\n\n[... document truncated ...]"
            user_content = (
                f"Source Document: {source_path.name}\n\n{source_content}\n\n"
                f"Today's date: {today}\n\n"
                "Produce a source page that preserves all numbered requirements, IDs, tables, "
                "RACI rows, payment terms, acceptance criteria, and constraints. "
                "Create entity pages only for clearly supported entities, modules, activities, "
                "requirements groups, technologies, and roles. Do not infer RACI roles unless "
                "they are explicitly shown in the source table. "
                "Start with ===FILE:=== immediately. Do NOT output index.md or overview.md."
            )
        else:
            user_content = (
                f"## Wiki Schema (AGENTS.md)\n\n{agents_content}\n\n"
                f"## Current wiki/index.md\n\n{current_index}\n\n"
                f"## Source Document: {source_path.name}\n\n{source_content}\n\n"
                f"Today's date: {today}\n\n"
                "Produce all required wiki pages for this source."
            )

        messages = [
            {"role": "system", "content": INGEST_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        yield {"event": "progress", "file": rel_path, "index": i + 1, "total": total,
               "message": f"LLM processing {source_path.name}..."}

        # Collect full LLM response (streaming to show token activity)
        response_chunks = []
        async for chunk in llm_service.stream_completion(cfg, messages):
            response_chunks.append(chunk)
            yield {"event": "token", "chunk": chunk}

        full_response = "".join(response_chunks)

        # Strip thinking/reasoning blocks from thinking models (e.g. Gemma 4 E2B)
        # Models may output: <|channel>thought\n...thinking...<|channel>response\n...actual output...
        # or: <think>...thinking...</think>\n...actual output...
        full_response = _strip_thinking(full_response)

        # Parse and write wiki pages
        pages_written = _parse_and_write_pages(
            wiki_root,
            full_response,
            source_text=extracted_source_content,
        )

        if not pages_written:
            yield {
                "event": "error",
                "file": rel_path,
                "message": (
                    "The model did not produce any valid wiki pages. "
                    "This can happen with small local models that lack the capacity "
                    "to follow the complex wiki schema. Consider using a larger "
                    "local model or a cloud-based LLM (e.g. Baseten, OpenAI)."
                ),
            }
            continue

        # Update current_index for next iteration
        if index_path.exists():
            current_index = index_path.read_text(encoding="utf-8")

        # Append log entry
        wiki_manager.append_log(
            wiki_root,
            f"## [{today}] ingest | {source_path.stem}",
        )

        # Auto-rebuild index as fallback (in case the LLM didn't output one)
        # This is especially important for small local models that run out of tokens
        try:
            wiki_manager.auto_rebuild_index(wiki_root)
        except Exception:
            pass  # Index rebuild is best-effort

        yield {
            "event": "file_done",
            "file": rel_path,
            "index": i + 1,
            "total": total,
            "pages_written": pages_written,
        }

    yield {"event": "done", "total": total}


def _strip_thinking(text: str) -> str:
    """Remove thinking/reasoning blocks from model output.

    Handles several patterns:
    - <|channel>thought\\n...<|channel>response\\n...actual output
    - <think>...</think> (some models)
    - <thinking>...</thinking>
    Keeps only the response/actual output portion.
    """
    import re as _re

    # Pattern 1: <|channel>thought ... <|channel>response ... (Gemma 4 E2B)
    # Extract everything after the last <|channel>response marker
    channel_match = _re.search(r"<\|channel\|>response\s*\n?(.*)", text, _re.DOTALL)
    if channel_match:
        text = channel_match.group(1)

    # Pattern 2: <think>...</think> — remove the block entirely
    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL)

    # Pattern 3: <thinking>...</thinking> — remove the block entirely
    text = _re.sub(r"<thinking>.*?</thinking>", "", text, flags=_re.DOTALL)

    # Pattern 4: Any remaining <|channel>...<|channel> blocks before content
    # If there's still a <|channel> tag, take everything after the last one
    if "<|channel>" in text:
        parts = text.split("<|channel>")
        # Take the last part (should be the response)
        text = parts[-1]
        # Remove leading "response" or "thought" label if present
        text = _re.sub(r"^(response|thought)\s*\n?", "", text.strip())

    return text.strip()


def _parse_and_write_pages(wiki_root: str, llm_output: str, source_text: str | None = None) -> list[str]:
    """Parse LLM output into individual files and write them."""
    # Split on ===FILE: path===
    parts = re.split(r"===FILE:\s*(.+?)===", llm_output)
    # parts[0] = text before first marker (ignore)
    # parts[1] = path, parts[2] = content, parts[3] = path, parts[4] = content ...
    written = []
    it = iter(parts[1:])
    for rel_path, content in zip(it, it):
        rel_path = rel_path.strip()
        content = content.strip()
        # Strip leading "wiki/" — write_wiki_page already writes under wiki/
        if rel_path.lower().startswith("wiki/"):
            rel_path = rel_path[5:]
        # Never let the LLM overwrite log.md — append_log() manages it
        if rel_path.lower() == "log.md":
            continue
        if rel_path and content:
            # Skip invalid Windows filenames (e.g. placeholder text from small models)
            invalid_chars = '<>:"|?*'
            if any(c in rel_path for c in invalid_chars) or rel_path.startswith('.'):
                continue  # Skip placeholder/invalid paths silently
            # Normalize path: ensure .md extension, convert spaces to hyphens in filename
            rel_path = _normalize_wiki_path(rel_path)
            if not rel_path:
                continue
            # If the LLM emitted a bare filename (no subdirectory), infer the correct
            # subdirectory from the page frontmatter type field.
            # Small local models often omit the "sources/" prefix.
            if "/" not in rel_path and rel_path not in ("index.md", "overview.md", "log.md"):
                type_match = re.search(r"^type:\s*(\w+)", content, re.MULTILINE)
                page_type = type_match.group(1).lower() if type_match else "source"
                type_dir_map = {
                    "source": "sources",
                    "entity": "entities",
                    "concept": "concepts",
                    "analysis": "analyses",
                }
                subdir = type_dir_map.get(page_type, "sources")
                rel_path = f"{subdir}/{rel_path}"
            if rel_path.startswith("sources/") and source_text:
                content = _append_extracted_source_text(content, source_text)
            try:
                wiki_manager.write_wiki_page(wiki_root, rel_path, content)
                written.append(rel_path)
            except (ValueError, OSError):
                pass  # Path traversal or invalid path — silently skip
    return written


def _append_extracted_source_text(content: str, source_text: str) -> str:
    """Append extracted source text to source pages as a deterministic evidence fallback."""
    if "## Extracted Source Text" in content:
        return content
    source_text = source_text.strip()
    if not source_text:
        return content
    max_chars = 20000
    if len(source_text) > max_chars:
        source_text = source_text[:max_chars].rstrip() + "\n\n[... extracted source text truncated ...]"
    source_text = source_text.replace("```", "` ` `")
    return f"{content.rstrip()}\n\n## Extracted Source Text\n\n```text\n{source_text}\n```\n"


def _normalize_wiki_path(rel_path: str) -> str:
    """Normalize a wiki page path from LLM output.
    - Ensures .md extension
    - Converts spaces in filename to hyphens (slug format)
    - Converts backslashes to forward slashes
    - Lowercases the filename portion
    """
    rel_path = rel_path.replace("\\", "/").strip()
    # Split into directory and filename
    parts = rel_path.rsplit("/", 1)
    if len(parts) == 2:
        directory, filename = parts
    else:
        directory, filename = "", parts[0]

    # Remove any existing .md extension for normalization
    if filename.lower().endswith(".md"):
        filename = filename[:-3]

    # Convert spaces to hyphens, lowercase
    filename = filename.strip().lower().replace(" ", "-")
    # Remove any remaining invalid chars
    filename = re.sub(r"[^\w\-.]", "", filename)

    # Detect and reject recursive/repetitive slugs (e.g. "admin-support-ticket-admin-support-ticket-...")
    # Small models sometimes get stuck in a loop repeating the same phrase
    parts = filename.split("-")
    if len(parts) >= 6:
        # Check if the slug is just repeating a short pattern
        # e.g. "a-b-c-a-b-c-a-b-c" → collapse to "a-b-c"
        for pattern_len in range(2, min(8, len(parts) // 2)):
            pattern = parts[:pattern_len]
            repetitions = len(parts) // pattern_len
            if pattern * repetitions == parts[:pattern_len * repetitions] and repetitions >= 2:
                # Keep only the first occurrence of the pattern
                filename = "-".join(parts[:pattern_len])
                break
        
        # Also check for single-word repetition (e.g. "email-email-email-...")
        # If any word appears 3+ times in the slug, it's likely a repetition loop
        if len(parts) >= 6:
            from collections import Counter
            word_counts = Counter(parts)
            if any(count >= 3 for count in word_counts.values()):
                # Remove repeated words, keeping only first occurrence of each
                seen = set()
                deduped = []
                for p in parts:
                    if p not in seen:
                        seen.add(p)
                        deduped.append(p)
                filename = "-".join(deduped)

    if not filename:
        return ""

    # Reassemble with .md
    if directory:
        return f"{directory}/{filename}.md"
    return f"{filename}.md"


def _read_source_file(path: Path) -> str:
    """Extract text from a source file. Handles .docx, .xlsx/.xls, and plain text."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            import docx  # python-docx
            doc = docx.Document(str(path))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            # Also extract tables
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        paragraphs.append(" | ".join(cells))
            return "\n\n".join(paragraphs) or "(empty document)"

        if suffix in (".xlsx", ".xls"):
            import openpyxl
            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
            lines = []
            for sheet in wb.worksheets:
                lines.append(f"## Sheet: {sheet.title}")
                for row in sheet.iter_rows(values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    if any(c.strip() for c in cells):
                        lines.append("\t".join(cells))
            wb.close()
            return "\n".join(lines) or "(empty spreadsheet)"

        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            pages = []
            for idx, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(f"## Page {idx}\n{text.strip()}")
            return "\n\n".join(pages) or "(no extractable PDF text; scanned PDFs require OCR)"

        if suffix in (".pptx", ".pptm"):
            from pptx import Presentation
            prs = Presentation(str(path))
            slides = []
            for idx, slide in enumerate(prs.slides, start=1):
                lines = [f"## Slide {idx}"]
                for shape in slide.shapes:
                    if getattr(shape, "has_text_frame", False):
                        text = "\n".join(
                            run.text
                            for paragraph in shape.text_frame.paragraphs
                            for run in paragraph.runs
                            if run.text.strip()
                        )
                        if text.strip():
                            lines.append(text.strip())
                    if getattr(shape, "has_table", False):
                        for row in shape.table.rows:
                            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                            if cells:
                                lines.append(" | ".join(cells))
                if len(lines) > 1:
                    slides.append("\n".join(lines))
            return "\n\n".join(slides) or "(no extractable presentation text)"

        if suffix == ".ppt":
            return "(Legacy .ppt files are not directly supported. Save or export as .pptx, then ingest again.)"

    except Exception as e:
        return f"(Could not extract content: {e})"

    # Default: plain text
    return path.read_text(encoding="utf-8", errors="replace")
