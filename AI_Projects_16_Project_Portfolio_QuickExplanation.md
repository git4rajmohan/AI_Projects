# AI / GenAI Portfolio — 16 Projects

Compact technical portfolio covering RAG, GraphRAG, Agentic AI, MCP, LLM safety, evaluation, document intelligence, workflow orchestration and voice agents.

## Projects

- [1. Hospital Appointment Scheduler & Confirmation Bot](#p1)
- [2. Automated Order Returns & Fraud Prevention Agent](#p2)
- [3. AI Guardrails — Safety & Control Layer for LLMs](#p3)
- [4. AI_RAGAS — RAG Evaluation & Quality Assurance](#p4)
- [5. Knowledge Graph Builder — AI-Powered GraphRAG Foundation](#p5)
- [6. Sentiment Analysis](#p6)
- [7. Agentic AI Multi-Agent E-Commerce Orchestrator](#p7)
- [8. Agentic AI Mindmap Orchestrator](#p8)
- [9. Agentic AI MCP Tool Orchestration](#p9)
- [10. Safe Support Ticket](#p10)
- [11. AgentFlow Orchestrator — Dynamic Multi-Agent Workflow & Skill Platform](#p11)
- [12. DocFlow — Invoice Approval Engine](#p12)
- [13. Enterprise Knowledge Assistant — Hybrid GraphRAG](#p13)
- [14. LLM Wiki UI — Self-Maintaining Knowledge Base](#p14)
- [15. RAG Documentation Assistant — Production RAG & Evaluation Pipeline](#p15)
- [16. Research Voice Agent — AI Research & Podcast Production](#p16)

---

<a id="p1"></a>

## 1. Hospital Appointment Scheduler & Confirmation Bot

*AI-assisted appointment booking with deterministic scheduling and SMS confirmation.*

### Business problem:

Hospital front desks spend time manually interpreting appointment requests, checking calendars, confirming bookings and handling rescheduling, with a risk of scheduling errors.

### What it does:

An AI-assisted booking bot understands natural-language requests, extracts appointment details, finds an available slot, sends SMS confirmation, and maintains a booking/audit history.

### Technical implementation:

```text
👤 USER INPUT
Natural-language request → Email / SMS / Web Chat
↓
🤖 AI / PROBABILISTIC
LangChain LCEL + LLM → Extract patient, department, date, time, phone and intent
↓
⚙️ DETERMINISTIC
Python + FastAPI → Validate → Route → Calendar Rules → Check Availability → Find Slot
↓
💾 DATABASE / 📱 EXTERNAL ACTION
SQLite / WAL → Booking + Audit | Twilio / Mock SMS → Confirmation
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — business logic and scheduling rules  
• LangChain LCEL — LLM processing pipeline  
• Ollama Cloud / gpt-oss:120b — natural-language understanding  
• Pydantic / PydanticOutputParser — structured output validation  
• FastAPI — REST API and backend services  
• SQLite / WAL — booking and SMS audit persistence  
• Twilio — SMS confirmation  
• HTML / CSS / JavaScript — chat and admin console  
• Pytest — automated testing  
• OpenAPI / Swagger — API documentation

### What is different:

AI reads; deterministic code decides. The LLM never selects an appointment slot. Weekday, business hours, availability, double-booking prevention and next-available search are controlled by deterministic rules.

### Value:

Automates appointment scheduling, reduces manual front-desk effort, and prevents double-booking.  
Provides natural-language booking, automatic alternatives, SMS confirmation and a complete audit trail.

### Technical explanation:

The LLM is limited to natural-language understanding and structured extraction. FastAPI and deterministic Python handle routing and calendar decisions, while SQLite and Twilio manage persistence and confirmation.

---

<a id="p2"></a>

## 2. Automated Order Returns & Fraud Prevention Agent

*AI-assisted returns workflow with deterministic policy, fraud controls and human approval.*

### Business problem:

E-commerce return teams manually review return reasons, policy eligibility, photos, refund fees and fraud signals, creating processing effort and inconsistent decisions.

### What it does:

Classifies the customer's reason, applies deterministic return policies, requests photo proof, calculates refunds, screens for fraud, automatically processes low-risk returns and routes high-value/high-risk cases to a manager.

### Technical implementation:

```text
👤 USER INPUT
Order + Return Reason + Photo / Return Details
↓
🤖 AI / PROBABILISTIC
Ollama LLM / gpt-oss:120b → Damaged/Defective OR Buyer Remorse
↓
⚙️ DETERMINISTIC
LangGraph StateGraph → Policy → Photo Proof → Fee → Fraud Score → Approval Rules
↓
🧑‍💼 HUMAN-IN-THE-LOOP
interrupt() → Manager Approve / Reject for high risk or high value
↓
💾 PERSISTENCE
SQLite Checkpoint → Every workflow step saved
↓
💳 EXTERNAL ACTION
Payment Gateway → Refund Processing
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — business rules, fraud scoring and workflow logic  
• LangGraph — state-machine orchestration and conditional workflow  
• Ollama Cloud / gpt-oss:120b — return-reason classification  
• FastAPI — REST APIs  
• Streamlit — customer, manager and pipeline dashboards  
• Pydantic v2 — validation and structured contracts  
• SQLite / SqliteSaver — durable workflow checkpointing  
• interrupt() / Command(resume) — human approval and workflow resumption  
• Pytest — automated testing  
• OpenAPI / Swagger — API documentation

### What is different:

AI classifies; the workflow decides; humans control risky transactions. Fees, refund amounts, fraud scores and approval thresholds are deterministic.

### Value:

Automates routine returns while retaining controls for financial and fraud-related decisions.  
Supports photo-proof loops, fraud screening, manager approval, auditability and restart-safe recovery.

### Technical explanation:

The LLM understands the free-form return reason. LangGraph executes the deterministic state machine for policy validation, evidence collection, fee calculation, fraud scoring and refund processing. interrupt() pauses risky cases and SQLite checkpointing makes workflows resumable.

---

<a id="p3"></a>

## 3. AI Guardrails — Safety & Control Layer for LLMs

*Defense-in-depth safety layer for enterprise LLM applications.*

### Business problem:

Enterprise LLM applications can receive jailbreaks, prompt injections, PII, sensitive requests and malicious content, while models may generate credentials, exploit techniques or system-prompt information.

### What it does:

Validates and sanitizes user input before it reaches the chatbot, uses semantic intent detection for subtle attacks, and scans every LLM response for sensitive information before returning it.

### Technical implementation:

```text
👤 USER INPUT
User Message
↓
⚙️ DETERMINISTIC
Python Regex Rails → PII → Injection → Urgency → Sanitization
↓
🤖 AI / PROBABILISTIC
FastEmbed → Local semantic shortlist
↓
🤖 AI / PROBABILISTIC
Guardrail LLM → Topic / Jailbreak / Sensitive Request classification
↓
BLOCKED → Scripted Safe Reply / Chatbot not called
CLEAN → Chatbot LLM → Generate Answer
↓
⚙️ DETERMINISTIC
Output Rails → Credentials → Private Keys → Exploits → Prompt Leaks
↓
💾 AUDIT / OBSERVABILITY
Logfire → Latency + Tokens + Decisions
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — deterministic security checks and sanitization  
• NVIDIA NeMo Guardrails — policy/rail orchestration  
• Colang + YAML — guardrail policies  
• Groq / ChatGroq — cloud LLM inference  
• llama-3.3-70b-versatile — semantic guardrail classification  
• llama-3.1-8b-instant — chatbot generation  
• FastEmbed — local CPU embeddings  
• Streamlit — interactive UI and experiments  
• Pydantic Logfire — optional tracing  
• LangChain callbacks — LLM/token tracking

### What is different:

Defense in depth rather than a single prompt or filter. Deterministic rails catch known patterns, semantic AI rails detect meaning-based attacks, and output rails provide a final safety check.

### Value:

Provides a practical safety layer between users and enterprise LLMs.  
Demonstrates protection against PII exposure, jailbreaks, prompt injection, sensitive requests and output leakage.

### Technical explanation:

Deterministic Python rails handle known patterns, FastEmbed provides local semantic matching, a dedicated guard LLM classifies higher-level intent, and NeMo Guardrails orchestrates policies. Only approved requests reach the chatbot.

---

<a id="p4"></a>

## 4. AI_RAGAS — RAG Evaluation & Quality Assurance

*Repeatable evaluation harness for retrieval, grounding and answer quality.*

### Business problem:

A RAG chatbot can produce fluent but incorrect answers because of poor retrieval, missing context, hallucination or factual errors. Manual review does not scale.

### What it does:

Sends test questions to a RAG endpoint, captures answers and retrieved documents, supports human review, then uses RAGAS metrics and an LLM judge to measure retrieval, groundedness and correctness. Results and explanations are stored for regression tracking.

### Technical implementation:

```text
👤 USER INPUT
Question Set + Ground-Truth Answers
↓
📡 RAG SYSTEM
HTTP Request → Answer + Retrieved Documents
↓
👤 HUMAN REVIEW
Review / Edit Answer + Contexts
↓
🤖 AI / PROBABILISTIC
RAGAS + Judge LLM
↓
📊 RESULTS
Retrieval: Context Relevance / Precision / Recall
Augmentation: Groundedness / Faithfulness
Generation: Factual Correctness / Rubric Score
↓
💾 PERSISTENCE
JSON run history + trend comparison
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — evaluation logic and orchestration  
• RAGAS — RAG evaluation metrics  
• LLM Judge / OpenAI-compatible API — scoring and explanations  
• Streamlit — review/results/analytics UI  
• pytest — CLI and automated tests  
• Requests — RAG endpoint communication  
• AsyncOpenAI — asynchronous judge communication  
• JSON — evaluation-run persistence  
• Plotly — visualization  
• Pydantic / RAGAS Samples — structured data

### What is different:

Evaluates the RAG pipeline stage-by-stage rather than judging only the final answer. Retrieval, grounding/faithfulness and factual correctness are measured separately.

### Value:

Provides repeatable, measurable RAG quality testing instead of subjective manual review.  
Enables regression testing after changes to chunking, retrieval, prompts or models.

### Technical explanation:

The RAG endpoint is tested first and its answer/contexts are reviewed before scoring. An OpenAI-compatible judge LLM then evaluates retrieval, augmentation and generation metrics, while JSON history enables regression and trend analysis.

---

<a id="p5"></a>

## 5. Knowledge Graph Builder — AI-Powered GraphRAG Foundation

*From spreadsheets/documents to an approved, queryable Neo4j knowledge graph.*

### Business problem:

Business data across spreadsheets and documents contains relationships between products, suppliers, customers, components and other entities, but extracting and querying them traditionally requires graph modeling and Cypher expertise.

### What it does:

Reads CSV, Markdown and JSON, proposes a graph schema, validates it through a Proposer → Critic → Checker loop, lets the user approve/edit it, builds Neo4j, and enables plain-English queries without writing Cypher.

### Technical implementation:

```text
👤 USER INPUT
CSV / Markdown / JSON + Goal Description
↓
🤖 AI / PROBABILISTIC
Google ADK Agents → Schema Proposer → Nodes + Relationships + Properties
↓
🔍 AI SELF-CRITIQUE
Critic Agent
↓
⚙️ VALIDATION
Checker → Invalid: retry with feedback up to 3 iterations
↓
👤 HUMAN APPROVAL
Review / Edit JSON Schema
↓
⚙️ DETERMINISTIC
Graph Builder → Cypher MERGE
↓
💾 DATABASE
Neo4j Knowledge Graph
↓
👤 USER INPUT
Plain-English Question
↓
🤖 AI / PROBABILISTIC
Query Agent → Schema → Cypher
↓
⚙️ DETERMINISTIC
Neo4j Executes Cypher
↓
🤖 AI / PROBABILISTIC
Result Summarization
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — application and graph-building logic  
• FastAPI — backend API  
• Google ADK — multi-agent orchestration  
• LiteLLM — LLM integration  
• LLM — schema proposal, critique and query generation  
• Neo4j — graph database  
• Cypher — deterministic graph operations  
• HTML / JavaScript — web UI  
• Graph visualization — relationship exploration  
• CSV / Markdown / JSON — source formats

### What is different:

AI proposes; humans approve; the graph provides the facts. Agentic schema refinement is separated from deterministic graph creation, with a human gate before Neo4j changes.

### Value:

Converts raw business files into a queryable knowledge graph without requiring graph modeling or Cypher expertise.  
Makes relationship-based questions accessible through natural language and visual graph exploration.

### Technical explanation:

Google ADK agents infer and refine the schema. A human reviews the JSON before deterministic Neo4j creation. A query agent generates Cypher from natural language, executes it and summarizes the results.

---

<a id="p6"></a>

## 6. Sentiment Analysis

*NLP pipeline for understanding sentiment from text.*

### Business problem:

Organizations need to identify positive, negative and neutral customer/user sentiment across large volumes of text.

### What it does:

Processes text through an NLP/LLM sentiment-analysis workflow and produces structured sentiment results for downstream review or analytics.

### Technical implementation:

```text
👤 USER INPUT
Text / Feedback
↓
🤖 AI / PROBABILISTIC
NLP / LLM Sentiment Classification
↓
⚙️ DETERMINISTIC
Result normalization and structured output
↓
📊 ANALYTICS
Sentiment label / score / explanation
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — processing and orchestration  
• NLP / LLM — sentiment understanding  
• Structured output — normalized results  
• Data processing / visualization — analysis and reporting

### What is different:

Uses AI-based language understanding rather than relying only on simple keyword rules.

### Value:

Turns unstructured feedback into actionable sentiment signals for analysis and downstream workflows.

### Technical explanation:

Text is submitted to a sentiment model, the result is normalized into a structured representation, and the structured output can be consumed by analytics or other AI workflows.

---

<a id="p7"></a>

## 7. Agentic AI Multi-Agent E-Commerce Orchestrator

*Conversational multi-agent shopping workflow from greeting to order summary.*

### Business problem:

Traditional e-commerce requires users to navigate separate catalog, cart, checkout and order-confirmation screens.

### What it does:

Four AI agents handle the shopping conversation: customer details, product selection, cart creation, shipping address and order summary, using shared session state.

### Technical implementation:

```text
👤 USER INPUT
"Hi" + Name + Email + Mobile
↓
🤖 AI / PROBABILISTIC
Orchestrator Agent → Greeting → Collect Details → Route
↓
🤖 AI / PROBABILISTIC
Catalog Agent → Browse → Select Product + Quantity
↓
⚙️ DETERMINISTIC
save_cart() → Session State
↓
🤖 AI / PROBABILISTIC
Checkout Agent → Shipping Address
↓
⚙️ DETERMINISTIC
save_shipping_address() → Session State
↓
🤖 AI / PROBABILISTIC
Order Summary Agent → Read State → Receipt
↓
💾 SESSION STATE
Customer + Cart + Shipping Data
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — agents and state-writing tools  
• Google ADK — multi-agent orchestration  
• LiteLLM — LLM integration  
• Ollama Cloud / gpt-oss:120b — common LLM  
• ToolContext.state — shared persistence  
• Function Tools — save_user_info, save_cart, save_shipping_address  
• ADK Dev UI — agent/tool/handoff tracing  
• python-dotenv — configuration

### What is different:

The architecture creates specialization rather than using different models. One LLM performs four roles through specialized prompts and an agent hierarchy.

### Value:

Demonstrates how a conversational interface can replace a multi-screen e-commerce workflow.  
The same orchestration pattern can be adapted by changing agents, instructions and tools.

### Technical explanation:

ADK manages a hierarchical agent system. Specialized agents perform focused tasks and write facts through Python tools into shared ToolContext.state; downstream agents consume that state.

---

<a id="p8"></a>

## 8. Agentic AI Mindmap Orchestrator

*Multi-agent content structuring and review pipeline for interactive mindmaps.*

### Business problem:

One-shot AI mindmap generation can produce flat, unbalanced or incomplete structures with no quality-control step.

### What it does:

Converts TXT/Markdown, YouTube transcripts or pasted text into a structured mindmap. A Creator proposes the hierarchy, a Reviewer evaluates six criteria, and a Reviser improves it until approval or the iteration limit.

### Technical implementation:

```text
👤 USER INPUT
TXT / Markdown / YouTube Transcript / Pasted Text
↓
⚙️ INPUT PROCESSING
Python → Text extraction / transcript retrieval
↓
🤖 AI / PROBABILISTIC
Schema Creator → JSON Mindmap Schema
↓
🤖 AI / PROBABILISTIC
Schema Reviewer → Coverage / Balance / Conciseness / Hierarchy / Accuracy / Structure
↓
NO → 🤖 Schema Reviser → feedback loop
YES → continue
↓
⚙️ DETERMINISTIC
schema_to_markdown() → JSON → Markdown
↓
🗺️ RENDERING
markmap.js → Interactive SVG
↓
💾 OUTPUT
Standalone HTML + Markdown
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — orchestration, parsing and deterministic conversion  
• Streamlit — interactive UI  
• Ollama — local LLM runtime  
• gpt-oss:120b — schema creation/review  
• OpenAI Python SDK — Ollama OpenAI-compatible endpoint  
• YouTubeTranscriptApi — transcript extraction  
• JSON — structured AI contract  
• markmap.js — interactive mindmap rendering  
• HTML/CSS/JavaScript — standalone output

### What is different:

Quality comes from the review loop rather than a single prompt. Creator proposes, Reviewer applies six criteria, Reviser incorporates feedback, and deterministic conversion renders the approved schema.

### Value:

Transforms unstructured content into structured interactive knowledge maps with AI quality control.  
Local-first processing keeps the workflow lightweight and produces standalone HTML.

### Technical explanation:

The Creator generates JSON, the Reviewer evaluates it, and the Reviser incorporates feedback. Once approved, deterministic Python converts JSON to Markdown and Markmap renders the interactive SVG.

---

<a id="p9"></a>

## 9. Agentic AI MCP Tool Orchestration

*One conversational AI interface for many enterprise tools through MCP.*

### Business problem:

Traditional AI assistants mainly generate text; tasks requiring Excel, files, databases, web browsing, browser automation, diagrams or enterprise systems require switching between applications.

### What it does:

A single Streamlit chat assistant uses one LLM as the decision layer and connects through Model Context Protocol to multiple specialized tool servers. The model selects tools, MCP servers execute actions, and results return to the model until the task is complete.

### Technical implementation:

```text
👤 USER INPUT
Chat / File / Image
↓
🤖 AI / PROBABILISTIC
Agno Agent / gpt-oss:120b
↓
🧠 TOOL DECISION
Select MCP tools
↓
🔌 MCP TOOL ORCHESTRATION
MCP Client / Tool Router
↓
14 MCP SERVERS / 101 TOOLS
Excel • Files • Web • Browser • SQL • Draw.io • Jira • AgilePoint • Analytics • Time • ...
↓
⚙️ DETERMINISTIC EXECUTION
Tool Server performs action
↓
🔁 RESULT → LLM
Next tool decision until completion
↓
🛡️ CONTROL LAYER
Retry • Timeout • Limits • Redaction • Scoping
↓
👤 USER OUTPUT
```

### Tech stack:

• Python 3.12 — orchestration and MCP infrastructure  
• Streamlit — conversational UI  
• Agno 2.5.10 — agent/tool-calling orchestration  
• MCP — standardized tool interface  
• JSON-RPC 2.0 / stdio — MCP transport  
• Ollama Cloud / gpt-oss:120b — reasoning/tool selection  
• glm-5.3-flash — vision model  
• httpx — async communication  
• Pydantic v2 — configuration validation  
• SQLite — session persistence  
• JSONL — execution/audit traces  
• MCP Tool Registry — tool discovery  
• Tool Router — tool dispatch  
• Playwright — browser automation  
• Excel / SQL / Draw.io / Jira / AgilePoint MCP servers — business capabilities

### What is different:

One AI brain, many interchangeable hands. MCP standardizes tool integration, while execution is isolated, bounded, retryable and logged.

### Value:

Creates one conversational interface for spreadsheets, files, databases, websites, browsers, diagrams and enterprise systems.  
New capabilities can be added or replaced through MCP configuration without changing the core application.

### Technical explanation:

Agno manages the tool-calling loop while MCP provides the standardized external capability layer. MCP servers run as isolated subprocesses; a registry discovers schemas and a router dispatches calls with limits, retries and trace logging.

---

<a id="p10"></a>

## 10. Safe Support Ticket

*Safety-controlled support-ticket workflow using AI understanding and deterministic execution.*

### Business problem:

Support systems need to understand free-form user requests while preventing unsafe actions, unauthorized changes and unreliable automation.

### What it does:

Classifies and structures support requests, applies safety/policy checks, routes tickets and controls actions through deterministic workflow logic.

### Technical implementation:

```text
👤 USER INPUT
Support Request
↓
🤖 AI / PROBABILISTIC
LLM → Understand intent and extract ticket information
↓
🛡️ SAFETY / POLICY
Guardrails → Validate allowed operation
↓
⚙️ DETERMINISTIC
Ticket routing / priority / workflow rules
↓
💾 DATABASE / 📱 EXTERNAL ACTION
Ticket system / controlled action
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — workflow logic  
• LLM — language understanding  
• Guardrails — safety and policy enforcement  
• FastAPI / API layer — service integration  
• Structured schemas — validated ticket data  
• Database / ticket system — persistence and action

### What is different:

AI interprets the request, while safety and execution rules remain deterministic.

### Value:

Demonstrates controlled agentic automation for support operations without allowing unrestricted model-driven actions.

### Technical explanation:

The LLM converts natural language into structured intent, after which policy checks and deterministic routing decide what the system is permitted to do.

---

<a id="p11"></a>

## 11. AgentFlow Orchestrator — Dynamic Multi-Agent Workflow & Skill Platform

*Intent → validated plan → approval → DAG execution → evaluation → reusable skill.*

### Business problem:

Typical AI agents rely on fixed prompts or hard-coded workflows and lack structured planning, approval, execution control, quality verification and reuse.

### What it does:

Converts natural-language intent into a validated multi-agent plan, gets approval, executes a dependency-aware DAG using real tools, evaluates the result, replans when necessary, and saves successful workflows as reusable versioned skills.

### Technical implementation:

```text
👤 USER INPUT
Natural-language Intent
↓
🤖 AI / PROBABILISTIC
Intent Parser
↓
🔍 SKILL DISCOVERY
Existing Skill?
→ Match: Reuse
→ No Match: LLM Planner
↓
🤖 AI / PROBABILISTIC
Planner → PlanSpec → Agents + Tools + Dependencies + Criteria
↓
⚙️ VALIDATION
Pydantic PlanSpec + DAG + permissions
↓
👤 HUMAN APPROVAL
Review Plan
↓
⚙️ AGENT ORCHESTRATOR
DAG → Sequential / Parallel → Retry ≤3
↓
🛡️ POLICY ENGINE
READ → WRITE → EXTERNAL_ACTION → DESTRUCTIVE
↓
🧑 HUMAN APPROVAL
External / Destructive Actions
↓
🛠️ TOOL EXECUTION
Python • Files • Web • HTTP
↓
🧮 EVALUATION
Criteria + Score
PASS → 💾 Versioned Skill
FAIL → 🔁 Correct / Retry → Replan
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — orchestration and tools  
• FastAPI — APIs and SSE event streaming  
• Google ADK — agent framework  
• LiteLLM — LLM integration/model routing  
• Ollama Cloud / gpt-oss:120b — planning/reasoning/evaluation  
• React 18 + TypeScript + Vite — frontend  
• Zustand — frontend state  
• Pydantic — PlanSpec/AgentSpec validation  
• Custom DAG Engine — dependency resolution and execution  
• asyncio — concurrency and approvals  
• SQLAlchemy Async + SQLite/WAL — state persistence  
• Built-in tools — file reader/writer, Python, calculator, HTTP, web search  
• Skill Registry — versioning/reuse/import/export  
• SSE — real-time events

### What is different:

The workflow is generated as validated data, not hard-coded prompts. PlanSpec defines agents, tools, dependencies, permissions and evaluation criteria.

### Value:

Turns natural-language objectives into approved, executable and verifiable multi-agent workflows.  
Successful workflows become reusable skills.

### Technical explanation:

The planner produces validated PlanSpec; the deterministic DAG engine controls dependencies, parallelism and retries; the policy engine controls permissions and approvals; evaluation triggers bounded correction/replanning; successful plans are versioned as skills.

---

<a id="p12"></a>

## 12. DocFlow — Invoice Approval Engine

*Controlled document intelligence for invoice extraction, verification, PO matching and approval.*

### Business problem:

Companies process invoice PDFs and scans requiring vendor verification, PO matching, arithmetic checks, duplicate detection and approval routing. Manual processing is slow and difficult to audit.

### What it does:

Reads invoices including image-only scans, extracts structured fields with confidence scores, verifies data against vendors and POs, applies deterministic approval rules, and approves, rejects or routes risky invoices to humans with evidence and audit history.

### Technical implementation:

```text
👤 USER INPUT
Invoice PDF / Scanned Invoice
↓
⚙️ DOCUMENT INGESTION
PyMuPDF → PDF text
↓
🔍 OCR FALLBACK
Tesseract + Pillow → Image-only pages
↓
🤖 AI / PROBABILISTIC
LLM Extraction → Structured JSON + Per-field confidence
↓
⚙️ DETERMINISTIC
9 Validation Checks → Vendor / Bank / Arithmetic / Currency / Duplicate / Date
↓
⚙️ DETERMINISTIC
PO Matching → 2-Way / 3-Way → Quantity / Price / Total / Goods Receipt
↓
⚖️ POLICY ENGINE
R001–R008 → First Trigger Wins
↓
AUTO APPROVE / REJECT / HUMAN REVIEW
↓
💾 DATABASE / AUDIT
SQLite → Invoice + Review + Append-only Audit
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — workflow and policy logic  
• FastAPI + Uvicorn — API  
• Pydantic v2 — structured models  
• Streamlit — reviewer UI  
• PyMuPDF — PDF extraction  
• Tesseract OCR + Pillow — OCR  
• OpenAI-compatible API / Ollama — LLM extraction  
• SQLite — persistence and audit  
• Deterministic Rules Engine — R001–R008  
• Pytest — automated testing  
• Evaluation Harness — invoice accuracy/recall/false-approval/latency metrics

### What is different:

AI reads; code verifies and decides; humans own the risk. The deterministic core contains no LLM imports.

### Value:

Automates routine invoice processing while keeping financial decisions deterministic, explainable and auditable.  
Routes exceptions to humans with the original document, extracted data, validation evidence and decision history.

### Technical explanation:

Document ingestion and OCR prepare the invoice; the LLM performs perception only. Deterministic Python validates fields, matches POs and evaluates policy. State transitions and human actions are captured in an append-only audit trail.

---

<a id="p13"></a>

## 13. Enterprise Knowledge Assistant — Hybrid GraphRAG

*Private enterprise RAG combining vector, keyword and knowledge-graph retrieval with mechanical evidence gating.*

### Business problem:

Enterprise policies and HR knowledge are distributed across PDFs, while conventional chatbots can generate plausible answers unsupported by source documents.

### What it does:

Ingests HR/policy PDFs into vector and graph stores, combines semantic, keyword and relationship-based retrieval, refuses unsupported questions before LLM generation, and provides source-backed answers.

### Technical implementation:

```text
👤 USER INPUT
Natural-language Question
↓
🔍 HYBRID RETRIEVAL
Qdrant Vector + BM25 Keyword + Cognee Knowledge Graph
↓
🧮 DETERMINISTIC
Reciprocal Rank Fusion
↓
🚪 EVIDENCE GATE
Best Evidence ≥ 0.55?
NO → Refuse / LLM not called
YES → Grounded LLM
↓
⚙️ CITATION BUILDER
Metadata-based sources
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — ingestion/retrieval/evaluation  
• LlamaIndex — RAG query engine  
• Cognee — entity/relationship extraction and graph  
• Qdrant — vector search  
• BM25 / rank-bm25 — exact keyword retrieval  
• Knowledge Graph — relationship retrieval  
• RRF — rank fusion  
• Ollama — LLM provider  
• qwen3:8b — local model  
• gpt-oss:120b — optional cloud model  
• nomic-embed-text — local embeddings  
• Streamlit — UI and debug trace  
• Pytest — testing  
• YAML / JSONL — quality configuration/evaluation

### What is different:

Grounding is enforced mechanically, not just requested through a prompt. Evidence is checked before generation and citations are built from metadata.

### Value:

Provides a private enterprise knowledge assistant using identifiable organizational evidence.  
Reduces hallucination risk through evidence gating, hybrid retrieval, citations and measurable quality gates.

### Technical explanation:

Cognee creates the graph and embeddings, Qdrant provides semantic retrieval, BM25 handles exact terminology, and graph retrieval handles relationships. RRF combines retrieval rankings, an evidence gate decides whether generation is allowed, and deterministic metadata creates citations.

### Evaluation:

58-question golden dataset covering factual, terminology, paraphrase, multi-hop, distractor, unsupported and ambiguous questions. Reported baseline: 96% citation accuracy, 94% context relevance and 84% answer correctness; refusal accuracy and faithfulness were identified as improvement areas.

---

<a id="p14"></a>

## 14. LLM Wiki UI — Self-Maintaining Knowledge Base

*Document-to-wiki platform using structured Markdown, wiki links and multi-provider LLMs.*

### Business problem:

Enterprise/product knowledge is scattered across PDFs, spreadsheets, presentations and documents, making a consistent, cross-referenced knowledge base difficult to maintain.

### What it does:

Ingests documents and creates source, entity, concept and analysis pages, connects them using Obsidian-style [[wiki-links]], provides tree/graph exploration, and answers questions with citations and confidence.

### Technical implementation:

```text
👤 USER INPUT
MD • DOCX • XLSX • PDF • PPTX
↓
🤖 AI / PROBABILISTIC
LLM Ingestion → Source / Entity / Concept pages
↓
⚙️ DETERMINISTIC
===FILE:=== Parser → Path Normalization → Type Routing → Index Rebuild
↓
💾 KNOWLEDGE BASE
Plain Markdown Files
↓
🔗 KNOWLEDGE GRAPH
[[wiki-links]]
↓
📁 TREE / 🕸️ D3 GRAPH
Browse / Explore
↓
👤 USER QUESTION
↓
🔍 RETRIEVAL
Keyword Search OR Semantic LLM Selection
↓
🤖 AI / PROBABILISTIC
LLM → Wiki Context Only
↓
⚙️ DETERMINISTIC
Citations + Confidence
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — ingestion and retrieval  
• FastAPI — backend service  
• React 18 — SPA UI  
• Vite — frontend build  
• Tailwind CSS — styling  
• Zustand — frontend state  
• D3.js — knowledge graph  
• React Markdown + GFM — wiki rendering  
• OpenAI / Anthropic SDKs — cloud providers  
• Ollama / LM Studio — local LLMs  
• llama-cpp-python — CPU GGUF inference  
• Hugging Face Hub — local model downloads  
• python-docx / openpyxl / pypdf / python-pptx — extraction  
• Pydantic — validation  
• SSE — streaming  
• Markdown + YAML Frontmatter — storage

### What is different:

The LLM writes the knowledge base, but the knowledge base remains plain files. AGENTS.md defines the schema and the controlled ===FILE:=== protocol provides a reliable output contract.

### Value:

Transforms documents into a reusable, cross-linked and queryable organizational knowledge base.  
Keeps knowledge portable, Git-friendly and editable without database/vendor lock-in.

### Technical explanation:

The LLM converts sources into structured Markdown pages. [[wiki-links]] create the knowledge graph, while the query service retrieves relevant pages and generates cited answers. Structural and semantic linting validate the knowledge base.

---

<a id="p15"></a>

## 15. RAG Documentation Assistant — Production RAG & Evaluation Pipeline

*Production-style RAG with multiple chunking strategies, hybrid retrieval, strict grounding and regression testing.*

### Business problem:

LLMs can answer confidently even when required information is absent from internal documentation. Production RAG therefore needs reliable retrieval, grounding, citations and regression testing.

### What it does:

Ingests Markdown using three chunking strategies, stores embeddings in ChromaDB, combines BM25 and vector retrieval with RRF, generates answers strictly from retrieved evidence with citations, and validates quality against a frozen golden dataset.

### Technical implementation:

```text
👤 USER INPUT
Markdown Documents
↓
⚙️ DOCUMENT INGESTION
Load → Chunk → Embed → Store
↓
✂️ CHUNKING
Character / Structural-Hybrid / Embedding-Semantic
↓
🤖 EMBEDDING
nomic-embed-text
↓
💾 VECTOR DATABASE
ChromaDB → Text + Vector + Metadata
↓
👤 USER QUESTION
↓
🔍 HYBRID RETRIEVAL
BM25 + Vector Similarity
↓
🧮 RRF FUSION
Top-K Chunks
↓
🤖 AI / PROBABILISTIC
Grounded gpt-oss:120b
↓
⚙️ DETERMINISTIC
Citation Extraction → [Source: Document, Section]
↓
Evidence available? → Answer / Refuse
↓
📊 EVALUATION
```

### Tech stack:

• Python — RAG/evaluation logic  
• LangGraph — stateful RAG workflow  
• ChromaDB — persistent vector store  
• BM25 — exact retrieval  
• RRF — ranking fusion  
• nomic-embed-text — local embeddings  
• Ollama — local embedding/model integration  
• Ollama Cloud / gpt-oss:120b — answer generation  
• FastAPI — visualizer API  
• OpenAI-compatible API — model interface  
• Pydantic / TypedDict — structured state  
• Ragas — optional LLM-judged evaluation  
• JSON snapshots — regression history  
• Vanilla JavaScript — visualizer

### What is different:

Treats RAG as an engineered measurable pipeline rather than simply vector search plus an LLM. Chunking strategies can be compared, retrieval signals are fused, claims require citations, and deterministic regression gates detect quality degradation.

### Value:

Provides grounded, traceable answers and explicitly refuses unsupported questions.  
Makes RAG quality repeatable through a frozen golden set and automated regression gates.

### Technical explanation:

Documents are chunked by character, structural or semantic strategies and embedded into persistent ChromaDB. BM25 and vector retrieval run independently and are fused using RRF before a strict grounding prompt. LangGraph controls retrieve → prompt → generate, while deterministic evaluation verifies quality.

### Evaluation:

19 frozen golden questions covering section-level, multi-hop and negative/refusal cases. Reported retrieval recall@k = 1.0, with citation coverage, must-term coverage, refusal accuracy and latency metrics; Ragas is optional and does not affect the deterministic regression verdict.

---

<a id="p16"></a>

## 16. Research Voice Agent — AI Research & Podcast Production

*Multi-agent pipeline that turns research prompts, transcripts or recordings into reports and podcasts.*

### Business problem:

Producing research-based podcasts normally requires separate research, fact gathering, report writing, script creation, audio recording and editing. A chatbot may generate text but does not complete the full production workflow.

### What it does:

Accepts a research prompt, meeting transcript or audio recording; performs research/transcription; creates a structured report and conversational script; and can generate a multi-host podcast with neural voices.

### Technical implementation:

```text
👤 USER INPUT
Research Prompt OR Meeting Transcript OR Audio Recording
↓
⚙️ MODE ROUTER
AI News / Meeting Recap / Audio Summary
↓
🤖 AI / PROBABILISTIC
Producer Agent → Google ADK + gpt-oss:120b
↓
LIVE RESEARCH / TRANSCRIPT PROCESSING
Web Search • Financial Context • Transcript Analysis
↓
⚙️ DETERMINISTIC
Tools + Guardrails → Whitelist • Freshness • Data Sourcing Notes
↓
💾 REPORT ARTIFACT
Markdown Report
↓
🤖 AI / PROBABILISTIC
Podcaster Agent → Report → Host Script
↓
📱 EXTERNAL ACTION
edge-tts → 1–4 Neural Voices
↓
💾 AUDIO ARTIFACT
MP3 Podcast
↓
👤 USER OUTPUT
```

### Tech stack:

• Python — workflow and application logic  
• Google ADK 1.22.1 — multi-agent orchestration  
• LiteLLM — LLM integration  
• Ollama Cloud / gpt-oss:120b — reasoning, research and writing  
• FastAPI + Uvicorn — API/server  
• Vanilla HTML/CSS/JavaScript — UI  
• ddgs / DuckDuckGo — web research  
• yfinance — financial context  
• edge-tts — neural TTS  
• faster-whisper — local speech-to-text  
• OpenAI ↔ Ollama Proxy — format bridge  
• python-dotenv — configuration  
• Markdown / MP3 / JSON — artifacts/configuration

### What is different:

Agents plan; tools perform the real work. ADK callbacks enforce domain whitelists and freshness and drive UI progress from actual tool events rather than model claims.

### Value:

Transforms research prompts, meeting transcripts and recordings into finished reports and/or podcasts through one workflow.  
Provides visible execution progress, auditable sourcing, configurable hosts/languages and local audio transcription.

### Technical explanation:

A producer agent orchestrates research/report generation and delegates audio to a podcaster sub-agent through AgentTool. Deterministic tools perform search, financial retrieval, file creation and TTS, while callbacks enforce research constraints. The Audio Summary path bypasses agents and runs faster-whisper in an isolated subprocess.

