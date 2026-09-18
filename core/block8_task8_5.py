"""
Block 8 — Task 8.5: latency optimization insight (read-only).

Converts the factual Task 8.4 ``LatencyAnalysis`` into a structured
optimization insight. Pure/read-only: does not mutate the analysis,
re-measures nothing, invents no values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.latency_instrumentation import LatencyAnalysis, OrderLatencyAttribution


@dataclass(frozen=True)
class LatencyOptimizationInsight:
    """
    Structured optimization insight derived from a ``LatencyAnalysis``.

    All numeric fields are in nanoseconds unless noted as percentage.
    """

    # High-level availability status.
    # "AVAILABLE"  -> analyzable data exists and execution_total_ns > 0.
    # "UNAVAILABLE" -> no analyzable attributions or execution_total_ns == 0.
    status: str

    # Number of attributions that had all three required fields present
    # and non-negative.
    analyzed_orders: int

    # Sum of total_execution_latency_ns over analyzable attributions.
    execution_total_ns: int

    # Sum of broker_api_time_ns over analyzable attributions.
    broker_api_total_ns: int

    # Sum of application_side_ns over analyzable attributions.
    application_side_total_ns: int

    # broker_api_total_ns / execution_total_ns * 100 (None when unavailable).
    broker_api_share_pct: Optional[float]

    # application_side_total_ns / execution_total_ns * 100 (None when unavailable).
    application_side_share_pct: Optional[float]

    # Human-readable reason when status == "UNAVAILABLE". Empty string when
    # status == "AVAILABLE" (kept for consistent field presence).
    reason: str


def _is_analyzable(attr: OrderLatencyAttribution) -> bool:
    """Return True iff the attribution has all three required fields present and non-negative."""
    return (
        attr.total_execution_latency_ns is not None
        and attr.broker_api_time_ns is not None
        and attr.application_side_ns is not None
        and attr.total_execution_latency_ns >= 0
        and attr.broker_api_time_ns >= 0
        and attr.application_side_ns >= 0
    )


def build_latency_insight(analysis: LatencyAnalysis) -> LatencyOptimizationInsight:
    """
    Build a read-only optimization insight from a Task 8.4 ``LatencyAnalysis``.

    Pure function: does not mutate ``analysis`` or any of its nested objects.

    Calculation uses ONLY ``analysis.attributions``. For each attribution the
    following fields are used:

    * ``total_execution_latency_ns``
    * ``broker_api_time_ns``
    * ``application_side_ns``

    ``broker_api_time_sequence_wide_ns`` is NOT used for the component split.

    An attribution is analyzable only when all three fields above are not
    ``None`` and are non-negative.

    If there are no analyzable attributions, or if the aggregated
    ``execution_total_ns`` is zero, the insight returns ``status="UNAVAILABLE"``
    with ``None`` percentages and a clear ``reason``.
    """
    analyzable = [attr for attr in analysis.attributions if _is_analyzable(attr)]
    analyzed_orders = len(analyzable)

    if analyzed_orders == 0:
        return LatencyOptimizationInsight(
            status="UNAVAILABLE",
            analyzed_orders=0,
            execution_total_ns=0,
            broker_api_total_ns=0,
            application_side_total_ns=0,
            broker_api_share_pct=None,
            application_side_share_pct=None,
            reason="No analyzable attributions (missing or incomplete fields)",
        )

    execution_total_ns = sum(attr.total_execution_latency_ns for attr in analyzable)
    broker_api_total_ns = sum(attr.broker_api_time_ns for attr in analyzable)
    application_side_total_ns = sum(attr.application_side_ns for attr in analyzable)

    if execution_total_ns == 0:
        return LatencyOptimizationInsight(
            status="UNAVAILABLE",
            analyzed_orders=analyzed_orders,
            execution_total_ns=0,
            broker_api_total_ns=broker_api_total_ns,
            application_side_total_ns=application_side_total_ns,
            broker_api_share_pct=None,
            application_side_share_pct=None,
            reason="Execution total latency is zero; cannot compute percentages",
        )

    broker_api_share_pct = (broker_api_total_ns / execution_total_ns) * 100.0
    application_side_share_pct = (application_side_total_ns / execution_total_ns) * 100.0

    return LatencyOptimizationInsight(
        status="AVAILABLE",
        analyzed_orders=analyzed_orders,
        execution_total_ns=execution_total_ns,
        broker_api_total_ns=broker_api_total_ns,
        application_side_total_ns=application_side_total_ns,
        broker_api_share_pct=broker_api_share_pct,
        application_side_share_pct=application_side_share_pct,
        reason="",
    )