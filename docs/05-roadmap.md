# 5. Roadmap — sections still to design

1. Identity & access (CanI Hub): auth provider, tenant model, entitlements/authorization model
2. RAG pipeline design (CanI Docs): ingestion, chunking, embeddings, retrieval, grounding, citations
3. Data model & storage: per-user document isolation, metadata store, vector store schema
4. AKS cluster design: node pools, networking, workload identity, ingress, autoscaling
5. ~~Azure Landing Zone design~~ — see [Section 6](06-azure-landing-zone-design.md)
6. IaC strategy: Pulumi project/stack structure, repo layout
7. CI/CD: GitHub Actions workflows, environments, OIDC, GitOps (optional)
8. Observability: Azure Monitor, Log Analytics, Container Insights, Application Insights, alerting
9. Security & compliance: threat model, data protection, secrets management
10. Cost management: budgets, autoscaling to zero where possible, cost allocation per spoke
11. Roadmap & phasing: what ships in v1 vs. later

---

[← Key architectural decisions](04-key-architectural-decisions.md) | [Back to index](README.md) | Next: [Azure Landing Zone design →](06-azure-landing-zone-design.md)
