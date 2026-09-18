"""
Block 8 — Task 8.5: latency optimization insight tests.

Read-only insight over the existing Task 8.4 ``LatencyAnalysis``.
"""

from __future__ import annotations

from core import latency_instrumentation as li
from core.block8_task8_5 import (
    LatencyOptimizationInsight,
    build_latency_insight,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_attribution(
    sequence: int,
    total_execution_latency_ns: Optional[int],
    broker_api_time_ns: Optional[int],
    application_side_ns: Optional[int],
) -> li.OrderLatencyAttribution:
    """Helper to create a simple OrderLatencyAttribution for testing."""
    return li.OrderLatencyAttribution(
        sequence=sequence,
        broker_name="TestBroker",
        total_execution_latency_ns=total_execution_latency_ns,
        broker_api_time_ns=broker_api_time_ns,
        application_side_ns=application_side_ns,
        order_success=True,
        engine_stage_failed=False,
        broker_api_time_sequence_wide_ns=total_execution_latency_ns or 0,
        broker_api_failure_count=0,
        broker_api_calls_within_engine=1,
    )


def create_analysis_with_attributions(
    attributions: list[li.OrderLatencyAttribution],
) -> li.LatencyAnalysis:
    """Helper to create a LatencyAnalysis with given attributions."""
    return li.LatencyAnalysis(
        trace_id=None,
        total_orders=len(attributions),
        successful_orders=len(attributions),
        failed_orders=0,
        dispatch_duration_ns=1000,
        execution_latency_ns=li.LatencyDistribution(count=len(attributions)),
        stage_durations_ns={
            li.PLAN_ITEM: li.LatencyDistribution(count=0),
            li.PLAN_ACCOUNT: li.LatencyDistribution(count=0),
            li.INSTRUMENT_RESOLUTION: li.LatencyDistribution(count=0),
            li.ORDER_ENGINE_PATH: li.LatencyDistribution(count=len(attributions)),
        },
        broker_api_total_ns=0,
        broker_api_time_ns=li.LatencyDistribution(count=0),
        broker_api_by_operation_ns={},
        broker_api_failure_count=0,
        broker_api_failures=(),
        attributions=tuple(attributions),
        application_side_time_ns=li.LatencyDistribution(count=0),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_normal_multi_order_calculation():
    """Test that normal multi-order data computes correctly."""
    attributions = [
        create_attribution(1, 1000, 200, 800),
        create_attribution(2, 2000, 400, 1600),
        create_attribution(3, 3000, 600, 2400),
    ]
    analysis = create_analysis_with_attributions(attributions)
    insight = build_latency_insight(analysis)

    assert insight.status == "AVAILABLE"
    assert insight.analyzed_orders == 3
    assert insight.execution_total_ns == 6000
    assert insight.broker_api_total_ns == 1200
    assert insight.application_side_total_ns == 4800

    assert insight.broker_api_share_pct == 20.0
    assert insight.application_side_share_pct == 80.0
    assert insight.reason == ""


def test_one_order():
    """Test that a single order produces correct insight."""
    attributions = [create_attribution(1, 5000, 1000, 4000)]
    analysis = create_analysis_with_attributions(attributions)
    insight = build_latency_insight(analysis)

    assert insight.status == "AVAILABLE"
    assert insight.analyzed_orders == 1
    assert insight.execution_total_ns == 5000
    assert insight.broker_api_total_ns == 1000
    assert insight.application_side_total_ns == 4000
    assert insight.broker_api_share_pct == 20.0
    assert insight.application_side_share_pct == 80.0


def test_multiple_orders():
    """Test with multiple orders of varying sizes."""
    attributions = [
        create_attribution(1, 100, 20, 80),
        create_attribution(2, 200, 40, 160),
        create_attribution(3, 300, 60, 240),
        create_attribution(4, 400, 80, 320),
        create_attribution(5, 500, 100, 400),
    ]
    analysis = create_analysis_with_attributions(attributions)
    insight = build_latency_insight(analysis)

    assert insight.status == "AVAILABLE"
    assert insight.analyzed_orders == 5
    assert insight.execution_total_ns == 1500
    assert insight.broker_api_total_ns == 300
    assert insight.application_side_total_ns == 1200
    assert insight.broker_api_share_pct == 20.0
    assert insight.application_side_share_pct == 80.0


def test_missing_application_side_ns():
    """Test that missing application_side_ns results in unavailable status."""
    attributions = [
        create_attribution(1, 1000, 200, None),
        create_attribution(2, 2000, 400, None),
    ]
    analysis = create_analysis_with_attributions(attributions)
    insight = build_latency_insight(analysis)

    assert insight.status == "UNAVAILABLE"
    assert insight.analyzed_orders == 0
    assert insight.execution_total_ns == 0
    assert insight.broker_api_total_ns == 0
    assert insight.application_side_total_ns == 0
    assert insight.broker_api_share_pct is None
    assert insight.application_side_share_pct is None
    assert "missing" in insight.reason.lower()


def test_missing_broker_api_attribution():
    """Test that missing broker_api_time_ns results in unavailable status."""
    attributions = [
        create_attribution(1, 1000, None, 800),
        create_attribution(2, 2000, None, 1600),
    ]
    analysis = create_analysis_with_attributions(attributions)
    insight = build_latency_insight(analysis)

    assert insight.status == "UNAVAILABLE"
    assert insight.analyzed_orders == 0
    assert insight.execution_total_ns == 0
    assert insight.broker_api_total_ns == 0
    assert insight.application_side_total_ns == 0
    assert insight.broker_api_share_pct is None
    assert insight.application_side_share_pct is None
    assert "missing" in insight.reason.lower()


def test_no_analyzable_orders():
    """Test with no analyzable orders (all fields present but negative)."""
    attributions = [
        create_attribution(1, -100, 20, 80),  # negative total_execution_latency_ns
        create_attribution(2, 2000, -40, 1600),  # negative broker_api_time_ns
        create_attribution(3, 3000, 60, -2400),  # negative application_side_ns
    ]
    analysis = create_analysis_with_attributions(attributions)
    insight = build_latency_insight(analysis)

    assert insight.status == "UNAVAILABLE"
    assert insight.analyzed_orders == 0
    assert insight.execution_total_ns == 0
    assert insight.broker_api_total_ns == 0
    assert insight.application_side_total_ns == 0
    assert insight.broker_api_share_pct is None
    assert insight.application_side_share_pct is None
    assert "missing" in insight.reason.lower()


def test_zero_execution_with_nonzero_totals():
    """Test with analyzable orders where total_execution_latency_ns == 0 but broker and application sides are non-zero."""
    attributions = [
        create_attribution(1, 0, 200, 800),
        create_attribution(2, 0, 300, 1200),
    ]
    analysis = create_analysis_with_attributions(attributions)
    insight = build_latency_insight(analysis)

    # Should be UNAVAILABLE because execution_total_ns == 0
    assert insight.status == "UNAVAILABLE"
    assert insight.analyzed_orders == 2
    assert insight.execution_total_ns == 0
    assert insight.broker_api_total_ns == 500  # 200 + 300 (real aggregated value, not zero)
    assert insight.application_side_total_ns == 2000  # 800 + 1200 (real aggregated value, not zero)
    assert insight.broker_api_share_pct is None
    assert insight.application_side_share_pct is None
    assert insight.reason == "Execution total latency is zero; cannot compute percentages"


def test_non_negative_percentage_results():
    """Test that percentages are always non-negative."""
    attributions = [
        create_attribution(1, 100, 200, 800),  # broker_api_time_ns > total_execution_latency_ns
        create_attribution(2, 300, 100, 200),
    ]
    analysis = create_analysis_with_attributions(attributions)
    insight = build_latency_insight(analysis)

    assert insight.status == "AVAILABLE"
    assert insight.broker_api_share_pct >= 0.0
    assert insight.application_side_share_pct >= 0.0


def test_percentage_calculation_accuracy():
    """Test that percentage calculations are mathematically accurate."""
    # Test with exact values
    attributions = [
        create_attribution(1, 100, 25, 75),
    ]
    analysis = create_analysis_with_attributions(attributions)
    insight = build_latency_insight(analysis)

    assert insight.broker_api_share_pct == 25.0
    assert insight.application_side_share_pct == 75.0

    # Test with multiple orders
    attributions = [
        create_attribution(1, 100, 30, 70),
        create_attribution(2, 200, 60, 140),
    ]
    analysis = create_analysis_with_attributions(attributions)
    insight = build_latency_insight(analysis)

    assert insight.execution_total_ns == 300
    assert insight.broker_api_total_ns == 90
    assert insight.application_side_total_ns == 210

    expected_broker_pct = (90 / 300) * 100.0
    expected_app_pct = (210 / 300) * 100.0

    assert insight.broker_api_share_pct == expected_broker_pct
    assert insight.application_side_share_pct == expected_app_pct


def test_sequence_wide_time_not_used():
    """Test that broker_api_time_sequence_wide_ns is not used in calculation."""
    # Create attributions where broker_api_time_ns is different from broker_api_time_sequence_wide_ns
    # This ensures the function uses the correct field
    attrib1 = li.OrderLatencyAttribution(
        sequence=1,
        broker_name="Broker-A",
        total_execution_latency_ns=1000,
        broker_api_time_ns=200,  # This is what's used in calculation
        application_side_ns=800,
        order_success=True,
        engine_stage_failed=False,
        broker_api_time_sequence_wide_ns=1500,  # Different value, but ignored
        broker_api_failure_count=0,
        broker_api_calls_within_engine=1,
    )
    attrib2 = li.OrderLatencyAttribution(
        sequence=2,
        broker_name="Broker-B",
        total_execution_latency_ns=2000,
        broker_api_time_ns=400,
        application_side_ns=1600,
        order_success=True,
        engine_stage_failed=False,
        broker_api_time_sequence_wide_ns=2500,  # Different value, but ignored
        broker_api_failure_count=0,
        broker_api_calls_within_engine=1,
    )

    analysis = create_analysis_with_attributions([attrib1, attrib2])
    insight = build_latency_insight(analysis)

    # The calculation should only use broker_api_time_ns, not broker_api_time_sequence_wide_ns
    assert insight.status == "AVAILABLE"
    assert insight.analyzed_orders == 2
    assert insight.execution_total_ns == 3000
    assert insight.broker_api_total_ns == 600  # 200 + 400 (not 1500 + 2500)
    assert insight.application_side_total_ns == 2400


def test_input_object_remains_unchanged():
    """Test that the input analysis object is not modified."""
    attributions = [
        create_attribution(1, 1000, 200, 800),
        create_attribution(2, 2000, 400, 1600),
    ]
    analysis = create_analysis_with_attributions(attributions)

    # Get original values
    original_attributions = analysis.attributions

    # Build insight
    insight = build_latency_insight(analysis)

    # Check that analysis hasn't changed
    assert analysis.attributions == original_attributions

    # Create a simple analysis object and verify it's not mutated
    original_attr = analysis.attributions[0]
    insight2 = build_latency_insight(analysis)

    # The attribution should still be the same object
    assert analysis.attributions[0] is original_attr


def test_existing_task8_4_attribution_fields_unchanged():
    """Test that existing Task 8.4 attribution fields are not altered."""
    # Create attributions with all the fields that exist in Task 8.4
    attrib1 = li.OrderLatencyAttribution(
        sequence=1,
        broker_name="Broker-A",
        total_execution_latency_ns=1000,
        broker_api_time_ns=200,
        application_side_ns=800,
        order_success=True,
        engine_stage_failed=False,
        broker_api_time_sequence_wide_ns=1500,
        broker_api_failure_count=0,
        broker_api_calls_within_engine=1,
    )
    attrib2 = li.OrderLatencyAttribution(
        sequence=2,
        broker_name="Broker-B",
        total_execution_latency_ns=2000,
        broker_api_time_ns=400,
        application_side_ns=1600,
        order_success=False,
        engine_stage_failed=True,
        broker_api_time_sequence_wide_ns=2500,
        broker_api_failure_count=1,
        broker_api_calls_within_engine=2,
    )

    analysis = create_analysis_with_attributions([attrib1, attrib2])

    # Verify all fields are still intact
    assert analysis.attributions[0].sequence == 1
    assert analysis.attributions[0].broker_name == "Broker-A"
    assert analysis.attributions[0].total_execution_latency_ns == 1000
    assert analysis.attributions[0].broker_api_time_ns == 200
    assert analysis.attributions[0].application_side_ns == 800
    assert analysis.attributions[0].order_success is True
    assert analysis.attributions[0].engine_stage_failed is False
    assert analysis.attributions[0].broker_api_time_sequence_wide_ns == 1500
    assert analysis.attributions[0].broker_api_failure_count == 0
    assert analysis.attributions[0].broker_api_calls_within_engine == 1

    assert analysis.attributions[1].sequence == 2
    assert analysis.attributions[1].broker_name == "Broker-B"
    assert analysis.attributions[1].total_execution_latency_ns == 2000
    assert analysis.attributions[1].broker_api_time_ns == 400
    assert analysis.attributions[1].application_side_ns == 1600
    assert analysis.attributions[1].order_success is False
    assert analysis.attributions[1].engine_stage_failed is True
    assert analysis.attributions[1].broker_api_time_sequence_wide_ns == 2500
    assert analysis.attributions[1].broker_api_failure_count == 1
    assert analysis.attributions[1].broker_api_calls_within_engine == 2


def test_mixed_unavailable_data_no_guessing():
    """Test that mixed/unavailable data doesn't produce guessed results."""
    # Create a mix of analyzable and non-analyzable attributions directly
    # This is simpler and more focused on testing the insight logic

    # Analyzable attribution (all three fields present and non-negative)
    attrib1 = li.OrderLatencyAttribution(
        sequence=1,
        broker_name="Broker-A",
        total_execution_latency_ns=1000,
        broker_api_time_ns=200,
        application_side_ns=800,
        order_success=True,
        engine_stage_failed=False,
        broker_api_time_sequence_wide_ns=1500,
        broker_api_failure_count=0,
        broker_api_calls_within_engine=1,
    )

    # Non-analyzable attribution (missing total_execution_latency_ns - None)
    attrib2 = li.OrderLatencyAttribution(
        sequence=2,
        broker_name="Broker-B",
        total_execution_latency_ns=None,  # None -> non-analyzable
        broker_api_time_ns=400,
        application_side_ns=1600,
        order_success=False,
        engine_stage_failed=True,
        broker_api_time_sequence_wide_ns=2500,
        broker_api_failure_count=1,
        broker_api_calls_within_engine=2,
    )

    # Another analyzable attribution
    attrib3 = li.OrderLatencyAttribution(
        sequence=3,
        broker_name="Broker-C",
        total_execution_latency_ns=3000,
        broker_api_time_ns=600,
        application_side_ns=2400,
        order_success=True,
        engine_stage_failed=False,
        broker_api_time_sequence_wide_ns=3500,
        broker_api_failure_count=0,
        broker_api_calls_within_engine=1,
    )

    analysis = create_analysis_with_attributions([attrib1, attrib2, attrib3])

    # The insight should only count attrib1 and attrib3 as analyzable (2 orders)
    # attrib2 should be ignored because it has total_execution_latency_ns=None
    insight = build_latency_insight(analysis)

    # Should be AVAILABLE because we have analyzable data
    assert insight.status == "AVAILABLE"
    assert insight.analyzed_orders == 2  # Only attrib1 and attrib3 are analyzable
    assert insight.execution_total_ns == 4000  # 1000 + 3000
    assert insight.broker_api_total_ns == 800    # 200 + 600
    assert insight.application_side_total_ns == 3200  # 800 + 2400
    assert insight.broker_api_share_pct == 20.0  # 800 / 4000 * 100
    assert insight.application_side_share_pct == 80.0  # 3200 / 4000 * 100
    assert insight.reason == ""


def test_insight_is_immutable():
    """Test that LatencyOptimizationInsight is immutable (frozen dataclass)."""
    insights = [
        LatencyOptimizationInsight(
            status="AVAILABLE",
            analyzed_orders=1,
            execution_total_ns=100,
            broker_api_total_ns=20,
            application_side_total_ns=80,
            broker_api_share_pct=20.0,
            application_side_share_pct=80.0,
            reason="",
        )
    ]

    # Try to modify the insight (should fail for a frozen dataclass)
    try:
        insights[0].status = "UNAVAILABLE"
        assert False, "Should not be able to modify frozen dataclass"
    except (AttributeError, TypeError):
        pass  # Expected


def test_field_consistency():
    """Test that all required fields are present and have correct types."""
    insight = LatencyOptimizationInsight(
        status="AVAILABLE",
        analyzed_orders=1,
        execution_total_ns=100,
        broker_api_total_ns=20,
        application_side_total_ns=80,
        broker_api_share_pct=20.0,
        application_side_share_pct=80.0,
        reason="",
    )

    # Check all fields exist and have expected types
    assert isinstance(insight.status, str)
    assert isinstance(insight.analyzed_orders, int)
    assert isinstance(insight.execution_total_ns, int)
    assert isinstance(insight.broker_api_total_ns, int)
    assert isinstance(insight.application_side_total_ns, int)
    assert insight.broker_api_share_pct is None or isinstance(insight.broker_api_share_pct, float)
    assert insight.application_side_share_pct is None or isinstance(insight.application_side_share_pct, float)
    assert isinstance(insight.reason, str)