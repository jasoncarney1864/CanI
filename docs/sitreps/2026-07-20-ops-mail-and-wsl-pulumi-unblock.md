SITREP — CanI Platform
Date: 2026-07-20 | Branch: main | Sprint: 3 (Reachability), 89% (32/36)

1. LAST COMPLETED

Unblocked the Pulumi infra apply path and routed all automated mail to a dedicated mailbox. The Pulumi azure-native plugin (an unsigned ~600 MB .exe) was blocked on Windows by Smart App Control with an "Application Control policy has blocked this file" error. SAC has no per-app allow-list and cannot be re-enabled once disabled, so rather than weaken the machine, infra now runs from WSL Ubuntu (SAC does not govern Linux binaries). WSL is set up and authenticated (Pulumi logged into the jasonbrookecarney-gmail-com backend; Azure CLI logged into the CanI subscription via the Default Directory tenant), and the exact plugin that was blocked on Windows now loads cleanly in WSL — the block is proven gone. Documented in runbooks/pulumi-from-wsl.md (PR #51). Separately, all machine-generated mail was moved off a personal Gmail to ops@canido.co (PR #50) and verified end to end.

2. WHERE WE ARE NOW

- Sprint 3 is 89% (32/36). Workstream A complete (A1, A2, A3); B and C complete (C3 shipped and verified earlier). Remaining: D1 (Key Vault CSI) and the closeout gate.
- Infra apply path unblocked via WSL: Pulumi 3.253 + Azure CLI installed and authed in Ubuntu; azure-native v3.20.0 plugin loads with no Application Control error. Windows Pulumi is still SAC-blocked by design (worked around, not "fixed") — infra commands now run through `wsl -d Ubuntu -- bash -lc '... pulumi ...'`.
- Automated mail routed to ops@canido.co and verified: Azure Monitor action group + budget (5 thresholds) via az CLI, cert-manager issuers via kubectl, GitHub (Actions failures, PRs, Dependabot) via account notification settings. A live Azure test alert was delivered to the ops mailbox (Status: Succeeded). The az-CLI updates match the committed Pulumi config, so no lasting drift.
- CanI remains live and healthy at https://app.canido.co (real Entra OIDC, in-UI upload with OCR, voice/typed query, cited answers, two-user owner-scoping) from the prior session.
- main is clean at 72d7aa2; PRs #42 through #51 all merged. One untracked earlier sitrep sits in docs/sitreps/ (left per the sitrep workflow).

3. NEXT STEPS

1. D1 — Key Vault CSI secret cutover. First set up a WSL-native Python venv for the Pulumi program (do NOT put it on the OneDrive-synced path — OneDrive churns/locks a venv). Then: install the Secrets Store CSI driver + Azure provider, wire workload identity, add a SecretProviderClass per workload, cut secrets over from plain k8s Secrets, and verify pods still read them. Runs from WSL. (Owner: Jason)
2. Sprint 3 closeout gate — final acceptance walkthrough + update implementation-status.md with Sprint 3 outcomes.
3. Optional / better long-term: move infra applies to CI (GitHub Actions Linux runner + Azure OIDC federated credentials), removing the laptop/WSL from the apply path entirely.
