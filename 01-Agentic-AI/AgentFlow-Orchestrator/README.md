# AgentFlow — Dynamic Multi-Agent Workflow & Skill Orchestrator

> A dynamic multi-agent orchestration platform where an LLM converts user intent into a structured agent workflow, obtains approval, executes it through tools, evaluates the result and saves successful workflows as reusable skills.

## What This Project Demonstrates

- Dynamic LLM workflow planning (intent → structured agent plan)
- DAG-based agent orchestration
- Human-in-the-loop approval before execution
- Evaluator/reviewer stage after execution
- Reusable, versioned skill workflows

## Why This Project Exists

Demonstrates dynamic multi-agent orchestration where the workflow is generated from user intent rather than being hard-coded into a fixed sequence of agents.

## Architecture

*To be verified against source code — diagram to be added from verified behavior.*

## Workflow

*To be verified from code.*

## Technology Stack

| Area | Technology |
|---|---|
| LLM | Ollama Cloud (gpt-oss:120b via LiteLLM) |
| AI Framework | Google ADK |
| Backend | FastAPI |
| Frontend | React |
| Database | SQLite |

*To be verified against the project's requirements files.*

## Demo

*Screenshots/demo assets to be added when project code is copied into this repository.*

## How to Run

*To be verified from the project's actual installation and execution instructions.*

## Key AI Engineering Concepts

- Dynamic workflow generation (vs. fixed multi-agent hierarchy)
- Structured plans + approval gates
- DAG execution
- Skill reuse

## Safety / Reliability

- User approval before execution (verified)
- Permission levels + approval gates (to be verified against policy module)

## Testing / Evaluation

*To be verified — existing test suite to be identified and documented.*

## How This Project Differs

Dynamic workflow generation rather than a fixed multi-agent hierarchy — the agent plan is generated per task, not predefined.

## AI-Assisted Development

This project was developed using AI-assisted coding workflows. Architecture, implementation decisions, testing, debugging and validation were reviewed and refined during development.