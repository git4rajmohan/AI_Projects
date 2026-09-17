"""FastAPI application entry point.

AgentOS — Agentic AI Workflow Platform
Backend wraps Google ADK Runner + custom platform routes.
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv

# Load .env file into OS environment BEFORE any other imports.
# This ensures OPENAI_API_KEY and OPENAI_API_BASE are available to LiteLLM.
load_dotenv(override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    # Startup
    setup_logging(settings.log_level)
    import logging
    logger = logging.getLogger(__name__)
    logger.info("AgentOS starting up...")
    logger.info(f"Database: {settings.db_url}")
    logger.info(f"LLM Model: {settings.llm_model}")

    # Initialize database tables
    await init_db()
    logger.info("Database initialized")

    yield

    # Shutdown
    logger.info("AgentOS shutting down...")


app = FastAPI(
    title="AgentOS",
    description="Agentic AI Workflow Platform — converts natural-language intent into executable, evaluated, and reusable AI workflows.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Alternative
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health Check ---

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "AgentOS",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# --- API Routes ---

from app.api import routes_tasks, routes_plans, routes_skills, routes_agents, routes_tools, routes_execution, routes_approvals, routes_memory, routes_models, routes_files  # noqa: E402

app.include_router(routes_tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(routes_plans.router, prefix="/api/plans", tags=["plans"])
app.include_router(routes_skills.router, prefix="/api/skills", tags=["skills"])
app.include_router(routes_agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(routes_tools.router, prefix="/api/tools", tags=["tools"])
app.include_router(routes_execution.router, prefix="/api/executions", tags=["executions"])
app.include_router(routes_approvals.router, prefix="/api/approvals", tags=["approvals"])
app.include_router(routes_memory.router, prefix="/api/memory", tags=["memory"])
app.include_router(routes_models.router, prefix="/api/models", tags=["models"])
app.include_router(routes_files.router, prefix="/api/files", tags=["files"])