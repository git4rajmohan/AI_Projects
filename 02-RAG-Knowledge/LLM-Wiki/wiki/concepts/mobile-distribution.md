---
title: "Mobile Distribution"
type: concept
tags: [mobile-distribution, app-stores, enterprise-distribution, emm]
created: 2026-04-16
updated: 2026-04-16
sources: 4
---

# Mobile Distribution

**Type**: Deployment Pattern

## Definition

Mobile Distribution describes the methods used to deliver custom mobile applications built with the [[mobile-app-accelerator]] to end users. AgilePoint NX supports two primary distribution paths: public app stores and enterprise-internal distribution.

## Distribution Methods

### Public App Store Distribution
- Publish apps to Apple App Store and Google Play
- End users download via standard store install process
- Automatic updates via store update mechanism
- Best for: broad user bases, external users, customer-facing apps

### Enterprise Distribution
- Distribute internally via Enterprise Mobile Management (EMM) systems or private app stores
- EMM: enforce security policies, manage installation/updates/access on employee devices
- Private stores: curated internal catalog, restricted to authorized personnel
- Best for: internal enterprise apps, security-controlled environments, regulated industries

## Decision Factors

| Factor | Public Stores | Enterprise Distribution |
|--------|---------------|------------------------|
| Audience | External or public | Internal employees only |
| Control | Low (store-managed) | High (IT-managed) |
| Security | Standard | Enforced policies |
| Update control | Store auto-update | IT-controlled rollout |

## Entities Using This Concept

[[mobile-app-accelerator]] · [[mobile-app]]

## Source Pages

- [[agilepoint-mobile-capabilities-overview]]
- [[agilepoint-nx-mobile-app-accelerator]]
- [[agilepoint-nx-app-store-distribution]]
- [[agilepoint-nx-enterprise-distribution]]
