# ADR-008: Store vectors in Postgres (pgvector), retiring Qdrant

**Status:** Accepted
**Date:** 2026-11-07
**Supersedes:** [ADR-003](adr-003-vector-store-qdrant.md)

**Context:** ADR-003 chose self-hosted Qdrant on AKS for the hands-on learning value of a
stateful AKS workload. That rationale is gone: the platform consolidated onto Azure Container
Apps (commit `25a8899`), and Qdrant moved first to an Azure Files share and then to Qdrant
Cloud's free tier. Along the way it produced the one real data-loss incident in the project's
history (`docs/sitreps/2026-08-09-qdrant-corruption-and-missing-backups.md`): a second
datastore with its own backup job that was defined in IaC but never applied, and a
point-count-vs-`chunk_manifests` reconciliation that the repository could never record as
closed. The 2026-11 rebuild targets the lowest possible monthly cost in a fresh subscription,
and the corpus is tens of thousands of chunks at most.

Options reconsidered:

| Option | Monthly cost | Notes |
|---|---|---|
| pgvector on the Postgres Flexible Server already in the bill of materials | $0 extra | HNSW index; DiskANN available on the same server if it ever outgrows HNSW |
| Qdrant Cloud free tier | $0 | External to Azure, second store to back up, free clusters can be paused when idle |
| Azure AI Search | ~$75 (Basic, the lowest production tier) | Hybrid + semantic ranking are real quality gains, but three times the whole rebuild budget; the free tier has no SLA and a 50 MB cap |
| Cosmos DB vector search | a few dollars serverless | Another service and data model for no gain at this scale |

**Decision:** Put the embeddings in the same Postgres database as everything else, using the
`vector` extension. Migration `0009_pgvector.sql` adds `chunk_embeddings` and
`law_chunk_embeddings`; `cani_shared.vector.store.OwnerScopedVectorStore` and
`cani_shared.vector.public_law_store.PublicLawVectorStore` replace the Qdrant wrappers with
the same seven-method surface, so the ingestion, deletion, retrieval, and law-refresh paths
did not change shape.

**Consequences:**
- A chunk's vector and its `chunk_manifests` row commit in the same transaction, and
  document deletion removes vectors inside the deletion job's transaction. The reconciliation
  the August incident left open no longer exists as a concept.
- The Postgres backup covers the vectors. The snapshot job, its blob container, and
  `runbooks/backup-restore-drill.md`'s Qdrant procedure are retired.
- Owner scoping is a `WHERE owner_user_id = %s` clause, enforced in the wrapper exactly as
  before (fail closed on a missing owner, re-verify every returned row). The access-boundary
  test now asserts that nothing outside the two wrappers names the embeddings tables.
- The embedding column is untyped (`vector`, no fixed width); the configured embedder's
  width is enforced at runtime by `ensure_collection()`, which refuses to run against rows of
  a different width and builds a width-specific HNSW expression index. This preserves the
  fakes-in-prod tripwire (CLAUDE.md) that the Qdrant wrapper had.
- Azure Database for PostgreSQL Flexible Server must allow-list the extension (server
  parameter `azure.extensions` includes `VECTOR`) before migration 0009 can run. The local
  compose image is `pgvector/pgvector:pg16`.
- Retrieval quality is unchanged: cosine similarity over the same embeddings, same top-k
  budgets per corpus. Hybrid (keyword + vector) search remains a future option via Postgres
  full-text search on the same table, with no new service.
- Revisit only if the corpus grows past what a Burstable-tier HNSW index serves comfortably
  (hundreds of thousands of chunks); the first step then is DiskANN on the same server, not a
  new store.

---

[← ADR log](README.md)
