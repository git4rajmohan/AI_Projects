"""
main.py — FastAPI backend for the Knowledge Graph UI app.

Endpoints:
  GET  /              → serve the frontend HTML
  GET  /api/files     → list available CSV files in input_files/
  POST /api/propose   → LLM proposes a construction plan from selected files + goals
  POST /api/build     → execute the construction plan (build domain graph)
  GET  /api/stats     → current graph statistics
  GET  /api/graph     → graph data for visualization (nodes + edges)
  POST /api/query     → natural-language question → Cypher → answer

Run:
  venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --port 8080
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional
from neo4j import GraphDatabase

# Make the app folder importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_builder import (
    list_input_files,
    propose_schema,
    build_domain_graph,
    get_graph_stats,
    get_graph_data,
    INPUT_DIR,
)
from query_engine import answer_question
from agents import (
    run_schema_proposal,
    run_query_agent,
    AGENT_METADATA,
)

app = FastAPI(title="Knowledge Graph UI", version="1.0.0")

# Serve static files (frontend)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Pydantic request models ───────────────────────────────────────────
class ProposeRequest(BaseModel):
    selected_files: list[str]
    goals: str

class BuildRequest(BaseModel):
    plan: dict
    database: Optional[str] = None

class QueryRequest(BaseModel):
    question: str
    database: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────
@app.get("/")
async def index():
    """Serve the main HTML page."""
    return FileResponse(str(static_dir / "index.html"))


@app.get("/api/files")
async def api_list_files(folder: str = None):
    """List all CSV/MD files in the given folder (or default input_files)."""
    try:
        if folder:
            folder_path = Path(folder)
            if not folder_path.exists():
                raise HTTPException(status_code=400, detail=f"Folder not found: {folder}")
        else:
            folder_path = None
        files = list_input_files(folder_path)
        return {"files": files, "folder": str(folder_path or INPUT_DIR)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/browse")
async def api_browse(path: str = None):
    """Browse the local filesystem — list subdirectories and files."""
    try:
        if not path:
            # Default to the input_files folder
            path = str(Path(__file__).resolve().parent.parent / "input_files")
        target = Path(path).resolve()
        if not target.exists():
            return {"path": str(target), "dirs": [], "files": [], "error": "Path not found"}
        dirs = []
        files = []
        for item in sorted(target.iterdir()):
            if item.is_dir() and not item.name.startswith('.'):
                dirs.append({"name": item.name, "path": str(item)})
            elif item.is_file() and item.suffix.lower() in ('.csv', '.md', '.json'):
                files.append({"name": item.name, "path": str(item), "size": item.stat().st_size})
        parent = str(target.parent) if target.parent != target else None
        return {"path": str(target), "parent": parent, "dirs": dirs, "files": files}
    except Exception as e:
        return {"path": path, "dirs": [], "files": [], "error": str(e)}


@app.post("/api/propose")
async def api_propose_schema(req: ProposeRequest):
    """Ask the ADK schema refinement loop to propose a construction plan from selected files + goals."""
    try:
        plan = await run_schema_proposal(req.selected_files, req.goals)
        return {"plan": plan, "agents": AGENT_METADATA["schema_proposal_pipeline"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/propose/stream")
async def api_propose_schema_stream(req: ProposeRequest):
    """SSE streaming version of /api/propose — sends live progress events as the ADK
    LoopAgent runs (proposal → critic → check → ...), then the final plan as the last event.

    Event format: ``data: {"type": "progress", "message": "..."}\\n\\n``
    Final event:   ``data: {"type": "result", "plan": {...}, "agents": {...}}\\n\\n``
    Error event:   ``data: {"type": "error", "message": "..."}\\n\\n``
    """
    import queue
    import threading

    msg_q: asyncio.Queue = asyncio.Queue()

    async def progress_cb(msg: str):
        await msg_q.put({"type": "progress", "message": msg})

    async def run_agent():
        try:
            plan = await run_schema_proposal(
                req.selected_files, req.goals, progress_callback=progress_cb
            )
            await msg_q.put({
                "type": "result",
                "plan": plan,
                "agents": AGENT_METADATA["schema_proposal_pipeline"],
            })
        except Exception as e:
            await msg_q.put({"type": "error", "message": str(e)})

    async def event_stream():
        task = asyncio.create_task(run_agent())
        while True:
            try:
                msg = await asyncio.wait_for(msg_q.get(), timeout=0.5)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("type") in ("result", "error"):
                    break
            except asyncio.TimeoutError:
                # Send a heartbeat to keep the connection alive
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        await task  # Ensure the agent task completes

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/build")
async def api_build_graph(req: BuildRequest):
    """Execute the construction plan and build the domain graph in Neo4j."""
    progress_messages = []
    def progress_cb(msg):
        progress_messages.append(msg)

    try:
        # Log the incoming plan for debugging
        plan_keys = [k for k in req.plan.keys() if not k.startswith("_")]
        progress_messages.append(f"Plan received with {len(plan_keys)} rules: {plan_keys}")
        for k, v in req.plan.items():
            if not k.startswith("_") and isinstance(v, dict):
                progress_messages.append(f"  {k}: type={v.get('construction_type', '?')}, file={v.get('source_file', '?')}")

        # Auto-create the database if it doesn't exist
        db_name = req.database
        if db_name and db_name != "neo4j":
            _ensure_database_exists(db_name, progress_messages)

        summary = build_domain_graph(req.plan, database=db_name, progress_callback=progress_cb)
        return {"summary": summary, "progress": progress_messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _ensure_database_exists(db_name: str, progress_messages=None):
    """Create a Neo4j database if it doesn't already exist."""
    from neo4j import GraphDatabase
    import os
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USERNAME", "neo4j"),
              os.getenv("NEO4J_PASSWORD", "password123"))
    )
    try:
        with driver.session(database="system") as session:
            result = session.run("SHOW DATABASES YIELD name WHERE name = $name RETURN name", name=db_name)
            exists = result.single() is not None
            if not exists:
                session.run(f"CREATE DATABASE `{db_name}` IF NOT EXISTS")
                # Wait for it to come online
                import time
                for _ in range(10):
                    time.sleep(0.5)
                    result = session.run(
                        "SHOW DATABASES YIELD name, currentStatus WHERE name = $name RETURN currentStatus",
                        name=db_name
                    )
                    record = result.single()
                    if record and record["currentStatus"] == "online":
                        break
                if progress_messages is not None:
                    progress_messages.append(f"Created new database: {db_name}")
            else:
                if progress_messages is not None:
                    progress_messages.append(f"Using existing database: {db_name}")
    finally:
        driver.close()


@app.get("/api/databases")
async def api_list_databases():
    """List all Neo4j databases (excluding system ones)."""
    from neo4j import GraphDatabase
    try:
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USERNAME", "neo4j"),
                  os.getenv("NEO4J_PASSWORD", "password123"))
        )
        databases = []
        try:
            with driver.session(database="system") as session:
                result = session.run(
                    "SHOW DATABASES YIELD name, currentStatus "
                    "WHERE NOT name IN ['system', 'neo4j'] "
                    "RETURN name, currentStatus ORDER BY name"
                )
                for record in result:
                    databases.append({
                        "name": record["name"],
                        "status": record["currentStatus"],
                    })
        finally:
            driver.close()
        return {"databases": databases}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def api_graph_stats(database: Optional[str] = None):
    """Return current graph statistics."""
    try:
        stats = get_graph_stats(database=database)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/graph")
async def api_graph_data(limit: int = 200, database: Optional[str] = None):
    """Return graph data (nodes + edges) for visualization."""
    try:
        data = get_graph_data(limit=limit, database=database)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/query")
async def api_query(req: QueryRequest):
    """Answer a natural-language question using the ADK query agent."""
    try:
        result = await run_query_agent(req.question, database=req.database)
        result["agent"] = AGENT_METADATA["query_pipeline"]
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agents")
async def api_agent_info():
    """Return metadata about all ADK agents used in this app."""
    return AGENT_METADATA


@app.get("/api/health")
async def api_health():
    """Health check."""
    return {"status": "ok"}


@app.get("/api/databases")
async def api_list_databases():
    """List all available Neo4j databases."""
    try:
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USERNAME", "neo4j"),
                  os.getenv("NEO4J_PASSWORD", "password123"))
        )
        with driver.session(database="system") as session:
            result = session.run("SHOW DATABASES YIELD name, currentStatus WHERE currentStatus = 'online' RETURN name")
            databases = [r["name"] for r in result]
        driver.close()
        # Filter out 'system' — it's not for user data
        databases = [db for db in databases if db != "system"]
        return {"databases": databases}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)