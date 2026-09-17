---
title: "Data Entities"
type: entity
tags: [agilepoint, data-entities, data-storage, data-modeling, database]
created: 2026-04-16
updated: 2026-04-16
sources: 2
---

# Data Entities

**Type**: Module — Built-in Data Storage  
**Parent**: [[nx-portal]]

## What It Is

Data Entities is the built-in data management module within [[agilepoint-nx]]. It provides a structured, database-style storage system accessible directly from the platform — without requiring an external database for most use cases.

## Data Structure Model

| Database Term | Data Entities Equivalent |
|---------------|--------------------------|
| Table | Entity |
| Column | Field |
| Row | Record |

## Entity Types

| Type | Description |
|------|-------------|
| Standard Entities | Built-in entities provided by the platform (system data) |
| Custom Entities | User-defined entities for application-specific data |

## Key Capabilities

- Visual entity design without SQL or database expertise
- Support for multiple field types: text, number, date, boolean, lookup, etc.
- Define relationships between entities using Dependent fields
- Integrates seamlessly with [[app-builder]] for application data requirements
- Accessible from [[page-builder]] for dynamic portal pages

## Relationships

- Lives within [[nx-portal]]
- Configured via [[settings]]
- Supplies data to applications built in [[app-builder]]
- Can be visualized on pages created in [[page-builder]]

## Source Pages

- [[agilepoint-platform-overview]]
- [[agilepoint-nx-data-entities]]
