# ARIA Wiki — Agent Instructions

This file is the schema and operating manual for the Aria product documentation wiki. Read this file at the start of every session before touching any other file.

---

## Purpose

This wiki is a persistent, LLM-maintained knowledge base for the **Aria** product. The LLM incrementally ingests documentation articles, builds structured wiki pages, maintains cross-references, and synthesizes the growing knowledge base. The human provides source material and asks questions; the LLM does all the writing and bookkeeping.

---

## Directory Structure

```
ARIA/
├── AGENTS.md              ← This file. Read first every session.
├── Clippings/             ← Raw source documents (immutable — never modify)
├── raw/
│   ├── articles/          ← Additional raw articles or exports
│   └── assets/            ← Downloaded images and attachments
└── wiki/
    ├── index.md           ← Master catalog — read this first when answering queries
    ├── log.md             ← Append-only activity record
    ├── overview.md        ← Evolving synthesis of the full wiki
    ├── sources/           ← One page per ingested source
    ├── entities/          ← Pages for platform components, modules, features
    ├── concepts/          ← Pages for overarching ideas, patterns, approaches
    └── analyses/          ← Comparisons, investigations, answered questions
```

**Rule**: The LLM reads from `Clippings/` and `raw/` but never modifies those folders. The LLM creates and updates everything under `wiki/`.

---

## Page Frontmatter

Every wiki page must start with YAML frontmatter:

```yaml
---
title: "Human-readable title"
type: source | entity | concept | analysis | overview | index
tags: [aria, <additional-tags>]
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: <number of sources this page draws from>
---
```

---

## Page Types

### `source`
One page per ingested clipping or article. Lives in `wiki/sources/`. Contains:
- A brief summary of what the source covers
- Key points extracted from the source
- Links to entity and concept pages this source touches

### `entity`
A page for a distinct component, module, feature, or object in Aria. Lives in `wiki/entities/`. Contains:
- What it is and what it does
- Key capabilities and properties
- How it relates to other entities
- Which source pages it appears in

### `concept`
A page for an overarching idea, pattern, or approach that spans multiple entities or features. Lives in `wiki/concepts/`. Contains:
- What the concept means in the context of Aria
- Which entities/features embody or use it
- Source pages that discuss it

### `analysis`
A page produced when answering a complex question that required synthesizing multiple sources. Lives in `wiki/analyses/`. Contains:
- The question that prompted it
- The synthesized answer with citations to source/entity/concept pages
- Any open threads or follow-up questions

### `overview`
The single `wiki/overview.md` page. A high-level synthesis of everything in the wiki. Updated every 3–5 new sources.

---

## Entity Types

| Type | Description | Examples |
|------|-------------|---------|
| Module | A major functional section of the product | Dashboard, Settings, Workspace |
| Feature | A specific capability within a module | Search, Export, Notifications |
| Data Component | A data model or storage concept | Records, Fields, Entities |
| Integration | An external system Aria connects with | APIs, third-party services |
| User Role | A type of user or actor in the system | Admin, End User, Developer |

*Update this table as new entity types emerge from ingested sources.*

---

## Concept Types

| Type | Description |
|------|-------------|
| Platform Capability | A cross-cutting platform-wide capability |
| Development Pattern | An approach to building or extending the product |
| User Workflow | A common end-to-end user workflow pattern |
| Deployment Pattern | How the product is deployed or distributed |
| Security & Access | Access control, permissions, authentication |

*Update this table as new concept types emerge from ingested sources.*

---

## Slug Format

All wiki filenames use lowercase with hyphens. No spaces, no underscores, no special characters.

Pattern: `<product-short>-<feature-or-topic-name>`

Examples:
- `aria-dashboard.md`
- `aria-user-management.md`
- `aria-api-integration.md`
- `multi-tenancy.md` (concepts don't need product prefix if generic)

---

## Ingest Workflow

When the user provides a new source document (drops it in `Clippings/` or pastes content):

1. **Read** the source document in full.
2. **Create a source page** in `wiki/sources/` with a concise summary and key points. Note every entity and concept it touches.
3. **Create or update entity pages** in `wiki/entities/` for each distinct component, module, or feature mentioned.
4. **Create or update concept pages** in `wiki/concepts/` for each overarching idea or pattern that spans entities.
5. **Update `wiki/index.md`** — prepend the new source to the Sources list; add/update entries in the Entities and Concepts tables.
6. **Append to `wiki/log.md`** — one entry per ingest: `## [YYYY-MM-DD] ingest | <Source Title>`.
7. **Update `wiki/overview.md`** if this is the 1st, 3rd, 5th, 8th, or every 5th source thereafter.

A single source may touch 5–15 wiki pages. That's expected.

---

## Query Workflow

When the user asks a question:

1. Read `wiki/index.md` to identify which entity, concept, and source pages are relevant.
2. Read those pages in full.
3. Synthesize and answer with citations using `[[wiki-links]]`.
4. If the answer required non-trivial synthesis (comparing multiple pages, resolving a contradiction, tracing a cross-cutting pattern), **file it as an analysis page** in `wiki/analyses/` and add it to `wiki/index.md`.

---

## Lint Workflow

When the user asks for a wiki health check:

1. Scan all pages for **broken `[[links]]`** — referenced pages that don't exist.
2. Find **orphan pages** — pages with no inbound links.
3. Identify **stale claims** — content contradicted by more recently ingested sources.
4. Note **concept gaps** — important ideas mentioned across multiple pages but lacking their own concept page.
5. Suggest **new sources to look for** that would fill identified knowledge gaps.
6. Append a `## [YYYY-MM-DD] lint | <summary>` entry to `wiki/log.md`.

---

## Linking Style

- Use Obsidian `[[wiki-link]]` syntax for all internal links.
- Use `[[Page Name|Display Text]]` when the display text should differ from the page title.
- Every entity and concept name mentioned in a page body should be linked on first occurrence.
- Source pages link to entities/concepts. Entity and concept pages link back to sources.

---

## Style Rules

- Write concisely. Prefer bullet points and tables over prose paragraphs.
- Avoid speculation — only state what is supported by ingested sources.
- When a source is ambiguous, note it explicitly rather than guessing.
- Update `updated: YYYY-MM-DD` in frontmatter whenever a page is modified.
- Never delete content — if a claim is superseded, mark it with a note like `*(superseded by [[source-slug]])* `.
