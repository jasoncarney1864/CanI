# Runbook: dev cost review (read-only first)

The Sprint 3 closeout projected roughly $540/month against the $200 dev budget, with VMs
and Log Analytics identified as the largest drivers at that time. That snapshot predates
the Container Apps consolidation, so it is not a safe basis for resizing current resources.

## Evidence collection (no resource changes)

Run from an authenticated operator terminal. Use at least the last complete seven days;
month-to-date alone is misleading near the start of a month.

```powershell
$from = (Get-Date).ToUniversalTime().Date.AddDays(-7).ToString("yyyy-MM-dd")
$to = (Get-Date).ToUniversalTime().Date.ToString("yyyy-MM-dd")
az consumption usage list --start-date $from --end-date $to -o json `
  --query "[].{resource:instanceName,group:resourceGroup,service:consumedService,cost:pretaxCost,currency:currency}"
az consumption budget show --budget-name cani-dev-monthly -o json
```

Record the date range, total/currency, top resources, and whether any old AKS, VM, public
IP, disk, or self-hosted Qdrant resources still incur charges. Do not delete a resource
because its seven-day cost is zero; first prove it is unreferenced by deployed configuration,
DNS, backup/restore procedures, and current app dependencies.

## Decision gate

Any scale, retention, SKU, reservation, shutdown schedule, or deletion changes cloud state
or financial posture. Present the measured saving, reliability impact, rollback, and exact
resource IDs for approval before applying one. Keep the existing budget alerts active while
optimizing; an alert is a guardrail, not a spending cap.
