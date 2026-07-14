"""Key Vault and baseline policy per docs/06-azure-landing-zone-design.md §6.3:
deny public network access on Storage/Key Vault (technically enforces ADR-007's
PHI-grade posture), require TLS 1.2+, require Key Vault soft-delete + purge protection.

Only two representative built-in policy assignments are wired here (deny public network
access for Storage and Key Vault) — the full policy set (tag enforcement, allowed
locations, diagnostic settings deploy-if-not-exists) is listed as deferred backlog in the
launch-readiness report; this is a real, working example of the pattern, not the full set.
"""

from __future__ import annotations

import pulumi_azure_native as azure_native
from pulumi import ComponentResource, ResourceOptions

# Built-in Azure Policy definition IDs (stable, tenant-agnostic).
POLICY_DENY_STORAGE_PUBLIC_NETWORK = (
    "/providers/Microsoft.Authorization/policyDefinitions/34c877ad-507e-4c82-993e-3452a6e0523b"
)
POLICY_DENY_KEYVAULT_PUBLIC_NETWORK = (
    "/providers/Microsoft.Authorization/policyDefinitions/55615ac9-af46-4a59-874e-391cc3dfb490"
)


class PlatformKeyVault(ComponentResource):
    def __init__(self, name: str, *, resource_group_name: str, tenant_id: str, tags: dict, opts: ResourceOptions | None = None):
        super().__init__("cani:platform:PlatformKeyVault", name, None, opts)

        self.vault = azure_native.keyvault.Vault(
            f"{name}-kv",
            resource_group_name=resource_group_name,
            properties=azure_native.keyvault.VaultPropertiesArgs(
                tenant_id=tenant_id,
                sku=azure_native.keyvault.SkuArgs(family="A", name=azure_native.keyvault.SkuName.STANDARD),
                enable_rbac_authorization=True,
                enable_soft_delete=True,
                soft_delete_retention_in_days=90,
                enable_purge_protection=True,
                public_network_access="Disabled",
                network_acls=azure_native.keyvault.NetworkRuleSetArgs(
                    default_action=azure_native.keyvault.NetworkRuleAction.DENY,
                ),
            ),
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs({"vault_id": self.vault.id})


class DenyPublicNetworkPolicies(ComponentResource):
    """Assigns the two built-in "deny public network access" policies at management
    group scope. Represents the pattern from §6.3 — the remaining baseline policies
    (required tags, allowed locations, TLS enforcement, diagnostic settings) are
    deferred; see the launch-readiness gap report."""

    def __init__(self, name: str, *, management_group_id: str, opts: ResourceOptions | None = None):
        super().__init__("cani:platform:DenyPublicNetworkPolicies", name, None, opts)

        self.storage_policy = azure_native.authorization.PolicyAssignment(
            f"{name}-deny-storage-public",
            policy_definition_id=POLICY_DENY_STORAGE_PUBLIC_NETWORK,
            scope=management_group_id,
            opts=ResourceOptions(parent=self),
        )
        self.keyvault_policy = azure_native.authorization.PolicyAssignment(
            f"{name}-deny-keyvault-public",
            policy_definition_id=POLICY_DENY_KEYVAULT_PUBLIC_NETWORK,
            scope=management_group_id,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs({})
