"""FastAPI application entry point."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.routers import (
    config_router,
    ingest_router,
    wiki_router,
    query_router,
    lint_router,
    utils_router,
)

app = FastAPI(title="LLMWikiUI", version="1.0.0")

# CORS — allow all origins so the app works when port is shared via tunnel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(config_router.router)
app.include_router(ingest_router.router)
app.include_router(wiki_router.router)
app.include_router(query_router.router)
app.include_router(lint_router.router)
app.include_router(utils_router.router)

# Serve React frontend static build (produced by: cd frontend && npm run build)
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Catch-all — serve React SPA index.html for all non-API routes."""
        index = FRONTEND_DIST / "index.html"
        return FileResponse(str(index))
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return {"message": "LLMWikiUI backend running. Build the frontend to serve the UI."}
