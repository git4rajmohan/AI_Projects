---
title: "AgilePoint Server"
type: entity
tags: [agilepoint, server, backend, process-engine]
created: 2026-04-16
updated: 2026-04-16
sources: 2
---

# AgilePoint Server

**Type**: Infrastructure / Backend Engine

## What It Is

AgilePoint Server is the core backend processing engine of the [[agilepoint-nx]] platform. It executes and manages all workflow processes and system operations. End users never interact with it directly — it operates as the invisible foundation that powers everything in the platform.

## Key Responsibilities

- **Process Orchestration** — Controls workflow execution paths and process logic
- **Task Execution** — Creates and completes work items; ensures proper assignment and processing
- **Event Processing** — Responds to system and user-generated events; triggers actions on workflow conditions
- **Integration** — Connects to external databases, APIs, and enterprise services
- **Security & Authentication** — Manages user authentication and access control
- **Data Processing** — Handles data flow within workflows

## Runtime Components Managed

| Component | Description |
|-----------|-------------|
| Process Instances | Active workflow executions |
| Work Items | Individual tasks within workflows |
| System Events | Triggers and background operations |

## Relationships

- Powers all modules in [[nx-portal]]
- Receives offline sync data from [[mobile-app]]
- Integrates with external systems (SharePoint, Salesforce, databases, APIs)

## Source Pages

- [[agilepoint-platform-overview]]
- [[agilepoint-server-overview]]
- [[agilepoint-nx-mobile-offline-support]]
