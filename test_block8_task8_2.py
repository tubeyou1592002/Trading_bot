"""
Block 8 — Task 8.2: internal Dispatch latency instrumentation tests.

Proves the minimum required measurement capability for the internal Dispatch
path, strictly as defined by Task 8.2:

  A. a single order produces one latency record carrying its own identity and
     all four applicable internal stage timings;
  B. multiple orders (different sequence / account / broker / instrument)
     keep independent, correctly attributed records — no cross-contamination;
  C. the normal ``dispatch(plan)`` result semantics are unchanged and
     instrumentation is opt-in;
  D. the measured path uses the same single execution implementation (no
     duplicated dispatch business logic);
  E. ``perf_counter_ns`` timing is structurally valid (no exact real-world
     duration assumptions; a deterministic injectable clock is used where
     concrete values are asserted).

Offline only: fake brokers / providers / accounts and the real ``OrderEngine``
path with ``live=False``. No network, no real trading, no optimization.
"""

import inspect
import time
from unittest.mock import patch

import pytest

from brokers.manager import BrokerManager
from core import dispatch_core as dispatch_core_module
from core.dispatch_contracts import DispatchResult, ExecutionPlan
from core.dispatch_core import DispatchCore
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from core.latency_instrumentation import (
    DISPATCH_STAGES,
    INSTRUMENT_RESOLUTION,
    ORDER_ENGINE_PATH,
    PLAN_ACCOUNT,
    PLAN_ITEM,
    DispatchLatencyReport,
    LatencyCollector,
    StageTiming,
)
from core.order_engine import OrderExecutionResult
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, Order
from models.trading_state import VERIFIED_TRADABLE


# ---------------------------------------------------------------------------
# Offline fakes (reused patterns from Block 7 end-to-end tests)
# ---------------------------------------------------------------------------


class FakeBroker:
    def __init__(self, name):
        self.name = name
        self.place_order_calls = []

    def login(self, username, password, **kwargs):
        return {"success": True, "username": username, "token": f"token-{self.name}"}

    def get_account(self):
        return Account(account_id=f"ACCOUNT-{self.name}")

    def place_order(self, order, live=False):
        self.place_order_calls.append((order, live))
        return {"mode": "DRY_RUN", "sent": False, "order_id": f"{self.name}-order"}

    def cancel_order(self, order_id):
        return {"canceled": True, "order_id": order_id}

    def get_trading_state(self, nsc_id):
        return VERIFIED_TRADABLE

    def get_buy_capacity(self, nsc_id, side_code, fund, price):
        return 1_000_000

    def get_sell_capacity(self, nsc_id, side_code, fund, price):
        return 1_000_000


class FakeInstrumentProvider:
    """Offline provider: ins_code resolves to itself as the broker nsc_id."""

    def __init__(self, broker):
        self._broker = broker
        self._cache = {}

    def get_instrument(self, ins_code):
        if ins_code not in self._cache:
            self._cache[ins_code] = make_instrument_pair(self._broker.name, ins_code)
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


def build_plan(pairs, plan_id="task8.2-plan"):
    """Build a real Block 1 plan: pairs = [(order, account_id, broker_name)]."""
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


def attach_accounts(plan, accounts):
    """Attach the bound Account objects the way the integration layer does."""
    plan.accounts = list(accounts)
    return plan


def make_manager(brokers):
    manager = BrokerManager()
    for name, broker in brokers.items():
        manager.register(name, broker, FakeInstrumentProvider)
    return manager


class StepClock:
    """Deterministic monotonic clock: every call advances by ``step``."""

    def __init__(self, step=10, start=0):
        self._value = start
        self._step = step

    def __call__(self):
        self._value += self._step
        return self._value


def single_order_setup(broker_name="Broker-A", ins_code="INS-A", account_id="ACC-1"):
    broker = FakeBroker(broker_name)
    manager = make_manager({broker_name: broker})
    order = make_order(ins_code)
    plan = build_plan([(order, account_id, broker_name)])
    attach_accounts(plan, [make_account(account_id)])
    return broker, manager, order, plan


# ---------------------------------------------------------------------------
# Test A — single order
# ---------------------------------------------------------------------------


def test_single_order_produces_one_complete_latency_record():
    broker, manager, order, plan = single_order_setup()
    core = DispatchCore(broker_manager=manager)

    result, report = core.dispatch_with_latency(plan)

    assert isinstance(result, DispatchResult)
    assert isinstance(report, DispatchLatencyReport)
    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert result.sent is False
    assert result.order_count == 1
    assert report.trace_id == result.trace_id

    # Exactly one latency record, for the plan's single sequence.
    assert report.sequences() == [1]
    record = report.order(1)
    assert record.sequence == 1
    assert record.account_id == "ACC-1"
    assert record.broker_name == "Broker-A"
    assert record.ins_code == "INS-A"

    # All four applicable internal stages, each structurally valid.
    assert record.stage_names() == list(DISPATCH_STAGES)
    for timing in record.stages:
        assert timing.end >= timing.start
        assert timing.duration_ns == timing.end - timing.start
        assert timing.duration_ns >= 0

    # The measured order carries the real execution result by reference.
    assert isinstance(record.execution_result, OrderExecutionResult)
    assert record.execution_result.order is order
    assert record.execution_result.mode == "DRY_RUN"
    assert record.execution_result.sent is False

    # Real execution still happened, dry-run, on the bound broker.
    assert len(broker.place_order_calls) == 1
    assert broker.place_order_calls[0][1] is False

    # Dispatch-level timing is a valid enclosing window.
    assert report.dispatch_end >= report.dispatch_start
    assert report.dispatch_duration == report.dispatch_end - report.dispatch_start
    assert report.dispatch_duration >= 0
    assert report.total_stage_duration_ns(PLAN_ITEM) <= report.dispatch_duration
    for timing in record.stages:
        assert report.dispatch_start <= timing.start
        assert timing.end <= report.dispatch_end


def test_empty_plan_measured_path_returns_valid_empty_report():
    core = DispatchCore()
    result, report = core.dispatch_with_latency(ExecutionPlan())

    assert result.mode == "NO_ORDERS"
    assert result.order_count == 0
    assert report.trace_id == result.trace_id
    assert report.orders == []
    assert report.dispatch_duration >= 0


# ---------------------------------------------------------------------------
# Test B — multiple orders, independent identity per sequence
# ---------------------------------------------------------------------------


def test_multiple_orders_keep_independent_identity():
    brokers = {
        "Broker-A": FakeBroker("Broker-A"),
        "Broker-B": FakeBroker("Broker-B"),
        "Broker-C": FakeBroker("Broker-C"),
    }
    manager = make_manager(brokers)
    core = DispatchCore(broker_manager=manager)

    orders = {
        "INS-1": make_order("INS-1"),
        "INS-2": make_order("INS-2"),
        "INS-3": make_order("INS-3"),
    }
    accounts = {aid: make_account(aid) for aid in ("ACC-1", "ACC-2", "ACC-3")}

    # Deliberately cross-aligned so any shared "current order" context bug
    # (e.g. Order 1 -> Account 3, Order 2 -> Broker 1) would be visible.
    pairs = [
        (orders["INS-1"], "ACC-3", "Broker-B"),
        (orders["INS-2"], "ACC-1", "Broker-C"),
        (orders["INS-3"], "ACC-2", "Broker-A"),
    ]
    plan = attach_accounts(
        build_plan(pairs),
        [accounts["ACC-3"], accounts["ACC-1"], accounts["ACC-2"]],
    )

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    assert result.order_count == 3
    assert report.sequences() == [1, 2, 3]

    expected = {
        1: ("ACC-3", "Broker-B", "INS-1"),
        2: ("ACC-1", "Broker-C", "INS-2"),
        3: ("ACC-2", "Broker-A", "INS-3"),
    }
    for sequence, expected_identity in expected.items():
        record = report.order(sequence)
        assert (
            record.account_id,
            record.broker_name,
            record.ins_code,
        ) == expected_identity
        assert record.sequence == sequence
        assert record.stage_names() == list(DISPATCH_STAGES)

    # The execution result attached to each record is that order's own.
    assert report.order(1).execution_result.order is orders["INS-1"]
    assert report.order(2).execution_result.order is orders["INS-2"]
    assert report.order(3).execution_result.order is orders["INS-3"]

    # Explicit no cross-contamination between records.
    records = [report.order(1), report.order(2), report.order(3)]
    assert len({r.account_id for r in records}) == 3
    assert len({r.broker_name for r in records}) == 3
    assert len({r.ins_code for r in records}) == 3
    assert len({id(r.execution_result) for r in records}) == 3
    assert len({id(r.stages) for r in records}) == 3

    # Actual routing agreed with each record's identity.
    assert [c[0].nsc_id for c in brokers["Broker-B"].place_order_calls] == ["INS-1"]
    assert [c[0].nsc_id for c in brokers["Broker-C"].place_order_calls] == ["INS-2"]
    assert [c[0].nsc_id for c in brokers["Broker-A"].place_order_calls] == ["INS-3"]


# ---------------------------------------------------------------------------
# Test C — normal dispatch compatibility / opt-in instrumentation
# ---------------------------------------------------------------------------


def test_normal_dispatch_semantics_unchanged_and_instrumentation_is_opt_in():
    _, _, _, plan = single_order_setup()
    core = DispatchCore(broker_manager=make_manager({"Broker-A": FakeBroker("Broker-A")}))

    result = core.dispatch(plan)

    # dispatch() keeps its public shape: a plain DispatchResult.
    assert isinstance(result, DispatchResult)
    assert not isinstance(result, tuple)
    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert result.sent is False
    assert result.order_count == 1
    assert not hasattr(result, "orders")

    # Identical plan semantics through both entry points.
    _, _, _, measured_plan = single_order_setup()
    measured_core = DispatchCore(
        broker_manager=make_manager({"Broker-A": FakeBroker("Broker-A")})
    )
    measured_result, _ = measured_core.dispatch_with_latency(measured_plan)
    assert (
        measured_result.success,
        measured_result.mode,
        measured_result.sent,
        measured_result.order_count,
    ) == (result.success, result.mode, result.sent, result.order_count)

    # Normal dispatch never reads the latency clock.
    _, _, _, normal_plan = single_order_setup()
    normal_core = DispatchCore(
        broker_manager=make_manager({"Broker-A": FakeBroker("Broker-A")})
    )
    with patch(
        "core.latency_instrumentation.time.perf_counter_ns",
        wraps=time.perf_counter_ns,
    ) as clock_spy:
        normal_result = normal_core.dispatch(normal_plan)
    assert normal_result.mode == "ALL_PROCESSED"
    assert clock_spy.call_count == 0

    # The measured path does read it.
    _, _, _, latency_plan = single_order_setup()
    latency_core = DispatchCore(
        broker_manager=make_manager({"Broker-A": FakeBroker("Broker-A")})
    )
    with patch(
        "core.latency_instrumentation.time.perf_counter_ns",
        wraps=time.perf_counter_ns,
    ) as clock_spy:
        latency_core.dispatch_with_latency(latency_plan)
    assert clock_spy.call_count > 0


def test_latency_does_not_add_fields_to_existing_contracts():
    import dataclasses

    dispatch_fields = {f.name for f in dataclasses.fields(DispatchResult)}
    assert dispatch_fields == {
        "success",
        "sent",
        "mode",
        "message",
        "broker_name",
        "order_count",
        "trace_id",
    }

    result_fields = {f.name for f in dataclasses.fields(OrderExecutionResult)}
    assert result_fields == {
        "success",
        "sent",
        "mode",
        "order",
        "broker_name",
        "message",
        "response",
    }


# ---------------------------------------------------------------------------
# Test D — one execution implementation
# ---------------------------------------------------------------------------


def test_measured_path_shares_the_single_execution_implementation():
    # Structural proof: both public entry points delegate to the one private
    # implementation, and there is exactly one OrderEngine execution call.
    assert "self._dispatch(" in inspect.getsource(DispatchCore.dispatch)
    assert "self._dispatch(" in inspect.getsource(DispatchCore.dispatch_with_latency)

    source = inspect.getsource(dispatch_core_module)
    assert source.count("def _dispatch(") == 1
    assert source.count("self.order_engine.execute_by_ins_code(") == 1
    assert source.count("def dispatch_with_latency(") == 1


def test_both_entry_points_funnel_into_the_same_dispatch_call():
    core = DispatchCore(broker_manager=make_manager({"Broker-A": FakeBroker("Broker-A")}))

    collectors = []
    original_dispatch = core._dispatch

    def spy_dispatch(plan, collector=None):
        collectors.append(collector)
        return original_dispatch(plan, collector=collector)

    core._dispatch = spy_dispatch

    engine_calls = []
    original_execute = core.order_engine.execute_by_ins_code

    def spy_execute(**kwargs):
        engine_calls.append(kwargs)
        return original_execute(**kwargs)

    core.order_engine.execute_by_ins_code = spy_execute

    _, _, _, plan = single_order_setup()
    core.dispatch(plan)
    core.dispatch_with_latency(plan)

    # Same implementation, differing only in whether collection is enabled.
    assert len(collectors) == 2
    assert collectors[0] is None
    assert isinstance(collectors[1], LatencyCollector)

    # Same OrderEngine entry point, same arguments, on both paths.
    assert len(engine_calls) == 2
    first, second = engine_calls
    assert first["ins_code"] == second["ins_code"] == "INS-A"
    assert first["live"] is second["live"] is False
    assert first["account"].account_id == second["account"].account_id == "ACC-1"
    assert first["order"].nsc_id == second["order"].nsc_id == "INS-A"


# ---------------------------------------------------------------------------
# Test E — timing sanity (deterministic clock, no sleeps)
# ---------------------------------------------------------------------------


def test_deterministic_clock_yields_exact_stage_durations():
    core = DispatchCore(
        broker_manager=make_manager({"Broker-A": FakeBroker("Broker-A")}),
        latency_clock=StepClock(step=10),
    )
    _, _, _, plan = single_order_setup()

    result, report = core.dispatch_with_latency(plan)

    assert result.mode == "ALL_PROCESSED"
    record = report.order(1)
    assert [t.stage_name for t in record.stages] == list(DISPATCH_STAGES)
    assert [t.start for t in record.stages] == [20, 40, 60, 80]
    assert [t.end for t in record.stages] == [30, 50, 70, 90]
    assert [t.duration_ns for t in record.stages] == [10, 10, 10, 10]
    assert report.dispatch_start == 10
    assert report.dispatch_end == 100
    assert report.dispatch_duration == 90


def test_blocked_order_records_only_applicable_stages_and_keeps_semantics():
    broker = FakeBroker("Broker-A")
    core = DispatchCore(
        broker_manager=make_manager({"Broker-A": broker}),
        latency_clock=StepClock(step=5),
    )
    order = make_order("INS-A")
    # No resolved Account object -> the existing fail-closed id-only path.
    plan = build_plan([(order, "ACC-1", "Broker-A")])

    result, report = core.dispatch_with_latency(plan)

    assert result.success is False
    assert result.mode == "BLOCKED"
    record = report.order(1)
    assert record.stage_names() == [PLAN_ITEM, PLAN_ACCOUNT]
    assert record.ins_code == "INS-A"
    assert record.execution_result is not None
    assert record.execution_result.mode == "BLOCKED"
    assert broker.place_order_calls == []


def test_exception_path_still_fails_closed_and_still_reports():
    core = DispatchCore(broker_manager=make_manager({"Broker-A": FakeBroker("Broker-A")}))
    _, _, _, plan = single_order_setup()

    def boom(**kwargs):
        raise RuntimeError("boom")

    core.order_engine.execute_by_ins_code = boom

    result, report = core.dispatch_with_latency(plan)

    assert result.success is False
    assert result.mode == "BLOCKED"
    record = report.order(1)
    assert record.stage_names() == list(DISPATCH_STAGES)
    timing = record.stage(ORDER_ENGINE_PATH)
    assert timing is not None
    assert timing.duration_ns >= 0
    assert record.execution_result.mode == "BLOCKED"


def test_raising_stage_closes_its_timing_and_keeps_fail_closed():
    """A measured stage that raises must still close its timing and must not
    rewrite execution semantics: no later stage is fabricated and the
    dispatch stays fail-closed BLOCKED.
    """
    core = DispatchCore(
        broker_manager=make_manager({"Broker-A": FakeBroker("Broker-A")}),
        latency_clock=StepClock(step=5),
    )
    _, _, _, plan = single_order_setup()

    def raising_plan_item(plan, sequence):
        raise RuntimeError("plan_item exploded")

    core._plan_item = raising_plan_item

    result, report = core.dispatch_with_latency(plan)

    assert result.success is False
    assert result.mode == "BLOCKED"
    assert report.dispatch_end >= report.dispatch_start
    assert report.dispatch_duration >= 0

    record = report.order(1)
    assert record.stage_names() == [PLAN_ITEM]
    timing = record.stage(PLAN_ITEM)
    assert timing is not None
    assert timing.end >= timing.start
    assert timing.duration_ns >= 0
    assert record.execution_result is None

    # Same fail-closed verdict without measurement (semantics preserved).
    normal_core = DispatchCore(
        broker_manager=make_manager({"Broker-A": FakeBroker("Broker-A")})
    )
    _, _, _, normal_plan = single_order_setup()
    normal_core._plan_item = raising_plan_item
    normal_result = normal_core.dispatch(normal_plan)
    assert (normal_result.success, normal_result.mode) == (False, "BLOCKED")


def test_invalid_timing_values_are_rejected():
    with pytest.raises(ValueError):
        StageTiming(stage_name=PLAN_ITEM, start=100, end=50)

    with pytest.raises(ValueError):
        DispatchLatencyReport(trace_id="t", dispatch_start=100, dispatch_end=50)


def test_real_clock_timing_is_valid_across_repeated_dispatches():
    for _ in range(5):
        core = DispatchCore(
            broker_manager=make_manager({"Broker-A": FakeBroker("Broker-A")})
        )
        _, _, _, plan = single_order_setup()
        _, report = core.dispatch_with_latency(plan)

        assert report.dispatch_end >= report.dispatch_start
        assert report.dispatch_duration >= 0
        for record in report.orders:
            for timing in record.stages:
                assert timing.duration_ns >= 0
                assert timing.end >= timing.start
                assert report.dispatch_start <= timing.start
                assert timing.end <= report.dispatch_end


def test_instrument_resolution_stage_is_present_and_named_once():
    _, manager, _, plan = single_order_setup()
    core = DispatchCore(broker_manager=manager)
    _, report = core.dispatch_with_latency(plan)

    record = report.order(1)
    assert record.stage_names().count(INSTRUMENT_RESOLUTION) == 1
    assert record.stage_names().count(ORDER_ENGINE_PATH) == 1
    assert record.duration_ns(INSTRUMENT_RESOLUTION) is not None
    assert record.duration_ns(ORDER_ENGINE_PATH) is not None
