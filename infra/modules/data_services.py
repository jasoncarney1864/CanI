"""Data service components per docs/09-data-model-and-storage.md and
docs/06-azure-landing-zone-design.md §6.2: shared ACR (platform), Postgres Flexible
Server + Blob Storage (workload). Qdrant is not provisioned here — it runs as a
StatefulSet inside AKS (see k8s/base/qdrant), per docs/10 §10.9.
"""

from __future__ import annotations

import hashlib

import pulumi_azure_native as azure_native
from pulumi import ComponentResource, Input, ResourceOptions


def _normalized_alnum_lower(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _stable_suffix(seed: str, length: int = 8) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:length]


def _acr_registry_name(base: str, seed: str) -> str:
    prefix = _normalized_alnum_lower(base) or "cani"
    candidate = (prefix + _stable_suffix(seed, length=10))[:50]
    if len(candidate) < 5:
        candidate = (candidate + "cani0")[:5]
    return candidate


def _storage_account_name(base: str, seed: str) -> str:
    prefix = _normalized_alnum_lower(base) or "cani"
    candidate = (prefix + _stable_suffix(seed, length=10))[:24]
    if len(candidate) < 3:
        candidate = (candidate + "cani")[:3]
    return candidate


class SharedContainerRegistry(ComponentResource):
    def __init__(
        self,
        name: str,
        *,
        resource_group_name: str,
        tags: dict,
        public_network_access: str = "Disabled",
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:platform:SharedContainerRegistry", name, None, opts)

        registry_name = _acr_registry_name(base=name, seed=f"{resource_group_name}:{name}:acr")

        self.registry = azure_native.containerregistry.Registry(
            f"{name}-acr",
            registry_name=registry_name,
            resource_group_name=resource_group_name,
            # Premium is required when disabling public network access.
            sku=azure_native.containerregistry.SkuArgs(name=azure_native.containerregistry.SkuName.PREMIUM),
            admin_user_enabled=False,  # workload identities pull via RBAC, not admin credentials
            public_network_access=public_network_access,
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
        private_dns_zone_arm_resource_id: Input[str],
        administrator_login: str,
        administrator_login_password: Input[str],
        tags: dict,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:workload:WorkloadPostgres", name, None, opts)

        self.server = azure_native.dbforpostgresql.Server(
            f"{name}-pg",
            resource_group_name=resource_group_name,
            sku=azure_native.dbforpostgresql.SkuArgs(name="Standard_B2s", tier="Burstable"),
            version="16",
            network=azure_native.dbforpostgresql.NetworkArgs(
                delegated_subnet_resource_id=subnet_id,
                private_dns_zone_arm_resource_id=private_dns_zone_arm_resource_id,
                public_network_access="Disabled",
            ),
            administrator_login=administrator_login,
            administrator_login_password=administrator_login_password,
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
        self,
        name: str,
        *,
        resource_group_name: str,
        tags: dict,
        public_network_access: str = "Disabled",
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:workload:WorkloadBlobStorage", name, None, opts)

        account_name = _storage_account_name(base=name, seed=f"{resource_group_name}:{name}:storage")

        self.account = azure_native.storage.StorageAccount(
            f"{name}-st",
            account_name=account_name,
            resource_group_name=resource_group_name,
            kind=azure_native.storage.Kind.STORAGE_V2,
            sku=azure_native.storage.SkuArgs(name=azure_native.storage.SkuName.STANDARD_LRS),
            minimum_tls_version=azure_native.storage.MinimumTlsVersion.TLS1_2,
            allow_blob_public_access=False,
            public_network_access=public_network_access,
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        # §9.10 accidental-deletion recovery: blob versioning keeps prior versions on
        # overwrite, and soft delete makes deleted blobs/containers recoverable for a
        # window instead of being gone immediately. 7-day window matches Postgres PITR
        # retention so all stores have the same recovery horizon.
        self.blob_service = azure_native.storage.BlobServiceProperties(
            f"{name}-blobsvc",
            account_name=self.account.name,
            resource_group_name=resource_group_name,
            blob_services_name="default",  # the only valid value for this resource
            is_versioning_enabled=True,
            delete_retention_policy=azure_native.storage.DeleteRetentionPolicyArgs(enabled=True, days=7),
            container_delete_retention_policy=azure_native.storage.DeleteRetentionPolicyArgs(
                enabled=True, days=7
            ),
            opts=ResourceOptions(parent=self),
        )

        # qdrant-snapshots holds the Qdrant snapshot exports (§9.10, C1). Separate from the
        # document containers so backup artifacts have their own lifecycle/access surface.
        for container in ("raw-documents", "extracted-text", "ingestion-artifacts", "qdrant-snapshots"):
            azure_native.storage.BlobContainer(
                f"{name}-container-{container}",
                account_name=self.account.name,
                resource_group_name=resource_group_name,
                container_name=container,
                public_access=azure_native.storage.PublicAccess.NONE,
                opts=ResourceOptions(parent=self),
            )

        self.register_outputs({"account_id": self.account.id})
