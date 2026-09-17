# Generic Agentic AI Workflow Platform
## Master Implementation Instructions

## 1. Project Objective

Build a generic Agentic AI Workflow Platform that converts a user's natural-language intent into an executable, reusable AI workflow.

Core lifecycle:

User Intent
→ Intent Understanding
→ Skill Discovery
→ Dynamic Planning
→ Plan Presentation
→ User Approval
→ Agent Assembly
→ Workflow Orchestration
→ Tool Execution
→ Memory
→ Evaluation
→ Final Result
→ Optional Skill Creation
→ Skill Library
→ Future Skill Reuse

The platform must not be designed around fixed business use cases. It must provide generic primitives supporting research, data analysis, coding, QA/testing, document processing, RAG evaluation, business analysis, web research, automation, reporting, multi-step workflows, human approval workflows, and reusable skills.

The user should be able to say:

> "I want to accomplish X."

The system determines how X can be accomplished, generates a plan, asks for approval, executes the plan, evaluates the result, and optionally saves the successful workflow as a reusable skill.

---

# 2. Core Design Principle

Do not build a collection of hard-coded agents.

Build a generic:

- Agent Runtime
- Workflow Engine
- Planning Engine
- Skill System
- Tool Registry
- Memory System
- Evaluation System
- Policy/Permission System
- Observability/Event System

The Planner dynamically determines:

- Number of agents
- Name and role of each agent
- Goal of each agent
- Required tools
- Required skills
- Required memory
- Dependencies
- Parallel vs sequential execution
- Human approval requirements
- Evaluation criteria
- Expected output
- Estimated cost
- Estimated execution time
- Risk level

For simple requests, use the minimum number of agents required.

Example:

"Convert this CSV to Excel."

Prefer:

File Processing Agent
→ Excel Output

Do not create unnecessary multi-agent workflows.

For complex requests, dynamically create multiple agents.

---

# 3. Core Concepts

## 3.1 User

The person interacting with the platform.

## 3.2 Intent

Natural-language description of what the user wants.

Example:

"Analyze these Excel files and explain why revenue declined."

## 3.3 Task

A concrete execution instance created from an intent.

## 3.4 Plan

A structured description of how a task will be completed.

A plan contains:

- Objective
- Agents
- Skills
- Tools
- Memory
- Workflow
- Dependencies
- Evaluation
- Permissions
- Estimated cost
- Estimated duration
- Approval requirements

## 3.5 Agent

An execution actor responsible for a specific goal.

An agent contains:

- ID
- Name
- Description
- Goal
- Model
- System prompt
- Tools
- Skills
- Memory
- Input schema
- Output schema
- Dependencies
- Permissions
- Iteration limits
- Timeout
- Evaluation criteria

## 3.6 Tool

An external capability used by agents.

Examples:

- Python
- File reader
- File writer
- Web search
- HTTP request
- SQL
- Browser
- GitHub
- Excel
- Database
- Terminal

A tool performs an external action.

## 3.7 Skill

A reusable capability or workflow.

A skill is NOT merely a prompt.

A skill can contain:

- Agents
- Prompts
- Tools
- Workflow
- Input schemas
- Output schemas
- Evaluation criteria
- Permissions
- Configuration
- Tests

Example:

"Excel Sales Analysis"

may internally use:

Data Agent
→ Analysis Agent
→ Report Agent

## 3.8 Workflow

An executable graph containing:

- Agents
- Tools
- Conditions
- Dependencies
- Human approval gates
- Retry behavior

## 3.9 Execution

One runtime instance of a workflow.

## 3.10 Memory

Information available to agents.

Initially support:

1. Working memory
2. Long-term memory
3. Skill memory

## 3.11 Evaluation

Assessment of whether the workflow achieved the user's objective.

## 3.12 Policy

Rules controlling what an agent is allowed to do.

---

# 4. High-Level Architecture

                         ┌──────────────────────┐
                         │       FRONTEND       │
                         │ Chat / Plan / Skills │
                         └───────────┬──────────┘
                                     │
                                     ▼
                         ┌──────────────────────┐
                         │   INTENT MANAGER     │
                         └───────────┬──────────┘
                                     │
                                     ▼
                         ┌──────────────────────┐
                         │   SKILL DISCOVERY    │
                         └───────────┬──────────┘
                                     │
                                     ▼
                         ┌──────────────────────┐
                         │   PLANNING ENGINE    │
                         └───────────┬──────────┘
                                     │
                                     ▼
                         ┌──────────────────────┐
                         │    PLAN APPROVAL     │
                         └───────────┬──────────┘
                                     │
                                     ▼
                         ┌──────────────────────┐
                         │     AGENT FACTORY    │
                         └───────────┬──────────┘
                                     │
                                     ▼
                     ┌────────────────────────────┐
                     │    ORCHESTRATION ENGINE    │
                     └──────────────┬─────────────┘
                                    │
             ┌──────────────────────┼──────────────────────┐
             ▼                      ▼                      ▼
      ┌─────────────┐        ┌─────────────┐        ┌─────────────┐
      │ Agent       │        │ Tool        │        │ Memory      │
      │ Runtime     │        │ Runtime     │        │ Manager     │
      └─────────────┘        └─────────────┘        └─────────────┘
             │                      │                      │
             └──────────────────────┼──────────────────────┘
                                    ▼
                         ┌──────────────────────┐
                         │  EVALUATION ENGINE   │
                         └───────────┬──────────┘
                                     │
                          ┌──────────┴───────────┐
                          ▼                      ▼
                    FINAL RESULT          SKILL CANDIDATE
                                                 │
                                                 ▼
                                      ┌──────────────────────┐
                                      │    SKILL LIBRARY     │
                                      └──────────────────────┘

---

# 5. Recommended Technology Stack

## Backend

Use:

- Python 3.11+
- FastAPI
- Pydantic
- SQLAlchemy
- SQLite initially
- asyncio
- httpx
- pytest

Design database models so migration to PostgreSQL is straightforward.

## Frontend

Use:

- React
- TypeScript
- Vite

Initial UI areas:

- Chat
- Plan
- Execution
- Skills
- Agents
- Tools
- Settings

Do not over-engineer visual design before runtime correctness.

---

# 6. LLM Abstraction

Do not hard-code a single LLM provider.

Create:

LLMProvider
├── OpenAIProvider
├── OllamaProvider
├── AnthropicProvider
└── MockProvider

At minimum support:

- OpenAI-compatible API
- Ollama
- Mock LLM for automated tests

The core system must be model-provider independent.

---

# 7. Repository Structure

Use approximately:

agentic-platform/
├── backend/
│   └── app/
│       ├── main.py
│       ├── api/
│       │   ├── routes_tasks.py
│       │   ├── routes_plans.py
│       │   ├── routes_skills.py
│       │   ├── routes_agents.py
│       │   ├── routes_tools.py
│       │   ├── routes_execution.py
│       │   └── routes_approvals.py
│       ├── core/
│       │   ├── config.py
│       │   ├── logging.py
│       │   └── security.py
│       ├── models/
│       │   ├── agent.py
│       │   ├── skill.py
│       │   ├── tool.py
│       │   ├── plan.py
│       │   ├── task.py
│       │   ├── execution.py
│       │   ├── memory.py
│       │   └── evaluation.py
│       ├── planner/
│       │   ├── planner.py
│       │   ├── intent.py
│       │   └── plan_validator.py
│       ├── agents/
│       │   ├── base_agent.py
│       │   ├── agent_factory.py
│       │   └── agent_runtime.py
│       ├── orchestration/
│       │   ├── engine.py
│       │   ├── dag.py
│       │   ├── scheduler.py
│       │   └── state.py
│       ├── skills/
│       │   ├── registry.py
│       │   ├── loader.py
│       │   ├── validator.py
│       │   ├── versioning.py
│       │   └── discovery.py
│       ├── tools/
│       │   ├── registry.py
│       │   ├── base_tool.py
│       │   └── builtins/
│       ├── memory/
│       │   ├── manager.py
│       │   ├── working_memory.py
│       │   └── long_term_memory.py
│       ├── evaluation/
│       │   ├── evaluator.py
│       │   └── metrics.py
│       └── llm/
│           ├── base.py
│           ├── openai.py
│           ├── ollama.py
│           └── mock.py
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/
│   │   ├── types/
│   │   └── App.tsx
│   └── package.json
├── skills/
│   └── builtin/
├── data/
│   ├── skills/
│   ├── executions/
│   └── memory/
├── tests/
├── docs/
├── docker-compose.yml
├── .env.example
├── README.md
└── instruction.md

---

# 8. Core Data Models

Use Pydantic models for API and runtime schemas.

## AgentSpec

```python
class AgentSpec(BaseModel):
    id: str
    name: str
    description: str
    goal: str

    model: str
    system_prompt: str

    tools: list[str]
    skills: list[str]
    memory_scopes: list[str]

    input_schema: dict
    output_schema: dict

    dependencies: list[str]

    max_iterations: int = 5
    max_tool_calls: int = 20
    timeout_seconds: int = 300

    requires_human_approval: bool = False
```

## SkillSpec

```python
class SkillSpec(BaseModel):
    id: str
    name: str
    description: str
    version: str

    inputs: dict
    outputs: dict

    agents: list[str]
    tools: list[str]

    workflow: dict

    evaluation: dict

    permissions: dict

    author: str | None = None
    tags: list[str] = []

    enabled: bool = True
```

## ToolSpec

```python
class ToolSpec(BaseModel):
    id: str
    name: str
    description: str

    input_schema: dict
    output_schema: dict

    permission_level: str

    enabled: bool = True
```

Every tool must expose structured input/output schemas.

---

# 9. Plan Model

The Planner MUST return structured JSON.

Example:

```json
{
  "task_id": "task-123",
  "objective": "Analyze sales data and identify revenue decline drivers",
  "summary": "Analyze sales trends, affected segments, products, and create a report.",
  "agents": [
    {
      "id": "data_agent",
      "name": "Data Analyst",
      "goal": "Analyze sales trends",
      "tools": ["python", "excel"],
      "skills": [],
      "dependencies": []
    },
    {
      "id": "customer_agent",
      "name": "Customer Analyst",
      "goal": "Identify customer segments responsible for decline",
      "tools": ["python"],
      "skills": [],
      "dependencies": ["data_agent"]
    }
  ],
  "workflow": {
    "type": "dag"
  },
  "memory": {
    "scope": "task"
  },
  "evaluation": {
    "criteria": [
      "accuracy",
      "completeness"
    ]
  },
  "permissions": {},
  "estimated_cost": 0.5,
  "estimated_duration_seconds": 180,
  "requires_approval": true
}
```

Validate plans using Pydantic.

Do not depend on free-form LLM output for executable plans.

---

# 10. Planner Responsibilities

The Planner must:

1. Understand intent.
2. Identify required output.
3. Identify constraints.
4. Search Skill Registry.
5. Determine whether an existing skill can solve the task.
6. Determine whether an existing skill partially solves the task.
7. Determine required agents.
8. Determine required tools.
9. Determine required memory.
10. Determine dependencies.
11. Determine parallelizable operations.
12. Determine evaluation criteria.
13. Determine human approval requirements.
14. Estimate complexity.
15. Estimate cost.
16. Estimate execution time.
17. Generate structured Plan JSON.

The Planner must not directly execute tools.

Planning and execution must remain separate.

---

# 11. Skill Discovery

Before creating dynamic agents, search the Skill Registry.

Flow:

User Intent
→ Skill Discovery
→ Existing Skill?
    → YES: Reuse / Adapt / Compose
    → NO: Generate New Plan

If an existing skill is a strong match, prefer it over generating a new workflow.

If multiple skills match, the Planner can compose them.

Example:

Excel Analysis Skill
+
Financial Analysis Skill
+
Report Generation Skill

→ Composite Workflow

---

# 12. Agent Blueprint

Introduce an intermediate Agent Blueprint.

The Planner first produces the blueprint.

Example:

Agent Blueprint

Task:
Generate quarterly business report

Agents:

1. DataCollector
   Goal: Collect KPI data
   Tools: SQL, Excel

2. Analyst
   Goal: Analyze KPIs
   Tools: Python
   Depends on: DataCollector

3. ReportWriter
   Goal: Create report
   Tools: Document generator
   Depends on: Analyst

Memory:
Task Memory

Orchestration:
DAG

Evaluation:
Accuracy + completeness

Estimated cost:
$0.42

Estimated time:
3 minutes

Only after user approval should the Agent Factory create executable agents.

---

# 13. Agent Factory

The Agent Factory converts AgentSpec into an executable Agent.

Responsibilities:

- Resolve model
- Resolve tools
- Resolve skills
- Initialize memory
- Validate permissions
- Validate dependencies
- Create runtime
- Initialize state
- Apply limits

All dynamic agents must pass through the Agent Factory.

---

# 14. Agent Runtime

Use a common interface:

```python
class Agent:
    async def run(self, context) -> AgentResult:
        ...
```

Runtime responsibilities:

1. Receive context.
2. Load memory.
3. Load skills.
4. Load tools.
5. Execute model interaction.
6. Validate output.
7. Execute tools.
8. Store tool results.
9. Update memory.
10. Return structured AgentResult.

Limits:

- max iterations
- max tool calls
- timeout

---

# 15. Orchestration Engine

Implement a DAG-based workflow engine.

Support:

## Sequential

A → B → C

## Parallel

A
├── B
├── C
└── D

## Merge

B + C + D
→ E

## Conditional

A
→ IF
    → true: B
    → false: C

## Retry

A
→ failure
→ retry

## Human Approval

A
→ approval
→ B

The orchestrator must track dependencies and state.

---

# 16. Execution State

Persist execution state.

Example:

```json
{
  "task_id": "task-123",
  "status": "running",
  "current_nodes": ["agent_2", "agent_3"],
  "completed_nodes": ["agent_1"],
  "failed_nodes": [],
  "outputs": {},
  "events": []
}
```

Critical state must not exist only in process memory.

Execution should be recoverable after application restart.

---

# 17. Event System

Generate events:

- TASK_CREATED
- PLAN_CREATED
- PLAN_APPROVED
- PLAN_REJECTED
- AGENT_CREATED
- AGENT_STARTED
- AGENT_COMPLETED
- AGENT_FAILED
- TOOL_STARTED
- TOOL_COMPLETED
- TOOL_FAILED
- HUMAN_APPROVAL_REQUIRED
- HUMAN_APPROVED
- HUMAN_REJECTED
- TASK_COMPLETED
- TASK_FAILED
- EVALUATION_STARTED
- EVALUATION_COMPLETED
- SKILL_CREATED
- SKILL_VERSION_CREATED

Store events in the database.

Events power the execution dashboard.

---

# 18. Memory Architecture

## Working Memory

Specific to one task.

Contains:

- user intent
- plan
- agent outputs
- tool results
- intermediate state
- decisions
- errors

## Long-Term Memory

Persistent information.

Initially use database-backed storage.

Do not over-engineer vector memory in the MVP.

## Skill Memory

Stores reusable workflow definitions.

Skill memory is separate from personal user memory.

---

# 19. Tool Registry

Implement:

```python
tool_registry.register(tool)
tool_registry.get(tool_id)
tool_registry.list()
tool_registry.remove(tool_id)
```

Initial tools:

- FileReader
- FileWriter
- PythonExecutor
- WebSearch
- HttpRequest
- Calculator

Later support:

- SQL
- GitHub
- Browser
- Excel
- Google Drive
- Email
- Slack
- Databases

Do not hard-code tools into agents.

Agents reference tools by ID.

---

# 20. Tool Security

Permission levels:

- READ
- WRITE
- EXTERNAL_ACTION
- DESTRUCTIVE

Examples:

- FileReader → READ
- ExcelWriter → WRITE
- GitHubCreatePR → EXTERNAL_ACTION
- DeleteFile → DESTRUCTIVE

Policy Engine must validate every tool execution.

Never allow destructive operations without appropriate authorization.

---

# 21. Policy Engine

Implement a centralized Policy Engine.

Evaluate:

- user permissions
- agent permissions
- tool permissions
- skill permissions
- task risk
- destructive operations
- external communication
- sensitive operations

Example:

Agent wants to send an email.

Policy:
EXTERNAL_ACTION + human approval required.

Workflow pauses.

---

# 22. Human-in-the-Loop

Support approval gates.

Example:

Agent wants to send 25 emails.

WAITING FOR APPROVAL

[Approve]
[Reject]

Approval pauses the workflow rather than terminating it.

After approval:

PAUSED
→ APPROVED
→ RESUME

---

# 23. Evaluation Engine

Every workflow should optionally be evaluated.

Evaluator input:

- Original Intent
- Plan
- Agent Outputs
- Tool Results
- Final Output
- Evaluation Criteria

Return:

```json
{
  "success": true,
  "score": 0.91,
  "criteria": {
    "accuracy": 0.95,
    "completeness": 0.88,
    "format": 1.0
  },
  "issues": [],
  "recommendations": []
}
```

Do not expose hidden chain-of-thought.

Expose only concise evaluation summaries and observable execution information.

---

# 24. Replanning

If evaluation fails:

Execution
→ Evaluation
→ Failure
→ Replanner
→ Modified Plan
→ Execution

Default:

MAX_REPLANS = 2

Never allow infinite planning loops.

---

# 25. Skill Creation

After successful execution, determine whether the workflow appears reusable.

Consider:

- multi-step workflow
- successful execution
- repeatable pattern
- reusable inputs/outputs
- likely future repetition
- user request

Then show:

"This workflow appears reusable. Would you like to save it as a skill?"

[Create Skill]
[Not Now]

Do not automatically persist skills without user approval in the MVP.

---

# 26. Skill Content

When creating a skill, store:

- Name
- Description
- Version
- Inputs
- Outputs
- Agents
- Tools
- Workflow
- Prompts
- Schemas
- Evaluation criteria
- Permissions
- Dependencies
- Tests
- Metadata

Initial version:

1.0.0

---

# 27. Skill Versioning

Use semantic versioning:

- 1.0.0
- 1.1.0
- 2.0.0

Never destroy old versions.

Support:

- Activate
- Deactivate
- Rollback
- Duplicate
- Export
- Import

Track:

- usage count
- success rate
- last used
- average duration
- evaluation score

---

# 28. Skill Import

Support:

.skill.zip

Example:

my_skill/
├── skill.yaml
├── agents/
├── prompts/
├── workflows/
├── schemas/
├── tests/
└── README.md

Import pipeline:

Upload
→ Extract
→ Validate
→ Security Scan
→ Dependency Check
→ Preview
→ User Approval
→ Install

Never execute an uploaded skill before validation.

---

# 29. Skill YAML Format

Example:

```yaml
name: sales-analysis
version: 1.0.0

description: >
  Analyze sales data and generate an executive report.

inputs:
  - name: input_file
    type: file

outputs:
  - name: report
    type: document

agents:
  - data_analyst
  - report_writer

tools:
  - python
  - excel

workflow:
  type: dag

evaluation:
  criteria:
    - accuracy
    - completeness

permissions:
  file_read: true
  file_write: true
  network: false
```

---

# 30. Skill Validation

Validate:

- Manifest
- Schema
- Required tools
- Required agents
- Dependencies
- Permissions
- Workflow
- Input/output definitions
- Version
- Tests

Reject invalid skills.

---

# 31. Skill Testing

Skills may contain tests.

Example:

```yaml
tests:
  - name: basic_sales_analysis
    input: test_data/sales.csv
    expected:
      required_sections:
        - revenue
        - trends
        - recommendations
```

Before activation:

Install
→ Validate
→ Run tests
→ Pass
→ Activate

---

# 32. Skill Composition

Skills must be composable.

Example:

Excel Analysis Skill
+
Financial Analysis Skill
+
Report Generation Skill

→ Composite Workflow

The Planner should be able to combine existing skills instead of rebuilding their logic.

---

# 33. Frontend — Chat

Main screen:

┌──────────────────────────────────────────────┐
│ Agentic AI Platform                          │
├──────────────────────────────────────────────┤
│ What do you want to accomplish?              │
│                                              │
│ [ Analyze these Excel files and explain     │
│   why revenue declined.                    ] │
│                                              │
│              [ Generate Plan ]               │
└──────────────────────────────────────────────┘

---

# 34. Frontend — Plan View

Display:

OBJECTIVE

Analyze sales data and identify revenue decline drivers.

AGENTS

1. Data Analyst
   Goal: Analyze sales trends
   Tools: Python, Excel

2. Customer Analyst
   Goal: Identify affected customer segments
   Tools: Python

3. Report Writer
   Goal: Create final report

WORKFLOW

Data Analyst
├── Customer Analyst
├── Product Analyst
└── Report Writer

SKILLS

Sales Analysis v2

ESTIMATED COST

$0.42

ESTIMATED TIME

~3 minutes

Buttons:

[Modify Plan]
[Approve & Execute]

---

# 35. Frontend — Execution View

Display live progress:

TASK #123

✓ Intent understood
✓ Plan created
✓ Plan approved
✓ Data Analyst
✓ Customer Analysis
● Product Analysis
○ Report Writer

Progress: 68%

Allow expansion of each node showing:

- status
- duration
- tool calls
- outputs
- errors
- retry count

Do not display hidden chain-of-thought.

---

# 36. Frontend — Skill Library

Features:

- Search
- Filter
- Create
- Upload
- Export
- Run
- Edit
- Duplicate
- Enable
- Disable
- Version management
- Delete

Display:

- Skill name
- Version
- Description
- Usage count
- Success rate
- Last used
- Required tools
- Permissions

---

# 37. Frontend — Agent Registry

Display:

- Agent
- Purpose
- Model
- Tools
- Skills
- Status
- Usage
- Success Rate

Support:

- Create
- Edit
- Clone
- Disable

---

# 38. Frontend — Tool Registry

Display:

- Tool
- Description
- Permission
- Provider
- Status

Support:

- Enable
- Disable
- Configure

---

# 39. Model Routing

Create a model abstraction now.

Later the Planner can select models based on:

- complexity
- cost
- latency
- task type
- reasoning requirements
- coding requirements

Example:

Simple task → fast inexpensive model
Complex planning → reasoning model
Coding → coding model
Summarization → fast model

For MVP use one configurable model while preserving the abstraction.

---

# 40. Observability

Every execution must have a timeline.

Example:

09:21:04 Intent received
09:21:05 Plan generated
09:21:17 User approved
09:21:20 ResearchAgent started
09:21:34 Web search executed
09:21:42 ResearchAgent completed
09:21:43 AnalystAgent started
09:22:10 Python executed
09:22:32 AnalystAgent completed
09:22:33 ReviewerAgent started
09:22:45 Validation passed
09:22:46 Task completed

Every event should contain:

- timestamp
- task_id
- execution_id
- agent_id
- event_type
- duration
- status
- error

---

# 41. Logging

Use structured logging.

Never log:

- API keys
- passwords
- access tokens
- secrets

Use correlation IDs:

- task_id
- execution_id
- agent_id
- tool_call_id

---

# 42. Error Handling

Handle:

- timeout
- network failure
- invalid model output
- schema validation failure
- authentication failure
- tool failure
- LLM failure
- rate limiting
- dependency failure

Default retry:

max_retries = 2
exponential_backoff = true

Retry behavior must be configurable.

---

# 43. Loop Protection

Every agent must have:

- max_iterations
- max_tool_calls
- timeout

Every workflow must have:

- max_execution_time
- max_replans
- max_total_tool_calls

Never allow runaway workflows.

---

# 44. Database

Initially use SQLite.

Tables approximately:

- users
- tasks
- plans
- agents
- agent_executions
- skills
- skill_versions
- tools
- workflows
- workflow_nodes
- executions
- execution_events
- memory
- evaluations
- approval_requests

Use SQLAlchemy.

Design for PostgreSQL migration.

---

# 45. API Endpoints

Implement approximately:

POST /api/tasks
GET  /api/tasks/{id}

POST /api/plans
GET  /api/plans/{id}
POST /api/plans/{id}/approve
POST /api/plans/{id}/reject

POST /api/tasks/{id}/execute
POST /api/tasks/{id}/cancel

GET /api/executions/{id}
GET /api/executions/{id}/events

GET  /api/skills
POST /api/skills
GET  /api/skills/{id}
PUT  /api/skills/{id}
DELETE /api/skills/{id}

POST /api/skills/upload
POST /api/skills/{id}/run
POST /api/skills/{id}/export

GET /api/agents
POST /api/agents

GET /api/tools
POST /api/tools

POST /api/approvals/{id}/approve
POST /api/approvals/{id}/reject

---

# 46. Built-in Agents

Initially provide:

- PlannerAgent
- ResearchAgent
- DataAnalysisAgent
- CodingAgent
- ReviewerAgent
- ReportAgent

These should be generic.

The system must still dynamically create additional agents.

---

# 47. Built-in Tools

Initially provide:

- FileReader
- FileWriter
- PythonExecutor
- WebSearch
- HttpRequest
- Calculator

---

# 48. Built-in Skills

Provide demonstration skills:

- Web Research
- Excel Analysis
- Document Summarization
- Data Cleaning
- Report Generation

These demonstrate the Skill system.

Do not hard-code their execution into the core orchestrator.

---

# 49. Important Architectural Rules

1. Do not hard-code business workflows into the orchestration engine.
2. Do not hard-code specific agents into workflows.
3. Do not couple the system to a single LLM provider.
4. Do not couple skills to a single model.
5. Do not allow tools to execute without permission validation.
6. Do not depend on free-form LLM output when structured schemas are possible.
7. Persist workflow state.
8. Make execution observable.
9. Separate planning from execution.
10. Separate skills from agents.
11. Separate tools from skills.
12. Keep the orchestration engine model-independent.
13. Do not expose hidden chain-of-thought.
14. Do not execute uploaded skills before validation.
15. Do not allow destructive operations without appropriate approval.
16. Prefer reuse of existing skills before creating new workflows.
17. Prefer the minimum number of agents required.
18. Keep all runtime components replaceable.
19. Use interfaces and dependency injection where appropriate.
20. Do not put business-specific assumptions into core abstractions.

---

# 50. Development Phases

Do not implement everything at once.

## Phase 1 — Foundation

Implement:

- project structure
- FastAPI
- React frontend
- SQLite
- SQLAlchemy
- configuration
- LLM abstraction
- Pydantic schemas
- basic database models

Acceptance:

Backend starts.
Frontend starts.
Database initializes.

## Phase 2 — Intent + Planning

Implement:

User Intent
→ Planner
→ Structured Plan
→ Plan UI

No actual multi-agent execution required yet.

Acceptance:

User enters:

"Analyze these Excel files."

System returns a structured plan containing:

- agents
- tools
- skills
- dependencies
- memory
- evaluation
- estimated cost/time

## Phase 3 — Agent Runtime

Implement:

- BaseAgent
- AgentFactory
- AgentRuntime
- ToolRegistry
- Basic tools

Acceptance:

One agent can execute a task using a tool.

## Phase 4 — Orchestration

Implement:

- DAG
- Sequential execution
- Parallel execution
- Conditional execution
- Retry
- State persistence

Acceptance:

A multi-agent workflow executes successfully.

## Phase 5 — Skill System

Implement:

- SkillSpec
- Skill Registry
- Skill Discovery
- Skill execution
- Skill creation
- Skill versioning

Acceptance:

Successful workflow can be saved as a skill and reused.

## Phase 6 — Evaluation

Implement:

- Evaluation Engine
- Scoring
- Evaluation criteria
- Failure detection
- Replanning

Acceptance:

A failed workflow can be evaluated and replanned.

## Phase 7 — Human Approval

Implement:

- Approval requests
- Pause
- Resume
- Approve
- Reject

Acceptance:

Workflow can pause before an external/destructive action and resume after approval.

## Phase 8 — Skill Import/Export

Implement:

- .skill.zip
- YAML manifest
- validation
- dependency checking
- security checks
- preview
- installation

Acceptance:

A skill exported from one environment can be imported into another.

## Phase 9 — Advanced Features

Only after MVP stability:

- Vector memory
- Advanced model routing
- Skill recommendation
- Skill marketplace
- Workflow optimization
- Agent benchmarking
- Cost optimization
- Distributed execution
- Remote agents
- External connectors
- Multi-user support

---

# 51. Mandatory Demo Scenarios

## Demo 1 — Simple Task

User:

"Convert this CSV into an Excel file."

Expected:

1 agent
FileReader
FileWriter

No unnecessary agents.

## Demo 2 — Multi-Agent Research

User:

"Research five AI testing tools and compare them."

Expected:

Planner
→ 5 parallel research tasks
→ Comparison Agent
→ Report Agent

## Demo 3 — Skill Reuse

First run:

"Research five AI testing tools and compare them."

Save as:

"AI Testing Tool Comparison"

Second run:

"Compare these five AI testing tools."

Expected:

Skill Discovery
→ Existing Skill Found
→ Reuse
→ Execute

## Demo 4 — Human Approval

User:

"Generate emails for these customers and prepare them for sending."

Expected:

Generate
→ Human Approval
→ Send

The system must not send before approval.

## Demo 5 — Failure Recovery

Create a workflow containing an intentionally failing tool.

Expected:

Tool Failure
→ Retry
→ Recovery
→ Continue

## Demo 6 — Skill Upload

Upload:

example.skill.zip

Expected:

Upload
→ Validate
→ Security Check
→ Preview
→ Install
→ Run

---

# 52. Advanced Use Cases

The architecture should eventually support:

## Research

- Competitive analysis
- Market research
- Technology comparison
- Literature review
- Vendor evaluation
- Product comparison
- Patent research
- Regulatory research

## Data

- Excel analysis
- CSV processing
- Data cleaning
- KPI analysis
- Anomaly detection
- Forecasting
- Dashboard generation
- Reconciliation

## Software

- Code generation
- Code review
- Unit tests
- Bug fixing
- Documentation
- GitHub workflows
- Pull request creation

## QA

- Test case generation
- Test automation
- Regression execution
- Failure analysis
- Root cause analysis
- Bug creation

## RAG

- RAG evaluation
- Retrieval analysis
- Chunking analysis
- Embedding comparison
- Citation validation
- Hallucination detection

## Documents

- PDF analysis
- Contract comparison
- Document extraction
- Report generation
- Policy analysis
- Resume processing

## Business

- Sales analysis
- Customer churn analysis
- Marketing analysis
- Financial analysis
- Management reporting

## Operations

- Incident analysis
- Log analysis
- Infrastructure troubleshooting
- Monitoring

## Manufacturing

- Sensor analysis
- Anomaly detection
- Predictive maintenance
- Machine monitoring

The core engine must remain generic.

---

# 53. Example Complex Workflows

## Example A — Sales Analysis

User:

"Analyze my company's sales data and explain why revenue dropped."

Possible plan:

Data Agent
→ Customer Segment Agent
→ Product Analysis Agent
→ Anomaly Detection Agent
→ Synthesis Agent
→ Report Agent

## Example B — Software Development

User:

"Create a REST API for employee management."

Possible plan:

Requirements Agent
→ Architecture Agent
→ Coding Agent
→ Test Agent
→ Security Agent
→ Code Review Agent
→ Documentation Agent

## Example C — QA

User:

"Create automated test cases for this application."

Possible plan:

Requirement Agent
→ Scenario Agent
→ Test Case Agent
→ Risk Agent
→ Automation Agent
→ Execution Agent
→ Failure Analysis Agent
→ Report Agent

## Example D — RAG Evaluation

User:

"Evaluate my RAG system using this test dataset."

Possible plan:

Dataset Agent
→ RAG Execution Agent
→ Citation Agent
→ Relevancy Agent
→ Correctness Agent
→ Hallucination Agent
→ Score Agent
→ Report Agent

## Example E — Manufacturing

User:

"Find abnormal machine behavior and recommend maintenance."

Possible plan:

Data Collection
→ Data Quality
→ Anomaly Detection
→ Trend Analysis
→ Failure Prediction
→ Root Cause
→ Maintenance Recommendation

---

# 54. Skill Discovery and Reuse

The planning pipeline should always prefer:

USER INTENT
→ UNDERSTAND
→ SEARCH SKILL LIBRARY
→ Existing Skill?
    → YES → Reuse
    → NO → Generate Plan
→ User Approval
→ Execute
→ Evaluate
→ Ask to Save as Skill

This prevents unnecessary regeneration.

---

# 55. Skill Composition

Example:

Excel Analysis Skill
+
Financial Analysis Skill
+
Management Report Skill

→ Composite Workflow

Skills must be treated as reusable building blocks.

---

# 56. Skill Quality Metrics

Track:

- Usage count
- Success rate
- Average execution time
- Average cost
- Evaluation score
- User rating if provided
- Last used
- Failure count
- Version

Example:

Skill:
Sales Analysis

Version:
1.3.0

Usage:
42

Success rate:
95.2%

Average duration:
2m 14s

Average cost:
$0.18

Evaluation score:
4.7/5

---

# 57. Skill Optimization

Future feature.

When a skill repeatedly fails or becomes expensive, the system may recommend:

- prompt changes
- agent changes
- model changes
- tool changes
- workflow changes
- additional validation
- parallelization

Do not automatically modify production skills in the MVP.

Use:

New Version
→ Test
→ Compare
→ Activate

---

# 58. Skill Marketplace — Future

Eventually support:

- Public/private skills
- Author
- Version
- Rating
- Usage
- Dependencies
- Permissions
- Compatibility
- Examples
- Evaluation score

Potential categories:

- Data
- Research
- QA
- Coding
- RAG
- Documents
- Business
- DevOps
- Automation

---

# 59. Testing Strategy

Write unit tests for:

- intent parser
- planner
- plan schema
- plan validator
- agent factory
- agent runtime
- tool registry
- tool permissions
- skill registry
- skill discovery
- skill loader
- skill validator
- skill versioning
- orchestrator
- sequential execution
- parallel execution
- conditional execution
- retry
- state recovery
- memory
- evaluator
- replanning
- human approval
- skill import
- skill export

Create a mandatory integration test:

Intent
→ Plan
→ Approval
→ Agent Creation
→ Execution
→ Evaluation
→ Skill Creation
→ Skill Reuse

---

# 60. Security Requirements

Treat agents as untrusted execution actors.

Implement:

- tool permissions
- skill permissions
- approval gates
- execution limits
- timeouts
- retry limits
- tool call limits
- file access restrictions
- network restrictions where possible
- secret protection
- uploaded skill validation

Never expose secrets to LLM prompts unnecessarily.

Never put API keys directly into prompts.

---

# 61. Definition of Done

The MVP is complete only when this complete loop works:

User enters intent
→ System understands intent
→ System searches existing skills
→ System creates structured plan
→ UI displays plan
→ User approves
→ Agent Factory creates agents
→ Orchestrator executes workflow
→ Tools execute
→ Memory stores state
→ Execution events appear in UI
→ Evaluator evaluates result
→ Final result displayed
→ System asks whether workflow should be saved as a skill
→ User approves
→ Skill created and versioned
→ User submits similar request later
→ Skill Discovery finds skill
→ Skill reused

This complete loop is the primary acceptance criterion.

---

# 62. Development Rules for the Coding Agent

Implement incrementally.

After every phase:

1. Run tests.
2. Fix errors.
3. Verify application starts.
4. Verify APIs.
5. Verify frontend.
6. Verify database.
7. Update documentation.
8. Do not proceed if the current phase is broken.

Do not generate huge amounts of untested code.

Do not create fake placeholder functionality that appears functional but does nothing.

If something is not implemented, expose a clear controlled "Not Implemented" state.

Prefer small, testable modules.

Use dependency injection and interfaces where appropriate.

Keep provider-specific code isolated.

---

# 63. Recommended Execution Interfaces

Use interfaces similar to:

```python
class Agent:
    async def run(self, context) -> AgentResult:
        ...


class Tool:
    async def execute(self, input) -> ToolResult:
        ...


class Skill:
    async def execute(self, input) -> SkillResult:
        ...


class Planner:
    async def create_plan(self, intent) -> Plan:
        ...


class Orchestrator:
    async def execute(self, plan) -> ExecutionResult:
        ...


class Evaluator:
    async def evaluate(self, task, result) -> EvaluationResult:
        ...
```

Implementations must remain replaceable.

---

# 64. Final Architectural Separation

Maintain these responsibilities strictly:

Planner
= decides WHAT should happen

Agent Factory
= decides WHO performs each role

Orchestrator
= decides WHEN and HOW workflow nodes execute

Agent Runtime
= performs reasoning and task execution

Tool Runtime
= performs external actions

Memory Manager
= provides contextual information

Policy Engine
= decides WHAT the agent is allowed to do

Evaluator
= determines WHETHER the objective was achieved

Skill Manager
= stores and reuses successful workflows

UI
= allows the user to understand, approve, control and observe execution

---

# 65. Final Product Vision

The goal is not:

"Build a multi-agent chatbot."

The goal is:

"Build a generic system that converts natural-language intent into executable, evaluated and reusable AI workflows."

Fundamental platform primitives:

- Intent
- Task
- Plan
- Agent
- Tool
- Skill
- Workflow
- Memory
- Execution
- Evaluation
- Policy
- Event

Everything else should be built on these primitives.

The system should be:

- Model-independent
- Tool-independent
- Skill-independent
- Business-domain-independent
- Extensible
- Observable
- Testable
- Secure
- Recoverable

The same engine should eventually handle:

"Analyze this Excel file."

"Research five competitors."

"Create automated test cases."

"Evaluate my RAG system."

"Build a Python application."

"Analyze customer complaints."

"Create a financial report."

"Investigate this application failure."

"Analyze machine sensor data."

"Create a reusable workflow for this task."

without requiring a new hard-coded workflow for each use case.

The ultimate objective is to create an extensible Agent Operating System / Agent Factory where successful workflows can become reusable skills and skills can be composed into increasingly powerful workflows.
