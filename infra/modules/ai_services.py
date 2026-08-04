"""Azure AI service accounts per docs/06-azure-landing-zone-design.md §6.2 and
docs/08-rag-pipeline-design.md: the Azure OpenAI account that backs embedding + grounding,
and the Document Intelligence (Form Recognizer) account that backs OCR extraction.

Both were hand-created through the CLI rather than IaC — `cani-docintel` during Sprint 2 and
`cani-openai` on 2026-08-04, when the closeout gate exposed that no Azure OpenAI resource had
ever existed and the platform had been silently running fake providers. Neither existed in
Pulumi, so a rebuild would have produced a cluster that came up healthy and answered every
question wrongly. This module closes that gap.

The **model deployments are the important part**. An Azure OpenAI account with no deployments
is an empty shell: `Settings.azure_ai_providers_configured` would still be True (endpoint and
key exist), so the app would not fall back to the fakes — it would fail every call instead.
Reproducing the account without reproducing `text-embedding-3-small` and `gpt-5-1` would just
trade one silent failure for a loud one.

Split across the two stacks, mirroring the Key Vault pattern in ``workload_secrets.py``:

- ``PlatformAiServices`` owns the accounts, in the platform subscription alongside Key Vault
  and ACR, because they are shared services rather than workload-specific ones.
- ``AiServicesPrivateAccess`` owns the private endpoints and private DNS in the *workload*
  vnet, because that is where the pods that call them run.

Adoption of the existing live resources is driven by the ``adopt_existing_ids`` mapping (see
``PlatformAiServices``), which is supplied from stack config and removed once the import has
been applied.
"""

from __future__ import annotations

import hashlib

import pulumi_azure_native as azure_native
from pulumi import ComponentResource, Input, Output, ResourceOptions

# Deployment shapes, matching what was provisioned and verified live on 2026-08-04.
#
# Regional `Standard` (not GlobalStandard/DataZoneStandard) is deliberate: the allowed-
# locations policy in security.py pins CanI to a single region for data residency
# (docs/06 §6.2), and a global-deployment SKU can serve requests from outside it. `gpt-5.1`
# is the current chat model that still offers plain `Standard` in eastus2.
EMBEDDING_DEPLOYMENT_NAME = "text-embedding-3-small"
EMBEDDING_MODEL = ("text-embedding-3-small", "1")
EMBEDDING_CAPACITY = 100

CHAT_DEPLOYMENT_NAME = "gpt-5-1"
CHAT_MODEL = ("gpt-5.1", "2025-11-13")
CHAT_CAPACITY = 30

# Azure's default content-filter policy. Named explicitly so it shows up in review rather
# than being an invisible service default.
RAI_POLICY = "Microsoft.DefaultV2"


def _deny_all_network_acls() -> azure_native.cognitiveservices.NetworkRuleSetArgs:
    return azure_native.cognitiveservices.NetworkRuleSetArgs(default_action="Deny")


def _derived_account_name(base: str, resource_group_name: Input[str]) -> Output[str]:
    """A per-resource-group account name, for stacks that don't pin one explicitly.

    An account name doubles as its custom subdomain, which is globally unique — so a
    hardcoded default would make a second stack in another subscription collide with the
    first. That is not hypothetical: it is exactly what happened to the shared ACR and the
    storage account (see the comments in ``data_services.py``), where a constant name was
    generated for every stack and clashed with the still-live resource in the old
    subscription.

    The seed must be the *resolved* resource group name, hence ``.apply()`` — interpolating
    an Output directly yields a placeholder string that hashes identically everywhere, which
    was the original bug rather than a hypothetical one.

    The hashing helpers in ``data_services.py`` are deliberately not shared yet: unifying
    them risks a one-character behaviour change renaming the live ACR/storage account, which
    would be a destructive replace for no benefit.
    """
    return Output.from_input(resource_group_name).apply(
        lambda rg: f"{base}-{hashlib.sha1(f'{rg}:{base}'.encode()).hexdigest()[:10]}"[:64]
    )


class PlatformAiServices(ComponentResource):
    """Azure OpenAI + Document Intelligence accounts and the OpenAI model deployments.

    ``public_network_access`` defaults to ``Disabled`` so a fresh stack is private by
    default; callers reach the accounts over the private endpoints created by
    ``AiServicesPrivateAccess``. It is a parameter rather than a constant only so the
    existing dev stack could be adopted before its private endpoints existed — turning it
    off and on is a one-line change with a verifiable blast radius.

    ``adopt_existing_ids`` maps a logical key (``openai``, ``documentIntelligence``,
    ``embeddingDeployment``, ``chatDeployment``) to the ARM id of an already-existing
    resource. Pulumi then imports rather than creates, and **fails loudly if the declared
    properties do not match reality** — which is the point: a silent PUT over a live account
    would be the same class of mistake as the fake-provider fallback this module exists to
    prevent. Import ids must be plain strings (Pulumi cannot resolve an Output for them), so
    they come from stack config, and the mapping is deleted once the import has applied.
    """

    def __init__(
        self,
        name: str,
        *,
        resource_group_name: Input[str],
        openai_account_name: str | None = None,
        document_intelligence_account_name: str | None = None,
        tags: dict,
        public_network_access: str = "Disabled",
        adopt_existing_ids: dict[str, str] | None = None,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:platform:PlatformAiServices", name, None, opts)

        adopt = adopt_existing_ids or {}
        private = public_network_access == "Disabled"

        openai_name: Input[str] = openai_account_name or _derived_account_name(
            f"{name}-openai", resource_group_name
        )
        docintel_name: Input[str] = document_intelligence_account_name or _derived_account_name(
            f"{name}-docintel", resource_group_name
        )

        def child(key: str) -> ResourceOptions:
            # import_ is only legal on the first apply that adopts the resource; afterwards
            # the key is dropped from config and this degrades to a plain parent option.
            return ResourceOptions(parent=self, import_=adopt.get(key))

        # A custom subdomain is mandatory for both AAD auth and private endpoints, and it is
        # immutable after creation. It is set to the account name, which is what makes the
        # account name globally unique rather than merely unique within the resource group.
        # Stacks that inherited hand-created accounts pin the literal name via config;
        # everything else gets a per-resource-group derived name (see _derived_account_name).
        self.openai = azure_native.cognitiveservices.Account(
            f"{name}-openai",
            account_name=openai_name,
            resource_group_name=resource_group_name,
            kind="OpenAI",
            sku=azure_native.cognitiveservices.SkuArgs(name="S0"),
            properties=azure_native.cognitiveservices.AccountPropertiesArgs(
                custom_sub_domain_name=openai_name,
                public_network_access=public_network_access,
                network_acls=_deny_all_network_acls() if private else None,
            ),
            tags=tags,
            opts=child("openai"),
        )

        self.document_intelligence = azure_native.cognitiveservices.Account(
            f"{name}-docintel",
            account_name=docintel_name,
            resource_group_name=resource_group_name,
            kind="FormRecognizer",
            sku=azure_native.cognitiveservices.SkuArgs(name="S0"),
            properties=azure_native.cognitiveservices.AccountPropertiesArgs(
                custom_sub_domain_name=docintel_name,
                public_network_access=public_network_access,
                network_acls=_deny_all_network_acls() if private else None,
            ),
            tags=tags,
            opts=child("documentIntelligence"),
        )

        # NoAutoUpgrade, unlike the chat deployment below, is not a style choice. Embeddings
        # are persisted: every vector in Qdrant was produced by this exact model version, and
        # queries are only comparable to them if the query embedder matches. A silent
        # version bump would leave the vector width unchanged (1536) so nothing would error —
        # retrieval would just quietly get worse, which is precisely the failure mode that
        # went unnoticed here for weeks. Re-embedding is a deliberate, verified operation.
        self.embedding_deployment = azure_native.cognitiveservices.Deployment(
            f"{name}-openai-embedding",
            account_name=self.openai.name,
            resource_group_name=resource_group_name,
            deployment_name=EMBEDDING_DEPLOYMENT_NAME,
            sku=azure_native.cognitiveservices.SkuArgs(name="Standard", capacity=EMBEDDING_CAPACITY),
            properties=azure_native.cognitiveservices.DeploymentPropertiesArgs(
                model=azure_native.cognitiveservices.DeploymentModelArgs(
                    format="OpenAI",
                    name=EMBEDDING_MODEL[0],
                    version=EMBEDDING_MODEL[1],
                ),
                version_upgrade_option="NoAutoUpgrade",
                rai_policy_name=RAI_POLICY,
            ),
            opts=child("embeddingDeployment"),
        )

        # The chat deployment carries no persisted state, so tracking the current default
        # version is safe and keeps the model from ageing into deprecation unattended —
        # `az cognitiveservices model list` cheerfully advertises models that are already
        # refused for new deployments, so drifting behind is worse than drifting forward.
        #
        # depends_on is not ordering pedantry: Azure rejects concurrent deployment writes to
        # the same account, and Pulumi would otherwise create both in parallel.
        self.chat_deployment = azure_native.cognitiveservices.Deployment(
            f"{name}-openai-chat",
            account_name=self.openai.name,
            resource_group_name=resource_group_name,
            deployment_name=CHAT_DEPLOYMENT_NAME,
            sku=azure_native.cognitiveservices.SkuArgs(name="Standard", capacity=CHAT_CAPACITY),
            properties=azure_native.cognitiveservices.DeploymentPropertiesArgs(
                model=azure_native.cognitiveservices.DeploymentModelArgs(
                    format="OpenAI",
                    name=CHAT_MODEL[0],
                    version=CHAT_MODEL[1],
                ),
                version_upgrade_option="OnceNewDefaultVersionAvailable",
                rai_policy_name=RAI_POLICY,
            ),
            opts=ResourceOptions(
                parent=self,
                import_=adopt.get("chatDeployment"),
                depends_on=[self.embedding_deployment],
            ),
        )

        self.register_outputs(
            {
                "openai_account_id": self.openai.id,
                "openai_endpoint": self.openai.properties.endpoint,
                "document_intelligence_account_id": self.document_intelligence.id,
                "document_intelligence_endpoint": self.document_intelligence.properties.endpoint,
            }
        )


class AiServicesPrivateAccess(ComponentResource):
    """Private endpoints + private DNS so pods reach the AI accounts without the public net.

    Mirrors ``KeyVaultPrivateAccess``: the zones live in the workload resource group and are
    linked to the workload vnet. Note that ``HubNetwork`` also declares
    ``privatelink.openai.azure.com`` in the hub per docs/06 §6.4, but those hub zones have no
    vnet link and so resolve nothing — the same pre-existing inconsistency Key Vault hit. This
    follows the pattern that demonstrably works rather than adding a third variant; unifying
    on hub-hosted zones is a separate change.

    Two zones are needed because the two accounts answer on different suffixes:
    ``cani-openai.openai.azure.com`` and ``cani-docintel.cognitiveservices.azure.com``. Both
    zone configs are attached to both endpoints, because a Cognitive Services account can
    also answer on the sibling suffix; an unused zone config is inert, whereas a missing one
    fails to resolve.
    """

    def __init__(
        self,
        name: str,
        *,
        resource_group_name: Input[str],
        openai_account_id: Input[str],
        document_intelligence_account_id: Input[str],
        private_endpoints_subnet_id: Input[str],
        vnet_id: Input[str],
        tags: dict,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:workload:AiServicesPrivateAccess", name, None, opts)
        child = ResourceOptions(parent=self)

        self.dns_zones = {}
        zone_configs = []
        for label, zone_name in (
            ("openai", "privatelink.openai.azure.com"),
            ("cognitiveservices", "privatelink.cognitiveservices.azure.com"),
        ):
            zone = azure_native.privatedns.PrivateZone(
                f"{name}-pdz-{label}",
                resource_group_name=resource_group_name,
                location="global",
                private_zone_name=zone_name,
                tags=tags,
                opts=child,
            )
            azure_native.privatedns.VirtualNetworkLink(
                f"{name}-pdz-{label}-link",
                resource_group_name=resource_group_name,
                location="global",
                private_zone_name=zone.name,
                virtual_network=azure_native.privatedns.SubResourceArgs(id=vnet_id),
                registration_enabled=False,
                tags=tags,
                opts=child,
            )
            self.dns_zones[label] = zone
            zone_configs.append(
                azure_native.network.PrivateDnsZoneConfigArgs(name=label, private_dns_zone_id=zone.id)
            )

        self.private_endpoints = {}
        for label, account_id in (
            ("openai", openai_account_id),
            ("docintel", document_intelligence_account_id),
        ):
            endpoint = azure_native.network.PrivateEndpoint(
                f"{name}-{label}-pe",
                resource_group_name=resource_group_name,
                subnet=azure_native.network.SubnetArgs(id=private_endpoints_subnet_id),
                private_link_service_connections=[
                    azure_native.network.PrivateLinkServiceConnectionArgs(
                        name=label,
                        private_link_service_id=account_id,
                        # "account" is the only group id Cognitive Services exposes.
                        group_ids=["account"],
                    )
                ],
                tags=tags,
                opts=child,
            )
            azure_native.network.PrivateDnsZoneGroup(
                f"{name}-{label}-pe-dnsgroup",
                resource_group_name=resource_group_name,
                private_endpoint_name=endpoint.name,
                private_dns_zone_configs=zone_configs,
                opts=child,
            )
            self.private_endpoints[label] = endpoint

        self.register_outputs(
            {f"{label}_private_endpoint_id": pe.id for label, pe in self.private_endpoints.items()}
        )
