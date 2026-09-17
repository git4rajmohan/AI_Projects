---
title: "Process Automation"
type: concept
tags: [process-automation, workflow, bpm, orchestration]
created: 2026-04-16
updated: 2026-04-16
sources: 6
---

# Process Automation

**Type**: Platform Capability / User Workflow

## Definition

Process automation in [[agilepoint-nx]] is the orchestration of business workflows — routing tasks between people and systems, enforcing business rules, triggering actions on events, and monitoring progress to completion. It is the primary value driver of the platform.

## Core Workflow Concepts

| Concept | Description |
|---------|-------------|
| Process Instance | A single running execution of a workflow |
| Work Item / Task | An individual human action required within a workflow |
| Event | A trigger that starts or advances a process |
| Delegation | Transferring task ownership to another user |

## How It Manifests in AgilePoint NX

- **Design**: Workflows built visually using [[app-builder]]
- **Execute**: [[agilepoint-server]] orchestrates process instances end-to-end
- **Monitor (Desktop)**: [[work-center]] and [[manage-center]] show running instances and tasks
- **Monitor (Mobile)**: [[mobile-app]] provides mobile task management and process monitoring
- **Approve (Mobile)**: [[mobile-app]] supports remote task approval and rejection
- **Report**: [[analytics-center]] visualizes process performance

## Key Workflow Patterns Supported

- Approval workflows
- Multi-step review and sign-off
- Automated escalations and reminders
- Event-driven process triggers
- System-to-system process handoffs

## Entities Using This Concept

[[agilepoint-server]] · [[app-builder]] · [[work-center]] · [[manage-center]] · [[mobile-app]] · [[analytics-center]]

## Source Pages

- [[agilepoint-platform-overview]]
- [[agilepoint-server-overview]]
- [[agilepoint-nx-work-center]]
- [[agilepoint-nx-manage-center]]
- [[agilepoint-nx-mobile-process-monitoring]]
- [[agilepoint-nx-mobile-task-approval]]
