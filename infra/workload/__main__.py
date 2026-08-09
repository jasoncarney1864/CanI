"""CanI workload landing zone (docs/09, docs/11-iac-strategy.md §11.6 cross-stack
contract). Consumes cani-platform's outputs via StackReference rather than hardcoding
resource IDs. Applied to the `dev` stack on 2026-07-14/15 (Sprint 1, B2) — live status
in docs/implementation-status.md.

The AKS cluster and its observability wiring were removed when the workload consolidated
onto Azure Container Apps (see infra/container-apps/main.bicep). What remains here is the
shared substrate Container Apps still depends on: the vnet, Postgres, blob storage, the
Key Vault private endpoint, the AI-services private endpoints, and — critically — the
user-assigned managed identity the container apps authenticate with.
"""

import sys
from pathlib import Path

import pulumi
import pulumi_azure_native as azure_native

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.ai_services import AiServicesPrivateAccess
from modules.data_services import WorkloadBlobStorage, WorkloadPostgres
from modules.naming import NamingContext, base_tags
from modules.networking import WorkloadNetwork
from modules.workload_secrets import KeyVaultPrivateAccess, WorkloadSecretsIdentity

config = pulumi.Config()
environment = pulumi.get_stack()
owner = config.get("owner") or "solo-operator"
postgres_admin_password = config.require_secret("postgresAdminPassword")
# Dev stopgap, aligned with live reality (see docs/implementation-status.md production
# blocker 2): the app reaches blob storage via an account-key connection string over the
# public endpoint, so dev sets publicDataEndpoints=true. Target state is private
# endpoints + workload identity, at which point this flag goes away. Stacks that leave
# it unset get the secure default (Disabled).
public_data_endpoints = "Enabled" if config.get_bool("publicDataEndpoints") else "Disabled"


platform_stack_ref = pulumi.StackReference(config.require("platformStackRef"))  # e.g. "org/cani-platform/dev"
hub_vnet_id = platform_stack_ref.get_output("hub_vnet_id")
log_analytics_workspace_id = platform_stack_ref.get_output("log_analytics_workspace_id")
acr_id = platform_stack_ref.get_output("acr_id")
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

# NOTE: WorkloadNetwork still provisions an AKS subnet. It is left in place deliberately —
# it costs nothing, and removing a subnet from a live vnet forces churn on every other
# subnet in it. Reclaim it in a later, standalone change if it is genuinely in the way.

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

# No oidc_issuer_url: there is no cluster to federate against. The container apps assign
# this identity directly (managedIdentityId in infra/container-apps/main.parameters.json),
# and it carries both the AcrPull and Key Vault Secrets User grants.
secrets_identity = WorkloadSecretsIdentity(
    "cani-secrets",
    resource_group_name=resource_group.name,
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

# AKS diagnostics, Container Insights and the P1 node-not-ready alert were removed with
# the cluster. Container Apps emits to the same Log Analytics workspace via the managed
# environment (infra/container-apps/main.bicep); replacement availability alerts belong
# there, not here.

# D1: consumed by the out-of-band elevated cutover (principal_id → the KV Secrets User
# role assignment). Container Apps references the identity by resource ID.
pulumi.export("secrets_identity_client_id", secrets_identity.client_id)
pulumi.export("secrets_identity_principal_id", secrets_identity.principal_id)
pulumi.export("key_vault_name", platform_key_vault_name)
pulumi.export("postgres_fqdn", postgres.server.fully_qualified_domain_name)
pulumi.export("storage_account_id", blob_storage.account.id)
pulumi.export("acr_id_reference", acr_id)
pulumi.export("openai_private_endpoint_id", ai_services_access.private_endpoints["openai"].id)
pulumi.export("docintel_private_endpoint_id", ai_services_access.private_endpoints["docintel"].id)
