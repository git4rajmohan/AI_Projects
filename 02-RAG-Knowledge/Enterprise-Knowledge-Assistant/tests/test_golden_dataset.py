"""Golden-dataset validation (item 13) — hermetic structural checks.

These tests guarantee the dataset itself is sound BEFORE any evaluation runs
(item 14): valid JSONL, unique IDs, all required fields, enum-legal category/
difficulty, refusal consistency, source filenames that exist in the corpus,
and coverage of every category the spec (§14) requires.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config.settings import get_settings

DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "eval" / "golden_dataset.jsonl"

REQUIRED_FIELDS = {
    "id", "question", "expected_answer", "expected_source", "expected_source_section",
    "difficulty", "category", "expected_keywords", "expected_source_any", "expect_refusal",
}
CATEGORIES = {"factual", "terminology", "paraphrase", "multi_hop", "distractor", "unsupported", "ambiguous"}
DIFFICULTIES = {"easy", "medium", "hard"}


def load_dataset() -> list[dict]:
    rows = []
    for line in DATASET_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(_parse_line(line))
    return rows


def _parse_line(line: str) -> dict:
    import json

    return json.loads(line)


def test_dataset_loads_and_is_valid_jsonl() -> None:
    rows = load_dataset()
    assert len(rows) >= 50, f"spec §14 requires 50-200 pairs; got {len(rows)}"


def test_dataset_ids_unique() -> None:
    rows = load_dataset()
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate golden-dataset IDs"


def test_all_rows_have_required_fields() -> None:
    for row in load_dataset():
        missing = REQUIRED_FIELDS - set(row)
        assert not missing, f"{row.get('id', '?')} missing fields: {missing}"


def test_category_and_difficulty_enums() -> None:
    for row in load_dataset():
        assert row["category"] in CATEGORIES, f"{row['id']}: bad category {row['category']!r}"
        assert row["difficulty"] in DIFFICULTIES, f"{row['id']}: bad difficulty {row['difficulty']!r}"


def test_coverage_of_all_spec_categories() -> None:
    rows = load_dataset()
    present = {r["category"] for r in rows}
    missing = CATEGORIES - present
    assert not missing, f"§14 requires all categories; missing: {missing}"
    # Refusal coverage: unsupported questions must exist and be marked.
    unsupported = [r for r in rows if r["category"] == "unsupported"]
    assert len(unsupported) >= 5
    assert all(r["expect_refusal"] for r in unsupported)


def test_refusal_rows_are_consistent() -> None:
    for row in load_dataset():
        if row["expect_refusal"]:
            assert row["expected_answer"].startswith("REFUSE"), (
                f"{row['id']}: refusal row must explain what is being refused"
            )
            assert not row["expected_source_any"], f"{row['id']}: refusal rows have no source"


def test_answerable_rows_cite_real_corpus_files() -> None:
    corpus = {p.name for p in get_settings().document_dir.iterdir() if p.is_file()}
    for row in load_dataset():
        if not row["expect_refusal"]:
            assert row["expected_source_any"], f"{row['id']}: answerable row must cite sources"
            for source in row["expected_source_any"]:
                assert source in corpus, f"{row['id']}: cited {source!r} not in data/documents/"
            assert row["expected_source"] is None or row["expected_source"] in corpus


def test_answerable_rows_have_grounding_keywords() -> None:
    for row in load_dataset():
        if not row["expect_refusal"]:
            assert row["expected_keywords"], f"{row['id']}: needs keywords for retrieval checks"


def test_min_keyword_matches_never_exceeds_available() -> None:
    for row in load_dataset():
        if row["expect_refusal"]:
            continue  # refusal rows carry no grounding keywords by design
        need = row.get("min_keyword_matches", 1)
        assert need >= 1 and need <= len(row["expected_keywords"]), (
            f"{row['id']}: min_keyword_matches={need} vs {len(row['expected_keywords'])} keywords"
        )