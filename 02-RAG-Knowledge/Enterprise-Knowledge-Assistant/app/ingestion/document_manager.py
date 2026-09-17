"""Inventory of data/documents + persistent metadata + duplicate detection.

The source of truth for "which documents have been seen" is the JSON store at
``<metadata_dir>/documents.json``. Ingestion (plan.md Phases 5/6) consults
:meth:`DocumentManager.sync` so unchanged files are never reprocessed.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.ingestion.metadata import DocumentMetadata

# Files we consider "documents" — mirrors the upload allowlist (instructions.md §53).
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".html"}


class DocumentManager:
    """Scans the document dir, hashes files, persists metadata, detects duplicates."""

    def __init__(self, document_dir: Path, metadata_dir: Path) -> None:
        self.document_dir = Path(document_dir)
        self.metadata_dir = Path(metadata_dir)
        self.metadata_file = self.metadata_dir / "documents.json"

    # -- scanning ------------------------------------------------------ #
    def inventory(self) -> list[DocumentMetadata]:
        """Freshly computed metadata for every supported file in document_dir."""
        if not self.document_dir.is_dir():
            return []
        files = sorted(
            p
            for p in self.document_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        return [DocumentMetadata.from_path(p) for p in files]

    # -- persistence ---------------------------------------------------- #
    def load_all(self) -> dict[str, DocumentMetadata]:
        """Stored metadata keyed by filename; empty dict when nothing stored yet."""
        if not self.metadata_file.exists():
            return {}
        raw = json.loads(self.metadata_file.read_text(encoding="utf-8"))
        return {item["filename"]: DocumentMetadata.from_dict(item) for item in raw}

    def save_all(self, records: dict[str, DocumentMetadata]) -> None:
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        payload = [m.to_dict() for m in sorted(records.values(), key=lambda m: m.filename)]
        self.metadata_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # -- duplicate detection -------------------------------------------- #
    def find_by_hash(self, file_hash: str) -> DocumentMetadata | None:
        """First stored document whose SHA-256 matches, else None."""
        for meta in self.load_all().values():
            if meta.file_hash == file_hash:
                return meta
        return None

    def sync(self) -> dict[str, int]:
        """Merge freshly scanned files into the store, skipping known hashes.

        Returns ``{"added": n_new, "duplicates": n_already_seen}`` — the real
        numbers Phase 6 logs as processing counts instead of fabricated ones.
        """
        stored = self.load_all()
        known_hashes = {m.file_hash for m in stored.values()}
        added = duplicates = 0
        for meta in self.inventory():
            if meta.file_hash in known_hashes:
                duplicates += 1
                continue
            stored[meta.filename] = meta
            added += 1
        self.save_all(stored)
        return {"added": added, "duplicates": duplicates}