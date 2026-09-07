"""
query_engine.py — Translates natural-language questions into Cypher
queries via the LLM, executes them against Neo4j, and formats the answer.
"""

import os
import re
import json
from typing import Optional
from dotenv import load_dotenv, find_dotenv
from openai import OpenAI
from neo4j import GraphDatabase

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


def _get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

def _get_llm_client():
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)


def _get_schema_context(database: str = None) -> str:
    """Query Neo4j for the current schema to provide as context to the LLM."""
    driver = _get_driver()
    db = database or NEO4J_DB
    context_parts = []

    try:
        with driver.session(database=db) as session:
            # Node labels and properties
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

            # Relationship types
            result = session.run("""
                MATCH (a)-[r]->(b)
                WHERE NOT any(l IN labels(a) WHERE l STARTS WITH '__')
                  AND NOT any(l IN labels(b) WHERE l STARTS WITH '__')
                RETURN DISTINCT labels(a)[0] AS from_label, type(r) AS rel_type, labels(b)[0] AS to_label
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

    return "\n".join(context_parts) if context_parts else "No schema information available."


def answer_question(question: str, database: str = None) -> dict:
    """
    Translate a natural-language question into a Cypher query via the LLM,
    execute it, and generate a human-readable answer from the results.

    Args:
        question: user's natural-language question
        database: Neo4j database name (None = default from env)

    Returns:
        dict with 'question', 'cypher', 'answer', 'raw_results', 'error'
    """
    client = _get_llm_client()
    schema_ctx = _get_schema_context(database=database)

    # ── Step 1: Generate Cypher from natural language ─────────────────
    cypher_system = """You are a Cypher query expert. Given a schema and a user question, 
generate a single Cypher query that answers the question.

Rules:
- Return ONLY the Cypher query, no explanations or markdown fences.
- Use MATCH patterns consistent with the schema below.
- Exclude internal labels starting with '__' (e.g., __Entity__, __KGBuilder__).
- Use coalesce() for properties that may use 'name' or 'product_name'.
- Always add LIMIT 25 to avoid too many results.
- For product names, try both 'name' and 'product_name' properties using coalesce().

IMPORTANT - Relationship directions:
- Products HAVE features: MATCH (p:Product)-[:INCLUDES_FEATURE]->(f)
- Products HAVE issues: MATCH (p:Product)-[:HAS_ISSUE]->(i)
- Products are USED IN locations: MATCH (p:Product)-[:USED_IN_LOCATION]->(l)
- Products CORRESPOND TO other products: MATCH (p1:Product)-[:CORRESPONDS_TO]->(p2)
- When a user asks about "features of X" or "what features does X have", traverse INCLUDES_FEATURE.
- When a user asks about "issues of X" or "problems with X", traverse HAS_ISSUE.
- When a user asks about "locations" or "where is X used", traverse USED_IN_LOCATION.
- When counting related items, use: MATCH (p:Product)-[:REL_TYPE]->(r) WITH p, count(r) AS cnt

Always traverse FROM Product TO the related node (Product is the source of the relationship).
"""

    cypher_user = f"""## Schema
{schema_ctx}

## Question
{question}

Generate a Cypher query that answers this question:"""

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": cypher_system},
                {"role": "user", "content": cypher_user},
            ],
            temperature=0,
        )
        cypher_query = resp.choices[0].message.content.strip()

        # Strip markdown fences if present
        if cypher_query.startswith("```"):
            cypher_query = re.sub(r"^```(?:cypher)?\s*", "", cypher_query)
            cypher_query = re.sub(r"\s*```$", "", cypher_query)
        cypher_query = cypher_query.strip()
    except Exception as e:
        return {"question": question, "cypher": "", "answer": "",
                "raw_results": [], "error": f"LLM error: {e}"}

    # ── Step 2: Execute the Cypher query ──────────────────────────────
    driver = _get_driver()
    db = database or NEO4J_DB
    raw_results = []
    try:
        with driver.session(database=db) as session:
            result = session.run(cypher_query)
            for r in result:
                raw_results.append({k: str(v)[:200] for k, v in r.items()})
    except Exception as e:
        driver.close()
        return {"question": question, "cypher": cypher_query, "answer": "",
                "raw_results": [], "error": f"Cypher execution error: {e}"}

    # ── Step 3: Generate a human-readable answer ──────────────────────
    results_str = json.dumps(raw_results[:25], indent=2) if raw_results else "No results found."

    answer_system = """You are a helpful assistant. Given a user's question, the Cypher query used, 
and the query results, provide a clear, concise answer in natural language.
If the results are empty, say so. If there's useful data, summarize it nicely."""

    answer_user = f"""## Question
{question}

## Cypher Query
{cypher_query}

## Results
{results_str}

Provide a natural-language answer:"""

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": answer_system},
                {"role": "user", "content": answer_user},
            ],
            temperature=0,
        )
        answer = resp.choices[0].message.content.strip()
    except Exception as e:
        answer = f"Could not generate answer: {e}\n\nRaw results:\n{results_str}"

    driver.close()
    return {
        "question": question,
        "cypher": cypher_query,
        "answer": answer,
        "raw_results": raw_results[:25],
        "error": None,
    }