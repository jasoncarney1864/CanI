"""Shared naming/tagging helpers (docs/11-iac-strategy.md §11.10). Centralized here so
naming logic can't drift between infra/platform and infra/workload.
"""

from __future__ import annotations

from dataclasses import dataclass

REQUIRED_TAGS = ("environment", "owner", "spoke")


@dataclass(frozen=True)
class NamingContext:
    project: str  # "platform" | "workload"
    layer: str  # e.g. "network", "aks", "data"
    environment: str  # "dev" | "prod"
    region: str = "eastus2"

    def resource_name(self, suffix: str) -> str:
        return f"cani-{self.project}-{self.layer}-{self.environment}-{self.region}-{suffix}"


def base_tags(*, environment: str, owner: str, spoke: str, cost_center: str = "cani-solo", workload_type: str = "") -> dict[str, str]:
    tags = {
        "environment": environment,
        "owner": owner,
        "spoke": spoke,
        "costCenter": cost_center,
    }
    if workload_type:
        tags["workloadType"] = workload_type
    return tags
