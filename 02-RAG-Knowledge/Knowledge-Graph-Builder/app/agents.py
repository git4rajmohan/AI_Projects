"""
agents.py — Google ADK agents for the Knowledge Graph UI app.

Replaces the direct LLM-calls in graph_builder.py and query_engine.py with
actual ADK LlmAgent + LoopAgent agents, following the same patterns as the
course lessons (03–05):

  ── Schema proposal pipeline (Tab 1→2) ──────────────────────────────────
  SchemaRefinementLoop (LoopAgent)
    ├─ schema_proposal_agent   (LlmAgent) — samples files, proposes nodes/rels
    ├─ schema_critic_agent     (LlmAgent) — critiques the proposal, writes feedback
    └─ CheckStatusAndEscalate (BaseAgent) — stops loop when critic says "valid"

  ── Query pipeline (Tab 4) ─────────────────────────────────────────────
  query_agent (LlmAgent) — translates question → Cypher → executes → answers
    Tools: get_schema_context, execute_cypher, generate_answer
"""

import os
import json
import re
import csv
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, AsyncGenerator
from itertools import islice

from dotenv import load_dotenv, find_dotenv

from google.adk.agents import LlmAgent, LoopAgent, BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import ToolContext
from google.adk.events import Event, EventActions
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types

from neo4j import GraphDatabase

# ── Config ────────────────────────────────────────────────────────────
load_dotenv(find_dotenv(), override=True)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "password123")
NEO4J_DB = os.getenv("NEO4J_DATABASE", "neo4j")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "ollama-cloud-proxy")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "http://127.0.0.1:11435/v1")
LLM_MODEL = os.getenv("OLLAMA_MODEL", "openai/gpt-oss:120b")

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
os.environ["OPENAI_API_BASE"] = OPENAI_API_BASE

# Input files directory (resolve relative to this file's parent)
INPUT_DIR = Path(os.getenv("INPUT_FILES_DIR", "input_files"))
if not INPUT_DIR.is_absolute():
    INPUT_DIR = Path(__file__).resolve().parent.parent / INPUT_DIR

# Neo4j import directory (for file:/// in LOAD CSV)
NEO4J_IMPORT_DIR = Path(os.getenv("NEO4J_IMPORT_DIR", ""))
if not NEO4J_IMPORT_DIR.is_absolute():
    _workspace_root = Path(find_dotenv()).resolve().parent
    NEO4J_IMPORT_DIR = _workspace_root / "neo4j" / "import"

# ── LLM ────────────────────────────────────────────────────────────────
llm = LiteLlm(model=LLM_MODEL)

# ── State keys ────────────────────────────────────────────────────────
PROPOSED_CONSTRUCTION_PLAN = "proposed_construction_plan"
APPROVED_CONSTRUCTION_PLAN = "approved_construction_plan"
APPROVED_USER_GOAL = "approved_user_goal"
APPROVED_FILES = "approved_files"


# ── Helper functions ──────────────────────────────────────────────────
def _get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))


def _tool_success(key: str, result: Any) -> Dict[str, Any]:
    return {"status": "success", key: result}


def _tool_error(message: str) -> Dict[str, Any]:
    return {"status": "error", "error_message": message}


def _csv_to_string(filepath: str, max_rows: int = 5) -> str:
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        lines = []
        for i, row in enumerate(reader):
            if i >= max_rows + 1:
                break
            lines.append(",".join(row))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
#  TOOLS for Schema Proposal Agent
# ══════════════════════════════════════════════════════════════════════

def get_approved_user_goal(tool_context: ToolContext) -> dict:
    """Returns the user's goal — a dictionary with kind_of_graph and description."""
    if APPROVED_USER_GOAL not in tool_context.state:
        return _tool_error("approved_user_goal not set.")
    return _tool_success("approved_user_goal", tool_context.state[APPROVED_USER_GOAL])


def get_approved_files(tool_context: ToolContext) -> dict:
    """Returns the list of approved files for import."""
    if APPROVED_FILES not in tool_context.state:
        return _tool_error("approved_files not set.")
    return _tool_success("approved_files", tool_context.state[APPROVED_FILES])


def sample_file(file_path: str, **kwargs) -> dict:
    """Reads up to 100 lines of a file as text for the agent to inspect.

    Args:
        file_path: path to the file (absolute, or relative to INPUT_DIR)
    """
    p = Path(file_path)
    if not p.is_absolute():
        p = INPUT_DIR / file_path
    if not p.exists():
        return _tool_error(f"File does not exist: {file_path}")
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            lines = list(islice(f, 100))
            content = "".join(lines)
            return _tool_success("content", content)
    except Exception as e:
        return _tool_error(f"Error reading {file_path}: {e}")


def search_file(file_path: str, query: str, **kwargs) -> dict:
    """Searches a file for lines containing the query string (case-insensitive grep).

    Args:
        file_path: path to the file (absolute, or relative to INPUT_DIR)
        query: the string to search for
    """
    p = Path(file_path)
    if not p.is_absolute():
        p = INPUT_DIR / file_path
    if not p.exists():
        return _tool_error(f"File does not exist: {file_path}")
    if not query:
        return _tool_success("search_results", {"matching_lines": [], "lines_found": 0})
    matching_lines = []
    search_query = query.lower()
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            for i, line in enumerate(f, 1):
                if search_query in line.lower():
                    matching_lines.append({"line_number": i, "content": line.strip()})
    except Exception as e:
        return _tool_error(f"Error searching {file_path}: {e}")
    return _tool_success("search_results", {
        "metadata": {"path": file_path, "query": query, "lines_found": len(matching_lines)},
        "matching_lines": matching_lines,
    })


def propose_node_construction(approved_file: str, proposed_label: str,
                              unique_column_name: str, proposed_properties: list[str],
                              tool_context: ToolContext) -> dict:
    """Propose a node construction rule. The file becomes nodes with this label.

    Args:
        approved_file: the source CSV file
        proposed_label: CamelCase label for the node (e.g., Product, Company)
        unique_column_name: the column that uniquely identifies nodes
        proposed_properties: column names to import as node properties
    """
    # Verify unique column exists in the file
    search_result = search_file(approved_file, unique_column_name)
    if search_result["status"] == "error":
        return search_result
    if search_result["search_results"]["metadata"]["lines_found"] == 0:
        return _tool_error(f"{approved_file} does not have column '{unique_column_name}'.")

    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    rule = {
        "construction_type": "node",
        "source_file": approved_file,
        "label": proposed_label,
        "unique_column_name": unique_column_name,
        "properties": proposed_properties,
    }
    plan[proposed_label] = rule
    tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
    return _tool_success("node_construction", rule)


def propose_relationship_construction(approved_file: str, proposed_relationship_type: str,
                                       from_node_label: str, from_node_column: str,
                                       to_node_label: str, to_node_column: str,
                                       proposed_properties: list[str],
                                       tool_context: ToolContext) -> dict:
    """Propose a relationship construction rule.

    Args:
        approved_file: the source CSV file
        proposed_relationship_type: UPPERCASE relationship type (e.g., PRODUCES, PURCHASED)
        from_node_label: label of the source node
        from_node_column: column identifying source nodes
        to_node_label: label of the target node
        to_node_column: column identifying target nodes
        proposed_properties: column names to import as relationship properties
    """
    # Verify from column
    sr = search_file(approved_file, from_node_column)
    if sr["status"] == "error" or sr["search_results"]["metadata"]["lines_found"] == 0:
        return _tool_error(f"{approved_file} does not have column '{from_node_column}'.")

    # Verify to column
    sr = search_file(approved_file, to_node_column)
    if sr["status"] == "error" or sr["search_results"]["metadata"]["lines_found"] == 0:
        return _tool_error(f"{approved_file} does not have column '{to_node_column}'.")

    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    rule = {
        "construction_type": "relationship",
        "source_file": approved_file,
        "relationship_type": proposed_relationship_type,
        "from_node_label": from_node_label,
        "from_node_column": from_node_column,
        "to_node_label": to_node_label,
        "to_node_column": to_node_column,
        "properties": proposed_properties,
    }
    plan[proposed_relationship_type] = rule
    tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
    return _tool_success("relationship_construction", rule)


def remove_node_construction(node_label: str, tool_context: ToolContext) -> dict:
    """Remove a previously proposed node construction from the plan."""
    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    if node_label in plan:
        del plan[node_label]
        tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
    return _tool_success("node_construction_removed", node_label)


def remove_relationship_construction(relationship_type: str, tool_context: ToolContext) -> dict:
    """Remove a previously proposed relationship construction from the plan."""
    plan = tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    if relationship_type in plan:
        plan.pop(relationship_type)
        tool_context.state[PROPOSED_CONSTRUCTION_PLAN] = plan
    return _tool_success("relationship_construction_removed", relationship_type)


def get_proposed_construction_plan(tool_context: ToolContext) -> dict:
    """Get the current proposed construction plan."""
    return tool_context.state.get(PROPOSED_CONSTRUCTION_PLAN, {})


# ══════════════════════════════════════════════════════════════════════
#  TOOLS for Query Agent
# ══════════════════════════════════════════════════════════════════════

def get_schema_context(database: Optional[str] = None) -> dict:
    """Query Neo4j for the current graph schema (labels, properties, relationship types).

    Args:
        database: Neo4j database name (optional, defaults to env)
    """
    driver = _get_driver()
    db = database or NEO4J_DB
    context_parts = []
    try:
        with driver.session(database=db) as session:
            result = session.run("""
                MATCH (n)
                WHERE NOT any(l IN labels(n) WHERE l STARTS WITH '__')
                UNWIND labels(n) AS label
                WITH label, collect(DISTINCT keys(n)) AS allKeys
                UNWIND allKeys AS keys
                UNWIND keys AS key
                WITH label, collect(DISTINCT key) AS props
                RETURN label, props ORDER BY label
            """)
            node_info = []
            for r in result:
                node_info.append(f"  (:{r['label']} {{{', '.join(r['props'])}}})")

            result = session.run("""
                MATCH (a)-[r]->(b)
                WHERE NOT any(l IN labels(a) WHERE l STARTS WITH '__')
                  AND NOT any(l IN labels(b) WHERE l STARTS WITH '__')
                RETURN DISTINCT labels(a)[0] AS from_label, type(r) AS rel_type,
                       labels(b)[0] AS to_label
                ORDER BY from_label, rel_type
            """)
            rel_info = []
            for r in result:
                rel_info.append(f"  (:{r['from_label']})-[:{r['rel_type']}]->(:{r['to_label']})")

            if node_info:
                context_parts.append("Node labels and properties:")
                context_parts.extend(node_info)
            if rel_info:
                context_parts.append("\nRelationship types:")
                context_parts.extend(rel_info)
    except Exception as e:
        context_parts.append(f"Could not retrieve schema: {e}")
    finally:
        driver.close()

    return _tool_success("schema", "\n".join(context_parts) if context_parts else "No schema available.")


def execute_cypher(cypher_query: str, database: Optional[str] = None) -> dict:
    """Execute a Cypher query against Neo4j and return results.

    Args:
        cypher_query: the Cypher query to execute
        database: Neo4j database name (optional)
    """
    driver = _get_driver()
    db = database or NEO4J_DB
    raw_results = []
    try:
        with driver.session(database=db) as session:
            result = session.run(cypher_query)
            for r in result:
                raw_results.append({k: str(v)[:200] for k, v in r.items()})
        return _tool_success("results", raw_results)
    except Exception as e:
        return _tool_error(f"Cypher execution error: {e}")
    finally:
        driver.close()


# ══════════════════════════════════════════════════════════════════════
#  Agent Instructions
# ══════════════════════════════════════════════════════════════════════

# ── Schema Proposal Agent ─────────────────────────────────────────────
PROPOSAL_AGENT_INSTRUCTION = """
You are an expert at knowledge graph modeling with property graphs. Propose an appropriate
schema by specifying construction rules which transform approved files into nodes or relationships.
The resulting schema should describe a knowledge graph based on the user goal.

Consider feedback if it is available:
<feedback>
{feedback}
</feedback>

Every file in the approved files list will become either a node or a relationship.
Determining whether a file likely represents a node or a relationship is based on a hint
from the filename and the identifiers found within the file.

General guidance for identifying a node or a relationship:
- If the file name is singular and has only 1 unique identifier it is likely a node
- If the file name is a combination of two things, it is likely a full relationship
- If the file name sounds like a node, but there are multiple unique identifiers, that
  is likely a node with reference relationships

Design rules for nodes:
- Nodes have unique identifiers
- Nodes may have identifiers used as reference relationships

Design rules for relationships:
- Full relationships appear in dedicated relationship files referencing two entities
- Reference relationships appear as foreign key references in node files

Process:
- get the user goal using the 'get_approved_user_goal' tool
- get the list of approved files using the 'get_approved_files' tool
- get the current construction plan using the 'get_proposed_construction_plan' tool

Think carefully, using tools to perform actions:
1. For EACH approved file (process ALL files, do not skip any), consider whether it represents a node or relationship.
   Check the content using the 'sample_file' tool.
   IMPORTANT: You MUST process every single file in the approved files list. Count the files
   and make sure you have created a construction rule for each one before finishing.
2. For each identifier, verify that it is unique by using the 'search_file' tool.
3. For a node file, propose a node construction using the 'propose_node_construction' tool.
4. If the node contains a reference relationship (foreign key to another entity), use 'propose_relationship_construction'.
5. For a relationship file (a file that connects two entities, like purchases or partnerships),
   use 'propose_relationship_construction'. This is critical — relationship files MUST become
   relationship construction rules, not node rules.
6. If you need to remove a construction, use 'remove_node_construction' or 'remove_relationship_construction'.
7. Before finishing, call 'get_proposed_construction_plan' and verify that EVERY approved file
   has a corresponding construction rule. If any file is missing, add it now.
8. When done, use 'get_proposed_construction_plan' to present the plan.
"""

# ── Schema Critic Agent ───────────────────────────────────────────────
CRITIC_AGENT_INSTRUCTION = """
You are an expert at knowledge graph modeling with property graphs.
Criticize the proposed schema for relevance to the user goal and approved files.

Criticize the proposed schema for relevance and correctness:
- Are unique identifiers actually unique? Use the 'search_file' tool to validate.
- Could any nodes be relationships instead? Double-check using 'search_file'.
- Can you manually trace through the source data to find information for a hypothetical question?
- Is every node in the schema connected? What relationships could be missing?
- Are hierarchical container relationships missing?
- Are any relationships redundant?
- CRITICAL: Are ALL approved files represented in the construction plan? Count the approved
  files and count the construction rules. If any file is missing, flag it as a problem.
- CRITICAL: Files with names like 'purchases', 'partnerships', 'orders', 'transactions' etc.
  are relationship files. If they appear as nodes instead of relationships, flag this as a problem.

Process:
- get the user goal using 'get_approved_user_goal'
- get the approved files using 'get_approved_files'
- get the construction plan using 'get_proposed_construction_plan'
- use 'sample_file' and 'search_file' to validate

1. Analyze each construction rule in the proposed construction plan.
2. Use tools to validate the construction rules.
3. Verify that EVERY approved file has a construction rule in the plan.
4. If the schema looks good, respond with one word: 'valid'.
5. If the schema has problems, respond with 'retry' and provide a concise bullet list of problems.
"""

# ── Query Agent ──────────────────────────────────────────────────────
QUERY_AGENT_INSTRUCTION = """
You are a knowledge graph query expert. Your job is to answer the user's natural-language
question about a knowledge graph stored in Neo4j.

Process:
1. Use the 'get_schema_context' tool to retrieve the current graph schema (labels, properties, relationships).
   If a specific database is mentioned, pass it as the 'database' parameter.
2. Based on the schema and the user's question, write a Cypher query that answers the question.
   Rules for Cypher:
   - Use MATCH patterns consistent with the schema.
   - Exclude internal labels starting with '__'.
   - Always add LIMIT 25.
   - Use coalesce() for properties that may use 'name' or 'product_name'.
3. Use the 'execute_cypher' tool to run the query against Neo4j.
   If a specific database was mentioned, pass it as the 'database' parameter.
4. Based on the query results, provide a clear, concise answer in natural language.
   If results are empty, say so. If there's useful data, summarize it nicely.

The user's message will contain their question, and optionally a database name in the format
"database: <dbname>" at the start.
"""


# ══════════════════════════════════════════════════════════════════════
#  Agent Definitions
# ══════════════════════════════════════════════════════════════════════

def _log_agent(callback_context: CallbackContext) -> None:
    """Callback that logs when an agent starts."""
    print(f"\n### Entering Agent: {callback_context.agent_name}")


# Schema Proposal Agent
schema_proposal_agent = LlmAgent(
    name="schema_proposal_agent",
    description="Proposes a knowledge graph schema based on the user goal and approved file list",
    model=llm,
    instruction=PROPOSAL_AGENT_INSTRUCTION,
    tools=[
        get_approved_user_goal, get_approved_files,
        get_proposed_construction_plan,
        sample_file, search_file,
        propose_node_construction, propose_relationship_construction,
        remove_node_construction, remove_relationship_construction,
    ],
    before_agent_callback=_log_agent,
)

# Schema Critic Agent (output_key="feedback" → writes to session state)
schema_critic_agent = LlmAgent(
    name="schema_critic_agent",
    description="Criticizes the proposed schema for relevance to the user goal and approved files.",
    model=llm,
    instruction=CRITIC_AGENT_INSTRUCTION,
    tools=[
        get_approved_user_goal, get_approved_files,
        get_proposed_construction_plan,
        sample_file, search_file,
    ],
    output_key="feedback",
    before_agent_callback=_log_agent,
)


# CheckStatusAndEscalate — non-LLM control flow agent
class CheckStatusAndEscalate(BaseAgent):
    """Stops the refinement loop when the critic says 'valid'."""
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        feedback = ctx.session.state.get("feedback", "valid")
        should_stop = "valid" in feedback.lower()
        yield Event(author=self.name, actions=EventActions(escalate=should_stop))


# Schema Refinement Loop (proposal → critic → check, up to 3 iterations)
schema_refinement_loop = LoopAgent(
    name="schema_refinement_loop",
    description="Analyzes approved files to propose a schema based on user intent and feedback",
    max_iterations=3,
    sub_agents=[
        schema_proposal_agent,
        schema_critic_agent,
        CheckStatusAndEscalate(name="StopChecker"),
    ],
    before_agent_callback=_log_agent,
)

# Query Agent
query_agent = LlmAgent(
    name="query_agent",
    description="Answers natural-language questions by generating Cypher, executing it, and summarizing results",
    model=llm,
    instruction=QUERY_AGENT_INSTRUCTION,
    tools=[get_schema_context, execute_cypher],
    before_agent_callback=_log_agent,
)


# ══════════════════════════════════════════════════════════════════════
#  Auto-detect missing rules (fallback when LLM skips files)
# ══════════════════════════════════════════════════════════════════════

def _auto_detect_rule(file_path: str, existing_plan: dict) -> dict:
    """Auto-detect whether a file should be a node or relationship based on its CSV headers.
    Uses heuristics to infer the construction rule when the LLM missed it."""
    import csv as _csv

    p = Path(file_path)
    if not p.exists():
        return None

    try:
        with open(p, encoding="utf-8-sig") as f:
            reader = _csv.reader(f)
            headers = next(reader)
            first_row = next(reader, [])
    except Exception:
        return None

    # Build a map of existing node labels → unique_column_name
    node_labels = {}
    for v in existing_plan.values():
        if isinstance(v, dict) and v.get("construction_type") == "node":
            node_labels[v.get("label", "")] = v.get("unique_column_name", "")

    # Heuristic: if the file has two columns that match existing node unique columns,
    # it's a relationship file
    matching_cols = []
    for col in headers:
        for label, uniq_col in node_labels.items():
            if col == uniq_col or col.endswith(f"_{uniq_col}") or col == f"{label.lower()}_id":
                matching_cols.append((col, label, uniq_col))

    fname_lower = p.stem.lower()
    rel_keywords = ["purchase", "partnership", "order", "transaction", "mapping", "link",
                    "relation", "connection", "association", "assignment"]

    if len(matching_cols) >= 2 or any(kw in fname_lower for kw in rel_keywords):
        # It's a relationship
        if len(matching_cols) >= 2:
            from_col, from_label, from_uniq = matching_cols[0]
            to_col, to_label, to_uniq = matching_cols[1]
        else:
            # Try to infer from column names
            from_col = headers[1] if len(headers) > 1 else headers[0]
            to_col = headers[2] if len(headers) > 2 else headers[1]
            from_label = _guess_label(from_col)
            to_label = _guess_label(to_col)
            from_uniq = from_col
            to_uniq = to_col

        # Clean up relationship type
        rel_type = fname_lower.replace("tech_", "").replace("project2_", "").upper()
        # Better relationship type names
        rel_name_map = {"PURCHASES": "PURCHASED", "PARTNERSHIPS": "PARTNERS_WITH"}
        rel_type = rel_name_map.get(rel_type, rel_type)

        # Properties = all columns except ID-like columns
        id_cols = {from_col, to_col}
        props = [h for h in headers if h not in id_cols and not h.endswith("_id")]

        return {
            "construction_type": "relationship",
            "source_file": file_path,
            "relationship_type": rel_type,
            "from_node_label": from_label,
            "from_node_column": from_col,
            "from_node_property": from_uniq,
            "to_node_label": to_label,
            "to_node_column": to_col,
            "to_node_property": to_uniq,
            "properties": props,
        }
    else:
        # It's a node — find a unique column
        unique_col = headers[0] if headers else ""
        for h in headers:
            if h.endswith("_id") or h in ("id", "ID"):
                unique_col = h
                break
        label = _guess_label(p.stem.replace("tech_", "").capitalize())
        props = [h for h in headers if h != unique_col]

        return {
            "construction_type": "node",
            "source_file": file_path,
            "label": label,
            "unique_column_name": unique_col,
            "properties": props,
        }


def _guess_label(col_or_name: str) -> str:
    """Guess a CamelCase label from a column name or filename."""
    # Remove common suffixes/prefixes
    name = col_or_name.replace("_id", "").replace("tech_", "").replace("project2_", "")
    # CamelCase
    parts = name.split("_")
    return "".join(p.capitalize() for p in parts if p)


def _auto_detect_reference_relationships(plan: dict, _log=None, file_paths: dict = None) -> None:
    """Scan node rules for foreign key columns that reference other node labels.
    If a column matches another node's unique_column_name but no relationship rule
    exists for it, auto-create a reference relationship rule."""
    import csv as _csv
    file_paths = file_paths or {}

    # Build node label → unique_column_name mapping
    node_rules = {}
    for k, v in plan.items():
        if isinstance(v, dict) and v.get("construction_type") == "node":
            node_rules[v.get("label", k)] = v

    # Collect existing relationship source_file+columns to avoid duplicates
    existing_rels = set()
    existing_rel_patterns = set()  # (filename, from_label, to_label) to avoid dup patterns
    for v in plan.values():
        if isinstance(v, dict) and v.get("construction_type") == "relationship":
            existing_rels.add((
                Path(v.get("source_file", "")).name,
                v.get("from_node_column", ""),
                v.get("to_node_column", ""),
            ))
            existing_rel_patterns.add((
                Path(v.get("source_file", "")).name,
                v.get("from_node_label", ""),
                v.get("to_node_label", ""),
            ))

    # For each node rule, check if any of its properties OR CSV columns match another node's unique column
    for node_name, node_rule in node_rules.items():
        source_file = node_rule.get("source_file", "")
        label = node_rule.get("label", node_name)
        props = node_rule.get("properties", [])
        unique_col = node_rule.get("unique_column_name", "")

        # Also scan the actual CSV headers for foreign key columns
        all_cols = list(props)
        try:
            sf_path = Path(source_file)
            if not sf_path.is_absolute():
                # Try to find the file
                for f in file_paths.values():
                    if Path(f).name == sf_path.name:
                        sf_path = Path(f)
                        break
            if sf_path.exists():
                with open(sf_path, encoding="utf-8-sig") as f:
                    reader = _csv.reader(f)
                    csv_headers = next(reader, [])
                    all_cols = list(set(all_cols + csv_headers))
        except Exception:
            pass

        for prop in all_cols:
            if prop == unique_col:
                continue  # Skip the node's own unique column
            for other_label, other_rule in node_rules.items():
                if other_label == label:
                    continue
                other_unique = other_rule.get("unique_column_name", "")
                if not other_unique:
                    continue

                # Check if this property is a foreign key to the other node
                is_fk = (
                    prop == other_unique or
                    prop == f"{other_label.lower()}_id" or
                    prop == f"{other_label.lower()}_{other_unique}" or
                    (other_unique.endswith("_id") and prop == other_unique)
                )

                if not is_fk:
                    continue

                # Check if a relationship rule already exists for this
                fname = Path(source_file).name
                rel_key = (fname, unique_col, prop)
                pattern_key = (fname, other_label, label)
                if rel_key in existing_rels or pattern_key in existing_rel_patterns:
                    continue

                # Create the reference relationship rule
                rel_type = f"{label.upper()}_TO_{other_label.upper()}"
                # Better names for common patterns (match on singular form)
                label_singular = label.rstrip("s")
                other_singular = other_label.rstrip("s")
                if other_singular == "Company" and label_singular == "Product":
                    rel_type = "PRODUCES"
                elif other_singular == "Company":
                    rel_type = "BELONGS_TO"
                elif other_singular == "Product":
                    rel_type = "HAS_PRODUCT"
                elif other_singular == "Customer":
                    rel_type = "HAS_CUSTOMER"

                rel_rule = {
                    "construction_type": "relationship",
                    "source_file": source_file,
                    "relationship_type": rel_type,
                    "from_node_label": other_label,
                    "from_node_column": prop,
                    "from_node_property": other_unique,
                    "to_node_label": label,
                    "to_node_column": unique_col,
                    "to_node_property": unique_col,
                    "properties": [],
                }

                plan[rel_type] = rel_rule
                existing_rels.add(rel_key)
                if _log:
                    _log(f"   → Auto-added reference: {rel_type} ({other_label}→{label}) from {fname}.{prop}")


# ══════════════════════════════════════════════════════════════════════
#  Agent Runner — convenience functions for the FastAPI backend
# ══════════════════════════════════════════════════════════════════════

async def run_schema_proposal(
    selected_files: list[str],
    goals: str,
    progress_callback=None,
) -> dict:
    """Run the schema refinement loop to propose a construction plan.

    Args:
        selected_files: list of file paths
        goals: user's natural-language goal description
        progress_callback: optional callable(msg: str) for progress updates

    Returns:
        dict: the proposed construction plan (nodes + relationships)
    """
    def _log(msg):
        if progress_callback:
            result = progress_callback(msg)
            if asyncio.iscoroutine(result):
                # We're inside an async function — schedule the coroutine
                loop = asyncio.get_event_loop()
                asyncio.ensure_future(result)
        print(msg)

    _log("🤖 Starting Schema Proposal Agent...")
    _log(f"   Files: {selected_files}")
    _log(f"   Goals: {goals}")

    session_service = InMemorySessionService()
    app_name = "schema_refinement_app"
    user_id = "kg_user"
    session_id = "schema_session_01"

    await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        state={
            "feedback": "",
            APPROVED_USER_GOAL: {
                "kind_of_graph": "structured data knowledge graph",
                "description": goals,
            },
            APPROVED_FILES: selected_files,
        },
    )

    runner = Runner(
        agent=schema_refinement_loop,
        app_name=app_name,
        session_service=session_service,
    )

    content = types.Content(
        role="user",
        parts=[types.Part(text="How can these files be imported to construct the knowledge graph?")],
    )

    _log("🔄 Running schema refinement loop (max 3 iterations)...")

    iteration_count = 0
    final_response = "No response from agent."
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        # Log agent transitions (non-final events = tool calls or intermediate steps)
        if event.author and not event.is_final_response():
            if event.author == "schema_refinement_loop":
                iteration_count += 1
                _log(f"   🔁 Loop iteration {iteration_count}...")
            elif event.author not in ("schema_proposal_agent", "schema_critic_agent", "StopChecker"):
                _log(f"   → {event.author}")
        elif event.is_final_response():
            if event.content and event.content.parts:
                final_response = event.content.parts[0].text
            _log(f"   ✅ Agent finished: {event.author}")

    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session_id,
    )

    plan = session.state.get(PROPOSED_CONSTRUCTION_PLAN, {})
    _log(f"✅ Schema proposal complete — {len(plan)} construction rules")
    for k, v in plan.items():
        if isinstance(v, dict):
            _log(f"   → {k}: type={v.get('construction_type', '?')}, file={v.get('source_file', '?')}")

    # Attach file path mapping for the builder
    file_paths = {}
    for f in selected_files:
        p = Path(f)
        if p.exists():
            file_paths[p.name] = str(p)
    plan["_file_paths"] = file_paths

    # Check for missing files — if the LLM didn't create rules for all files,
    # auto-detect relationship files and add them
    covered_files = set()
    for v in plan.values():
        if isinstance(v, dict):
            sf = v.get("source_file", "")
            if sf:
                covered_files.add(Path(sf).name)

    for f in selected_files:
        fname = Path(f).name
        if fname not in covered_files:
            _log(f"⚠️ No rule for {fname} — auto-detecting...")
            auto_rule = _auto_detect_rule(f, plan)
            if auto_rule:
                rule_name = auto_rule.get("label") or auto_rule.get("relationship_type", fname)
                plan[rule_name] = auto_rule
                _log(f"   → Auto-added: {rule_name} ({auto_rule.get('construction_type', '?')})")

    # Check for missing reference relationships — node files with foreign key columns
    # that reference other node labels but don't have a corresponding relationship rule
    _auto_detect_reference_relationships(plan, _log, file_paths)

    return plan


async def run_query_agent(
    question: str,
    database: Optional[str] = None,
) -> dict:
    """Run the query agent to answer a natural-language question.

    Args:
        question: user's question
        database: Neo4j database name (optional)

    Returns:
        dict with 'answer', 'cypher', 'raw_results', 'error'
    """
    session_service = InMemorySessionService()
    app_name = "query_app"
    user_id = "kg_user"
    session_id = "query_session_01"

    await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        state={},
    )

    runner = Runner(
        agent=query_agent,
        app_name=app_name,
        session_service=session_service,
    )

    # Include database in the message if specified
    msg = question
    if database:
        msg = f"database: {database}\n\nQuestion: {question}"

    content = types.Content(
        role="user",
        parts=[types.Part(text=msg)],
    )

    final_response = "Agent did not produce a response."
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response():
            if event.content and event.content.parts:
                final_response = event.content.parts[0].text

    # Try to extract Cypher from the session events (the agent's tool calls)
    # The agent's final response is the natural-language answer
    cypher = ""
    raw_results = []
    # Check session state for tool outputs
    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session_id,
    )

    return {
        "question": question,
        "cypher": cypher,
        "answer": final_response,
        "raw_results": raw_results,
        "error": None,
    }


# ══════════════════════════════════════════════════════════════════════
#  Agent metadata for the UI
# ══════════════════════════════════════════════════════════════════════

AGENT_METADATA = {
    "schema_proposal_pipeline": {
        "type": "LoopAgent",
        "name": "schema_refinement_loop",
        "description": "Iteratively proposes and critiques a knowledge graph schema",
        "max_iterations": 3,
        "sub_agents": [
            {
                "name": "schema_proposal_agent",
                "type": "LlmAgent",
                "role": "Knowledge graph architect — samples files, proposes node & relationship construction rules",
                "tools": [
                    "get_approved_user_goal", "get_approved_files",
                    "get_proposed_construction_plan", "sample_file", "search_file",
                    "propose_node_construction", "propose_relationship_construction",
                    "remove_node_construction", "remove_relationship_construction",
                ],
            },
            {
                "name": "schema_critic_agent",
                "type": "LlmAgent",
                "role": "Schema critic — validates the proposal, returns 'valid' or 'retry' with feedback",
                "tools": [
                    "get_approved_user_goal", "get_approved_files",
                    "get_proposed_construction_plan", "sample_file", "search_file",
                ],
                "output_key": "feedback",
            },
            {
                "name": "StopChecker",
                "type": "CheckStatusAndEscalate (BaseAgent)",
                "role": "Control flow — stops the loop when critic says 'valid'",
            },
        ],
    },
    "query_pipeline": {
        "type": "LlmAgent",
        "name": "query_agent",
        "description": "Translates natural-language questions → Cypher → executes → natural-language answer",
        "tools": ["get_schema_context", "execute_cypher"],
    },
}