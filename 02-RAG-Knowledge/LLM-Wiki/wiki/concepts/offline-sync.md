---
title: "Offline Sync"
type: concept
tags: [offline, sync, mobile, connectivity, field-operations]
created: 2026-04-16
updated: 2026-04-16
sources: 3
---

# Offline Sync

**Type**: Platform Capability / User Workflow

## Definition

Offline Sync is the capability of [[mobile-app]] to function without an active internet connection and to automatically synchronize locally captured data back to [[agilepoint-server]] when connectivity is restored.

## How It Works

1. **User goes offline** — disconnected from network or AgilePoint Server
2. **Work continues** — eForms can be accessed, filled, and submitted
3. **Local queuing** — Submitted data is stored in an offline outbox on the device
4. **Reconnect** — When network connectivity returns, the device detects the connection
5. **Auto-sync** — Queued submissions are automatically sent to AgilePoint Server
6. **Consistency restored** — Central system updated; workflow progresses normally

## Use Cases

- Field operations workers in areas with unreliable connectivity
- Remote employees outside network coverage
- Regulated industries requiring task completion independent of connectivity
- Travel or inspection workflows where internet access is intermittent

## Constraints and Behaviors

- Forms must have been loaded while online (pre-cached) to be available offline
- Data remains in local queue until sync completes successfully
- Conflict resolution managed by [[agilepoint-server]] on sync

## Entities Using This Concept

[[mobile-app]] · [[agilepoint-server]]

## Source Pages

- [[agilepoint-mobile-app-overview]]
- [[agilepoint-nx-mobile-offline-support]]
- [[agilepoint-ios-support]]
