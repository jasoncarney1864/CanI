"""Data service components per docs/09-data-model-and-storage.md and
docs/06-azure-landing-zone-design.md §6.2: shared ACR (platform), Postgres Flexible
Server + Blob Storage (workload). Qdrant is not provisioned here — it runs as a
StatefulSet inside AKS (see k8s/base/qdrant), per docs/10 §10.9.
"""

from __future__ import annotations

import pulumi_azure_native as azure_native
from pulumi import ComponentResource, Input, ResourceOptions


class SharedContainerRegistry(ComponentResource):
    def __init__(
        self, name: str, *, resource_group_name: str, tags: dict, opts: ResourceOptions | None = None
    ):
        super().__init__("cani:platform:SharedContainerRegistry", name, None, opts)

        self.registry = azure_native.containerregistry.Registry(
            f"{name}-acr",
            resource_group_name=resource_group_name,
            sku=azure_native.containerregistry.SkuArgs(name=azure_native.containerregistry.SkuName.STANDARD),
            admin_user_enabled=False,  # workload identities pull via RBAC, not admin credentials
            public_network_access="Disabled",
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs({"registry_id": self.registry.id, "login_server": self.registry.login_server})


class WorkloadPostgres(ComponentResource):
    def __init__(
        self,
        name: str,
        *,
        resource_group_name: str,
        subnet_id: Input[str],
        administrator_login: str,
        tags: dict,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:workload:WorkloadPostgres", name, None, opts)

        self.server = azure_native.dbforpostgresql.Server(
            f"{name}-pg",
            resource_group_name=resource_group_name,
            sku=azure_native.dbforpostgresql.SkuArgs(name="Standard_B2s", tier="Burstable"),
            version="16",
            network=azure_native.dbforpostgresql.NetworkArgs(delegated_subnet_resource_id=subnet_id),
            administrator_login=administrator_login,
            storage=azure_native.dbforpostgresql.StorageArgs(storage_size_gb=32),
            backup=azure_native.dbforpostgresql.BackupArgs(
                backup_retention_days=7, geo_redundant_backup="Disabled"
            ),
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs({"server_id": self.server.id, "fqdn": self.server.fully_qualified_domain_name})


class WorkloadBlobStorage(ComponentResource):
    def __init__(
        self, name: str, *, resource_group_name: str, tags: dict, opts: ResourceOptions | None = None
    ):
        super().__init__("cani:workload:WorkloadBlobStorage", name, None, opts)

        self.account = azure_native.storage.StorageAccount(
            f"{name}-st",
            resource_group_name=resource_group_name,
            kind=azure_native.storage.Kind.STORAGE_V2,
            sku=azure_native.storage.SkuArgs(name=azure_native.storage.SkuName.STANDARD_LRS),
            minimum_tls_version=azure_native.storage.MinimumTlsVersion.TLS1_2,
            allow_blob_public_access=False,
            public_network_access=azure_native.storage.PublicNetworkAccess.DISABLED,
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        for container in ("raw-documents", "extracted-text", "ingestion-artifacts"):
            azure_native.storage.BlobContainer(
                f"{name}-container-{container}",
                account_name=self.account.name,
                resource_group_name=resource_group_name,
                container_name=container,
                public_access=azure_native.storage.PublicAccess.NONE,
                opts=ResourceOptions(parent=self),
            )

        self.register_outputs({"account_id": self.account.id})
