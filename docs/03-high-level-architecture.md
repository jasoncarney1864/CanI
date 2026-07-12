# 3. High-level architecture

## 3.1 Logical / application view — hub and spoke

CanI Hub owns identity, authorization, and routing — it has no domain logic of its own. CanI Docs is a shared platform spoke: it owns the generic capability of "RAG over personal documents" (ingestion, chunking, embeddings, vector search, grounded Q&A, citations). CanI Legal and CanI Health are thin vertical spokes that call into CanI Docs, adding domain-specific document classification, taxonomy, and prompt specialization on top of the shared engine — they should not duplicate ingestion/retrieval logic.

**Open design question** (to resolve in the CanI Docs deep dive): should CanI Legal / CanI Health be genuinely separate deployable services that call CanI Docs over an internal API, or thin configuration layers within CanI Docs itself (same deployment, domain selected by tag)? This affects the AKS topology, the data model, and how much independence future verticals get.

## 3.2 Physical / Azure infrastructure view

Two landing zones (as subscriptions, or resource-group groupings to start if you'd rather stay single-subscription initially):

- **Platform landing zone** — governance, hub networking, centralized logging (Log Analytics), shared registry (ACR), Key Vault for platform secrets. Changes rarely.
- **Workload landing zone** — the AKS cluster and the AI/data services the apps depend on (Azure OpenAI, vector store, Blob Storage, Document Intelligence). Changes constantly.

GitHub Actions deploys into the workload landing zone using Pulumi with OIDC federated credentials — no long-lived Azure secrets stored in GitHub.

---

[← Requirements](02-requirements.md) | [Back to index](README.md) | Next: [Key architectural decisions →](04-key-architectural-decisions.md)
