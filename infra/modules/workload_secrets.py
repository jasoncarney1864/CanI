"""D1 — Key Vault CSI secret access for the workload (docs/10 §10.6, docs/14 §14.10).

Two ComponentResources wire the AKS workload to the platform's private Key Vault so the
Secrets Store CSI driver can mount secrets at runtime, with no plaintext in manifests:

- ``KeyVaultPrivateAccess`` — a private endpoint for the (public-access-Disabled) platform
  Key Vault in the workload vnet's PrivateEndpoints subnet, plus the
  ``privatelink.vaultcore.azure.net`` private DNS zone + link so pods resolve the vault to
  its private IP. Mirrors the Postgres private-DNS pattern in ``networking.py``.
- ``WorkloadSecretsIdentity`` — a user-assigned managed identity, a federated identity
  credential per app service account (so the CSI driver authenticates as the workload via
  the cluster's OIDC issuer), and a Key Vault Secrets User role assignment scoped to the
  vault. The identity's ``client_id`` feeds the SecretProviderClass / service-account
  annotations.

Two privileged steps are applied out-of-band by an elevated operator, NOT by CI (the CI
service principal is Contributor-only, which can't create role assignments or write RBAC
Key Vault secret values) — see ``runbooks/keyvault-secret-cutover.md``:
  1. the ``Key Vault Secrets User`` role assignment for this identity on the vault;
  2. the KV secret *values* (written via the ARM management plane, which bypasses the
     vault's disabled data-plane network).
This mirrors the DINE-policy precedent (``runbooks/policy-baseline-dine.md``).
"""

from __future__ import annotations

import pulumi_azure_native as azure_native
from pulumi import ComponentResource, Input, ResourceOptions

# App service accounts that must read secrets from Key Vault, as (namespace, name). Each
# gets a federated credential so its pods can token-exchange for the managed identity.
SECRET_CONSUMER_SERVICE_ACCOUNTS = (
    ("docs-platform", "docs-api"),
    ("docs-platform", "web"),
    ("docs-platform", "retrieval-worker"),
    ("docs-platform", "ingestion-worker"),
    ("hub-system", "hub-api"),
)


class KeyVaultPrivateAccess(ComponentResource):
    """Private endpoint + private DNS for the platform Key Vault, in the workload vnet."""

    def __init__(
        self,
        name: str,
        *,
        resource_group_name: Input[str],
        key_vault_id: Input[str],
        private_endpoints_subnet_id: Input[str],
        vnet_id: Input[str],
        tags: dict,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:workload:KeyVaultPrivateAccess", name, None, opts)

        self.dns_zone = azure_native.privatedns.PrivateZone(
            f"{name}-pdz-vaultcore",
            resource_group_name=resource_group_name,
            location="global",
            private_zone_name="privatelink.vaultcore.azure.net",
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        self.dns_link = azure_native.privatedns.VirtualNetworkLink(
            f"{name}-pdz-vaultcore-link",
            resource_group_name=resource_group_name,
            location="global",
            private_zone_name=self.dns_zone.name,
            virtual_network=azure_native.privatedns.SubResourceArgs(id=vnet_id),
            registration_enabled=False,
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        self.private_endpoint = azure_native.network.PrivateEndpoint(
            f"{name}-kv-pe",
            resource_group_name=resource_group_name,
            subnet=azure_native.network.SubnetArgs(id=private_endpoints_subnet_id),
            private_link_service_connections=[
                azure_native.network.PrivateLinkServiceConnectionArgs(
                    name="keyvault",
                    private_link_service_id=key_vault_id,
                    group_ids=["vault"],
                )
            ],
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        # Register the PE's private IP into the vaultcore zone so <vault>.vault.azure.net
        # resolves privately from the cluster.
        self.dns_zone_group = azure_native.network.PrivateDnsZoneGroup(
            f"{name}-kv-pe-dnsgroup",
            resource_group_name=resource_group_name,
            private_endpoint_name=self.private_endpoint.name,
            private_dns_zone_configs=[
                azure_native.network.PrivateDnsZoneConfigArgs(
                    name="vaultcore",
                    private_dns_zone_id=self.dns_zone.id,
                )
            ],
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs({"private_endpoint_id": self.private_endpoint.id})


class WorkloadSecretsIdentity(ComponentResource):
    """User-assigned managed identity + per-service-account federation + KV read role."""

    def __init__(
        self,
        name: str,
        *,
        resource_group_name: Input[str],
        oidc_issuer_url: Input[str],
        tags: dict,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:workload:WorkloadSecretsIdentity", name, None, opts)

        self.identity = azure_native.managedidentity.UserAssignedIdentity(
            f"{name}-id",
            resource_group_name=resource_group_name,
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        # One federated credential per consuming service account. The subject binds the
        # AKS OIDC token (system:serviceaccount:<ns>:<sa>) to this managed identity.
        self.federated_credentials = [
            azure_native.managedidentity.FederatedIdentityCredential(
                f"{name}-fic-{namespace}-{sa}",
                resource_group_name=resource_group_name,
                resource_name_=self.identity.name,
                audiences=["api://AzureADTokenExchange"],
                issuer=oidc_issuer_url,
                subject=f"system:serviceaccount:{namespace}:{sa}",
                opts=ResourceOptions(parent=self),
            )
            for namespace, sa in SECRET_CONSUMER_SERVICE_ACCOUNTS
        ]

        # The "Key Vault Secrets User" role assignment for this identity is applied
        # out-of-band by an elevated operator (Contributor CI can't create role
        # assignments) — see the module docstring + runbooks/keyvault-secret-cutover.md.
        self.client_id = self.identity.client_id
        self.principal_id = self.identity.principal_id
        self.register_outputs(
            {
                "identity_client_id": self.identity.client_id,
                "identity_principal_id": self.identity.principal_id,
                "identity_id": self.identity.id,
            }
        )
