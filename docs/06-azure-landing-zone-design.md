# 6. Azure Landing Zone design

Lean "ALZ-lite" — hand-built in Pulumi per [ADR-004](adr/adr-004-hand-built-alz.md), right-sized for a solo project rather than the full enterprise-scale reference tree.

## 6.1 Management group hierarchy

```
Tenant Root Group
 └─ CanI                     (root MG for the whole platform)
     ├─ Platform              — shared services, changes rarely
     ├─ Landing Zones
     │   └─ Workload          — AKS, AI services, changes constantly
     └─ Sandbox                — relaxed policy, safe experimentation
```

No separate Connectivity / Identity / Management subscriptions, no Corp / Online split — that's the textbook enterprise-scale tree, and it's overkill for one developer. Subdivide later only if CanI ever needs to onboard other people or teams.

## 6.2 Subscriptions

- **Platform subscription** (new) — hub VNet, central Log Analytics workspace, ACR, platform-level Key Vault. Isolated blast radius from anything that redeploys often.
- **Workload subscription** — the owner's existing subscription, moved under Landing Zones. Hosts AKS, Qdrant, Azure OpenAI, Storage, Document Intelligence.
- **Sandbox** — left empty for now; a place to try new Azure services under relaxed policy without touching anything that matters.

## 6.3 Policies (assigned at Platform / Landing Zones; Sandbox gets a relaxed or absent version)

Hand-authored via Pulumi's `azure-native` policy resources rather than importing the ALZ accelerator's library wholesale. Specific policy definitions can still be sourced from Microsoft's public ALZ policy repo as reference JSON where one is worth reusing.

- Required tags (`environment`, `owner`, `spoke`) on every resource
- Allowed locations — pinned to one region initially, for cost predictability and data residency
- Deny public network access on Storage accounts and Key Vaults — this is where [ADR-007](adr/adr-007-phi-pii-data-posture.md)'s "PHI-grade by default" posture gets technically enforced, not just documented
- Require TLS 1.2+ everywhere
- Require diagnostic settings routed to the central Log Analytics workspace (deploy-if-not-exists) — makes the Observability section (8) complete by construction rather than opt-in per resource
- Require Key Vault soft-delete and purge protection

## 6.4 Hub-spoke network

- **Hub VNet** `10.0.0.0/16` (Platform subscription): `NatGatewaySubnet` (`10.0.0.0/26`), `AzureBastionSubnet` (`10.0.1.0/26`), shared services / private DNS resolver (`10.0.2.0/24`)
- **Workload VNet** `10.1.0.0/16` (Workload subscription): AKS nodes (`10.1.0.0/22`), private endpoints (`10.1.4.0/24` — Key Vault, Storage, ACR, Azure OpenAI), `10.1.8.0/22`+ reserved for whatever Section 4 (AKS cluster design) decides about additional node pools or per-spoke subnets
- Peered hub ↔ workload. Private DNS zones (`privatelink.vaultcore.azure.net`, `privatelink.blob.core.windows.net`, `privatelink.azurecr.io`, `privatelink.openai.azure.com`) live in the hub and link to the workload VNet.
- **Egress: NAT Gateway, not Azure Firewall, to start.** A fraction of the cost, still gets a stable outbound IP and real NSG/subnet design experience. Azure Firewall is a reasonable *later* addition specifically as a learning exercise (policies, application rules, threat intel) once the core platform is stable — not funded from day one.
- Azure Bastion in the hub means nothing needs a public IP to be reachable for management, which matters given the PHI posture.

## 6.5 Identity & RBAC

Two federated GitHub Actions identities rather than one all-powerful service principal:
- **Platform identity** — rights scoped to the Platform management group. Used rarely (governance/network changes).
- **Workload identity** — rights scoped to the Workload management group/subscription. Used constantly (AKS, Qdrant, AI services).

This is the concrete mechanism behind the OIDC connection shown in the infrastructure diagram in [Section 3.2](03-high-level-architecture.md#32-physical--azure-infrastructure-view) — least-privilege by construction, not by policy statement.

## 6.6 Bootstrapping gotcha

Creating management groups and assigning policy at that scope requires elevated rights that even a Global Administrator doesn't have by default. One-time manual step: "Elevate access" in Entra ID (Portal → Entra ID → Properties → Access management for Azure resources), under the owner's own admin account, then run the first `pulumi up` for the platform stack interactively as that user. After that bootstrap, the Platform GitHub identity holds a narrower, permanent role at the CanI management group scope — it never needs root-level rights.

## 6.7 Pulumi project structure (preview of Section 6 in the roadmap — IaC strategy)

Two Pulumi programs: `platform` (management groups, policy, hub VNet, Log Analytics, ACR) and `workload` (VNet peering, AKS, Qdrant, AI services). `workload` reads `platform`'s outputs via `StackReference` rather than hardcoding resource IDs. This project-per-layer split holds regardless of how the monorepo/polyrepo question (open decision 5) resolves.

---

[← Roadmap](05-roadmap.md) | [Back to index](README.md) | Next: [Identity & access (CanI Hub) →](07-identity-and-access.md)
