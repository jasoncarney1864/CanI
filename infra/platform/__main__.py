"""CanI platform landing zone (docs/06-azure-landing-zone-design.md, docs/11-iac-strategy.md).

Not applied this session (no live Azure subscription in this environment) — see the
launch-readiness gap report. §6.6 bootstrapping note applies: management-group-scope
resources require an interactive `pulumi up` under an "elevated access" admin session
the first time; after that, the platform GitHub identity holds a narrower permanent role.
"""

import sys
from pathlib import Path

import pulumi
import pulumi_azure_native as azure_native

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.naming import NamingContext, base_tags
from modules.networking import HubNetwork
from modules.observability import CentralLogAnalytics
from modules.data_services import SharedContainerRegistry
from modules.security import DenyPublicNetworkPolicies, PlatformKeyVault

config = pulumi.Config()
environment = pulumi.get_stack()  # "dev" | "prod"
tenant_id = config.require("tenantId")
owner = config.get("owner") or "solo-operator"

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
        parent=azure_native.management.CreateManagementGroupDetailsParentGroupIdArgs(id=root_mg.id)
    ),
)
landing_zones_mg = azure_native.management.ManagementGroup(
    "cani-landing-zones-mg",
    group_id="cani-landing-zones",
    details=azure_native.management.CreateManagementGroupDetailsArgs(
        parent=azure_native.management.CreateManagementGroupDetailsParentGroupIdArgs(id=root_mg.id)
    ),
)
workload_mg = azure_native.management.ManagementGroup(
    "cani-workload-mg",
    group_id="cani-workload",
    details=azure_native.management.CreateManagementGroupDetailsArgs(
        parent=azure_native.management.CreateManagementGroupDetailsParentGroupIdArgs(id=landing_zones_mg.id)
    ),
)
sandbox_mg = azure_native.management.ManagementGroup(
    "cani-sandbox-mg",
    group_id="cani-sandbox",
    details=azure_native.management.CreateManagementGroupDetailsArgs(
        parent=azure_native.management.CreateManagementGroupDetailsParentGroupIdArgs(id=root_mg.id)
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

acr = SharedContainerRegistry(
    "cani-shared",
    resource_group_name=resource_group.name,
    tags=tags,
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
pulumi.export("acr_login_server", acr.registry.login_server)
pulumi.export("acr_id", acr.registry.id)
pulumi.export("platform_key_vault_id", platform_vault.vault.id)
pulumi.export("workload_management_group_id", workload_mg.id)
