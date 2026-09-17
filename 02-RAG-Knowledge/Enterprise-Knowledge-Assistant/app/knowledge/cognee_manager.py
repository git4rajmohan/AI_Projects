"""Cognee integration — the SOLE ingestion/embedding entry point (plan.md Phase 5).

Every Cognee-specific call in the application lives in this module; nothing else
imports cognee. Responsibilities:

    add_documents(paths)   stage document files into Cognee's data store
    process()              run the knowledge pipeline (chunk -> extract -> graph)
    get_status()           REAL graph node/relationship counts + Qdrant state

Verified against the installed pair cognee==1.4.2 + cognee-community-vector-
adapter-qdrant==0.4.0 (do not trust older tutorials):

  * Cognee configuration is env-var driven (pydantic-settings, ``lru_cache``d) —
    env vars must be set BEFORE the first cognee import/config access in the
    process. ``configure()`` below does exactly that and is idempotent.
  * Cognee's ``"ollama"`` LLM provider is an OpenAI-compatible client
    (``AsyncOpenAI(base_url=endpoint)``), so it must point at the Ollama Cloud
    ``/v1`` surface (native Ollama ``/api`` would NOT work here).
  * Cognee's ``"ollama"`` embedding engine posts to the LOCAL daemon's native
    ``/api/embed`` endpoint (the cloud plan has no embedding models).
  * Qdrant is a community adapter registered by importing
    ``cognee_community_vector_adapter_qdrant.register`` (registers
    ``use_vector_adapter("qdrant", QDrantAdapter)``).
  * The graph backend is the built-in embedded Ladybug store (file-based),
    rooted at ``SYSTEM_ROOT_DIRECTORY`` so state lands in ``data/cognee/`` and
    never inside site-packages.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import requests

from app.config.settings import Settings
from app.vectorstore import qdrant_manager

_configured: bool = False


# -- ingested-document ledger (Phase 6 duplicate skip) ------------------- #
# ponytail: hash->filename JSON ledger; per-run transactionality is cognee's
# incremental_loading job, not ours. Replace with real bookkeeping only if
# partial-failure recovery ever becomes a demo requirement.
_LEDGER_FILE = "ingested.json"


def _load_ledger(settings: Settings) -> dict[str, str]:
    path = settings.metadata_dir / _LEDGER_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_ledger(settings: Settings, ledger: dict[str, str]) -> None:
    settings.metadata_dir.mkdir(parents=True, exist_ok=True)
    path = settings.metadata_dir / _LEDGER_FILE
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")


def seed_ledger(settings: Settings, filenames: list[str]) -> int:
    """Record files that were already cognified before the ledger existed.

    One-time migration (e.g. the Phase 5 subset run); silently skips names
    that don't exist on disk. Returns how many entries were added.
    """
    ledger = _load_ledger(settings)
    from app.ingestion.metadata import DocumentMetadata

    added = 0
    for name in filenames:
        path = settings.document_dir / name
        if not path.is_file():
            continue
        meta = DocumentMetadata.from_path(path)
        if meta.file_hash not in ledger:
            ledger[meta.file_hash] = name
            added += 1
    if added:
        _save_ledger(settings, ledger)
    return added


def _llm_endpoint(settings: Settings) -> str:
    """OpenAI-compatible chat endpoint for cognee's 'ollama' provider.

    # ponytail: Ollama Cloud's native base is .../api (Settings default) but
    # its OpenAI-compat surface lives at ollama.com/v1, so strip a trailing
    # /api before appending /v1. Revisit if cognee ships a native-Ollama adapter.
    """
    base = settings.cloud_base_url if settings.is_cloud_provider else settings.local_base_url
    base = base.rstrip("/")
    if base.endswith("/api"):
        base = base[: -len("/api")]
    return f"{base}/v1"


def _embedding_endpoint(settings: Settings) -> str:
    """Cognee's OllamaEmbeddingEngine posts to the daemon's NATIVE /api/embed."""
    return f"{settings.local_base_url.rstrip('/')}/api/embed"


def _probe_embedding_dimensions(settings: Settings) -> int:
    """One real /api/embed call to learn the true vector size (never guess)."""
    resp = requests.post(
        _embedding_endpoint(settings),
        json={"model": settings.embed_model, "input": "dimension probe"},
        timeout=120,
    )
    resp.raise_for_status()
    payload = resp.json()
    embeddings = payload.get("embeddings") or [payload.get("embedding")]
    if not embeddings or not embeddings[0]:
        raise RuntimeError(f"Embedding probe failed for {settings.embed_model!r}: {payload}")
    return len(embeddings[0])


# ponytail: reasoning models (gpt-oss:120b) treat cognee's bundled
# "Output two sections only" summarize prompt as higher-priority than
# instructor's JSON-schema instruction and answer in markdown -> every
# SummarizedContent validation fails on JSON parse. We rewrite the prompt to
# request JSON directly (leading sentence + bulleted facts = the schema's
# `summary` description). Backed up once, restored on reset. Remove this
# fixup if cognee ships a JSON-native summarize prompt.
_PROMPT_BACKUP_SUFFIX = ".orig"


def _fix_summarize_prompt() -> None:
    """Rewrite cognee's summarize_content.txt so structured output succeeds."""
    import cognee
    from cognee.root_dir import get_absolute_path

    prompt_path = Path(get_absolute_path("./infrastructure/llm/prompts/summarize_content.txt"))
    backup = prompt_path.with_suffix(prompt_path.suffix + _PROMPT_BACKUP_SUFFIX)
    if backup.exists():
        return  # already patched
    backup.write_text(prompt_path.read_text(encoding="utf-8"), encoding="utf-8")
    prompt_path.write_text(
        "Summarize the chunk for retrieval.\n\n"
        'Return ONLY a JSON object with one string field "summary".\n'
        "The value must be: one leading sentence stating what the chunk is about, "
        "followed by a bulleted list of self-contained facts covering the full "
        "content of the chunk. Do not invent. Max 200 tokens.\n",
        encoding="utf-8",
    )


def configure(settings: Settings | None = None) -> None:
    """Set the env vars Cognee reads, then import cognee + the Qdrant adapter.

    Idempotent: pydantic-settings caches config singletons, so re-running with
    a second Settings object in the same process is not supported (one process,
    one configuration).
    """
    global _configured
    if _configured:
        return
    s = settings or __import__("app.config.settings", fromlist=["get_settings"]).get_settings()

    # Storage: keep Cognee's relational/graph/data state inside the project's
    # data dir (default is site-packages/.cognee_system — unacceptable).
    system_root = s.data_dir / "cognee" / "system"
    data_root = s.data_dir / "cognee" / "data"
    os.environ["SYSTEM_ROOT_DIRECTORY"] = str(system_root)
    os.environ["DATA_ROOT_DIRECTORY"] = str(data_root)

    # LLM: cognee's "ollama" provider is OpenAI-compatible (AsyncOpenAI client).
    os.environ["LLM_PROVIDER"] = "ollama"
    os.environ["LLM_ENDPOINT"] = _llm_endpoint(s)
    os.environ["LLM_MODEL"] = s.llm_model
    os.environ["LLM_API_KEY"] = s.api_key

    # Embeddings: LOCAL daemon, native /api/embed, real dimensions probed once.
    dimensions = _probe_embedding_dimensions(s)
    os.environ["EMBEDDING_PROVIDER"] = "ollama"
    os.environ["EMBEDDING_ENDPOINT"] = _embedding_endpoint(s)
    os.environ["EMBEDDING_MODEL"] = s.embed_model
    os.environ["EMBEDDING_DIMENSIONS"] = str(dimensions)

    # Vector backend: the community Qdrant adapter registers itself on import.
    os.environ["VECTOR_DB_PROVIDER"] = "qdrant"
    os.environ["VECTOR_DB_URL"] = s.qdrant_url
    # Cognee 1.4.2 defaults multi-user access control ON and pairs the vector
    # provider with a "vector dataset handler" — its built-in list has no
    # qdrant pairing, so use the one the adapter package itself registers.
    os.environ["VECTOR_DATASET_DATABASE_HANDLER"] = "qdrant"

    # Indexing concurrency: the default (150 concurrent data points) floods a
    # local Qdrant with upserts until it answers 408 Request Timeout and the
    # whole pipeline fails + rolls back. 30 keeps the local daemon/Qdrant
    # comfortably busy without saturation.
    os.environ.setdefault("EMBEDDING_MAX_CONCURRENT_DATA_POINTS", "30")

    import cognee  # noqa: F401  (after env vars — config caches on first use)
    import cognee_community_vector_adapter_qdrant.register  # noqa: F401

    _fix_summarize_prompt()

    _configured = True


class CognifyManager:
    """Thin facade over cognee.add / cognee.cognify / real graph counts."""

    def __init__(self, settings: Settings | None = None) -> None:
        from app.config.settings import get_settings

        self.settings = settings or get_settings()
        self.dataset_name = "main_dataset"
        configure(self.settings)

    # -- ingestion ----------------------------------------------------- #
    def add_documents(self, paths: list[Path]) -> dict[str, Any]:
        """Stage files into Cognee's data store (no processing yet)."""
        missing = [str(p) for p in paths if not Path(p).is_file()]
        if missing:
            raise FileNotFoundError(f"Documents not found: {missing}")
        import cognee

        result = asyncio.run(
            cognee.add(
                [str(p) for p in paths],
                dataset_name=self.dataset_name,
                incremental_loading=True,
            )
        )
        return result if isinstance(result, dict) else {"result": repr(result)}

    def process(self, chunk_size: int | None = None) -> dict[str, Any]:
        """Run the knowledge pipeline on staged data (extract + graph + vectors)."""
        import cognee

        result = asyncio.run(
            cognee.cognify(
                datasets=[self.dataset_name],
                chunk_size=chunk_size or self.settings.chunk_size,
            )
        )
        return result if isinstance(result, dict) else {"result": repr(result)}

    def ingest_all(self, paths: list[Path]) -> dict[str, Any]:
        """Full-corpus ingestion entry point (Phase 6): hash-skip unchanged files.

        Uses the ingested-hash ledger (NOT documents.json, which is the Phase 3
        inventory) so a re-run skips everything already cognified instead of
        reprocessing the corpus. Files are staged via add_documents() and
        processed via process() — this method owns no embedding logic itself;
        Cognee remains the sole ingestion path.
        """
        ledger = _load_ledger(self.settings)
        from app.ingestion.metadata import DocumentMetadata

        new_paths = []
        skipped = 0
        for p in paths:
            meta = DocumentMetadata.from_path(Path(p))
            if meta.file_hash in ledger:
                skipped += 1
                continue
            new_paths.append(Path(p))

        result: dict[str, Any] = {
            "discovered": len(paths),
            "new": len(new_paths),
            "skipped_duplicates": skipped,
            "processed": 0,
        }
        if new_paths:
            self.add_documents(new_paths)
            self.process()
            result["processed"] = len(new_paths)
            for p in new_paths:
                ledger[DocumentMetadata.from_path(p).file_hash] = Path(p).name
            _save_ledger(self.settings, ledger)
        return result

    # -- provenance ----------------------------------------------------- #
    def get_chunk_document_map(self) -> dict[str, str]:
        """Map DocumentChunk node-id -> source document stem (REAL provenance).

        The Cognee graph records ``DocumentChunk --is_part_of--> TextDocument``
        (131 edges / 11 docs in this corpus), and TextDocument.name is the
        document stem (e.g. ``benefits-overview``). Verified 2026-09-07. This
        is how Phase 7+ citations resolve — never guessed.

        Cacheable: the graph only changes when documents are (re-)ingested.
        """
        import cognee
        from cognee.context_global_variables import set_database_global_context_variables
        from cognee.modules.data.methods.get_datasets import get_datasets
        from cognee.modules.users.methods import get_default_user

        async def _map() -> dict[str, str]:
            user = await get_default_user()
            datasets = await get_datasets(user.id)
            dataset = next((d for d in datasets if d.name == self.dataset_name), None)
            if dataset is None:
                return {}
            async with set_database_global_context_variables(dataset.id, user.id):
                from cognee.infrastructure.databases.graph import get_graph_engine

                engine = await get_graph_engine()
                nodes, edges = await engine.get_graph_data()
            node_types = {nid: props.get("type") for nid, props in nodes}
            doc_names = {
                nid: props.get("name", "")
                for nid, props in nodes
                if props.get("type") == "TextDocument"
            }
            mapping: dict[str, str] = {}
            for src, dst, rel, *_ in edges:
                if rel == "is_part_of" and node_types.get(src) == "DocumentChunk":
                    name = doc_names.get(dst)
                    if name:
                        mapping[src] = name
            return mapping

        return asyncio.run(_map())

    # -- status --------------------------------------------------------- #
    def get_status(self) -> dict[str, Any]:
        """REAL counts from Cognee's graph store + Qdrant. Never fabricates.

        Returns {'graph': {...}, 'vector': {...}}; keys carry 'error' entries
        when a store can't be reached or no dataset exists yet.

        Graph reads need the per-dataset database context Cognee's pipeline
        itself used (graph file lives under <system>/databases/<dataset_id>/),
        so we resolve the dataset UUID and enter the same context manager.
        """
        import cognee
        from cognee.context_global_variables import set_database_global_context_variables
        from cognee.modules.data.methods.get_datasets import get_datasets
        from cognee.modules.users.methods import get_default_user

        graph: dict[str, Any] = {}

        async def _graph_counts() -> None:
            user = await get_default_user()
            datasets = await get_datasets(user.id)
            dataset = next((d for d in datasets if d.name == self.dataset_name), None)
            if dataset is None:
                graph["error"] = f"dataset {self.dataset_name!r} not found (not ingested yet)"
                return
            async with set_database_global_context_variables(dataset.id, user.id):
                from cognee.infrastructure.databases.graph import get_graph_engine

                engine = await get_graph_engine()
                nodes, edges = await engine.get_graph_data()
            graph["nodes"] = len(nodes)
            graph["relationships"] = len(edges)
            types: dict[str, int] = {}
            for _nid, props in nodes:
                t = props.get("type", "unknown")
                types[t] = types.get(t, 0) + 1
            graph["node_types"] = types

        try:
            asyncio.run(_graph_counts())
        except Exception as exc:  # noqa: BLE001 — report, don't fake
            graph["error"] = f"{type(exc).__name__}: {exc}"

        vector: dict[str, Any] = {}
        health = qdrant_manager.health_check()
        vector["qdrant_health"] = health
        collections = {}
        for name in health.get("collections", []):
            info = qdrant_manager.get_collection_info(name)
            if info:
                collections[name] = info
        vector["collections"] = collections
        return {"graph": graph, "vector": vector}

    # -- reset ------------------------------------------------------------ #
    def reset(self) -> dict[str, Any]:
        """Wipe ALL knowledge state: graph + vectors + relational records.

        Cognee's ``forget(everything=True)`` covers the graph, vector points
        and relational datasets/data records for the user; dropping every
        remaining Qdrant collection catches orphans (shared EdgeType points,
        pre-marker collections). The app's metadata JSONs are the caller's
        job (the UI and scripts/reset_database.py own their own files).

        Verified against cognee 1.4.2 source + live graph probe: this graph
        is marked ``delete_mode='graph_native'`` so forget routes through the
        provenance path (execute_source_ref_removal), which deletes graph
        nodes AND vector points; the collection drop below is belt-and-braces
        for the empty state the demo expects.
        """
        import cognee

        result: dict[str, Any] = {}
        result["cognee"] = asyncio.run(cognee.forget(everything=True))
        dropped = [name for name in qdrant_manager.list_collections() if qdrant_manager.delete_collection(name)]
        result["qdrant_dropped"] = dropped
        return result