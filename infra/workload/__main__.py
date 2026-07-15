"""CanI workload landing zone (docs/09, docs/10, docs/11-iac-strategy.md §11.6 cross-
stack contract). Consumes cani-platform's outputs via StackReference rather than
hardcoding resource IDs. Not applied this session — see docs/implementation-status.md.
"""

import sys
from pathlib import Path

import pulumi
import pulumi_azure_native as azure_native

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.compute_aks import CaniAksCluster
from modules.data_services import WorkloadBlobStorage, WorkloadPostgres
from modules.naming import NamingContext, base_tags
from modules.networking import WorkloadNetwork
from modules.observability import send_diagnostics_to_workspace

config = pulumi.Config()
environment = pulumi.get_stack()
owner = config.get("owner") or "solo-operator"
aad_admin_group_object_ids = config.require_object("aadAdminGroupObjectIds")  # list[str]
postgres_admin_password = config.require_secret("postgresAdminPassword")


def _aks_dns_prefix(stack_name: str) -> str:
    safe_stack = "".join(ch if ch.isalnum() else "-" for ch in stack_name.lower()).strip("-")
    candidate = f"cani-{safe_stack or 'env'}-aks"[:54].rstrip("-")
    return candidate or "cani-aks"

platform_stack_ref = pulumi.StackReference(config.require("platformStackRef"))  # e.g. "org/cani-platform/dev"
hub_vnet_id = platform_stack_ref.get_output("hub_vnet_id")
log_analytics_workspace_id = platform_stack_ref.get_output("log_analytics_workspace_id")
acr_id = platform_stack_ref.get_output("acr_id")

naming = NamingContext(project="workload", layer="core", environment=environment)
tags = base_tags(environment=environment, owner=owner, spoke="docs-platform", workload_type="api")

resource_group = azure_native.resources.ResourceGroup(
    naming.resource_name("rg"),
    tags=tags,
)

network = WorkloadNetwork(
    "cani-workload",
    resource_group_name=resource_group.name,
    hub_vnet_id=hub_vnet_id,
    tags=tags,
)

aks = CaniAksCluster(
    "cani",
    resource_group_name=resource_group.name,
    subnet_id=network.aks_subnet_id,
    dns_prefix=_aks_dns_prefix(environment),
    aad_admin_group_object_ids=aad_admin_group_object_ids,
    tags=tags,
)

postgres = WorkloadPostgres(
    "cani",
    resource_group_name=resource_group.name,
    subnet_id=network.postgres_subnet_id,
    private_dns_zone_arm_resource_id=network.postgres_private_dns_zone.id,
    administrator_login="caniadmin",
    administrator_login_password=postgres_admin_password,
    tags=tags,
)

blob_storage = WorkloadBlobStorage(
    "cani",
    resource_group_name=resource_group.name,
    tags=tags,
)

send_diagnostics_to_workspace(
    "aks",
    target_resource_id=aks.cluster.id,
    workspace_id=log_analytics_workspace_id,
)

pulumi.export("aks_cluster_id", aks.cluster.id)
pulumi.export("aks_oidc_issuer_url", aks.cluster.oidc_issuer_profile.issuer_url)
pulumi.export("postgres_fqdn", postgres.server.fully_qualified_domain_name)
pulumi.export("storage_account_id", blob_storage.account.id)
pulumi.export("acr_id_reference", acr_id)
