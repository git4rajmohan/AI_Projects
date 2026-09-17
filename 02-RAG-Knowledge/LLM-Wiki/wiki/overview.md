---
title: "Overview"
type: overview
tags: [aria, agilepoint, overview, synthesis]
created: 2026-04-16
updated: 2026-04-16
sources: 25
---

# Aria Product Wiki — Overview

*This page is the evolving synthesis of everything in the wiki. It is updated after every 3–5 new sources. It represents the current best understanding, not a permanent conclusion.*

---

## Current State

25 sources ingested (April 16, 2026). All clippings from the initial documentation set have been processed. 16 entity pages and 5 concept pages have been created. The wiki provides full coverage of the AgilePoint NX platform.

---

## What Is AgilePoint NX?

[[agilepoint-nx]] is a **low-code enterprise application platform** that enables organizations to design, automate, and manage business processes and applications without traditional software development. It serves business users, citizen developers, administrators, and IT teams within a single unified product.

Two invisible layers power the platform:
- [[agilepoint-server]] — the backend engine handling all workflow orchestration, task execution, and integrations
- [[nx-portal]] — the central web interface organizing all user-facing modules

---

## Platform Architecture

```
AgilePoint NX
├── NX Portal (Web)
│   ├── Home Page            → entry dashboard, quick launch
│   ├── Work Center          → task and process management for users
│   ├── Manage Center        → admin, runtime, access control
│   ├── App Builder          → low-code application development
│   ├── Page Builder         → visual portal page design
│   ├── Analytics Center     → reports and dashboards
│   ├── Collaboration Center → messaging, notifications, feeds
│   ├── App Store            → app marketplace and templates
│   ├── Data Entities        → built-in data storage
│   ├── Settings             → platform-wide configuration
│   └── Tour Guide           → interactive onboarding
├── AgilePoint Server (Backend)
│   └── process orchestration, task execution, event processing, integrations
└── Mobile
    ├── Mobile App           → native iOS/Android (task, approval, monitoring, offline)
    └── Mobile App Accelerator → custom-branded enterprise mobile apps
```

---

## Emerging Themes

### 1. Low-Code Is the Core Philosophy
Every user-facing capability in [[agilepoint-nx]] is designed for visual, wizard-driven interaction. [[app-builder]] uses drag-and-drop forms and process modelers. [[page-builder]] uses layout grids and widget libraries. [[data-entities]] uses visual field definitions instead of SQL. [[analytics-center]] uses a guided Report Builder. The platform consistently eliminates code as a prerequisite.

### 2. The Portal Is the Unified Hub
[[nx-portal]] is not just a navigation menu — it is the complete workspace. Different user personas operate in different areas: end users live in [[work-center]], admins operate in [[manage-center]], developers use [[app-builder]] and [[page-builder]], analysts use [[analytics-center]]. The portal boundary is intentional — all work stays inside a single product.

### 3. Mobile Is First-Class
AgilePoint NX treats mobile not as a companion but as a primary delivery channel. The [[mobile-app]] provides full task management, process monitoring, and offline capability. The [[mobile-app-accelerator]] takes this further: organizations can ship custom-branded, fully customized iOS/Android apps without writing mobile code. Two distinct distribution paths — public app stores and enterprise EMM — address both external and internal audiences.

### 4. [[offline-sync]] Enables Field Operations
Offline capability is a designed-in architectural feature, not a workaround. The [[mobile-app]] queues offline eForm submissions locally, then syncs automatically. This is a core value driver for field service, inspections, remote work, and any workflow that can't wait for connectivity.

### 5. [[agilepoint-server]] Is Invisible but Central
All runtime orchestration — process execution, task routing, event handling, integrations — flows through [[agilepoint-server]]. No module directly exposes it, but every module depends on it. Understanding its role is essential for understanding how workflows actually execute.

---

## Key Components Map

| Component | Type | Primary Purpose |
|-----------|------|-----------------|
| [[agilepoint-nx]] | Platform | The complete product |
| [[agilepoint-server]] | Backend | Workflow execution engine |
| [[nx-portal]] | Web UI | Central user interface |
| [[work-center]] | Module | User task workspace |
| [[manage-center]] | Module | Admin operations |
| [[app-builder]] | Module | App development |
| [[page-builder]] | Module | Portal page design |
| [[analytics-center]] | Module | Reports and dashboards |
| [[collaboration-center]] | Module | Communication |
| [[app-store]] | Module | App marketplace |
| [[data-entities]] | Module | Data storage |
| [[settings]] | Module | Configuration |
| [[tour-guide]] | Feature | User onboarding |
| [[mobile-app]] | Mobile | iOS/Android app |
| [[mobile-app-accelerator]] | Feature | Custom mobile app builder |

---

## Open Questions

1. **App Builder depth** — No dedicated App Builder clipping exists. Its full capabilities (workflow modeling, eForm components, conditionals, integrations) are implied but not documented in this batch.
2. **Help Center** — Referenced in the portal module list but no dedicated article exists in the current clipping set.
3. **Integrations** — The platform mentions Microsoft 365, SharePoint, Salesforce, and external APIs/databases. No dedicated integration documentation exists in this set.
4. **User Roles** — Role-based access is mentioned (Work Center, Manage Center) but no role hierarchy or permission model documentation exists in this batch.
5. **Process Modeling** — The workflow/BPM design experience (the process modeler in App Builder) has no dedicated article in this batch.
