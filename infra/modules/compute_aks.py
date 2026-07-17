"""AKS cluster per docs/10-aks-cluster-design.md: private cluster, Entra-integrated RBAC,
Azure CNI Overlay, systempool/appspool/datapool node pools, workload identity enabled.
KEDA/HPA and the Qdrant StatefulSet are applied via k8s/ manifests, not here — this
module only provisions the cluster and node pools (§10.14 checklist items 1-3).
"""

from __future__ import annotations

import pulumi_azure_native as azure_native
from pulumi import ComponentResource, Input, ResourceOptions


class CaniAksCluster(ComponentResource):
    def __init__(
        self,
        name: str,
        *,
        resource_group_name: str,
        subnet_id: Input[str],
        dns_prefix: Input[str],
        aad_admin_group_object_ids: list[str],
        log_analytics_workspace_id: Input[str],
        tags: dict,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:workload:CaniAksCluster", name, None, opts)

        self.cluster = azure_native.containerservice.ManagedCluster(
            f"{name}-aks",
            resource_group_name=resource_group_name,
            dns_prefix=dns_prefix,
            sku=azure_native.containerservice.ManagedClusterSKUArgs(
                name=azure_native.containerservice.ManagedClusterSKUName.BASE,
                tier=azure_native.containerservice.ManagedClusterSKUTier.STANDARD,
            ),
            api_server_access_profile=azure_native.containerservice.ManagedClusterAPIServerAccessProfileArgs(
                enable_private_cluster=True,
            ),
            aad_profile=azure_native.containerservice.ManagedClusterAADProfileArgs(
                managed=True,
                enable_azure_rbac=True,
                admin_group_object_ids=aad_admin_group_object_ids,
            ),
            network_profile=azure_native.containerservice.ContainerServiceNetworkProfileArgs(
                network_plugin=azure_native.containerservice.NetworkPlugin.AZURE,
                network_plugin_mode=azure_native.containerservice.NetworkPluginMode.OVERLAY,
                # Calico enforces the deny-by-default NetworkPolicies in k8s/base
                # (docs/14 §14.6); it is the policy engine that supports Azure CNI Overlay.
                # NOTE: on an already-provisioned cluster this field is enabled in-place via
                # `az aks update --network-policy calico` and reconciled into state with
                # `pulumi refresh` — a plain `pulumi up` of this change alone would force a
                # destructive cluster REPLACE. New clusters get it at creation.
                network_policy=azure_native.containerservice.NetworkPolicy.CALICO,
            ),
            oidc_issuer_profile=azure_native.containerservice.ManagedClusterOIDCIssuerProfileArgs(
                enabled=True
            ),
            security_profile=azure_native.containerservice.ManagedClusterSecurityProfileArgs(
                workload_identity=azure_native.containerservice.ManagedClusterSecurityProfileWorkloadIdentityArgs(
                    enabled=True
                ),
            ),
            identity=azure_native.containerservice.ManagedClusterIdentityArgs(
                type=azure_native.containerservice.ResourceIdentityType.SYSTEM_ASSIGNED
            ),
            addon_profiles={
                # Key Vault Secrets Provider (CSI) — target delivery path for runtime
                # secrets (docs/10 §10.6); enabled live, declared so pulumi up won't strip it.
                "azureKeyvaultSecretsProvider": azure_native.containerservice.ManagedClusterAddonProfileArgs(
                    enabled=True
                ),
                # Container Insights (docs/13 §13.6): cluster/pod health + logs to the
                # central Log Analytics workspace. AAD auth (no workspace keys in the addon).
                "omsagent": azure_native.containerservice.ManagedClusterAddonProfileArgs(
                    enabled=True,
                    config={
                        "logAnalyticsWorkspaceResourceID": log_analytics_workspace_id,
                        "useAADAuth": "true",
                    },
                ),
            },
            agent_pool_profiles=[
                azure_native.containerservice.ManagedClusterAgentPoolProfileArgs(
                    name="systempool",
                    mode=azure_native.containerservice.AgentPoolMode.SYSTEM,
                    count=2,
                    vm_size="Standard_D2s_v4",
                    vnet_subnet_id=subnet_id,
                ),
                # User pools roll in-place (max_surge=0/max_unavailable=1) rather than by
                # surging new nodes: the subscription's regional vCPU quota (10) is fully
                # consumed by the running pools, so a surge upgrade has no capacity and
                # fails with InsufficientVCPUQuota. System pools must keep surge (Azure
                # forbids max_unavailable on them), so systempool is left at the default.
                azure_native.containerservice.ManagedClusterAgentPoolProfileArgs(
                    name="appspool",
                    mode=azure_native.containerservice.AgentPoolMode.USER,
                    min_count=1,
                    max_count=4,
                    enable_auto_scaling=True,
                    vm_size="Standard_D2s_v4",
                    vnet_subnet_id=subnet_id,
                    upgrade_settings=azure_native.containerservice.AgentPoolUpgradeSettingsArgs(
                        max_surge="0", max_unavailable="1"
                    ),
                ),
                azure_native.containerservice.ManagedClusterAgentPoolProfileArgs(
                    name="datapool",
                    mode=azure_native.containerservice.AgentPoolMode.USER,
                    count=1,
                    vm_size="Standard_D4s_v4",
                    vnet_subnet_id=subnet_id,
                    node_taints=["dedicated=data:NoSchedule"],
                    upgrade_settings=azure_native.containerservice.AgentPoolUpgradeSettingsArgs(
                        max_surge="0", max_unavailable="1"
                    ),
                ),
            ],
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs(
            {"cluster_id": self.cluster.id, "oidc_issuer_url": self.cluster.oidc_issuer_profile.issuer_url}
        )
