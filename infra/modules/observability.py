"""Central Log Analytics workspace (docs/06 §6.1, docs/13-observability.md §13.2) and a
diagnostic-settings helper so every resource module can route logs/metrics to it without
repeating the wiring.
"""

from __future__ import annotations

import pulumi_azure_native as azure_native
from pulumi import ComponentResource, Input, ResourceOptions


class CentralLogAnalytics(ComponentResource):
    def __init__(
        self,
        name: str,
        *,
        resource_group_name: str,
        tags: dict,
        daily_quota_gb: float | None = None,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:platform:CentralLogAnalytics", name, None, opts)

        self.workspace = azure_native.operationalinsights.Workspace(
            f"{name}-law",
            resource_group_name=resource_group_name,
            sku=azure_native.operationalinsights.WorkspaceSkuArgs(name="PerGB2018"),
            retention_in_days=30,  # dev default; §15.13 open question on prod retention
            # §15 cost backstop: hard daily ingestion cap. When hit, ALL ingestion stops
            # for the rest of the UTC day (including app telemetry and audit logs), so
            # this is a circuit breaker against runaway sources — sized well above
            # expected volume, never as normal-operation throttling. Added after the
            # unbounded `allLogs` AKS diagnostic setting ingested 5.78 GB/day of
            # kube-audit before anyone was looking (Sprint 2 A2 recon, 2026-07-17).
            workspace_capping=(
                azure_native.operationalinsights.WorkspaceCappingArgs(daily_quota_gb=daily_quota_gb)
                if daily_quota_gb is not None
                else None
            ),
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs({"workspace_id": self.workspace.id})


class ApplicationInsights(ComponentResource):
    """Workspace-based Application Insights for app telemetry (docs/13 §13.7). Traces,
    logs, and metrics from the four services flow here via the Azure Monitor
    OpenTelemetry distro; it shares the central Log Analytics workspace so app and
    cluster signals correlate in one place. Workspace-based is required — classic
    (key-only) App Insights is retired."""

    def __init__(
        self,
        name: str,
        *,
        resource_group_name: str,
        workspace_id: Input[str],
        tags: dict,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:platform:ApplicationInsights", name, None, opts)

        self.component = azure_native.applicationinsights.Component(
            f"{name}-appi",
            resource_group_name=resource_group_name,
            kind="web",
            application_type=azure_native.applicationinsights.ApplicationType.WEB,
            workspace_resource_id=workspace_id,
            ingestion_mode=azure_native.applicationinsights.IngestionMode.LOG_ANALYTICS,
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs(
            {
                "component_id": self.component.id,
                "connection_string": self.component.connection_string,
            }
        )


def send_diagnostics_to_workspace(
    name: str,
    *,
    target_resource_id: Input[str],
    workspace_id: Input[str],
    log_categories: list[str] | None = None,
    opts: ResourceOptions | None = None,
) -> azure_native.monitor.DiagnosticSetting:
    """§6.3: "Require diagnostic settings routed to the central Log Analytics workspace."
    Call once per resource that needs to forward logs/metrics — makes observability
    complete-by-construction rather than opt-in per resource.

    `log_categories` selects specific categories instead of the `allLogs` group. For
    chatty resources this is a cost control, not an observability compromise: on AKS,
    `allLogs` ingested 5.78 GB/day — 76% of it the read-inclusive `kube-audit` category
    (~$400/month at PerGB2018, on a dev cluster). Pass the categories that carry signal
    (e.g. `kube-audit-admin` keeps every write/delete audit event) and drop the rest.
    """
    if log_categories:
        logs = [
            azure_native.monitor.LogSettingsArgs(category=category, enabled=True)
            for category in log_categories
        ]
    else:
        logs = [azure_native.monitor.LogSettingsArgs(category_group="allLogs", enabled=True)]
    return azure_native.monitor.DiagnosticSetting(
        f"{name}-diag",
        resource_uri=target_resource_id,
        workspace_id=workspace_id,
        logs=logs,
        metrics=[azure_native.monitor.MetricSettingsArgs(category="AllMetrics", enabled=True)],
        opts=opts,
    )


class ContainerInsightsCollection(ComponentResource):
    """Data Collection Rule + association that actually makes Container Insights flow.

    The AKS `omsagent` addon with `useAADAuth: true` (compute_aks.py) deploys the
    ama-logs agents but does NOT create the DCR that tells them what to collect and
    where to send it — enabling via `az aks enable-addons` creates it implicitly, but
    the Pulumi addon profile alone does not. Result observed in A2 recon (2026-07-17):
    agents Running for days, zero ContainerLogV2/KubeNodeInventory rows in the
    workspace. This component supplies the missing pieces. The association name MUST be
    "ContainerInsightsExtension" — the agent looks it up by that exact name."""

    def __init__(
        self,
        name: str,
        *,
        resource_group_name: Input[str],
        location: Input[str],
        cluster_id: Input[str],
        workspace_id: Input[str],
        tags: dict,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:workload:ContainerInsightsCollection", name, None, opts)

        self.rule = azure_native.monitor.DataCollectionRule(
            f"{name}-dcr",
            resource_group_name=resource_group_name,
            location=location,
            kind="Linux",
            data_sources=azure_native.monitor.DataCollectionRuleDataSourcesArgs(
                extensions=[
                    azure_native.monitor.ExtensionDataSourceArgs(
                        name="ContainerInsightsExtension",
                        extension_name="ContainerInsights",
                        streams=["Microsoft-ContainerInsights-Group-Default"],
                        extension_settings={
                            "dataCollectionSettings": {
                                "interval": "1m",
                                "namespaceFilteringMode": "Off",
                                "enableContainerLogV2": True,
                            }
                        },
                    )
                ]
            ),
            destinations=azure_native.monitor.DataCollectionRuleDestinationsArgs(
                log_analytics=[
                    azure_native.monitor.LogAnalyticsDestinationArgs(
                        workspace_resource_id=workspace_id,
                        name="ciworkspace",
                    )
                ]
            ),
            data_flows=[
                azure_native.monitor.DataFlowArgs(
                    streams=["Microsoft-ContainerInsights-Group-Default"],
                    destinations=["ciworkspace"],
                )
            ],
            tags=tags,
            opts=ResourceOptions(parent=self),
        )

        self.association = azure_native.monitor.DataCollectionRuleAssociation(
            f"{name}-dcra",
            association_name="ContainerInsightsExtension",  # exact name required by the addon
            resource_uri=cluster_id,
            data_collection_rule_id=self.rule.id,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs({"dcr_id": self.rule.id})
