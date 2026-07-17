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
from modules.data_services import SharedContainerRegistry
from modules.naming import NamingContext, base_tags
from modules.networking import HubNetwork
from modules.observability import ApplicationInsights, CentralLogAnalytics
from modules.security import DenyPublicNetworkPolicies, PlatformKeyVault

config = pulumi.Config()
environment = pulumi.get_stack()  # "dev" | "prod"
tenant_id = config.require("tenantId")
owner = config.get("owner") or "solo-operator"
# Dev stopgap (see docs/implementation-status.md): GitHub-hosted runners push images
# over ACR's public endpoint until private networking for CI lands, so dev sets
# publicDataEndpoints=true. Stacks that leave it unset get the secure default (Disabled).
public_data_endpoints = "Enabled" if config.get_bool("publicDataEndpoints") else "Disabled"

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
)

app_insights = ApplicationInsights(
    "cani-central",
    resource_group_name=resource_group.name,
    workspace_id=log_analytics.workspace.id,
    tags=tags,
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
