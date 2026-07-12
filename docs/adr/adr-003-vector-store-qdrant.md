# ADR-003: Self-host Qdrant on AKS as the vector store

**Status:** Accepted
**Date:** 2026-07-11

**Context:** CanI Docs needs a vector store for embedding retrieval. Options were Azure AI Search (managed, native Azure OpenAI integration), Postgres Flexible Server + pgvector (managed, cheaper, more portable), or a self-hosted OSS vector DB (Qdrant/Weaviate) on AKS.

**Decision:** Self-host Qdrant on AKS.

**Consequences:**
- Requires a StatefulSet with persistent storage (Azure Disk-backed PVCs) — real hands-on AKS stateful-workload experience.
- We own backup/restore (Qdrant snapshots to Blob Storage) and upgrades — no managed SLA to lean on.
- Qdrant has no built-in per-tenant auth model, so per-user isolation must be enforced at the application layer (collection-per-user or payload-filtered queries with mandatory tenant-id filters on every read) — this becomes a hard requirement in the RAG pipeline and data model sections, not a nice-to-have.
- Network policy must restrict Qdrant to only be reachable from the CanI Docs backend pods, never exposed externally or to other spokes directly.
- Revisit if query latency or operational load becomes a burden — Azure AI Search remains the fallback with the least migration pain (Postgres+pgvector would be a bigger rewrite).

---

[← ADR log](README.md)
