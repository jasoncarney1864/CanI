"""CanI platform landing zone (docs/06-azure-landing-zone-design.md, docs/11-iac-strategy.md).

Applied to the `dev` stack on 2026-07-14 (Sprint 1, B1) — live status in
docs/implementation-status.md. §6.6 bootstrapping note: management-group-scope resources
required the one-time interactive `pulumi up` under an "elevated access" admin session
(completed); the platform GitHub identity now holds the narrower permanent role.
"""

import sys
from pathlib import Path

import pulumi
import pulumi_azure_native as azure_native

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.alerting import OpsAlerting
from modules.cost import SubscriptionBudget
from modules.data_services import SharedContainerRegistry
from modules.naming import NamingContext, base_tags
from modules.networking import HubNetwork
from modules.observability import ApplicationInsights, CentralLogAnalytics
from modules.security import BaselineGovernancePolicies, DenyPublicNetworkPolicies, PlatformKeyVault

config = pulumi.Config()
environment = pulumi.get_stack()  # "dev" | "prod"
tenant_id = config.require("tenantId")
owner = config.get("owner") or "solo-operator"
# Dev stopgap (see docs/implementation-status.md): GitHub-hosted runners push images
# over ACR's public endpoint until private networking for CI lands, so dev sets
# publicDataEndpoints=true. Stacks that leave it unset get the secure default (Disabled).
public_data_endpoints = "Enabled" if config.get_bool("publicDataEndpoints") else "Disabled"
# §15.3 monthly cost budget (USD). Config-driven so the cap moves without a code change.
monthly_budget_usd = config.get_float("monthlyBudgetUsd") or 200.0

naming = NamingContext(project="platform", layer="core", environment=environment)
tags = base_tags(environment=environment, owner=owner, spoke="platform")

resource_group = azure_native.resources.ResourceGroup(
    naming.resource_name("rg"),
    tags=tags,
)

# Management group hierarchy per §6.1. Requires the one-time elevated-access bootstrap
# described in §6.6 before the platform GitHub identity can apply this unattended.
root_mg = azure_native.management.ManagementGroup("cani-root-mg", group_id="cani-root")
platform_mg = azure_native.management.ManagementGroup(
    "cani-platform-mg",
    group_id="cani-platform",
    details=azure_native.management.CreateManagementGroupDetailsArgs(
        parent=azure_native.management.CreateParentGroupInfoArgs(id=root_mg.id)
    ),
)
landing_zones_mg = azure_native.management.ManagementGroup(
    "cani-landing-zones-mg",
    group_id="cani-landing-zones",
    details=azure_native.management.CreateManagementGroupDetailsArgs(
        parent=azure_native.management.CreateParentGroupInfoArgs(id=root_mg.id)
    ),
)
workload_mg = azure_native.management.ManagementGroup(
    "cani-workload-mg",
    group_id="cani-workload",
    details=azure_native.management.CreateManagementGroupDetailsArgs(
        parent=azure_native.management.CreateParentGroupInfoArgs(id=landing_zones_mg.id)
    ),
)
sandbox_mg = azure_native.management.ManagementGroup(
    "cani-sandbox-mg",
    group_id="cani-sandbox",
    details=azure_native.management.CreateManagementGroupDetailsArgs(
        parent=azure_native.management.CreateParentGroupInfoArgs(id=root_mg.id)
    ),
)

policies = DenyPublicNetworkPolicies("cani-platform-policies", management_group_id=platform_mg.id)

hub_network = HubNetwork(
    "cani-hub",
    resource_group_name=resource_group.name,
    tags=tags,
)

log_analytics = CentralLogAnalytics(
    "cani-central",
    resource_group_name=resource_group.name,
    tags=tags,
    # Runaway-source circuit breaker, not a throttle. Raised 3 -> 5 GB after the initial
    # 3 GB tripped on the pre-trim kube-audit backlog and, while OverQuota, silently
    # dropped the very telemetry the alerts fire on (Sprint 2 A2). Steady state after the
    # AKS diagnostic-category trim is ~1.5-2 GB/day, so 5 GB leaves headroom for a traffic
    # burst (when visibility matters most) while still catching a genuine runaway like the
    # 5.78 GB/day leak that trim fixed. Cost is bounded further by B1 budget alerts.
    daily_quota_gb=5,
)

app_insights = ApplicationInsights(
    "cani-central",
    resource_group_name=resource_group.name,
    workspace_id=log_analytics.workspace.id,
    tags=tags,
)

# §6.3 baseline governance policy set (Sprint 2 D1): allowed locations, required tags,
# TLS, and deploy-if-not-exists Key Vault diagnostics — assigned at platform MG scope.
baseline_policies = BaselineGovernancePolicies(
    "cani-baseline",
    management_group_id=platform_mg.id,  # full ARM id for assignment / role scopes
    management_group_name=platform_mg.name,  # group id string for the policy definition
    workspace_id=log_analytics.workspace.id,
    location=config.get("location") or "eastus2",
    allowed_locations=["eastus2"],
)

ops_alert_email = config.require("opsAlertEmail")

ops_alerting = OpsAlerting(
    "cani-ops",
    resource_group_name=resource_group.name,
    location=resource_group.location,
    workspace_id=log_analytics.workspace.id,
    alert_email=ops_alert_email,
    tags=tags,
)

# §15.3 subscription monthly budget with 50/75/90/100% burn alerts (+ forecasted 100%).
# Subscription-scoped, so it does not depend on the resource group and is unaffected by the
# Log Analytics daily cap that can pause telemetry.
subscription_budget = SubscriptionBudget(
    "cani-dev",
    subscription_id=azure_native.authorization.get_client_config().subscription_id,
    monthly_amount=monthly_budget_usd,
    alert_email=ops_alert_email,
    start_date="2026-07-01T00:00:00Z",
)

acr = SharedContainerRegistry(
    "cani-shared",
    resource_group_name=resource_group.name,
    tags=tags,
    public_network_access=public_data_endpoints,
)

platform_vault = PlatformKeyVault(
    "cani-platform",
    resource_group_name=resource_group.name,
    tenant_id=tenant_id,
    tags=tags,
)

# Stable output contract consumed by cani-workload via StackReference (§11.6).
pulumi.export("hub_vnet_id", hub_network.vnet.id)
pulumi.export("log_analytics_workspace_id", log_analytics.workspace.id)
pulumi.export(
    "app_insights_connection_string",
    pulumi.Output.secret(app_insights.component.connection_string),
)
pulumi.export("acr_login_server", acr.registry.login_server)
pulumi.export("acr_id", acr.registry.id)
pulumi.export("platform_key_vault_id", platform_vault.vault.id)
pulumi.export("workload_management_group_id", workload_mg.id)
pulumi.export("ops_action_group_id", ops_alerting.action_group.id)
pulumi.export("monthly_budget_id", subscription_budget.budget.id)
