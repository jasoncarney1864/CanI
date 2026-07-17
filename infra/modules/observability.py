"""Central Log Analytics workspace (docs/06 §6.1, docs/13-observability.md §13.2) and a
diagnostic-settings helper so every resource module can route logs/metrics to it without
repeating the wiring.
"""

from __future__ import annotations

import pulumi_azure_native as azure_native
from pulumi import ComponentResource, Input, ResourceOptions


class CentralLogAnalytics(ComponentResource):
    def __init__(
        self, name: str, *, resource_group_name: str, tags: dict, opts: ResourceOptions | None = None
    ):
        super().__init__("cani:platform:CentralLogAnalytics", name, None, opts)

        self.workspace = azure_native.operationalinsights.Workspace(
            f"{name}-law",
            resource_group_name=resource_group_name,
            sku=azure_native.operationalinsights.WorkspaceSkuArgs(name="PerGB2018"),
            retention_in_days=30,  # dev default; §15.13 open question on prod retention
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
    opts: ResourceOptions | None = None,
) -> azure_native.monitor.DiagnosticSetting:
    """§6.3: "Require diagnostic settings routed to the central Log Analytics workspace."
    Call once per resource that needs to forward logs/metrics — makes observability
    complete-by-construction rather than opt-in per resource."""
    return azure_native.monitor.DiagnosticSetting(
        f"{name}-diag",
        resource_uri=target_resource_id,
        workspace_id=workspace_id,
        logs=[azure_native.monitor.LogSettingsArgs(category_group="allLogs", enabled=True)],
        metrics=[azure_native.monitor.MetricSettingsArgs(category="AllMetrics", enabled=True)],
        opts=opts,
    )
