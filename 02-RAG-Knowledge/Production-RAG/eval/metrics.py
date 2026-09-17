"""
Phase 1 — deterministic (LLM-free) evaluation metrics.

Every metric here is computed from data we already have after one pipeline
pass over a golden question: the retrieved chunks and the generated answer.
No judge LLM is involved, so a full suite runs in seconds-to-minutes and is
fully reproducible.

Metrics per question
--------------------
recall_at_k          1.0 if ANY of the top-k retrieved chunks matches one of
                     the question's expected_sections (matched on
                     doc_title + section_title). None for negative cases.
first_relevant_rank  1-indexed rank of the first matching chunk (None if no
                     chunk matched). Lower is better.
citation_coverage    fraction of retrieved chunks whose (doc, section) the
                     answer actually cites with [Source: ..., Section: ...].
must_term_coverage   fraction of "must terms" (significant words extracted
                     from the reference answer) that appear in the generated
                     answer.
refusal_correct      negative cases only: 1.0 if the model refused ("could
                     not find ...") instead of hallucinating.
latency              retrieve_ms / generate_ms / total_ms.

Aggregates (see aggregate()) average these over the suite, split by kind.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

# Words too common to be useful as "must terms".
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "was", "were", "be", "been", "by", "that", "this", "these", "those",
    "it", "its", "as", "at", "from", "into", "when", "which", "who", "whom",
    "what", "how", "why", "can", "could", "would", "should", "shall", "will",
    "may", "might", "must", "if", "then", "than", "not", "no", "yes", "so",
    "such", "there", "their", "they", "them", "you", "your", "we", "our", "us",
    "also", "but", "all", "any", "each", "per", "via", "between", "both",
    "more", "most", "less", "least", "only", "about", "over", "under", "other",
    "some", "have", "has", "had", "do", "does", "did", "one", "two", "use",
    "used", "using", "example", "e.g", "i.e",
}

_REFUSAL_RE = re.compile(r"could\s+not\s+find|no\s+relevant|not\s+covered|don'?t\s+know", re.I)
_CITATION_RE = re.compile(r"\[Source:\s*(?P<doc>.+?),\s*Section:\s*(?P<sec>.+?)\]")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def extract_must_terms(reference_answer: str, max_terms: int = 12) -> List[str]:
    """Significant words from the reference answer, in first-seen order."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9_\-./]{2,}", reference_answer or "")
    terms: List[str] = []
    for w in words:
        lw = w.lower().strip(".-_/")
        if len(lw) < 4 or lw in _STOPWORDS or lw in terms:
            continue
        terms.append(lw)
        if len(terms) >= max_terms:
            break
    return terms


def section_match(chunk_meta: Dict[str, Any], expected_sections: List[Dict[str, Any]]) -> bool:
    """
    True if a retrieved chunk's metadata matches one expected section.

    Strict match: doc_title AND section_title equal (case/whitespace-insensitive).
    Fallback match for headerless chunking strategies (character windows and
    semantic-embedding chunks whose section_title is a derived label rather
    than a real document heading): doc_title equality is enough, otherwise
    those strategies would be unfairly scored 0 recall.
    """
    exp = [
        {"doc_title": _norm(e.get("doc_title", "")), "section_title": _norm(e.get("section_title", ""))}
        for e in (expected_sections or [])
    ]
    if not exp:
        return False
    doc = _norm(str(chunk_meta.get("doc_title", "")))
    sec = _norm(str(chunk_meta.get("section_title", "")))
    strategy = str(chunk_meta.get("strategy", ""))
    headerless = strategy in ("character", "semantic-embedding")
    for e in exp:
        if doc == e["doc_title"] and sec == e["section_title"]:
            return True
        if headerless and e["section_title"] and doc == e["doc_title"]:
            return True
    return False


def matched_sections(retrieved_meta: List[Dict[str, Any]],
                     expected_sections: List[Dict[str, Any]]) -> List[str]:
    """Expected sections that were hit by at least one retrieved chunk."""
    hits = []
    for e in expected_sections or []:
        label = f"{e.get('doc_title', '?')} · {e.get('section_title', '?')}"
        if any(section_match(m, [e]) for m in retrieved_meta):
            hits.append(label)
    return hits


def recall_at_k(retrieved_meta: List[Dict[str, Any]], expected_sections: List[Dict[str, Any]]) -> Optional[float]:
    """1.0 if any retrieved chunk matches an expected section, else 0.0. None if no expectations."""
    if not expected_sections:
        return None
    return 1.0 if any(section_match(m, expected_sections) for m in retrieved_meta) else 0.0


def first_relevant_rank(retrieved_meta: List[Dict[str, Any]],
                        expected_sections: List[Dict[str, Any]]) -> Optional[int]:
    """1-indexed rank of the first matching chunk; None if nothing matched / no expectations."""
    if not expected_sections:
        return None
    for i, m in enumerate(retrieved_meta, start=1):
        if section_match(m, expected_sections):
            return i
    return None


def parse_citations(answer_text: str) -> List[Dict[str, str]]:
    """[Source: <doc>, Section: <sec>] occurrences as {doc, section} dicts."""
    return [{"doc": m.group("doc").strip(), "section": m.group("sec").strip()}
            for m in _CITATION_RE.finditer(answer_text or "")]


def citation_coverage(answer_text: str, retrieved_meta: List[Dict[str, Any]]) -> Optional[float]:
    """
    Fraction of retrieved chunks that the answer cites by (doc, section).
    None when nothing was retrieved (negative cases) — coverage is undefined.
    """
    if not retrieved_meta:
        return None
    cited = {(_norm(c["doc"]), _norm(c["section"])) for c in parse_citations(answer_text)}
    if not cited:
        return 0.0
    hits = 0
    for m in retrieved_meta:
        key = (_norm(str(m.get("doc_title", ""))), _norm(str(m.get("section_title", ""))))
        if key in cited:
            hits += 1
    return round(hits / len(retrieved_meta), 4)


def must_term_coverage(answer_text: str, must_terms: List[str]) -> Optional[float]:
    """Fraction of must terms present in the answer (case-insensitive). None if no terms."""
    if not must_terms:
        return None
    text = _norm(answer_text)
    hits = sum(1 for t in must_terms if re.search(re.escape(t), text))
    return round(hits / len(must_terms), 4)


def refusal_correct(answer_text: str) -> float:
    """1.0 if the answer is a proper refusal, 0.0 if it hallucinated content."""
    return 1.0 if _REFUSAL_RE.search(answer_text or "") else 0.0


def score_question(item: Dict[str, Any],
                   answer_text: str,
                   retrieved_meta: List[Dict[str, Any]],
                   retrieve_ms: int,
                   generate_ms: int,
                   strategy: str,
                   retriever: str) -> Dict[str, Any]:
    """All deterministic metrics for one golden question after one pipeline pass."""
    kind = item.get("kind", "section")
    expected = item.get("expected_sections", []) or []
    is_negative = kind == "negative"
    terms = extract_must_terms(item.get("reference_answer", ""))
    return {
        "id": item.get("id"),
        "kind": kind,
        "question": item.get("question", ""),
        "strategy": strategy,
        "retriever": retriever,
        "expected_sections": expected,
        "matched_sections": [] if is_negative else matched_sections(retrieved_meta, expected),
        "recall_at_k": None if is_negative else recall_at_k(retrieved_meta, expected),
        "first_relevant_rank": None if is_negative else first_relevant_rank(retrieved_meta, expected),
        "citation_coverage": None if is_negative else citation_coverage(answer_text, retrieved_meta),
        "must_term_coverage": None if is_negative else must_term_coverage(answer_text, terms),
        "refusal_correct": refusal_correct(answer_text) if is_negative else None,
        "n_citations": len(parse_citations(answer_text)),
        "retrieve_ms": retrieve_ms,
        "generate_ms": generate_ms,
        "total_ms": retrieve_ms + generate_ms,
        "n_retrieved": len(retrieved_meta),
    }


def _mean(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def _p95(rows: List[Dict[str, Any]], key: str) -> int:
    vals = sorted(r[key] for r in rows if r.get(key) is not None)
    if not vals:
        return 0
    idx = max(0, min(len(vals) - 1, int(round(0.95 * len(vals))) - 1))
    return int(vals[idx])


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Suite-level aggregates for one (chunking, retriever, top_k) combo."""
    answerable = [r for r in rows if r.get("kind") != "negative"]
    negatives = [r for r in rows if r.get("kind") == "negative"]
    sections = [r for r in answerable if r.get("kind") == "section"]
    multihop = [r for r in answerable if r.get("kind") == "multi-hop"]
    return {
        "n_questions": len(rows),
        "n_answerable": len(answerable),
        "n_negative": len(negatives),
        "recall_at_k": _mean(answerable, "recall_at_k"),
        "recall_section": _mean(sections, "recall_at_k"),
        "recall_multihop": _mean(multihop, "recall_at_k"),
        "first_relevant_rank": _mean(answerable, "first_relevant_rank"),
        "citation_coverage": _mean(answerable, "citation_coverage"),
        "must_term_coverage": _mean(answerable, "must_term_coverage"),
        "refusal_accuracy": _mean(negatives, "refusal_correct"),
        "mean_total_ms": int(sum(r["total_ms"] for r in rows) / len(rows)) if rows else 0,
        "p95_total_ms": _p95(rows, "total_ms"),
    }


AGG_METRICS = [
    "recall_at_k", "recall_section", "recall_multihop", "first_relevant_rank",
    "citation_coverage", "must_term_coverage", "refusal_accuracy",
    "mean_total_ms", "p95_total_ms",
]


def now_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")