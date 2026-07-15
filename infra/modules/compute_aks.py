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
            agent_pool_profiles=[
                azure_native.containerservice.ManagedClusterAgentPoolProfileArgs(
                    name="systempool",
                    mode=azure_native.containerservice.AgentPoolMode.SYSTEM,
                    count=2,
                    vm_size="Standard_D2s_v4",
                    vnet_subnet_id=subnet_id,
                ),
                azure_native.containerservice.ManagedClusterAgentPoolProfileArgs(
                    name="appspool",
                    mode=azure_native.containerservice.AgentPoolMode.USER,
                    min_count=1,
                    max_count=4,
                    enable_auto_scaling=True,
                    vm_size="Standard_D2s_v4",
                    vnet_subnet_id=subnet_id,
                ),
                azure_native.containerservice.ManagedClusterAgentPoolProfileArgs(
                    name="datapool",
                    mode=azure_native.containerservice.AgentPoolMode.USER,
                    count=1,
                    vm_size="Standard_D4s_v4",
                    vnet_subnet_id=subnet_id,
                    node_taints=["dedicated=data:NoSchedule"],
                ),
            ],
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs(
            {"cluster_id": self.cluster.id, "oidc_issuer_url": self.cluster.oidc_issuer_profile.issuer_url}
        )
