Languages: **English** | [日本語](README.ja.md)
# 🔗 Knowledge Graph Builder

> Turn spreadsheets and text documents into an interactive, queryable knowledge graph — powered by AI agents, Neo4j, and Google ADK.

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.x-008CC1.svg)](https://neo4j.com)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-1.5-4285F4.svg)](https://google.github.io/adk-docs/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---


## Demo Video

[![Knowledge Graph Builder Demo](https://img.youtube.com/vi/sLEjyoeSjuU/0.jpg)](https://youtu.be/sLEjyoeSjuU)

## 📖 Overview

The **Knowledge Graph Builder** is a web application that automates the creation of knowledge graphs from structured data files (CSV) and unstructured text (Markdown). Instead of manually designing graph schemas and writing Cypher queries, you simply:

1. **Select** your data files
2. **Describe** what you want the graph to capture
3. **Let AI agents** propose and refine the schema
4. **Review, approve, and build** — then ask questions in plain English

The app uses a team of AI agents (Google ADK `LoopAgent`) that iteratively propose, critique, and validate a graph schema, then constructs the graph in Neo4j, and finally lets you query it using natural language — all through a clean web UI.

---

## ✨ Features

- 🤖 **AI-Powered Schema Proposal** — A 3-agent refinement loop (Proposer → Critic → Checker) proposes the optimal graph structure from your data
- 📁 **File Browser** — Navigate your filesystem and select CSV, Markdown, or JSON files
- 🏗️ **One-Click Graph Building** — Automatically creates Neo4j databases, copies CSVs, and executes Cypher `LOAD CSV` to build nodes and relationships
- 🔍 **Natural Language Q&A** — Ask questions in plain English; an AI agent translates them to Cypher, executes the query, and summarizes the results
- 📊 **Interactive Graph Visualization** — Canvas-based graph explorer with zoom, pan, and drag
- 📡 **Live Agent Progress** — SSE streaming shows real-time agent activity as the schema proposal loop runs
- 🗄️ **Multi-Database Support** — Each project gets its own isolated Neo4j database
- 📋 **6 Sample Datasets** — Furniture, Tech, Reviews, Healthcare, E-commerce, and Education

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Browser (Vanilla HTML/JS/CSS)              │
│    4-step wizard · Canvas graph viz · SSE progress      │
└────────────────────┬────────────────────────────────────┘
                     │ REST API + SSE
┌────────────────────▼────────────────────────────────────┐
│              FastAPI Backend (main.py)                  │
│   /api/browse · /api/propose · /api/build · /api/query  │
└─────┬──────────────┬──────────────────┬─────────────────┘
      │              │                  │
┌─────▼─────┐ ┌──────▼───────┐ ┌────────▼──────────┐
│  Neo4j    │ │  agents.py   │ │  graph_builder.py │
│  Database │ │  (ADK agents)│ │  (Cypher builder) │
│           │ │              │ │                   │
│ bolt://   │ │ LoopAgent:   │ │ LOAD CSV → MERGE  │
│ :7687     │ │  Proposer    │ │  docker cp        │
│           │ │  Critic      │ │  auto-detect      │
│           │ │  Checker     │ │  stats/graph data │
│           │ │ LlmAgent:    │ └───────────────────┘
│           │ │  QueryAgent  │
└───────────┘ └──────┬───────┘
                     │
              ┌──────▼───────┐
              │  LLM (LiteLLm)│
              │  Ollama Cloud │
              │  via proxy    │
              └──────────────┘
```

### AI Agent Pipeline

| Agent | Type | Role |
|-------|------|------|
| `schema_proposal_agent` | LlmAgent | Reads files, proposes node & relationship construction rules |
| `schema_critic_agent` | LlmAgent | Validates proposal, returns "valid" or "retry" with feedback |
| `CheckStatusAndEscalate` | BaseAgent | Stops loop when critic says "valid" (max 3 iterations) |
| `query_agent` | LlmAgent | Translates NL questions → Cypher → executes → summarizes answer |

---

## 📸 Screenshots

### User Guide — How It Works (Tab 1)

![User Guide Tab 1 — How It Works](images/userguide-tab1-full.png)

### User Guide — Technical Details (Tab 2)

![User Guide Tab 2 — Technical Details](images/userguide-tab2-full.png)

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+**
- **Neo4j 5.x** (running locally or via Docker)
- **Ollama** account (for cloud LLM access) or local Ollama instance
- **Google ADK** (`google-adk` package)

### 1. Clone the repository

```bash
git clone https://github.com/git4rajmohan/AI_Projects.git
cd AI_Projects/KnowledgegraphUIapp
```

### 2. Create a virtual environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
# Copy the template and fill in your values
cp .env.example .env
# Edit .env with your Ollama API key, Neo4j password, etc.
```

### 5. Start Neo4j

```bash
# Option A: Docker
docker run -d --name neo4j-adk \
  -p 7687:7687 -p 7474:7474 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:5

# Option B: Local Neo4j installation
# Ensure Neo4j is running on bolt://localhost:7687
```

### 6. Start the Ollama Cloud proxy (if using cloud LLM)

```bash
# From the parent workspace directory
python ollama_cloud_proxy.py
# This runs on http://127.0.0.1:11435/v1
```

### 7. Run the app

```bash
python -m uvicorn app.main:app --reload --port 8080
```

### 8. Open the UI

Navigate to **http://localhost:8080** in your browser.

---

## 📂 Project Structure

```
KnowledgegraphUIapp/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI web server & REST endpoints
│   ├── agents.py            # Google ADK agents (LoopAgent + LlmAgent)
│   ├── graph_builder.py     # Cypher LOAD CSV graph construction
│   ├── query_engine.py      # Direct LLM query (fallback path)
│   └── static/
│       └── index.html       # Single-page frontend (vanilla JS)
├── input_files/             # 6 sample datasets
│   ├── project1_furniture/  # Products, suppliers, components, assemblies
│   ├── project2_tech/       # Companies, customers, products, purchases
│   ├── project3_reviews/    # Markdown product reviews (10 files)
│   ├── project4_healthcare/ # Doctors, hospitals, patients, prescriptions
│   ├── project5_ecommerce/  # Buyers, sellers, orders, products, reviews
│   └── project6_education/  # Students, professors, courses, universities
├── tests/
│   ├── test_app.py          # Unit tests
│   ├── e2e_test.py          # End-to-end test (project 1)
│   └── e2e_test_project2.py # End-to-end test (project 2)
├── images/                  # Screenshots for documentation
├── userguide.html           # Interactive user guide (2 tabs)
├── requirements.txt
├── .env.example             # Environment template (safe to commit)
└── .gitignore
```

---

## 🔄 How It Works

### Step 1: Select Files & Describe Goals
Browse your filesystem, select CSV/MD/JSON files, name your Neo4j database, and describe what you want the graph to capture.

### Step 2: AI Proposes Schema
A Google ADK `LoopAgent` runs a 3-agent refinement loop (max 3 iterations):
- **Proposer Agent** reads files and proposes node/relationship rules
- **Critic Agent** validates the proposal and returns "valid" or "retry" with feedback
- **Checker** stops the loop when the critic approves

You see live progress via SSE streaming and can edit the final JSON plan.

### Step 3: Build Graph
The app creates the Neo4j database (if needed), copies CSVs to the import directory (via `docker cp` if needed), and executes Cypher `LOAD CSV` + `MERGE` queries to build nodes and relationships.

### Step 4: Query & Explore
Ask questions in natural language. The `query_agent` (ADK `LlmAgent`) retrieves the graph schema, generates Cypher, executes it, and summarizes the answer. An interactive Canvas visualization shows the graph structure.

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI 0.115 + Uvicorn |
| AI Agents | Google ADK 1.5 (LlmAgent, LoopAgent, Runner) |
| LLM | Ollama Cloud (gpt-oss:120b) via LiteLLM proxy |
| Graph Database | Neo4j 5.x (Python driver 5.28) |
| Frontend | Vanilla HTML/CSS/JavaScript (no framework) |
| Graph Viz | HTML5 Canvas (custom renderer) |
| Streaming | Server-Sent Events (SSE) |
| Validation | Pydantic |

---

## 📦 Dependencies

```
fastapi==0.115.0
uvicorn==0.30.6
neo4j==5.28.1
neo4j-graphrag==1.8.0
python-dotenv==1.0.1
google-adk==1.5.0
litellm==1.73.6
openai
pydantic
```

---

## 📝 Sample Datasets

| Project | Files | Domain |
|---------|-------|--------|
| Furniture | 5 CSVs | Products, assemblies, components, suppliers, part-supplier mappings |
| Tech | 5 CSVs | Companies, customers, partnerships, products, purchases |
| Reviews | 10 Markdown files | Product reviews with features, issues, and locations |
| Healthcare | 6 CSVs | Doctors, hospitals, medications, patients, prescriptions, treatments |
| E-commerce | 5 CSVs | Buyers, sellers, orders, products, reviews |
| Education | 5 CSVs | Students, professors, courses, enrollments, universities |

---

## 🔒 Security

- **`.env` is gitignored** — never commit real API keys or passwords
- Use `.env.example` as a template for configuration
- The Ollama cloud proxy uses a dummy `OPENAI_API_KEY` — the real key (`OLLAMA_API_KEY`) stays in `.env`
- Neo4j credentials are read from environment variables, not hardcoded

---

## 📄 License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

---

## 👤 Author

**Raj Mohan**
- GitHub: [@git4rajmohan](https://github.com/git4rajmohan)
- Email: svrajmohan@gmail.com
