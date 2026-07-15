"""Hub-spoke networking per docs/06-azure-landing-zone-design.md §6.4. Two
ComponentResources: HubNetwork (platform subscription) and WorkloadNetwork (workload
subscription), peered together with private DNS zones for the private-endpoint services
used elsewhere (Key Vault, Blob, ACR, Azure OpenAI).
"""

from __future__ import annotations

import pulumi
import pulumi_azure_native as azure_native
from pulumi import ComponentResource, ResourceOptions

PRIVATE_DNS_ZONES = (
    "privatelink.vaultcore.azure.net",
    "privatelink.blob.core.windows.net",
    "privatelink.azurecr.io",
    "privatelink.openai.azure.com",
    "privatelink.postgres.database.azure.com",
)


class HubNetwork(ComponentResource):
    def __init__(
        self, name: str, *, resource_group_name: str, tags: dict, opts: ResourceOptions | None = None
    ):
        super().__init__("cani:platform:HubNetwork", name, None, opts)

        self.vnet = azure_native.network.VirtualNetwork(
            f"{name}-vnet",
            resource_group_name=resource_group_name,
            address_space=azure_native.network.AddressSpaceArgs(address_prefixes=["10.0.0.0/16"]),
            subnets=[
                azure_native.network.SubnetArgs(name="NatGatewaySubnet", address_prefix="10.0.0.0/26"),
                azure_native.network.SubnetArgs(name="AzureBastionSubnet", address_prefix="10.0.1.0/26"),
                azure_native.network.SubnetArgs(name="SharedServicesSubnet", address_prefix="10.0.2.0/24"),
            ],
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        self.private_dns_zones = {
            zone: azure_native.privatedns.PrivateZone(
                f"{name}-pdz-{zone.split('.')[1]}",
                resource_group_name=resource_group_name,
                location="global",
                private_zone_name=zone,
                tags=tags,
                opts=ResourceOptions(parent=self),
            )
            for zone in PRIVATE_DNS_ZONES
        }

        self.register_outputs({"vnet_id": self.vnet.id})


class WorkloadNetwork(ComponentResource):
    def __init__(
        self,
        name: str,
        *,
        resource_group_name: str,
        hub_vnet_id: pulumi.Input[str],
        tags: dict,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:workload:WorkloadNetwork", name, None, opts)

        self.vnet = azure_native.network.VirtualNetwork(
            f"{name}-vnet",
            resource_group_name=resource_group_name,
            address_space=azure_native.network.AddressSpaceArgs(address_prefixes=["10.1.0.0/16"]),
            subnets=[
                azure_native.network.SubnetArgs(name="AksNodesSubnet", address_prefix="10.1.0.0/22"),
                azure_native.network.SubnetArgs(name="PrivateEndpointsSubnet", address_prefix="10.1.4.0/24"),
            ],
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        # Peering is bidirectional; the platform stack's HubNetwork creates the reverse
        # peering back to this VNet once the workload stack publishes vnet_id via StackReference.
        self.peering_to_hub = azure_native.network.VirtualNetworkPeering(
            f"{name}-peer-to-hub",
            resource_group_name=resource_group_name,
            virtual_network_name=self.vnet.name,
            remote_virtual_network=azure_native.network.SubResourceArgs(id=hub_vnet_id),
            allow_virtual_network_access=True,
            allow_forwarded_traffic=True,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs({"vnet_id": self.vnet.id})
