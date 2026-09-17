"""
Phase 0 — Golden-set generation from the ingested corpus.

Pipeline (LLM generates -> auto-filters -> human freezes):
1. Read chunks from ChromaDB and group them by section_title.
2. Per section: ask the cloud chat LLM for question/reference-answer pairs
   answerable ONLY from that section (JSON output).
3. Plus: multi-hop pairs (two sections of the same doc) and negative cases
   (topic absent from the docs -> expected fallback answer).
4. Auto-filters:
   - closed-book check: if the LLM can answer the question WITHOUT the chunk,
     the question does not measure retrieval -> rejected.
   - grounding check: a second judge pass verifies the reference answer is
     entailed by the source text -> rejected otherwise.
   - dedupe: embed questions locally; drop pairs >0.9 cosine similar.
5. Nothing is persisted until the UI review step calls freeze().
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any, Dict, List

from openai import OpenAI

from config.settings import CHAT_BASE_URL, CHAT_MODEL, CHROMA_PATH, COLLECTION_NAME
from vectorstore.embedder import load_embedding_model

GOLDEN_FILE = None  # resolved lazily to eval/golden_set.jsonl

GENERATION_PROMPT = """You are creating an evaluation dataset for a RAG system.

Below is ONE section of a documentation file.

Document: {doc_title}
Section: {section_title}

--- SECTION TEXT ---
{section_text}
--- END ---

Write {n_pairs} question/answer pairs that test retrieval on this section.
Rules:
- Each question must be answerable ONLY from this section's text (not general knowledge).
- Prefer questions that name concrete entities, tools, numbers or steps from the text.
- The reference answer must be a faithful 2-4 sentence paraphrase of the section. Never invent facts.
- Do not mention "the document" or "the section" in the question.

Return ONLY a JSON array (no markdown fences):
[{{"question": "...", "reference_answer": "..."}}]"""

MULTIHOP_PROMPT = """You are creating an evaluation dataset for a RAG system.

Below are TWO different sections from the same documentation file.

--- SECTION A ({section_a}) ---
{section_a}
--- END ---

--- SECTION B ({section_b}) ---
{section_b}
--- END ---

Write ONE question whose answer requires combining information from BOTH sections,
plus a 2-4 sentence reference answer. The question must be answerable only using
these two sections combined, not general knowledge.

Return ONLY a JSON array (no markdown fences):
[{{"question": "...", "reference_answer": "..."}}]"""

NEGATIVE_PROMPT = """You are creating negative evaluation cases for a RAG system that only
knows about these topics: {topics}.

Pick ONE closely-related but ABSENT topic (something a user might plausibly ask
about, expecting the docs to cover it, but which the docs do not cover).
Write a natural question about that absent topic and the correct refusal answer:
"I could not find an answer to this question in the provided documentation."

Return ONLY a JSON array (no markdown fences):
[{{"question": "...", "reference_answer": "..."}}]"""

CLOSED_BOOK_PROMPT = """Answer this question using only general knowledge, without any provided context.
If you cannot answer confidently, say "I don't know".

Question: {question}

If you can answer, respond with exactly: ANSWERABLE
If you would be guessing or do not know the specific details, respond with exactly: NOT_IN_GENERAL_KNOWLEDGE"""

GROUNDING_PROMPT = """Is the ANSWER below fully supported by the SOURCE text?
Reply with exactly one word: SUPPORTED or UNSUPPORTED.

--- SOURCE ---
{source}
--- END ---

--- ANSWER ---
{reference_answer}
--- END ---"""


def _chat_json(client: OpenAI, prompt: str, max_tokens: int = 1200) -> list:
    """Call the chat model and robustly extract a JSON array from the reply."""
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.choices[0].message.content or ""
    # strip reasoning-ish fences / leading prose: find first [ ... last ]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _chat_judge(client: OpenAI, prompt: str, max_tokens: int = 6) -> str:
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()


def _load_sections() -> List[Dict[str, Any]]:
    """Group stored chunks by (doc_title, section_title)."""
    from vectorstore.store import load_collection
    col = load_collection(CHROMA_PATH, COLLECTION_NAME)
    if col.count() == 0:
        raise RuntimeError("Collection is empty — run ingestion first")
    got = col.get(include=["documents", "metadatas"])
    sections: Dict[tuple, List[str]] = {}
    for doc, meta in zip(got["documents"], got["metadatas"]):
        key = (meta.get("doc_title", "?"), meta.get("section_title", "Unknown"))
        sections.setdefault(key, []).append(doc)
    return [
        {"doc_title": k[0], "section_title": k[1], "text": "\n\n".join(v)[:6000]}
        for k, v in sections.items()
        if len("\n\n".join(v)) > 200  # skip stub sections (e.g. bare headings)
        and not k[1].strip().startswith("---")  # skip separator-only section titles
    ]


def generate_candidates(
    pairs_per_section: int = 2,
    max_sections: int = 12,
    do_filters: bool = True,
    log: Any = print,
) -> Dict[str, Any]:
    """Generate candidate golden items + run auto-filters. Returns a report;
    nothing is written to disk (freeze() does that after human review)."""
    t0 = time.perf_counter()
    client = OpenAI(base_url=CHAT_BASE_URL, api_key=os.getenv("OLLAMA_API_KEY"))
    sections = _load_sections()[:max_sections]
    if not sections:
        raise RuntimeError("No sections with enough text found in the collection")

    candidates: List[Dict[str, Any]] = []

    # 1) per-section pairs
    for sec in sections:
        raw = _chat_json(client, GENERATION_PROMPT.format(
            doc_title=sec["doc_title"], section_title=sec["section_title"],
            section_text=sec["text"], n_pairs=pairs_per_section))
        for item in raw[:pairs_per_section]:
            q, a = str(item.get("question", "")).strip(), str(item.get("reference_answer", "")).strip()
            if not q or not a:
                continue
            candidates.append({
                "id": uuid.uuid4().hex[:8],
                "kind": "section",
                "question": q,
                "reference_answer": a,
                "doc_title": sec["doc_title"],
                "section_title": sec["section_title"],
                "expected_sections": [
                    {"doc_title": sec["doc_title"], "section_title": sec["section_title"]}
                ],
            })

    # 2) one multi-hop pair per document (pair first two sections of each doc)
    by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for sec in sections:
        by_doc.setdefault(sec["doc_title"], []).append(sec)
    for doc_title, secs in by_doc.items():
        if len(secs) < 2:
            continue
        raw = _chat_json(client, MULTIHOP_PROMPT.format(
            section_a=secs[0]["section_title"], section_b=secs[1]["section_title"],
            section_a_text=secs[0]["text"][:3000], section_b_text=secs[1]["text"][:3000]))
        for item in raw[:1]:
            q, a = str(item.get("question", "")).strip(), str(item.get("reference_answer", "")).strip()
            if not q or not a:
                continue
            candidates.append({
                "id": uuid.uuid4().hex[:8],
                "kind": "multi-hop",
                "question": q,
                "reference_answer": a,
                "doc_title": doc_title,
                "section_title": f"{secs[0]['section_title']} + {secs[1]['section_title']}",
                "expected_sections": [
                    {"doc_title": s["doc_title"], "section_title": s["section_title"]} for s in secs[:2]
                ],
            })

    # 3) negative cases
    topics = ", ".join(sorted({s["doc_title"] for s in sections}))
    for _ in range(2):
        raw = _chat_json(client, NEGATIVE_PROMPT.format(topics=topics))
        for item in raw[:1]:
            q, a = str(item.get("question", "")).strip(), str(item.get("reference_answer", "")).strip()
            if not q or not a:
                continue
            candidates.append({
                "id": uuid.uuid4().hex[:8],
                "kind": "negative",
                "question": q,
                "reference_answer": a,
                "doc_title": "(none)",
                "section_title": "(fallback expected)",
                "expected_sections": [],
            })

    # 4) auto-filters
    stats = {"generated": len(candidates), "closed_book_rejected": 0, "grounding_rejected": 0}
    kept: List[Dict[str, Any]] = []
    for cand in candidates:
        # closed-book: a question answerable without the docs doesn't test retrieval
        verdict = _chat_judge(client, CLOSED_BOOK_PROMPT.format(question=cand["question"]))
        if verdict.upper().startswith("ANSWERABLE") and cand["kind"] != "negative":
            stats["closed_book_rejected"] += 1
            cand["rejected"] = f"closed-book answerable ({verdict[:40]})"
            continue
        # grounding: reference answer must be entailed by the source chunk(s)
        if cand["kind"] in ("section", "multi-hop"):
            src = next((s["text"][:2500] for s in sections
                        if s["doc_title"] == cand["doc_title"]
                        and s["section_title"] in cand.get("section_title", "")), sections[0]["text"][:2500])
            gverdict = _chat_judge(client, GROUNDING_PROMPT.format(source=src, reference_answer=cand["reference_answer"]))
            if gverdict.upper().startswith("UNSUPP"):
                stats["grounding_rejected"] += 1
                cand["rejected"] = "grounding: reference not supported by source"
                continue
        cand.pop("rejected", None)
        kept.append(cand)

    # 5) dedupe by question embedding similarity
    if kept:
        model = load_embedding_model("nomic-embed-text")
        vecs = model.encode([c["question"] for c in kept])
        import numpy as np
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        unit = vecs / np.maximum(norms, 1e-9)
        sim = unit @ unit.T
        drop: set = set()
        for i in range(len(kept)):
            if i in drop:
                continue
            for j in range(i + 1, len(kept)):
                if sim[i, j] > 0.9:
                    drop.add(j)
        stats["deduped"] = len(drop)
        kept = [c for i, c in enumerate(kept) if i not in drop]
    stats["kept"] = len(kept)

    report = {
        "candidates": kept,
        "rejected": [c for c in candidates if c.get("rejected")],
        "stats": stats,
        "sections_seen": len(sections),
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }
    return report


GOLDEN_DIR = None


def _golden_path():
    from pathlib import Path
    return Path(__file__).resolve().parent / "golden_set.jsonl"


def freeze(approved: List[Dict[str, Any]], generator_model: str = CHAT_MODEL) -> Dict[str, Any]:
    """Persist human-approved candidates as the frozen golden set."""
    if not approved:
        raise ValueError("No approved items to freeze")
    path = _golden_path()
    lines = [{
        "id": c.get("id") or uuid.uuid4().hex[:8],
        "question": c["question"],
        "reference_answer": c["reference_answer"],
        "expected_sections": c.get("expected_sections", []),
        "kind": c.get("kind", "section"),
        "generator_model": generator_model,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    } for c in approved]
    path.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines), encoding="utf-8")
    return {"frozen": len(lines), "path": str(path)}


def load_frozen() -> List[Dict[str, Any]]:
    path = _golden_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out