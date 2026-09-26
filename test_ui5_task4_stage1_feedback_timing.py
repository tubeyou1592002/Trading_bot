"""
UI-5 Task 4 Stage 1 — Order Feedback Timing Capture tests.

Tests the three required timestamps per order:
1. sent_at_ns — when the application sends the order
2. broker_registered_at_ns — when broker registration feedback received (decisionId)
3. matching_engine_registered_at_ns — when matching engine registration feedback received

Uses the existing Block 8 LatencyCollector infrastructure.
"""

import time
from unittest.mock import patch

from core.safety_gate import SafetyGate

from brokers.manager import BrokerManager
from core.dispatch_core import DispatchCore
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from core.latency_instrumentation import (
    LatencyCollector,
    OP_PLACE_ORDER,
    ORDER_ENGINE_PATH,
)
from core.order_engine import OrderEngine, OrderExecutionResult
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, Order
from models.trading_state import VERIFIED_TRADABLE


# ---------------------------------------------------------------------------
# Deterministic clocks and fakes
# ---------------------------------------------------------------------------


class FakeClock:
    """Monotonic fake clock: every read advances by step."""

    def __init__(self, step=1):
        self._value = 0
        self._step = step

    def __call__(self):
        self._value += self._step
        return self._value

    def advance(self, ns):
        self._value += ns


class FakeBroker:
    def __init__(self, name, clock=None, delays=None, raise_on=None, live_response=None):
        self.name = name
        self.clock = clock
        self.delays = dict(delays or {})
        self.raise_on = dict(raise_on or {})
        self.call_log = []
        self.place_order_calls = []
        self.trading_state_calls = []
        self.capacity_calls = []
        # Agah contract: { "isSuccess": true, "data": { "decisionId": "..." } }
        self.live_response = live_response or {
            "isSuccess": True,
            "data": {"decisionId": "DEC-123"}
        }

    def touch(self, operation):
        self.call_log.append(operation)
        if self.clock is not None:
            self.clock.advance(self.delays.get(operation, 0))
        failure = self.raise_on.get(operation)
        if failure is not None:
            raise failure

    def login(self, username, password, **kwargs):
        return {"success": True, "username": username, "token": "fake"}

    def get_account(self):
        self.touch("get_account")
        return Account(account_id=f"ACCOUNT-{self.name}")

    def place_order(self, order, live=False):
        self.place_order_calls.append((order, live))
        self.touch(OP_PLACE_ORDER)
        if live:
            return self.live_response
        return {"mode": "DRY_RUN", "sent": False, "order_id": f"{self.name}-order"}

    def cancel_order(self, order_id):
        return {"canceled": True, "order_id": order_id}

    def get_trading_state(self, nsc_id):
        self.trading_state_calls.append(nsc_id)
        self.touch("get_trading_state")
        return VERIFIED_TRADABLE

    def get_buy_capacity(self, nsc_id, side_code, fund, price):
        self.capacity_calls.append(("get_buy_capacity", nsc_id))
        self.touch("get_buy_capacity")
        return 1_000_000

    def get_sell_capacity(self, nsc_id, side_code, fund, price):
        self.capacity_calls.append(("get_sell_capacity", nsc_id))
        self.touch("get_sell_capacity")
        return 1_000_000


class FakeInstrumentProvider:
    def __init__(self, broker):
        self._broker = broker
        self._cache = {}

    def get_instrument(self, ins_code):
        if ins_code not in self._cache:
            self._cache[ins_code] = make_instrument_pair(
                self._broker.name, ins_code
            )
        return self._cache[ins_code]

    def get_nsc_id(self, ins_code):
        return self.get_instrument(ins_code)[1].nsc_id

    def refresh_cache(self):
        self._cache.clear()


def make_instrument_pair(broker_name, ins_code):
    return (
        Instrument(symbol=ins_code, name=f"{broker_name}:{ins_code}", ins_code=ins_code),
        BrokerInstrument(
            name=f"{broker_name}:{ins_code}",
            company_name=f"{broker_name} Co",
            nsc_id=ins_code,
            tse_id=ins_code,
            minimum_order_quantity=1,
            lot_size=1,
            fixed_price_tick=1,
            lower_price_threshold=1,
            upper_price_threshold=1_000_000,
            maximum_order_quantity_for_buy=1_000_000,
            maximum_order_quantity_for_sell=1_000_000,
        ),
    )


def make_order(nsc_id, side=BUY, price=100, quantity=10):
    return Order(nsc_id=nsc_id, side=side, price=price, quantity=quantity)


def make_account(account_id, balance=10_000_000):
    return Account(
        account_id=account_id,
        last_balance=balance,
        tradable_balance_t1=balance,
        tradable_balance_t2=balance,
    )


def build_plan(pairs, plan_id="ui5_task4_plan"):
    planned = [
        PlannedOrder(
            order=order,
            account_id=account_id,
            broker_name=broker_name,
            sequence=sequence,
        )
        for sequence, (order, account_id, broker_name) in enumerate(pairs, start=1)
    ]
    return ExecutionPlanner().build_plan(
        LogicalOrderInstruction(plan_id=plan_id, orders=planned)
    )


def make_manager(brokers):
    manager = BrokerManager()
    for name, broker in brokers.items():
        manager.register(name, broker, FakeInstrumentProvider)
    return manager


def shared_clock_core(manager, clock, safety_gate=None):
    """DispatchCore with same clock for stage and broker layers."""
    return DispatchCore(
        broker_manager=manager,
        latency_clock=clock,
        broker_clock=clock,
        safety_gate=safety_gate,
    )


def permissive_safety_gate():
    """Permissive SafetyGate for live trading tests."""
    return SafetyGate(
        live_block9_state="COMPLETED",
        explicit_live_request=True,
        human_approval=True,
        live_state="KNOWN",
        m6_status="READY",
        broker_status="READY",
        acceptable_m6_statuses=["READY"],
        acceptable_broker_statuses=["READY"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sent_timestamp_captured_for_live_order():
    """sent_at_ns is captured at the actual send point for live orders."""
    clock = FakeClock()
    broker = FakeBroker("Broker-A", clock=clock)
    core = shared_clock_core(make_manager({"Broker-A": broker}), clock, safety_gate=permissive_safety_gate())

    order = make_order("INS-A")
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]

    # Enable live trading for this test
    broker.live_trading_enabled = True

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    record = report.order(1)

    # sent_at_ns should be captured
    assert record.sent_at_ns is not None
    assert record.sent_at_ns > 0

    # Should be within the ORDER_ENGINE_PATH stage
    engine_stage = record.stage(ORDER_ENGINE_PATH)
    assert engine_stage is not None
    assert record.sent_at_ns >= engine_stage.start
    assert record.sent_at_ns <= engine_stage.end


def test_broker_registered_timestamp_captured_for_live_order():
    """broker_registered_at_ns is captured when broker response received."""
    clock = FakeClock()
    broker = FakeBroker("Broker-A", clock=clock)
    core = shared_clock_core(make_manager({"Broker-A": broker}), clock, safety_gate=permissive_safety_gate())

    order = make_order("INS-A")
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]

    broker.live_trading_enabled = True

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    record = report.order(1)

    # broker_registered_at_ns should be captured (response contains decisionId)
    assert record.broker_registered_at_ns is not None
    assert record.broker_registered_at_ns > 0

    # Should be at or after sent_at_ns
    assert record.broker_registered_at_ns >= record.sent_at_ns

    # Should be within the ORDER_ENGINE_PATH stage
    engine_stage = record.stage(ORDER_ENGINE_PATH)
    assert record.broker_registered_at_ns >= engine_stage.start
    assert record.broker_registered_at_ns <= engine_stage.end


def test_broker_registered_timestamp_not_captured_without_decision_id():
    """
    broker_registered_at_ns is NOT captured when isSuccess=True but data.decisionId is missing.

    Agah contract requires data.decisionId for initial registration confirmation.
    """
    clock = FakeClock()
    # Response with isSuccess=True but NO data.decisionId
    broker = FakeBroker(
        "Broker-A",
        clock=clock,
        live_response={"isSuccess": True, "data": {}}  # missing decisionId
    )
    core = shared_clock_core(make_manager({"Broker-A": broker}), clock, safety_gate=permissive_safety_gate())

    order = make_order("INS-A")
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]

    broker.live_trading_enabled = True

    result, report = core.dispatch_with_latency(plan)

    # Order succeeds but broker_registered_at_ns should NOT be captured
    assert result.success is True
    record = report.order(1)

    assert record.sent_at_ns is not None
    assert record.broker_registered_at_ns is None
    assert record.matching_engine_registered_at_ns is None


def test_matching_engine_timestamp_not_captured_without_pusher():
    """
    matching_engine_registered_at_ns remains None when no Pusher feedback arrives.

    This is expected — the Pusher/OMS integration for AcceptedByBourse (5)
    does not exist yet. The field is reserved for future implementation.
    """
    clock = FakeClock()
    broker = FakeBroker("Broker-A", clock=clock)
    core = shared_clock_core(make_manager({"Broker-A": broker}), clock)

    order = make_order("INS-A")
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]

    broker.live_trading_enabled = True
    core.live_trading_enabled = True

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    record = report.order(1)

    # matching_engine_registered_at_ns should be None (no Pusher integration)
    assert record.matching_engine_registered_at_ns is None


def test_timestamps_associated_with_correct_order():
    """
    Timing information remains associated with the correct order
    even with multiple orders and cross-aligned identity.
    """
    clock = FakeClock()
    brokers = {
        name: FakeBroker(name, clock=clock)
        for name in ("Broker-A", "Broker-B", "Broker-C")
    }
    core = shared_clock_core(make_manager(brokers), clock, safety_gate=permissive_safety_gate())

    orders = {code: make_order(code) for code in ("INS-1", "INS-2", "INS-3")}
    accounts = {aid: make_account(aid) for aid in ("ACC-1", "ACC-2", "ACC-3")}

    # Cross-aligned to detect any "current order" context leak
    pairs = [
        (orders["INS-1"], "ACC-3", "Broker-B"),
        (orders["INS-2"], "ACC-1", "Broker-C"),
        (orders["INS-3"], "ACC-2", "Broker-A"),
    ]
    plan = build_plan(pairs)
    plan.accounts = [accounts["ACC-3"], accounts["ACC-1"], accounts["ACC-2"]]

    for b in brokers.values():
        b.live_trading_enabled = True

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    assert result.order_count == 3

    expected = {
        1: ("ACC-3", "Broker-B", "INS-1"),
        2: ("ACC-1", "Broker-C", "INS-2"),
        3: ("ACC-2", "Broker-A", "INS-3"),
    }
    for sequence, identity in expected.items():
        record = report.order(sequence)
        assert (
            record.account_id,
            record.broker_name,
            record.ins_code,
        ) == identity

        # Each order has its own timestamps
        assert record.sent_at_ns is not None
        assert record.broker_registered_at_ns is not None
        assert record.matching_engine_registered_at_ns is None

        # Timestamps are per-order (different clock values)
        assert record.sent_at_ns > 0
        assert record.broker_registered_at_ns >= record.sent_at_ns

    # Each order owns distinct timing containers
    records = [report.order(1), report.order(2), report.order(3)]
    assert len({id(r.sent_at_ns) for r in records}) == 3  # different int objects


def test_timestamps_per_order_not_reordered():
    """
    Timestamps are correctly associated with their respective orders.

    The dispatch path processes orders sequentially in submission order.
    Each order's timestamps are isolated by sequence.
    """
    clock = FakeClock()
    brokers = {
        "Broker-Fast": FakeBroker("Broker-Fast", clock=clock),
        "Broker-Slow": FakeBroker("Broker-Slow", clock=clock),
    }
    core = shared_clock_core(make_manager(brokers), clock, safety_gate=permissive_safety_gate())

    order_1 = make_order("INS-1")
    order_2 = make_order("INS-2")

    pairs = [
        (order_1, "ACC-1", "Broker-Fast"),  # sequence 1
        (order_2, "ACC-2", "Broker-Slow"),  # sequence 2
    ]
    plan = build_plan(pairs)
    plan.accounts = [make_account("ACC-1"), make_account("ACC-2")]

    for b in brokers.values():
        b.live_trading_enabled = True

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    assert result.order_count == 2

    # Orders processed in submission order (sequence 1, then 2)
    record_1 = report.order(1)
    record_2 = report.order(2)

    assert record_1.ins_code == "INS-1"
    assert record_2.ins_code == "INS-2"

    # Each order has its own timestamps
    assert record_1.sent_at_ns is not None
    assert record_1.broker_registered_at_ns is not None
    assert record_2.sent_at_ns is not None
    assert record_2.broker_registered_at_ns is not None

    # Timestamps belong to the correct order (sequence isolation)
    assert record_1.sent_at_ns != record_2.sent_at_ns
    assert record_1.broker_registered_at_ns != record_2.broker_registered_at_ns


def test_dry_run_behavior_unchanged():
    """
    Dry-run behavior remains unchanged — no broker registration timestamp captured
    because no actual broker submission occurs.
    """
    clock = FakeClock()
    broker = FakeBroker("Broker-A", clock=clock)
    core = shared_clock_core(make_manager({"Broker-A": broker}), clock)

    order = make_order("INS-A")
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]

    # live_trading_enabled = False (default) -> dry-run
    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert result.sent is False

    record = report.order(1)
    assert record.execution_result.mode == "DRY_RUN"
    assert record.execution_result.sent is False

    # In dry-run, place_order is called but with live=False
    # The broker returns DRY_RUN immediately, no decisionId, no isSuccess
    # So broker_registered_at_ns should NOT be captured
    assert record.sent_at_ns is not None
    assert record.broker_registered_at_ns is None
    assert record.matching_engine_registered_at_ns is None


def test_no_duplicate_order_submission():
    """Each order is submitted exactly once."""
    clock = FakeClock()
    broker = FakeBroker("Broker-A", clock=clock)
    core = shared_clock_core(make_manager({"Broker-A": broker}), clock)

    order = make_order("INS-A")
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]

    broker.live_trading_enabled = True
    core.live_trading_enabled = True

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    assert len(broker.place_order_calls) == 1
    assert broker.place_order_calls[0][0] is order
    # live flag depends on SafetyGate; without it, dry-run (live=False) is used.
    # The key assertion: exactly ONE call per order.


def test_feedback_timestamps_use_broker_clock_not_stage_clock():
    """
    Feedback timestamps use the broker clock, not the stage clock,
    so they don't consume Task 8.2 stage clock reads.
    """
    stage_clock = FakeClock(step=10)
    broker_clock = FakeClock(step=100)

    broker = FakeBroker("Broker-A", clock=broker_clock)
    core = DispatchCore(
        broker_manager=make_manager({"Broker-A": broker}),
        latency_clock=stage_clock,
        broker_clock=broker_clock,
        safety_gate=permissive_safety_gate(),
    )

    order = make_order("INS-A")
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]

    broker.live_trading_enabled = True

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    record = report.order(1)

    # Stage clock should only advance for the 4 stages + dispatch window
    # (2 reads per stage = 8 reads, plus dispatch start/end = 2 reads = 10 reads)
    # With step=10, dispatch_end should be around 100
    assert report.dispatch_end >= 90
    assert report.dispatch_end <= 110

    # Feedback timestamps use broker_clock (step=100), so they should
    # be much larger values (at least 100+)
    assert record.sent_at_ns >= 100
    assert record.broker_registered_at_ns >= 100

    # Cross-clock: application_side_ns should be None since clocks differ
    assert record.application_side_ns is None


def test_existing_block8_latency_tests_unaffected():
    """Existing Block 8 latency measurements continue to work (dry-run)."""
    clock = FakeClock()
    broker = FakeBroker("Broker-A", clock=clock)
    core = shared_clock_core(make_manager({"Broker-A": broker}), clock)

    order = make_order("INS-A")
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    record = report.order(1)

    # All four Task 8.2 stages present
    assert record.stage_names() == [
        "plan_item",
        "plan_account",
        "instrument_resolution",
        "order_engine_path",
    ]

    # Task 8.3 broker/API calls measured
    assert record.broker_api_operations() == [
        "get_instrument",
        "get_instrument",
        "get_trading_state",
        "get_buy_capacity",
        "place_order",
    ]

    # Application windows derived correctly
    assert record.application_before_broker_ns is not None
    assert record.application_after_broker_ns is not None
    assert record.application_side_ns is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])