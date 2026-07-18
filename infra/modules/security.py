"""Key Vault and baseline policy per docs/06-azure-landing-zone-design.md §6.3:
deny public network access on Storage/Key Vault (technically enforces ADR-007's
PHI-grade posture), require TLS 1.2+, require Key Vault soft-delete + purge protection.

`DenyPublicNetworkPolicies` wires the two deny-public-network assignments;
`BaselineGovernancePolicies` (Sprint 2 D1) completes the §6.3 set — allowed locations,
required tags, TLS enforcement, and deploy-if-not-exists diagnostics.
"""

from __future__ import annotations

import uuid

import pulumi_azure_native as azure_native
from pulumi import ComponentResource, Input, ResourceOptions

_DEF = "/providers/Microsoft.Authorization/policyDefinitions"
_ROLE = "/providers/Microsoft.Authorization/roleDefinitions"

# Built-in Azure Policy definition IDs (stable, tenant-agnostic).
POLICY_DENY_STORAGE_PUBLIC_NETWORK = f"{_DEF}/b2982f36-99f2-4db5-8eff-283140c09693"
POLICY_DENY_KEYVAULT_PUBLIC_NETWORK = f"{_DEF}/55615ac9-af46-4a59-874e-391cc3dfb490"
POLICY_ALLOWED_LOCATIONS = f"{_DEF}/e56962a6-4747-49cd-b67b-bf8b01975c4c"
POLICY_STORAGE_SECURE_TRANSFER = f"{_DEF}/404c3081-a854-4457-ae30-26a93ef643f9"  # TLS/HTTPS
POLICY_DINE_KEYVAULT_DIAGNOSTICS = f"{_DEF}/951af2fa-529b-416e-ab6e-066fd85ac459"

# Roles the DINE remediation identity needs (from the policy's roleDefinitionIds).
ROLE_LOG_ANALYTICS_CONTRIBUTOR = f"{_ROLE}/92aaf0da-9dab-42b6-94a3-d43ce8d16293"
ROLE_MONITORING_CONTRIBUTOR = f"{_ROLE}/749f88d5-cbae-40b8-bcfc-e573ddc772fa"

# Tags every CanI resource carries (naming.REQUIRED_TAGS). Audited, not denied — see below.
_REQUIRED_TAGS = ("environment", "owner", "spoke")


class PlatformKeyVault(ComponentResource):
    def __init__(
        self,
        name: str,
        *,
        resource_group_name: str,
        tenant_id: str,
        tags: dict,
        opts: ResourceOptions | None = None,
    ):
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
    deferred; see docs/implementation-status.md."""

    def __init__(self, name: str, *, management_group_id: str, opts: ResourceOptions | None = None):
        super().__init__("cani:platform:DenyPublicNetworkPolicies", name, None, opts)

        self.storage_policy = azure_native.authorization.PolicyAssignment(
            f"{name}-deny-storage-public",
            policy_assignment_name="cani-deny-stg-pub",
            policy_definition_id=POLICY_DENY_STORAGE_PUBLIC_NETWORK,
            scope=management_group_id,
            opts=ResourceOptions(parent=self),
        )
        self.keyvault_policy = azure_native.authorization.PolicyAssignment(
            f"{name}-deny-keyvault-public",
            policy_assignment_name="cani-deny-kv-pub",
            policy_definition_id=POLICY_DENY_KEYVAULT_PUBLIC_NETWORK,
            scope=management_group_id,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs({})


class BaselineGovernancePolicies(ComponentResource):
    """Completes the §6.3 baseline policy set at management-group scope (Sprint 2 D1):

    - Allowed locations (Deny): resources must be in `allowed_locations`. Global resources
      are excluded by the built-in, so this is safe to enforce.
    - Required tags (Audit): reports resources missing environment/owner/spoke. Audited,
      NOT denied — a Deny at MG scope would block AKS-managed / untagged resources and
      break deployments; audit gives compliance visibility without that risk.
    - TLS (Audit): storage accounts must require secure transfer (HTTPS/TLS). Our storage
      already complies, so this reports compliant.
    - Deploy-if-not-exists diagnostics: auto-configures Key Vault diagnostic settings to
      the central workspace for resources that lack them. Needs a managed identity + role
      assignments (Monitoring + Log Analytics Contributor) for the remediation task.
    """

    def __init__(
        self,
        name: str,
        *,
        management_group_id: Input[str],  # full ARM id — assignment / role-assignment scope
        management_group_name: Input[str],  # the group id string — policy-definition scope
        workspace_id: Input[str],
        location: str,
        allowed_locations: list[str],
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:platform:BaselineGovernancePolicies", name, None, opts)
        child = ResourceOptions(parent=self)

        azure_native.authorization.PolicyAssignment(
            f"{name}-allowed-locations",
            policy_assignment_name="cani-allowed-locations",
            policy_definition_id=POLICY_ALLOWED_LOCATIONS,
            scope=management_group_id,
            display_name="CanI - allowed locations",
            parameters={"listOfAllowedLocations": {"value": allowed_locations}},
            opts=child,
        )

        # One reusable custom definition (audit a missing tag), assigned once per tag.
        # NB: PolicyDefinitionAtManagementGroup.management_group_id is the group *name*
        # string (e.g. "cani-platform"), not the full ARM id that assignment scopes use.
        tag_def = azure_native.authorization.PolicyDefinitionAtManagementGroup(
            f"{name}-require-tag-def",
            policy_definition_name="cani-audit-required-tag",
            management_group_id=management_group_name,
            policy_type="Custom",
            mode="Indexed",  # tag/location-scoped resources only
            display_name="CanI - audit missing required tag",
            parameters={"tagName": {"type": "String", "metadata": {"displayName": "Tag name"}}},
            policy_rule={
                "if": {
                    "field": "[concat('tags[', parameters('tagName'), ']')]",
                    "exists": "false",
                },
                "then": {"effect": "audit"},
            },
            opts=child,
        )
        for tag in _REQUIRED_TAGS:
            azure_native.authorization.PolicyAssignment(
                f"{name}-require-tag-{tag}",
                policy_assignment_name=f"cani-req-tag-{tag}",
                policy_definition_id=tag_def.id,
                scope=management_group_id,
                display_name=f"CanI - require tag: {tag}",
                parameters={"tagName": {"value": tag}},
                opts=child,
            )

        azure_native.authorization.PolicyAssignment(
            f"{name}-storage-tls",
            policy_assignment_name="cani-storage-secure-transfer",
            policy_definition_id=POLICY_STORAGE_SECURE_TRANSFER,
            scope=management_group_id,
            display_name="CanI - storage secure transfer (TLS)",
            parameters={"effect": {"value": "Audit"}},
            opts=child,
        )

        # Deploy-if-not-exists needs a system-assigned identity (hence a location) whose
        # principal is then granted the roles the remediation task uses.
        dine = azure_native.authorization.PolicyAssignment(
            f"{name}-dine-kv-diagnostics",
            policy_assignment_name="cani-dine-kv-diag",
            policy_definition_id=POLICY_DINE_KEYVAULT_DIAGNOSTICS,
            scope=management_group_id,
            display_name="CanI - deploy Key Vault diagnostics",
            location=location,
            identity=azure_native.authorization.IdentityArgs(
                type=azure_native.authorization.ResourceIdentityType.SYSTEM_ASSIGNED
            ),
            parameters={
                "logAnalytics": {"value": workspace_id},
                "diagnosticsSettingNameToUse": {"value": "cani-kv-diagnostics"},
                "effect": {"value": "DeployIfNotExists"},
            },
            opts=child,
        )

        principal_id = dine.identity.apply(lambda i: i.principal_id if i else "")
        for role_name, role_id in (
            ("monitoring", ROLE_MONITORING_CONTRIBUTOR),
            ("log-analytics", ROLE_LOG_ANALYTICS_CONTRIBUTOR),
        ):
            azure_native.authorization.RoleAssignment(
                f"{name}-dine-role-{role_name}",
                # Deterministic GUID so re-applies target the same assignment.
                role_assignment_name=str(uuid.uuid5(uuid.NAMESPACE_URL, f"cani-dine-{role_name}")),
                scope=management_group_id,
                role_definition_id=role_id,
                principal_id=principal_id,
                principal_type=azure_native.authorization.PrincipalType.SERVICE_PRINCIPAL,
                opts=ResourceOptions(parent=self, depends_on=[dine]),
            )

        self.register_outputs({})
