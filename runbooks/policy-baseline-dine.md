# Deploy-if-not-exists Key Vault diagnostics (Sprint 2 D1, §6.3)

The baseline governance policy set has four parts. Three (allowed locations, required
tags, storage TLS) are plain policy assignments and live in IaC
(`infra/modules/security.py::BaselineGovernancePolicies`) — the CI deploy identity has the
policy-write rights to apply them.

The fourth, **deploy-if-not-exists (DINE) Key Vault diagnostics**, is applied here by hand
because Azure only lets an **Owner or User Access Administrator** create a policy
assignment that carries a managed identity and grant that identity its remediation roles.
The CI service principal is intentionally **Contributor-only** (least privilege), so this
is a one-time elevated step run by an operator — the same pattern §6.6 uses for the
management-group bootstrap. It is idempotent: re-running updates in place.

## Prerequisites

- Signed in as an operator with Owner (or User Access Administrator) on the subscription.
- Git Bash on Windows mangles `/`-leading ARM ids into local paths — every command below
  sets `MSYS_NO_PATHCONV=1` to prevent that. (Symptom if you forget: a `MissingSubscription`
  error, or a scope like `C:/Program Files/Git/subscriptions/...`.)

## Apply

```bash
export MSYS_NO_PATHCONV=1
SUB=6591cee6-ee26-4155-ae71-3777bf7e9c73
WS="/subscriptions/$SUB/resourceGroups/cani-platform-core-dev-eastus2-rg1227b5a0/providers/Microsoft.OperationalInsights/workspaces/cani-central-law2b7b024f"

# 1. Assign the built-in DINE policy with a system-assigned identity (subscription scope —
#    all resources live here; the az CLI has a resolve bug for built-ins at MG scope).
az policy assignment create \
  --name cani-dine-kv-diag \
  --display-name "CanI - deploy Key Vault diagnostics" \
  --policy 951af2fa-529b-416e-ab6e-066fd85ac459 \
  --scope "/subscriptions/$SUB" \
  --mi-system-assigned --location eastus2 \
  --params "{\"logAnalytics\":{\"value\":\"$WS\"},\"diagnosticsSettingNameToUse\":{\"value\":\"cani-kv-diagnostics\"},\"effect\":{\"value\":\"DeployIfNotExists\"}}"

# 2. Grant the assignment's identity the roles its remediation task needs.
PID=$(az policy assignment show --name cani-dine-kv-diag --scope "/subscriptions/$SUB" \
  --query identity.principalId -o tsv)
for role in "Monitoring Contributor" "Log Analytics Contributor"; do
  az role assignment create --assignee-object-id "$PID" \
    --assignee-principal-type ServicePrincipal --role "$role" --scope "/subscriptions/$SUB"
done
```

## Verify

```bash
export MSYS_NO_PATHCONV=1
SUB=6591cee6-ee26-4155-ae71-3777bf7e9c73
PID=$(az policy assignment show --name cani-dine-kv-diag --scope "/subscriptions/$SUB" \
  --query identity.principalId -o tsv)
az role assignment list --assignee "$PID" --all --query "[].roleDefinitionName" -o tsv
# expect: Monitoring Contributor, Log Analytics Contributor
```

New Key Vaults then get diagnostics auto-configured to the central workspace; existing
ones show non-compliant until a remediation task runs
(`az policy remediation create --name kv-diag --policy-assignment cani-dine-kv-diag`).

## Reference

- Policy: `951af2fa-529b-416e-ab6e-066fd85ac459` — "Deploy - Configure diagnostic settings
  for Azure Key Vault to Log Analytics workspace".
- Roles: Monitoring Contributor `749f88d5-cbae-40b8-bcfc-e573ddc772fa`,
  Log Analytics Contributor `92aaf0da-9dab-42b6-94a3-d43ce8d16293`.
