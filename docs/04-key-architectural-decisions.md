# 4. Key architectural decisions (to formalize as ADRs)

Flagged now; each gets a full ADR (context / options / trade-offs / decision) when we drill into its section.

1. **CanI Docs topology** — shared platform spoke called by Legal/Health over an API, vs. embedded config-driven engine within one deployment.
2. **AKS cluster topology** — one shared cluster with per-spoke namespaces (cheaper, strong multi-tenancy learning) vs. cluster-per-environment vs. cluster-per-spoke.
3. **Vector store ([ADR-003](adr/adr-003-vector-store-qdrant.md), Accepted)** — Self-hosted Qdrant on AKS. Chosen over Azure AI Search and Postgres+pgvector for maximum hands-on AKS/ops learning value. See [Appendix B](adr/README.md).
4. **ALZ approach ([ADR-004](adr/adr-004-hand-built-alz.md), Accepted)** — Hand-built ALZ conceptual architecture (management groups, policy, hub-spoke network) entirely in Pulumi Python; no Microsoft ALZ accelerator tooling. See [Appendix B](adr/README.md).
5. **Repo strategy** — monorepo (hub + spokes + shared platform + infra in one repo) vs. polyrepo. Leaning monorepo for solo velocity; final call in the IaC/CI-CD section.
6. **Document intake pipeline** — sync vs. async ingestion (upload → OCR/parse → chunk → embed → index), and how failures/retries are handled.
7. **Data sensitivity handling ([ADR-007](adr/adr-007-phi-pii-data-posture.md), Accepted)** — PHI/PII-grade handling as the default posture for all documents, regardless of formal HIPAA applicability. See [Appendix B](adr/README.md).

---

[← High-level architecture](03-high-level-architecture.md) | [Back to index](README.md) | Next: [Roadmap →](05-roadmap.md)
