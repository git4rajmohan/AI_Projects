"""Phase 3 + Phase 13 tests: metadata schema, duplicate detection, and real
file ingestion (pdf/txt per instructions.md §46).

Real file bytes are used (plan.md forbids mocked file content); the corpus
files are copied into a tmp directory so the tests never write into the real
``data/metadata/`` store. Skips cleanly if the corpus isn't present.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

import pytest

from app.config.settings import PROJECT_ROOT
from app.ingestion.document_manager import DocumentManager
from app.ingestion.metadata import DocumentMetadata

_REAL_DOCS = PROJECT_ROOT / "data" / "documents"
_SAMPLE_NAMES = ("benefits-overview.pdf", "holiday-schedule.pdf")


def _seed_two_pdfs(tmp_path: Path) -> Path:
    """Copy two real corpus PDFs into a hermetic tmp document dir."""
    sources = [_REAL_DOCS / name for name in _SAMPLE_NAMES]
    if not all(p.exists() for p in sources):
        pytest.skip("real document corpus not present")
    doc_dir = tmp_path / "documents"
    doc_dir.mkdir()
    for src in sources:
        shutil.copy2(src, doc_dir / src.name)
    return doc_dir


def test_metadata_creation(tmp_path: Path) -> None:
    """Metadata built from a real PDF: correct SHA-256, schema defaults, round-trip."""
    path = _REAL_DOCS / "holiday-schedule.pdf"
    if not path.exists():
        pytest.skip("real document corpus not present")

    meta = DocumentMetadata.from_path(path)

    assert meta.filename == "holiday-schedule.pdf"
    assert meta.document_id == "holiday-schedule"
    # Real hash, verified against an independent computation.
    assert meta.file_hash == hashlib.sha256(path.read_bytes()).hexdigest()
    # Schema defaults per instructions.md §15 — no invented values.
    assert meta.document_type == "Unknown"
    assert meta.department == "Unknown"
    assert meta.version == "Unknown"
    assert meta.status == "new"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta.upload_date)
    assert Path(meta.source_path) == path.resolve()
    # Survives a round-trip through the JSON store representation.
    assert DocumentMetadata.from_dict(meta.to_dict()) == meta


def test_duplicate_detection(tmp_path: Path) -> None:
    """Re-running sync skips unchanged files; renamed copies are still caught by hash."""
    doc_dir = _seed_two_pdfs(tmp_path)
    mgr = DocumentManager(doc_dir, tmp_path / "metadata")

    first = mgr.sync()
    assert first == {"added": 2, "duplicates": 0}

    # Unchanged corpus -> nothing reprocessed.
    second = mgr.sync()
    assert second == {"added": 0, "duplicates": 2}
    assert len(mgr.load_all()) == 2

    # Same bytes under a different name -> duplicate by hash, no new record.
    shutil.copy2(doc_dir / "benefits-overview.pdf", doc_dir / "renamed-copy.pdf")
    third = mgr.sync()
    assert third == {"added": 0, "duplicates": 3}
    assert len(mgr.load_all()) == 2

    # Direct hash-lookup API.
    meta = DocumentMetadata.from_path(doc_dir / "benefits-overview.pdf")
    assert mgr.find_by_hash(meta.file_hash) is not None
    assert mgr.find_by_hash("0" * 64) is None


# --------------------------------------------------------------------- #
# Phase 13 (§46): real file ingestion — pdf + txt                        #
# --------------------------------------------------------------------- #
def test_pdf_ingestion(tmp_path: Path) -> None:
    """A real corpus PDF flows through DocumentManager with true content hash.

    Asserts what the pipeline can honestly guarantee from the file bytes:
    correct SHA-256, round-trip through the JSON store, and that Cognee's own
    text extractor (the component that will actually read it during
    ingestion) pulls real text out of these exact bytes.
    """
    src = _REAL_DOCS / "benefits-overview.pdf"
    if not src.exists():
        pytest.skip("real document corpus not present")

    doc_dir = tmp_path / "documents"
    doc_dir.mkdir()
    shutil.copy2(src, doc_dir / src.name)
    mgr = DocumentManager(doc_dir, tmp_path / "metadata")

    sync = mgr.sync()
    assert sync == {"added": 1, "duplicates": 0}

    stored = mgr.load_all()[src.name]
    assert stored.file_hash == hashlib.sha256(src.read_bytes()).hexdigest()
    assert Path(stored.source_path) == (doc_dir / src.name).resolve()

    # Round-trip: fresh manager over the same store sees it as duplicate.
    assert DocumentManager(doc_dir, tmp_path / "metadata").sync() == {
        "added": 0,
        "duplicates": 1,
    }

    # The real extraction step (Cognee's) reads meaningful text from these bytes.
    from cognee.infrastructure.files.utils.extract_text_from_file import (
        extract_text_from_file,
    )
    from cognee.infrastructure.files.utils.guess_file_type import guess_file_type

    with src.open("rb") as fh:
        file_type = guess_file_type(fh, src.name)
        assert file_type.extension == "pdf"
        text = extract_text_from_file(fh, file_type)
    assert text and "benefits" in text.lower(), "PDF text extraction returned no real content"


def test_txt_ingestion(tmp_path: Path) -> None:
    """A real .txt file is inventoried, hashed, and extractable by Cognee.

    The corpus is all-PDF, so the .txt leg uses a real file written to disk
    (not an in-memory mock) and exercises the same DocumentManager path the
    §53 upload flow uses for text documents.
    """
    doc_dir = tmp_path / "documents"
    doc_dir.mkdir()
    note = doc_dir / "remote-work-faq.txt"
    note.write_text(
        "Acme Corp - Remote Work FAQ\n"
        "Employees may work fully remote up to 20 days per year.\n",
        encoding="utf-8",
    )
    mgr = DocumentManager(doc_dir, tmp_path / "metadata")

    assert mgr.sync() == {"added": 1, "duplicates": 0}
    stored = mgr.load_all()[note.name]
    assert stored.file_hash == hashlib.sha256(note.read_bytes()).hexdigest()
    assert mgr.find_by_hash(stored.file_hash) is not None

    # Cognee's real extractor handles .txt (extension-based dispatch, verified
    # against installed cognee 1.4.2's guess_file_type/extract_text_from_file).
    from cognee.infrastructure.files.utils.extract_text_from_file import (
        extract_text_from_file,
    )
    from cognee.infrastructure.files.utils.guess_file_type import guess_file_type

    with note.open("rb") as fh:
        file_type = guess_file_type(fh, note.name)
        assert file_type.extension == "txt"
        text = extract_text_from_file(fh, file_type)
    # Compare against RAW bytes (read_text would translate \r\n -> \n on
    # Windows and mask the extractor's true output).
    assert text == note.read_bytes().decode("utf-8")