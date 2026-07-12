# 2. Requirements

### Functional
- Users create an account and authenticate once at the hub, then access whichever spokes they're entitled to.
- Users upload personal documents/images (PDF, scans, photos) into a spoke, starting with CanI Docs.
- Documents are parsed, chunked, embedded, and indexed for retrieval.
- Users ask natural-language questions; answers are grounded strictly in their own uploaded documents (no general knowledge injection), with citations back to the source document/section.
- CanI Legal and CanI Health reuse the same core RAG engine, specialized by prompt, taxonomy, and document classification per domain.
- The hub manages authentication, authorization (which spokes/documents a user can access), and routing.
- The platform adds new spokes without re-architecting the hub.

### Non-functional
- **Security & privacy first** — uploaded documents may contain sensitive personal/health data. Treat as sensitive PII even though CanI is not a HIPAA-covered entity.
- **Multi-tenant isolation** — one user must never retrieve another user's document chunks, even via prompt injection or embedding collision.
- **Cost-aware** — solo-funded project; every "always-on" resource is a recurring personal expense.
- **Learning-optimized** — prefer architectures that build transferable skills (AKS, ALZ, Pulumi, GitHub Actions, Azure Monitor) even where a simpler PaaS path exists.
- Availability/scale targets are intentionally modest for v1 — this is not designed for enterprise-scale traffic yet.

### Constraints
- Solo developer, no team.
- Existing Azure subscription, no Landing Zone deployed yet.
- IaC must be Pulumi, Python.
- Compute must include AKS (explicit choice, not the "right-sized" tool — that's fine, it's the point).
- CI/CD via GitHub Actions, source in GitHub repos.
- Budget not yet defined — open item, to revisit in the Cost section.

---

[← Vision & goals](01-vision-and-goals.md) | [Back to index](README.md) | Next: [High-level architecture →](03-high-level-architecture.md)
