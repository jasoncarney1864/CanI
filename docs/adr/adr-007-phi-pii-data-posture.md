# ADR-007: PHI/PII-grade handling as the default data posture

**Status:** Accepted
**Date:** 2026-07-11

**Context:** CanI is not a HIPAA-covered entity and has no BAA obligations, but it stores personal legal and health documents that are functionally as sensitive as PHI.

**Decision:** Treat all uploaded documents — legal and health alike — as PHI/PII-sensitive by default, everywhere, rather than adding protections only where a specific rule requires them.

**Consequences (to be threaded through every later section, not solved here):**
- Encryption at rest and in transit for every data store (Blob Storage, Qdrant's persistent volumes, any metadata DB), with Key Vault-managed keys and customer-managed keys (CMK) where Azure supports them.
- Private endpoints for all data services — Storage, Key Vault, and Qdrant reachable only inside the workload landing zone's network, never over the public internet.
- Per-user data isolation enforced at multiple layers: application authorization, mandatory tenant-id filtering at the data-access layer, and network policy — not authorization checks alone.
- Raises baseline cost and operational complexity everywhere (private endpoints, a private-ish AKS networking posture, CMK/Key Vault dependencies on nearly every component) — accepted as a deliberate trade-off given the data sensitivity, not something to relax later without re-architecting.
- This will be formalized into an explicit threat model in the Security & compliance section, and into concrete controls (partition keys, network policies, RBAC) in the Data model and AKS sections.

---

[← ADR log](README.md)
