# Developer Instructions: E-Commerce Return & Fraud Prevention Agent

## 1. Executive Summary & Objective
Build a stateful, event-driven backend service using **LangGraph (Python)**, **FastAPI**, and **Pydantic** that handles customer return and refund workflows.

The service will:
1. Validate return policy rules (30-day window check).
2. Calculate return shipping fees based on item condition (damaged vs. buyer remorse).
3. Handle multi-turn interaction loops if photo proof of item damage is missing.
4. Natively **interrupt execution (Human-in-the-Loop)** if the return value exceeds **$200.00**, persisting state to a SQLite database.
5. Resume execution upon manager approval or rejection and return the final refund status.

**Primary Framework Mandate:** Use **LangGraph** with a `MemorySaver` / SQLite checkpointer. The architecture MUST showcase cyclical node loops, state persistence, and native `interrupt()` mechanisms for human authorization gates.

---

## 2. Technical Stack & Dependencies
* **Language:** Python 3.11+
* **State & Agent Runtime:** `langgraph`, `langchain-core`, `langchain-openai`
* **API Framework:** `fastapi`, `uvicorn`
* **Data Validation:** `pydantic` v2
* **Persistence:** `sqlite3` (or `langgraph-checkpoint-sqlite`)
* **Testing:** `pytest`, `pytest-asyncio`

---

## 3. Project Directory Structure
Agents must set up the project adhering to the following structure:

```text
return-agent/
│── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI entry point & human-approval routes
│   ├── schemas.py           # Pydantic state schemas & API payload contracts
│   ├── graph.py             # LangGraph state machine, nodes, edges, & interrupts
│   ├── services.py          # Mock Order DB & Refund Payment Gateway
│   └── config.py            # Environment configurations
│── tests/
│   ├── test_graph.py        # Tests for LangGraph state transitions & interrupts
│   └── test_api.py          # FastAPI integration tests
│── .env.example
│── INSTRUCTIONS.md
│── requirements.txt
└── README.md
