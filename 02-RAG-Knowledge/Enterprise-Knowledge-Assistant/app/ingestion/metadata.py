"""Document metadata schema + SHA-256 hashing for the ingestion layer."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_HASH_CHUNK = 1024 * 1024  # 1 MiB


@dataclass
class DocumentMetadata:
    """Metadata tracked for every ingested document (instructions.md §15)."""

    document_id: str
    filename: str
    document_type: str = "Unknown"
    department: str = "Unknown"
    version: str = "Unknown"
    upload_date: str = ""
    source_path: str = ""
    file_hash: str = ""
    status: str = "new"  # flipped to "indexed" once processed (Phase 5+)

    @classmethod
    def from_path(cls, path: Path) -> "DocumentMetadata":
        """Build metadata (including the SHA-256) for a real file on disk."""
        path = Path(path)
        return cls(
            # ponytail: filename stem as id — unique within data/documents; UUIDs only if collisions ever matter
            document_id=path.stem,
            filename=path.name,
            upload_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            source_path=str(path.resolve()),
            file_hash=hash_file(path),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentMetadata":
        return cls(**data)


def hash_file(path: Path) -> str:
    """SHA-256 hex digest, streamed in 1 MiB chunks (large PDFs never fully in memory)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()