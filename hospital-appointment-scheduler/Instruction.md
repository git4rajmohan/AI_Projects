# Developer Instructions: Appointment Scheduler & Confirmation Bot

## 1. Executive Summary & Objective
Build a lightweight, deterministic backend service using **LangChain (Python)**, **FastAPI**, and **Pydantic** that processes inbound patient/client scheduling requests. 

The service will:
1. Parse raw natural language input (e.g., text/email).
2. Extract structured appointment variables (intent, target date/time, department, contact info).
3. Query a mock Calendar API to check availability.
4. Execute an SMS API confirmation call via Twilio (or mock equivalent).
5. Return a structured JSON execution summary.

**Primary Framework Mandate:** Use **LangChain (LCEL)** for prompt management and structured output parsing. Do NOT use heavy state-machine engines (e.g., LangGraph) or vector index retrievers (e.g., LlamaIndex)—keep the pipeline strictly linear and low-latency.

---

## 2. Technical Stack & Dependencies
* **Language:** Python 3.11+
* **LLM Orchestration:** `langchain`, `langchain-core`, `langchain-openai`
* **API Framework:** `fastapi`, `uvicorn`
* **Data Validation:** `pydantic` v2
* **Environment Management:** `python-dotenv`
* **Testing:** `pytest`, `pytest-asyncio`

---

## 3. Project Directory Structure
Agents must set up the project adhering to the following structure:

```text
appointment-bot/
│── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI entry point
│   ├── schemas.py           # Pydantic schemas for input/output & extraction
│   ├── chain.py             # LangChain LCEL pipeline logic
│   ├── services.py          # Mock Calendar & SMS integrations
│   └── config.py            # Environment configurations
│── tests/
│   ├── test_chain.py        # Tests for LLM parsing & extraction logic
│   └── test_api.py          # FastAPI endpoint integration tests
│── .env.example
│── INSTRUCTIONS.md
│── requirements.txt
└── README.md