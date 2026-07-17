"""Azure Monitor alert baseline (docs/13-observability.md §13.8, Sprint 2 A2).

One action group + the initial alert set as code. The three log alerts live here
(platform stack, next to the workspace they query); the node not-ready alert is a
platform *metric* alert on the AKS cluster resource, so it lives in the workload stack
(see infra/workload/__main__.py) and consumes this module's action group via the §11.6
StackReference contract (`ops_action_group_id`).

Signal sources — chosen deliberately, verified against live workspace data 2026-07-17:
- 5xx and latency query `AppRequests` (App Insights, proven flowing since A1).
- Dead-letter growth queries `ContainerLogV2` (pod stdout via Container Insights): the
  ingestion-worker's structlog `job_dead_lettered` event goes to stdout, NOT to
  AppTraces (structlog uses PrintLoggerFactory, bypassing stdlib logging), and psycopg
  emits no spans — so container stdout is the only place this signal exists.
"""

from __future__ import annotations

import pulumi_azure_native as azure_native
from pulumi import ComponentResource, Input, ResourceOptions

# Runbook/spec references surfaced in each alert's description per §13.8 ("include
# runbook link and owning service tag in each alert").
_REPO = "https://github.com/jasoncarney1864/CanI/blob/main"


class OpsAlerting(ComponentResource):
    """Email action group + the §13.8 log-query alert baseline over the central
    Log Analytics workspace."""

    def __init__(
        self,
        name: str,
        *,
        resource_group_name: Input[str],
        location: Input[str],
        workspace_id: Input[str],
        alert_email: Input[str],
        tags: dict,
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:platform:OpsAlerting", name, None, opts)
        child = ResourceOptions(parent=self)

        self.action_group = azure_native.monitor.ActionGroup(
            f"{name}-ag",
            resource_group_name=resource_group_name,
            location="Global",  # action groups are global resources
            group_short_name="cani-ops",  # 12-char limit; shown in notification subject
            enabled=True,
            email_receivers=[
                azure_native.monitor.EmailReceiverArgs(
                    name="ops-email",
                    email_address=alert_email,
                    use_common_alert_schema=True,
                )
            ],
            tags=tags,
            opts=child,
        )

        def _log_alert(
            resource_suffix: str,
            *,
            display_name: str,
            description: str,
            severity: int,
            query: str,
            threshold: float,
            operator: str,
            time_aggregation: str,
            window: str,
            frequency: str,
            metric_measure_column: str | None = None,
        ) -> azure_native.monitor.ScheduledQueryRule:
            return azure_native.monitor.ScheduledQueryRule(
                f"{name}-{resource_suffix}",
                resource_group_name=resource_group_name,
                location=location,  # log alerts are regional; must match workspace region
                display_name=display_name,
                description=description,
                severity=severity,
                enabled=True,
                scopes=[workspace_id],
                evaluation_frequency=frequency,
                window_size=window,
                auto_mitigate=True,  # resolve automatically when the condition clears
                criteria=azure_native.monitor.ScheduledQueryRuleCriteriaArgs(
                    all_of=[
                        azure_native.monitor.ConditionArgs(
                            query=query,
                            time_aggregation=time_aggregation,
                            metric_measure_column=metric_measure_column,
                            operator=operator,
                            threshold=threshold,
                            failing_periods=azure_native.monitor.ConditionFailingPeriodsArgs(
                                min_failing_periods_to_alert=1,
                                number_of_evaluation_periods=1,
                            ),
                        )
                    ]
                ),
                actions=azure_native.monitor.ActionsArgs(action_groups=[self.action_group.id]),
                tags=tags,
                opts=child,
            )

        # P1 — elevated 5xx on the API surface. Count threshold rather than a rate:
        # at dev traffic volume a percentage is dominated by single requests, while
        # >=5 server errors in 15 minutes is unambiguous at any volume.
        self.elevated_5xx = _log_alert(
            "5xx",
            display_name="cani-p1-elevated-5xx",
            description=(
                "P1: >=5 server errors (5xx) across hub/docs APIs in 15m. "
                f"Owning services: hub-api, docs-api. Triage: {_REPO}/docs/13-observability.md "
                "(section 13.8); check App Insights failures blade by cloud_RoleName, then pod "
                "logs. Common causes: bad deploy (check app-cd-dev run), Postgres/Qdrant "
                "connectivity, missing migration (whoami smoke catches this)."
            ),
            severity=1,
            query='AppRequests | where Success == false and toint(ResultCode) >= 500',
            time_aggregation="Count",
            operator="GreaterThanOrEqual",
            threshold=5,
            window="PT15M",
            frequency="PT5M",
        )

        # P2 — retrieval latency SLO breach (docs/02 requirement: query P95 < 5s
        # end-to-end). Measured at docs-api's POST /query (the user-facing edge of the
        # retrieval path); POST /retrieve included so we can tell which hop regressed.
        self.latency_slo = _log_alert(
            "latency",
            display_name="cani-p2-retrieval-latency-slo",
            description=(
                "P2: P95 latency for POST /query exceeded the 5s SLO (docs/02 section 2, "
                "docs/13 section 13.10) sustained over 30m. Owning service: docs-api / "
                "retrieval-worker. Triage: App Insights distributed trace for a slow "
                "operation — the per-hop breakdown (docs-api -> retrieval-worker -> Qdrant "
                "-> Azure OpenAI) shows which dependency regressed."
            ),
            severity=2,
            query=(
                'AppRequests | where Name == "POST /query"'
                " | summarize p95_ms = percentile(DurationMs, 95)"
            ),
            time_aggregation="Average",
            metric_measure_column="p95_ms",
            operator="GreaterThan",
            threshold=5000,
            window="PT30M",
            frequency="PT15M",
        )

        # P2 — ingestion dead-letter growth. Any dead-lettered job is a document a user
        # uploaded that silently never became searchable, so the threshold is
        # "any occurrence", not a rate.
        self.dead_letter = _log_alert(
            "deadletter",
            display_name="cani-p2-ingestion-dead-letter",
            description=(
                "P2: one or more ingestion jobs dead-lettered in 15m — an uploaded document "
                "failed all retries and is NOT searchable. Owning service: ingestion-worker. "
                f"Runbook: {_REPO}/runbooks/ingestion-dead-letter.md"
            ),
            severity=2,
            query=(
                'ContainerLogV2 | where ContainerName == "ingestion-worker"'
                ' | where LogMessage has "job_dead_lettered"'
            ),
            time_aggregation="Count",
            operator="GreaterThan",
            threshold=0,
            window="PT15M",
            frequency="PT15M",
        )

        self.register_outputs({"action_group_id": self.action_group.id})


def node_not_ready_alert(
    name: str,
    *,
    resource_group_name: Input[str],
    cluster_id: Input[str],
    action_group_id: Input[str],
    tags: dict,
    opts: ResourceOptions | None = None,
) -> azure_native.monitor.MetricAlert:
    """P1 node not-ready (§13.8), as a platform metric alert on the AKS cluster itself.

    Deliberately NOT a Container Insights log query: the platform metric
    `kube_node_status_condition` comes from the control plane, so this alert still fires
    when the agent pipeline (ama-logs -> DCR -> workspace) is itself broken — which is
    exactly the failure mode A2 recon found (agents Running, no data flowing).
    Dimension names verified against the live cluster's metric definitions
    (condition/status/status2/node); the baseline filter is condition=Ready,
    status2=NotReady.
    """
    return azure_native.monitor.MetricAlert(
        name,
        resource_group_name=resource_group_name,
        location="global",  # metric alerts are global resources
        description=(
            "P1: one or more AKS nodes NotReady for 5m. Owning layer: cluster. Triage: "
            f"{_REPO}/docs/10-aks-cluster-design.md; `az aks command invoke ... kubectl get "
            "nodes` then `kubectl describe node`. Note: cluster runs at the regional vCPU "
            "quota ceiling (10 cores), so a lost node cannot be replaced by scale-out until "
            "quota is raised."
        ),
        severity=1,
        enabled=True,
        scopes=[cluster_id],
        evaluation_frequency="PT1M",
        window_size="PT5M",
        auto_mitigate=True,
        criteria=azure_native.monitor.MetricAlertSingleResourceMultipleMetricCriteriaArgs(
            odata_type="Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
            all_of=[
                azure_native.monitor.MetricCriteriaArgs(
                    criterion_type="StaticThresholdCriterion",
                    name="node-not-ready",
                    metric_name="kube_node_status_condition",
                    metric_namespace="Microsoft.ContainerService/managedClusters",
                    dimensions=[
                        azure_native.monitor.MetricDimensionArgs(
                            name="condition", operator="Include", values=["Ready"]
                        ),
                        azure_native.monitor.MetricDimensionArgs(
                            name="status2", operator="Include", values=["NotReady"]
                        ),
                    ],
                    operator="GreaterThan",
                    threshold=0,
                    time_aggregation="Average",
                )
            ],
        ),
        actions=[azure_native.monitor.MetricAlertActionArgs(action_group_id=action_group_id)],
        tags=tags,
        opts=opts,
    )
