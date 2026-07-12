# ADR-004: Hand-build the Azure Landing Zone in Pulumi (no ALZ accelerator)

**Status:** Accepted
**Date:** 2026-07-11

**Context:** CanI needs the governance/network foundation an Azure Landing Zone provides (management groups, policy, hub-spoke networking, centralized logging), but the owner's existing subscription has none of this yet. Microsoft's ALZ accelerator (Bicep, or a Terraform variant) is the standard way to bootstrap this, but it's a second IaC tool separate from Pulumi.

**Decision:** Implement the ALZ conceptual architecture directly in Pulumi Python — no accelerator run. We'll design a scaled-down "ALZ-lite" management group hierarchy sized for a solo project rather than a full enterprise-scale tree, and author the baseline policies ourselves (using Microsoft's published ALZ policy definitions as reference material, not as an imported deployment tool).

**Consequences:**
- All platform IaC lives in one language/tool — cleaner mental model, easier to reason about as a solo dev.
- We lose the accelerator's pre-built policy library and pipeline — that governance code has to be designed and written (see [Section 6: Azure Landing Zone design](../06-azure-landing-zone-design.md)). This is more upfront work, but it's concentrated, transferable Pulumi + Azure Policy learning.
- The management group hierarchy will be intentionally lean (a handful of groups, not the reference architecture's full tree) — right-sized for one developer, not a large org.
- Revisit if the project ever needs to onboard other people/teams — a hand-rolled ALZ is harder to keep current with Microsoft's evolving guardrails than the accelerator is.

---

[← ADR log](README.md)
