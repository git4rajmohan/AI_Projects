"""§46 health tests: Ollama connection, Qdrant connection, Cognee initialization.

The local services (Ollama daemon, Qdrant) are free and hard-required — the
tests fail loudly when they're genuinely down but skip cleanly when the suite
is run on a machine without them. The paid Ollama Cloud leg is skipped — never
failed — when the API key is a placeholder or the endpoint is unreachable, per
§46's "Tests must not require paid cloud services".

No mocks are needed here: every probe targets a real service, and check logic
is REUSED from ``scripts/check_services.py`` (the single source of truth also
powering the UI's System Status panel) rather than re-implemented.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
import requests

from app.config.settings import PROJECT_ROOT, get_settings
from app.vectorstore import qdrant_manager

# scripts/ is not a package; tests/conftest.py puts the project root on sys.path.
from scripts.check_services import (  # noqa: E402
    _check_embed_model,
    _check_local_llm,
    _check_local_ollama,
    _check_ollama_cloud,
)


def _local_services_up() -> bool:
    """True when the free local services (Qdrant + Ollama daemon) respond."""
    settings = get_settings()
    try:
        requests.get(f"{settings.qdrant_url}/collections", timeout=3).raise_for_status()
        requests.get(f"{settings.local_base_url.rstrip('/')}/api/tags", timeout=3).raise_for_status()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _local_services_up(), reason="local services not running")


# --------------------------------------------------------------------- #
# §46: test_ollama_connection                                            #
# --------------------------------------------------------------------- #
def test_ollama_connection() -> None:
    """Local daemon + configured embedding model respond for real.

    The selected provider's LLM leg is also checked: locally via /api/tags
    (free) when OLLAMA_PROVIDER=local, or via the cloud chat endpoint when
    provider=cloud — the cloud leg SKIPS on failure so the suite never
    requires the paid service.
    """
    settings = get_settings()

    ok, detail = _check_local_ollama(settings.local_base_url)
    assert ok, detail

    ok, detail = _check_embed_model(settings.local_base_url, settings.embed_model)
    assert ok, detail

    if settings.is_cloud_provider:
        ok, detail = _check_ollama_cloud(settings.cloud_base_url, settings.api_key, settings.llm_model)
        if not ok:
            pytest.skip(f"Ollama Cloud unavailable in this environment: {detail}")
    else:
        ok, detail = _check_local_llm(settings.local_base_url, settings.llm_model)
        assert ok, detail


# --------------------------------------------------------------------- #
# §46: test_qdrant_connection                                            #
# --------------------------------------------------------------------- #
def test_qdrant_connection() -> None:
    """Real health check against the running Qdrant instance."""
    health = qdrant_manager.health_check()
    assert health["ok"] is True, health
    assert "collections" in health


# --------------------------------------------------------------------- #
# §46: test_cognee_initialization                                        #
# --------------------------------------------------------------------- #
def test_cognee_initialization() -> None:
    """configure() + Cognee's vector engine resolve to the Qdrant adapter.

    The resolved engine class IS the initialization proof: the community
    Qdrant adapter only becomes resolvable after
    ``cognee_community_vector_adapter_qdrant.register`` ran inside
    ``configure()``. Storage redirection into the project's ``data/`` tree is
    asserted too — the site-packages default is the failure mode this app
    must never hit (Phase 9/11 gotcha).
    """
    from app.knowledge.cognee_manager import configure

    # MUST precede any cognee import in the process (Phase 9 gotcha).
    configure()

    import cognee  # noqa: F401 — only importable meaningfully after configure()

    from cognee.infrastructure.databases.vector import get_vector_engine_async

    engine = asyncio.run(get_vector_engine_async())
    # The lazy handle resolves the real adapter through __class__.
    assert engine.__class__.__name__ == "QDrantAdapter", engine.__class__
    assert engine.__class__.__module__.startswith("cognee_community_vector_adapter_qdrant")

    # Storage redirected into the project tree, not site-packages.
    system_root = Path(os.environ["SYSTEM_ROOT_DIRECTORY"])
    assert system_root.is_absolute()
    assert PROJECT_ROOT in system_root.parents, f"{system_root} outside {PROJECT_ROOT}"