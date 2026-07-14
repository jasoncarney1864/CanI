# CanI Platform — Architecture Design Document (Living Draft)

**Status:** Draft — in progress
**Last updated:** 2026-07-13
**Owner:** Solo developer
**Purpose:** Working design document for the CanI hub-and-spoke RAG platform, built iteratively, section by section.

This document is split into one file per section. Start with [Vision & goals](01-vision-and-goals.md) or jump to any section below.

## Contents

1. [Vision & goals](01-vision-and-goals.md)
2. [Requirements](02-requirements.md)
3. [High-level architecture](03-high-level-architecture.md)
4. [Key architectural decisions (to formalize as ADRs)](04-key-architectural-decisions.md)
5. [Roadmap — sections still to design](05-roadmap.md)
6. [Azure Landing Zone design](06-azure-landing-zone-design.md)
7. [Identity & access (CanI Hub)](07-identity-and-access.md)
8. [RAG pipeline design (CanI Docs)](08-rag-pipeline-design.md)
9. [Data model & storage](09-data-model-and-storage.md)
10. [AKS cluster design](10-aks-cluster-design.md)
11. [IaC strategy](11-iac-strategy.md)
12. [CI/CD strategy](12-cicd-strategy.md)
13. [Observability](13-observability.md)
14. [Security & compliance](14-security-and-compliance.md)
15. [Cost management](15-cost-management.md)
16. [Roadmap & phasing](16-roadmap-and-phasing.md)

Appendices:
- [Appendix A — Glossary](appendix-a-glossary.md)
- [Appendix B — ADR log](adr/README.md)

Implementation (v1 core loop, `feat/v1-core-loop-checkpoint`):
- [Implementation status](implementation-status.md) — delivered vs. scaffolded vs. deferred, mapped to sections 7-16
- [PR summary](pr-summary-v1-core-loop.md)
