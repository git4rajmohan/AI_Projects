"""
graph_builder.py — Analyzes CSV files, proposes a schema via LLM,
and constructs the knowledge graph in Neo4j.

Workflow:
  1. User selects CSV files + describes goals
  2. LLM proposes a construction plan (node + relationship rules)
  3. Domain graph is built from CSVs via Cypher LOAD CSV
  4. (Optional) Unstructured files processed via SimpleKGPipeline
"""

import os
import re
import json
import csv
import asyncio
from pathlib import Path
from typing import Any, Optional
from dotenv import load_dotenv, find_dotenv

from neo4j import GraphDatabase
from openai import OpenAI
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────
load_dotenv(find_dotenv(), override=True)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "password123")
NEO4J_DB = os.getenv("NEO4J_DATABASE", "neo4j")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "ollama-cloud-proxy")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "http://127.0.0.1:11435/v1")
LLM_MODEL = os.getenv("OLLAMA_MODEL", "openai/gpt-oss:120b")
if LLM_MODEL.startswith("openai/"):
    LLM_MODEL = LLM_MODEL[len("openai/"):]

INPUT_DIR = Path(os.getenv("INPUT_FILES_DIR", "input_files"))
if not INPUT_DIR.is_absolute():
    # resolve relative to this file's parent (the app root)
    INPUT_DIR = Path(__file__).resolve().parent.parent / INPUT_DIR


# ── Pydantic models for the construction plan ─────────────────────────
class NodeRule(BaseModel):
    construction_type: str = Field(default="node")
    source_file: str
    label: str
    unique_column_name: str
    properties: list[str] = Field(default_factory=list)

class RelationshipRule(BaseModel):
    construction_type: str = Field(default="relationship")
    source_file: str
    relationship_type: str
    from_node_label: str
    from_node_column: str
    to_node_label: str
    to_node_column: str
    properties: list[str] = Field(default_factory=list)

class ConstructionPlan(BaseModel):
    nodes: dict[str, NodeRule] = Field(default_factory=dict)
    relationships: dict[str, RelationshipRule] = Field(default_factory=dict)


# ── Helpers ───────────────────────────────────────────────────────────
def _get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

def _get_llm_client():
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)

def list_input_files(folder=None) -> list[dict]:
    """Return list of CSV/MD files in the given folder (or default INPUT_DIR) with metadata."""
    search_dir = folder if folder else INPUT_DIR
    files = []
    for f in sorted(search_dir.glob("*.csv")):
        # Read header + first 2 rows for preview
        try:
            with open(f, encoding="utf-8-sig") as fh:
                reader = csv.reader(fh)
                header = next(reader, [])
                sample = []
                for _ in range(2):
                    row = next(reader, None)
                    if row:
                        sample.append(row)
            files.append({
                "filename": f.name,
                "path": str(f),
                "columns": header,
                "row_count": sum(1 for _ in open(f, encoding="utf-8-sig")) - 1,
                "sample_rows": sample,
            })
        except Exception as e:
            files.append({"filename": f.name, "path": str(f), "error": str(e)})
    # Also list .md files if any
    for f in sorted(search_dir.glob("*.md")):
        files.append({
            "filename": f.name,
            "path": str(f),
            "type": "markdown",
            "size_bytes": f.stat().st_size,
        })
    return files


def _csv_to_string(filepath: str, max_rows: int = 5) -> str:
    """Read first N rows of a CSV as a string for the LLM prompt."""
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        lines = []
        for i, row in enumerate(reader):
            if i >= max_rows + 1:  # header + max_rows
                break
            lines.append(",".join(row))
    return "\n".join(lines)


# ── Schema Proposal via LLM ────────────────────────────────────────────
def propose_schema(selected_files: list[str], goals: str) -> dict:
    """
    Ask the LLM to propose a construction plan based on the selected CSV
    files and the user's goals.

    Args:
        selected_files: list of CSV filenames in input_files/
        goals: natural-language description of what the user wants

    Returns:
        dict with 'nodes' and 'relationships' rules
    """
    client = _get_llm_client()

    # Build context from the selected files
    file_contexts = []
    file_path_map = {}
    for fname in selected_files:
        fpath = Path(fname) if Path(fname).is_absolute() else INPUT_DIR / fname
        if fpath.exists() and fpath.suffix == ".csv":
            file_path_map[fpath.name] = str(fpath)
            preview = _csv_to_string(str(fpath), max_rows=5)
            file_contexts.append(f"### File: {fpath.name}\n```csv\n{preview}\n```")
        elif fpath.exists() and fpath.suffix == ".md":
            file_path_map[fpath.name] = str(fpath)
            file_contexts.append(f"### File: {fpath.name}\n(Markdown file, {fpath.stat().st_size} bytes)")

    files_text = "\n\n".join(file_contexts)

    system_prompt = """You are a knowledge graph architect. Given CSV files and a user's goals, 
propose a construction plan as JSON. The plan defines:
1. Node rules: which CSV files become which node labels, with their unique ID column and properties.
2. Relationship rules: which CSV files define relationships between nodes, with from/to labels and columns.

Return ONLY valid JSON (no markdown fences) with this structure:
{
  "nodes": {
    "LabelName": {
      "construction_type": "node",
      "source_file": "filename.csv",
      "label": "LabelName",
      "unique_column_name": "id_column",
      "properties": ["col1", "col2"]
    }
  },
  "relationships": {
    "REL_TYPE": {
      "construction_type": "relationship",
      "source_file": "filename.csv",
      "relationship_type": "REL_TYPE",
      "from_node_label": "LabelA",
      "from_node_column": "col_a",
      "to_node_label": "LabelB",
      "to_node_column": "col_b",
      "properties": ["prop1"]
    }
  }
}

Rules:
- Use the CSV column names exactly as they appear in the header.
- Every node must have a unique_column_name.
- Relationship from/to columns must exist in the source CSV.
- Label names should be singular CamelCase (e.g., Product, Supplier, Assembly).
- Relationship types should be UPPERCASE_WITH_UNDERSCORES (e.g., SUPPLIED_BY, CONTAINS).
"""

    user_prompt = f"""## User Goals
{goals}

## Selected Files
{files_text}

Propose the construction plan as JSON:"""

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        plan = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            plan = json.loads(match.group())
        else:
            raise ValueError(f"LLM did not return valid JSON:\n{raw[:500]}")

    # Attach file path mapping so build_domain_graph can locate files
    plan["_file_paths"] = file_path_map
    return plan


# ── Domain Graph Construction ─────────────────────────────────────────
def build_domain_graph(plan: dict, database: str = None, progress_callback=None) -> dict:
    """
    Execute the construction plan: create nodes and relationships from CSV
    files using Cypher LOAD CSV queries.

    Args:
        plan: dict with 'nodes' and 'relationships' rules
        database: Neo4j database name (None = default from env)
        progress_callback: optional callable(msg: str) for progress updates

    Returns:
        dict with summary counts
    """
    driver = _get_driver()
    db = database or NEO4J_DB
    summary = {"nodes_created": 0, "relationships_created": 0, "errors": []}

    # First: clean the database (optional — remove existing non-entity nodes)
    def _log(msg):
        if progress_callback:
            progress_callback(msg)

    # Copy CSV files into Neo4j import directory (via docker cp if needed)
    # For local Neo4j, files must be in the import folder.
    # We'll use file:/// prefix which reads from the Neo4j import directory.
    _log("Checking Neo4j connection...")
    with driver.session(database=db) as session:
        result = session.run("RETURN 1 AS test")
        _log("Neo4j connected.")

    # File path mapping (from propose_schema) to locate files outside INPUT_DIR
    file_paths = plan.get("_file_paths", {})

    # ── Separate nodes and relationships from the plan ────────────────
    # The plan from the agent is a flat dict where each key is a rule name
    # and each value has a "construction_type" of "node" or "relationship".
    # Some plans may also have nested "nodes"/"relationships" keys.
    node_rules = {}
    rel_rules = {}

    if "nodes" in plan and isinstance(plan["nodes"], dict):
        node_rules = plan["nodes"]
        rel_rules = plan.get("relationships", {})
    else:
        for key, rule in plan.items():
            if key.startswith("_"):
                continue
            if not isinstance(rule, dict):
                continue
            ctype = rule.get("construction_type", "node")
            if ctype == "relationship":
                rel_rules[key] = rule
            else:
                node_rules[key] = rule

    # ── Create nodes ──────────────────────────────────────────────────
    for rule_name, rule in node_rules.items():
        if isinstance(rule, dict):
            source_file = rule.get("source_file", "")
            label = rule.get("label", rule_name)
            unique_col = rule.get("unique_column_name", "")
            props = rule.get("properties", [])

            if not source_file or not label or not unique_col:
                _log(f"  Skipping {rule_name}: missing required fields")
                continue

            _log(f"  Creating {label} nodes from {source_file}...")

            # Build property mappings
            prop_assignments = ", ".join([f"{p}: row.{p}" for p in props])
            all_props = [unique_col] + [p for p in props if p != unique_col]

            # Copy the CSV to the Neo4j import dir (handle Docker container + subfolders)
            import_rel = _copy_csv_to_neo4j_import(file_paths.get(source_file, source_file))

            set_clause = ", ".join([f"n.{p} = row.{p}" for p in props])
            cypher = (
                f"LOAD CSV WITH HEADERS FROM 'file:///{import_rel}' AS row\n"
                f"MERGE (n:{label} {{{unique_col}: row.{unique_col}}})\n"
                f"SET {set_clause}"
            )

            try:
                with driver.session(database=db) as session:
                    result = session.run(cypher)
                    count = result.consume().counters.nodes_created
                    summary["nodes_created"] += count
                    _log(f"    ✓ Created {count} {label} nodes")
            except Exception as e:
                err = f"Error creating {label} nodes: {e}"
                summary["errors"].append(err)
                _log(f"    ✗ {err}")

    # ── Create relationships ──────────────────────────────────────────
    for rule_name, rule in rel_rules.items():
        if isinstance(rule, dict):
            source_file = rule.get("source_file", "")
            rel_type = rule.get("relationship_type", rule_name)
            from_label = rule.get("from_node_label", "")
            from_col = rule.get("from_node_column", "")
            to_label = rule.get("to_node_label", "")
            to_col = rule.get("to_node_column", "")
            props = rule.get("properties", [])

            if not all([source_file, rel_type, from_label, from_col, to_label, to_col]):
                _log(f"  Skipping relationship {rule_name}: missing required fields")
                continue

            _log(f"  Creating {rel_type} relationships from {source_file}...")

            import_rel = _copy_csv_to_neo4j_import(file_paths.get(source_file, source_file))

            # The node property to match on may differ from the CSV column name
            # If from_node_property/to_node_property aren't specified, look up
            # the unique_column_name from the node rules in the plan
            from_prop = rule.get("from_node_property")
            to_prop = rule.get("to_node_property")
            if not from_prop:
                for nr in node_rules.values():
                    if isinstance(nr, dict) and nr.get("label") == from_label:
                        from_prop = nr.get("unique_column_name", from_col)
                        break
                if not from_prop:
                    from_prop = from_col
            if not to_prop:
                for nr in node_rules.values():
                    if isinstance(nr, dict) and nr.get("label") == to_label:
                        to_prop = nr.get("unique_column_name", to_col)
                        break
                if not to_prop:
                    to_prop = to_col

            prop_set = ""
            if props:
                prop_set = " SET " + ", ".join([f"r.{p} = row.{p}" for p in props])

            cypher = (
                f"LOAD CSV WITH HEADERS FROM 'file:///{import_rel}' AS row\n"
                f"MATCH (from:{from_label} {{{from_prop}: row.{from_col}}})\n"
                f"MATCH (to:{to_label} {{{to_prop}: row.{to_col}}})\n"
                f"MERGE (from)-[r:{rel_type}]->(to){prop_set}"
            )

            try:
                with driver.session(database=db) as session:
                    result = session.run(cypher)
                    count = result.consume().counters.relationships_created
                    summary["relationships_created"] += count
                    _log(f"    ✓ Created {count} {rel_type} relationships")
            except Exception as e:
                err = f"Error creating {rel_type} relationships: {e}"
                summary["errors"].append(err)
                _log(f"    ✗ {err}")

    driver.close()
    _log(f"\nDone! Nodes: {summary['nodes_created']}, Relationships: {summary['relationships_created']}")
    return summary


def _copy_csv_to_neo4j_import(file_ref: str) -> str:
    """Copy a CSV to the Neo4j import directory, preserving project subfolder structure.
    file_ref can be a filename (relative to INPUT_DIR) or an absolute path.
    Tries docker cp if a neo4j container is running, otherwise copies
    to common local Neo4j import paths.

    Returns the relative path inside the import dir (e.g. 'project1_furniture/products.csv')
    so the caller can use it in LOAD CSV file:/// URL."""
    import shutil
    import subprocess

    file_path = Path(file_ref)
    if file_path.is_absolute():
        src = file_path
        # Try to compute the relative path from INPUT_DIR so we preserve the subfolder
        try:
            rel = file_path.relative_to(INPUT_DIR)
            import_rel = str(rel).replace("\\", "/")
        except ValueError:
            import_rel = file_path.name
    else:
        src = INPUT_DIR / file_ref
        import_rel = file_ref.replace("\\", "/")
    if not src.exists():
        return import_rel

    # Try to find a Neo4j Docker container and copy the file
    try:
        # Search by image name prefix (covers neo4j, neo4j:5-enterprise, etc.)
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=neo4j", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=5
        )
        containers = [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]
        if not containers:
            # Fallback: try ancestor filter
            result = subprocess.run(
                ["docker", "ps", "--filter", "ancestor=neo4j", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=5
            )
            containers = [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]
        for container in containers:
            if container:
                # Ensure parent subfolder exists in container
                parent_dir = "/".join(import_rel.split("/")[:-1])
                if parent_dir:
                    subprocess.run(
                        ["docker", "exec", container, "mkdir", "-p", f"/var/lib/neo4j/import/{parent_dir}"],
                        capture_output=True, timeout=5
                    )
                subprocess.run(
                    ["docker", "cp", str(src), f"{container}:/var/lib/neo4j/import/{import_rel}"],
                    capture_output=True, timeout=10
                )
                return import_rel
    except Exception:
        pass

    # Fallback: try common local Neo4j import paths
    local_paths = [
        Path.home() / ".neo4j" / "import",
        Path("C:/neo4j/import"),
        Path("/var/lib/neo4j/import"),
        Path(__file__).resolve().parent.parent.parent / "neo4j" / "import",
    ]
    for p in local_paths:
        if p.exists():
            dest = p / import_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dest))
            return import_rel
    return import_rel


# ── Graph statistics ──────────────────────────────────────────────────
def get_graph_stats(database: str = None) -> dict:
    """Return current graph statistics (node counts, relationship counts, patterns)."""
    driver = _get_driver()
    db = database or NEO4J_DB
    stats = {"nodes": {}, "relationships": {}, "patterns": []}

    try:
        with driver.session(database=db) as session:
            # Node counts
            result = session.run("MATCH (n) RETURN labels(n) AS labels, count(*) AS count")
            for r in result:
                labels = r["labels"]
                key = "+".join(sorted(labels))
                stats["nodes"][key] = r["count"]

            # Relationship counts
            result = session.run("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count")
            for r in result:
                stats["relationships"][r["type"]] = r["count"]

            # Relationship patterns (from_label, type, to_label, count)
            result = session.run("""
                MATCH (a)-[r]->(b)
                RETURN labels(a) AS from_labels, type(r) AS rel_type, labels(b) AS to_labels, count(*) AS count
            """)
            for r in result:
                from_labels = [l for l in r["from_labels"] if not l.startswith("__")]
                to_labels = [l for l in r["to_labels"] if not l.startswith("__")]
                if not from_labels or not to_labels:
                    continue
                stats["patterns"].append({
                    "from": "+".join(sorted(from_labels)),
                    "type": r["rel_type"],
                    "to": "+".join(sorted(to_labels)),
                    "count": r["count"],
                })
    except Exception as e:
        stats["error"] = str(e)
    finally:
        driver.close()

    return stats


def get_graph_data(limit: int = 50, database: str = None) -> dict:
    """Return nodes and relationships for graph visualization."""
    driver = _get_driver()
    db = database or NEO4J_DB
    nodes = []
    edges = []

    try:
        with driver.session(database=db) as session:
            # Get entity nodes — keep nodes with a "real" label (Feature, Issue,
            # Location, Product, etc.) even if they also carry __KGBuilder__/__Entity__.
            # Exclude purely internal nodes (Chunk, Document) which are scaffolding.
            result = session.run(f"""
                MATCH (n)
                WHERE any(l IN labels(n) WHERE NOT l STARTS WITH '__')
                  AND NOT any(l IN labels(n) WHERE l IN ['Chunk', 'Document'])
                WITH n LIMIT {limit}
                RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props
            """)
            for r in result:
                # Pick a display name from common properties
                props = r["props"]
                # Use the non-internal label as the display type
                real_labels = [l for l in r["labels"] if not l.startswith("__")]
                display_type = real_labels[0] if real_labels else "Node"
                name = (props.get("name") or props.get("product_name") or
                        props.get("label") or props.get("title") or
                        props.get("id") or
                        str(r["id"]))
                nodes.append({
                    "id": r["id"],
                    "label": name,
                    "type": display_type,
                    "labels": r["labels"],
                    "properties": {k: str(v)[:100] for k, v in props.items()},
                })

            # Get relationships between the fetched nodes (same filter — both
            # endpoints must have at least one non-internal label)
            if nodes:
                node_ids = [n["id"] for n in nodes]
                result = session.run("""
                    MATCH (a)-[r]->(b)
                    WHERE any(la IN labels(a) WHERE NOT la STARTS WITH '__' AND NOT la IN ['Chunk', 'Document'])
                      AND any(lb IN labels(b) WHERE NOT lb STARTS WITH '__' AND NOT lb IN ['Chunk', 'Document'])
                      AND id(a) IN $ids AND id(b) IN $ids
                    RETURN id(a) AS source, id(b) AS target, type(r) AS type
                    LIMIT 500
                """, ids=node_ids)
                for r in result:
                    edges.append({
                        "source": r["source"],
                        "target": r["target"],
                        "type": r["type"],
                    })
    except Exception as e:
        return {"error": str(e), "nodes": [], "edges": []}
    finally:
        driver.close()

    return {"nodes": nodes, "edges": edges}