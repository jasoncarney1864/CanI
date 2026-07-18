"""Cost governance (docs/15-cost-management.md §15.3, Sprint 2 B1).

A subscription-scoped monthly Cost budget with burn-threshold notifications. Because the
whole subscription is the dev environment today, the subscription budget *is* the dev
environment budget; a separate prod budget arrives with a prod subscription (§15.3
environment-level budgets), tracked as deferred.

Notifications go to the same ops email A2 validated. Budgets deliver via their own
Consumption notification channel (contact_emails), independent of the Monitor action
group and the Log Analytics workspace — so a budget alert still fires even if the
telemetry pipeline or its daily cap is having a bad day.
"""

from __future__ import annotations

import pulumi_azure_native as azure_native
from pulumi import ComponentResource, Input, Output, ResourceOptions

# §15.3 burn thresholds: early warning -> investigate -> mitigate -> freeze.
_BURN_THRESHOLDS = (50, 75, 90, 100)


class SubscriptionBudget(ComponentResource):
    def __init__(
        self,
        name: str,
        *,
        subscription_id: Input[str],
        monthly_amount: float,
        alert_email: Input[str],
        # First of a month, fixed so the budget is stable across deploys (Azure rejects a
        # moving start_date on an existing budget, and a monthly grain requires the 1st).
        start_date: str,
        end_date: str = "2030-12-31T00:00:00Z",
        opts: ResourceOptions | None = None,
    ):
        super().__init__("cani:platform:SubscriptionBudget", name, None, opts)

        # An Actual-cost notification per burn threshold, plus one Forecasted notification
        # at 100% — the forecast warns you're *trending* to blow the cap before you
        # actually have, which is the difference between "mitigate" and "already frozen".
        notifications = {
            f"actual-{pct}pct": azure_native.consumption.NotificationArgs(
                enabled=True,
                operator=azure_native.consumption.OperatorType.GREATER_THAN_OR_EQUAL_TO,
                threshold=float(pct),
                threshold_type=azure_native.consumption.ThresholdType.ACTUAL,
                contact_emails=[alert_email],
            )
            for pct in _BURN_THRESHOLDS
        }
        notifications["forecasted-100pct"] = azure_native.consumption.NotificationArgs(
            enabled=True,
            operator=azure_native.consumption.OperatorType.GREATER_THAN_OR_EQUAL_TO,
            threshold=100.0,
            threshold_type=azure_native.consumption.ThresholdType.FORECASTED,
            contact_emails=[alert_email],
        )

        self.budget = azure_native.consumption.Budget(
            f"{name}-budget",
            budget_name=f"{name}-monthly",
            # get_client_config().subscription_id is a plain str, but callers could also
            # pass an Output; from_input normalizes both before building the scope.
            scope=Output.from_input(subscription_id).apply(lambda s: f"/subscriptions/{s}"),
            category=azure_native.consumption.CategoryType.COST,
            amount=monthly_amount,
            time_grain=azure_native.consumption.TimeGrainType.MONTHLY,
            time_period=azure_native.consumption.BudgetTimePeriodArgs(
                start_date=start_date, end_date=end_date
            ),
            notifications=notifications,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs({"budget_id": self.budget.id})
