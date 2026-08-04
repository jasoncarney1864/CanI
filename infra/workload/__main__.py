"""CanI workload landing zone (docs/09, docs/10, docs/11-iac-strategy.md §11.6 cross-
stack contract). Consumes cani-platform's outputs via StackReference rather than
hardcoding resource IDs. Applied to the `dev` stack on 2026-07-14/15 (Sprint 1, B2) —
live status in docs/implementation-status.md.
"""

import sys
from pathlib import Path

import pulumi
import pulumi_azure_native as azure_native

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.ai_services import AiServicesPrivateAccess
from modules.alerting import node_not_ready_alert
from modules.compute_aks import CaniAksCluster
from modules.data_services import WorkloadBlobStorage, WorkloadPostgres
from modules.naming import NamingContext, base_tags
from modules.networking import WorkloadNetwork
from modules.observability import ContainerInsightsCollection, send_diagnostics_to_workspace
from modules.workload_secrets import KeyVaultPrivateAccess, WorkloadSecretsIdentity

config = pulumi.Config()
environment = pulumi.get_stack()
owner = config.get("owner") or "solo-operator"
aad_admin_group_object_ids = config.require_object("aadAdminGroupObjectIds")  # list[str]
postgres_admin_password = config.require_secret("postgresAdminPassword")
# Dev stopgap, aligned with live reality (see docs/implementation-status.md production
# blocker 2): the app reaches blob storage via an account-key connection string over the
# public endpoint, so dev sets publicDataEndpoints=true. Target state is private
# endpoints + workload identity, at which point this flag goes away. Stacks that leave
# it unset get the secure default (Disabled).
public_data_endpoints = "Enabled" if config.get_bool("publicDataEndpoints") else "Disabled"


def _aks_dns_prefix(stack_name: str) -> str:
    safe_stack = "".join(ch if ch.isalnum() else "-" for ch in stack_name.lower()).strip("-")
    candidate = f"cani-{safe_stack or 'env'}-aks"[:54].rstrip("-")
    return candidate or "cani-aks"


platform_stack_ref = pulumi.StackReference(config.require("platformStackRef"))  # e.g. "org/cani-platform/dev"
hub_vnet_id = platform_stack_ref.get_output("hub_vnet_id")
log_analytics_workspace_id = platform_stack_ref.get_output("log_analytics_workspace_id")
acr_id = platform_stack_ref.get_output("acr_id")
ops_action_group_id = platform_stack_ref.get_output("ops_action_group_id")
platform_key_vault_id = platform_stack_ref.get_output("platform_key_vault_id")
platform_key_vault_name = platform_stack_ref.get_output("platform_key_vault_name")
openai_account_id = platform_stack_ref.get_output("openai_account_id")
document_intelligence_account_id = platform_stack_ref.get_output("document_intelligence_account_id")

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
    log_analytics_workspace_id=log_analytics_workspace_id,
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
    public_network_access=public_data_endpoints,
)

# D1: Key Vault CSI access — a private endpoint so the CSI driver can reach the
# public-access-Disabled platform Key Vault, plus a workload identity federated to each app
# service account with read access to the vault's secrets.
key_vault_access = KeyVaultPrivateAccess(
    "cani",
    resource_group_name=resource_group.name,
    key_vault_id=platform_key_vault_id,
    private_endpoints_subnet_id=network.private_endpoints_subnet_id,
    vnet_id=network.vnet.id,
    tags=tags,
)

secrets_identity = WorkloadSecretsIdentity(
    "cani-secrets",
    resource_group_name=resource_group.name,
    oidc_issuer_url=aks.cluster.oidc_issuer_profile.issuer_url,
    tags=tags,
)

# Private endpoints for Azure OpenAI + Document Intelligence, so the ingestion/retrieval
# workers reach them over the vnet instead of the public internet — the same posture Key
# Vault and Postgres already have. Both accounts live in the platform stack; only the
# endpoints and DNS belong here, next to the pods that resolve them.
ai_services_access = AiServicesPrivateAccess(
    "cani-ai",
    resource_group_name=resource_group.name,
    openai_account_id=openai_account_id,
    document_intelligence_account_id=document_intelligence_account_id,
    private_endpoints_subnet_id=network.private_endpoints_subnet_id,
    vnet_id=network.vnet.id,
    tags=tags,
)

send_diagnostics_to_workspace(
    "aks",
    target_resource_id=aks.cluster.id,
    workspace_id=log_analytics_workspace_id,
    # Cost control (§15, Sprint 2 A2): `allLogs` on AKS ingested 5.78 GB/day, 76% of it
    # the read-inclusive kube-audit category. kube-audit-admin keeps every write/delete
    # audit event; guard keeps AAD/authn events. Control-plane chatter (apiserver,
    # scheduler, autoscaler, CCM) is droppable in dev — it's diagnosable on demand via
    # `az aks kollect` when actually needed.
    log_categories=["kube-audit-admin", "guard"],
)

# Container Insights data collection — the omsagent addon (compute_aks.py) only deploys
# the agents; without this DCR + association they collect nothing (A2 recon finding).
container_insights = ContainerInsightsCollection(
    "cani-ci",
    resource_group_name=resource_group.name,
    location=resource_group.location,
    cluster_id=aks.cluster.id,
    workspace_id=log_analytics_workspace_id,
    tags=tags,
)

# §13.8 P1 node not-ready — platform metric alert so it keeps working even when the
# agent/log pipeline is what broke. Action group comes from the platform stack (§11.6).
node_not_ready_alert(
    "cani-p1-node-not-ready",
    resource_group_name=resource_group.name,
    cluster_id=aks.cluster.id,
    action_group_id=ops_action_group_id,
    tags=tags,
)

pulumi.export("aks_cluster_id", aks.cluster.id)
pulumi.export("aks_oidc_issuer_url", aks.cluster.oidc_issuer_profile.issuer_url)
# D1: consumed by the k8s SecretProviderClass / service-account annotations, and by the
# out-of-band elevated cutover (principal_id → the KV Secrets User role assignment).
pulumi.export("secrets_identity_client_id", secrets_identity.client_id)
pulumi.export("secrets_identity_principal_id", secrets_identity.principal_id)
pulumi.export("key_vault_name", platform_key_vault_name)
pulumi.export("postgres_fqdn", postgres.server.fully_qualified_domain_name)
pulumi.export("storage_account_id", blob_storage.account.id)
pulumi.export("acr_id_reference", acr_id)
pulumi.export("openai_private_endpoint_id", ai_services_access.private_endpoints["openai"].id)
pulumi.export("docintel_private_endpoint_id", ai_services_access.private_endpoints["docintel"].id)
