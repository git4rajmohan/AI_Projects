"""Wiki router — file tree, page content, search, backlinks, link resolution."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.config import load_config
from backend.services import wiki_manager

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


def _get_project(project_id: str | None = None):
    cfg = load_config()
    pid = project_id or cfg.active_project_id
    if not pid:
        raise HTTPException(400, "No active project")
    project = next((p for p in cfg.projects if p.id == pid), None)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("/tree")
def get_tree(project_id: str | None = None):
    project = _get_project(project_id)
    return wiki_manager.get_file_tree(project.root_path)


@router.get("/page")
def get_page(path: str, project_id: str | None = None):
    project = _get_project(project_id)
    page = wiki_manager.read_page(project.root_path, path)
    if not page:
        raise HTTPException(404, "Page not found")
    return page


@router.get("/search")
def search(q: str, project_id: str | None = None):
    if not q or len(q) < 2:
        raise HTTPException(400, "Query too short")
    project = _get_project(project_id)
    return wiki_manager.search_pages(project.root_path, q)


@router.get("/backlinks")
def backlinks(path: str, project_id: str | None = None):
    project = _get_project(project_id)
    links = wiki_manager.get_backlinks(project.root_path, path)
    return {"backlinks": [{"path": p} for p in links]}


@router.get("/resolve")
def resolve(slug: str, project_id: str | None = None):
    project = _get_project(project_id)
    resolved = wiki_manager.resolve_wikilink(project.root_path, slug)
    if not resolved:
        raise HTTPException(404, f"No page found for slug: {slug}")
    return {"path": resolved}


@router.get("/graph")
def get_graph(project_id: str | None = None):
    """Return nodes and edges for the wiki link graph."""
    import re
    from pathlib import Path

    project = _get_project(project_id)
    wiki = wiki_manager._effective_root(project.root_path) / "wiki"
    if not wiki.exists():
        return {"nodes": [], "edges": []}

    nodes = []
    edges = []
    seen_nodes: set[str] = set()

    for md_file in sorted(wiki.rglob("*.md")):
        rel = md_file.relative_to(wiki).as_posix()
        if rel not in seen_nodes:
            seen_nodes.add(rel)
            # Determine group by folder
            parts = rel.split("/")
            group = parts[0] if len(parts) > 1 else "root"
            nodes.append({"id": rel, "label": md_file.stem, "group": group})

        text = md_file.read_text(encoding="utf-8")
        links = re.findall(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]", text)
        for slug in links:
            slug = slug.strip()
            target = wiki_manager.resolve_wikilink(project.root_path, slug)
            if target and target != rel:
                edges.append({"source": rel, "target": target})

    return {"nodes": nodes, "edges": edges}
