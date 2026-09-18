"""
Block 8 — Task 8.3 Phase A: offline Broker/API boundary measurement tests.

Proves, without any network access, that the existing dispatch path can
separate:

  * application-side work,
  * Broker/API round-trip work (measured around the existing broker/provider
    calls),
  * application-side work after the Broker/API call returns,

while keeping ONE execution implementation and unchanged execution semantics.

  A. a single order produces broker/API round-trip timings with correct
     identity and valid non-negative durations;
  B. multiple orders (different sequence / account / broker / instrument)
     keep their broker/API timings attached to the correct sequence;
  C. a raising broker call still closes its timing, keeps the existing
     fail-closed behavior, and produces no fabricated response timing;
  D. normal ``dispatch(plan)`` is unchanged and performs no measurement;
  E. everything here is fully offline (no credentials, no HTTP).

Timers are deterministic fake clocks — no ``sleep()`` and no exact real-world
duration assumptions.

NOTE ON INTERPRETATION: a measured ``broker_api_round_trip`` is the duration
of the whole existing broker method call (local preparation + transfer +
remote processing + local response handling). It is NOT pure network latency,
and no DNS/TCP/TLS instrumentation is involved.
"""

import inspect
import time
from unittest.mock import patch

import pytest

from brokers.manager import BrokerManager
from core import dispatch_core as dispatch_core_module
from core import order_engine as order_engine_module
from core.dispatch_contracts import DispatchResult
from core.dispatch_core import DispatchCore
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from core.latency_instrumentation import (
    INSTRUMENT_RESOLUTION,
    OP_GET_BUY_CAPACITY,
    OP_GET_INSTRUMENT,
    OP_GET_SELL_CAPACITY,
    OP_GET_TRADING_STATE,
    OP_PLACE_ORDER,
    ORDER_ENGINE_PATH,
    READ_ONLY_OPERATIONS,
    SUBMISSION_OPERATION,
    BrokerApiCallTiming,
    BrokerCallRecorder,
)
from core.order_engine import OrderEngine, OrderExecutionResult
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, SELL, Order
from models.trading_state import VERIFIED_TRADABLE, TradingStateUnavailable


# ---------------------------------------------------------------------------
# Deterministic clocks
# ---------------------------------------------------------------------------


class FakeClock:
    """
    Monotonic fake clock: every read advances by ``step``.

    ``advance(ns)`` injects a synthetic delay from inside a fake broker call,
    which lets tests prove attribution (broker time vs application time)
    deterministically without sleeping.
    """

    def __init__(self, step=1):
        self._value = 0
        self._step = step

    def __call__(self):
        self._value += self._step
        return self._value

    def advance(self, ns):
        self._value += ns


# ---------------------------------------------------------------------------
# Offline fakes
# ---------------------------------------------------------------------------


class FakeBroker:
    def __init__(self, name, clock=None, delays=None, raise_on=None):
        self.name = name
        self.clock = clock
        self.delays = dict(delays or {})
        self.raise_on = dict(raise_on or {})
        self.call_log = []
        self.place_order_calls = []
        self.trading_state_calls = []
        self.capacity_calls = []

    def touch(self, operation):
        """Advance the fake clock and/or raise, exactly like a slow/failing API."""
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
        return {"mode": "DRY_RUN", "sent": False, "order_id": f"{self.name}-order"}

    def cancel_order(self, order_id):
        return {"canceled": True, "order_id": order_id}

    def get_trading_state(self, nsc_id):
        self.trading_state_calls.append(nsc_id)
        self.touch(OP_GET_TRADING_STATE)
        return VERIFIED_TRADABLE

    def get_buy_capacity(self, nsc_id, side_code, fund, price):
        self.capacity_calls.append((OP_GET_BUY_CAPACITY, nsc_id))
        self.touch(OP_GET_BUY_CAPACITY)
        return 1_000_000

    def get_sell_capacity(self, nsc_id, side_code, fund, price):
        self.capacity_calls.append((OP_GET_SELL_CAPACITY, nsc_id))
        self.touch(OP_GET_SELL_CAPACITY)
        return 1_000_000


class FakeInstrumentProvider:
    def __init__(self, broker):
        self._broker = broker
        self._cache = {}

    def get_instrument(self, ins_code):
        self._broker.touch(OP_GET_INSTRUMENT)
        if ins_code not in self._cache:
            self._cache[ins_code] = make_instrument_pair(
                self._broker.name, ins_code
            )
        return self._cache[ins_code]

    def get_nsc_id(self, ins_code):
        return self.get_instrument(ins_code)[1].nsc_id

    def refresh_cache(self):
        self._cache.clear()


class SlowValidator:
    """Application-side work: delays inside ``prepare`` but NOT a broker call."""

    def __init__(self, delegate, clock, delay_ns):
        self._delegate = delegate
        self._clock = clock
        self._delay_ns = delay_ns

    def validate(self, *args, **kwargs):
        self._clock.advance(self._delay_ns)
        return self._delegate.validate(*args, **kwargs)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


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


def build_plan(pairs, plan_id="task8.3-plan"):
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


def shared_clock_core(manager, clock):
    """
    A measured DispatchCore whose stage layer AND broker/API layer are timed
    on the SAME injectable clock, so nested intervals and the derived
    application accounting are deterministic.
    """
    return DispatchCore(
        broker_manager=manager,
        latency_clock=clock,
        broker_clock=clock,
    )


def single_order_setup(**broker_kwargs):
    """(clock, broker, core, order, plan) for one BUY order on Broker-A."""
    clock = broker_kwargs.pop("clock", None) or FakeClock()
    broker = FakeBroker("Broker-A", clock=clock, **broker_kwargs)
    core = shared_clock_core(make_manager({"Broker-A": broker}), clock)
    order = make_order("INS-A")
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]
    return clock, broker, core, order, plan


def assert_call_inside(call, stage):
    assert call.start >= stage.start, (call, stage)
    assert call.end <= stage.end, (call, stage)


# ---------------------------------------------------------------------------
# Test A — single order: broker/API round trip measured with the right identity
# ---------------------------------------------------------------------------


def test_single_order_measures_broker_api_round_trips_with_identity():
    clock, broker, core, order, plan = single_order_setup()

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert result.sent is False

    assert report.sequences() == [1]
    record = report.order(1)
    assert record.sequence == 1
    assert record.account_id == "ACC-1"
    assert record.broker_name == "Broker-A"
    assert record.ins_code == "INS-A"

    # Exactly the existing broker/provider calls of one dry-run order.
    assert record.broker_api_operations() == [
        OP_GET_INSTRUMENT,     # DispatchCore instrument_resolution
        OP_GET_INSTRUMENT,     # OrderEngine instrument step
        OP_GET_TRADING_STATE,  # M6-A trading-state gate
        OP_GET_BUY_CAPACITY,   # M6-C BUY capacity gate
        OP_PLACE_ORDER,        # dry-run submission
    ]
    engine_result = record.execution_result
    assert isinstance(engine_result, OrderExecutionResult)
    assert engine_result.mode == "DRY_RUN"
    assert engine_result.order is order
    assert engine_result.sent is False
    assert len(broker.place_order_calls) == 1
    assert broker.place_order_calls[0][1] is False  # live=False preserved

    for call in record.broker_api_calls:
        assert call.ok is True
        assert call.end >= call.start
        assert call.duration_ns == call.end - call.start
        assert call.duration_ns >= 0

    # Aggregate round trip + per-operation detail.
    assert record.broker_api_round_trip_ns == sum(
        c.duration_ns for c in record.broker_api_calls
    )
    assert record.broker_api_round_trip_ns > 0
    assert record.broker_api_round_trip_for(OP_PLACE_ORDER) == (
        record.broker_api_call(OP_PLACE_ORDER).duration_ns
    )
    totals = record.broker_api_totals_by_operation()
    assert totals[OP_GET_INSTRUMENT] == sum(
        c.duration_ns for c in record.broker_api_calls_for(OP_GET_INSTRUMENT)
    )
    assert report.broker_api_round_trip_ns == record.broker_api_round_trip_ns
    assert report.total_broker_api_calls() == 5

    # Every measured call is nested inside the stage that actually contains it.
    instrument_stage = record.stage(INSTRUMENT_RESOLUTION)
    engine_stage = record.stage(ORDER_ENGINE_PATH)
    assert_call_inside(record.broker_api_calls[0], instrument_stage)
    for call in record.broker_api_calls[1:]:
        assert_call_inside(call, engine_stage)

    # The submission boundary splits the engine stage into application windows.
    submission = record.broker_api_call(SUBMISSION_OPERATION)
    assert submission.operation == OP_PLACE_ORDER
    assert record.application_before_broker_ns == submission.start - engine_stage.start
    assert record.application_after_broker_ns == engine_stage.end - submission.end
    assert record.application_before_broker_ns >= 0
    assert record.application_after_broker_ns >= 0
    assert (
        record.application_before_broker_ns
        + submission.duration_ns
        + record.application_after_broker_ns
        == engine_stage.duration_ns
    )

    # Application-side remainder excludes the nested broker calls.
    assert record.application_side_ns is not None
    assert record.application_side_ns >= 0
    assert record.application_side_ns < engine_stage.duration_ns


def test_sell_order_measures_sell_capacity_operation():
    clock = FakeClock()
    broker = FakeBroker("Broker-A", clock=clock)
    core = shared_clock_core(make_manager({"Broker-A": broker}), clock)
    order = make_order("INS-A", side=SELL)
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    record = report.order(1)
    assert OP_GET_SELL_CAPACITY in record.broker_api_operations()
    assert OP_GET_BUY_CAPACITY not in record.broker_api_operations()
    assert broker.capacity_calls == [(OP_GET_SELL_CAPACITY, "INS-A")]


# ---------------------------------------------------------------------------
# Test A2 — the separation itself (application vs Broker/API)
# ---------------------------------------------------------------------------


def test_slow_broker_call_is_attributed_to_broker_api_not_application():
    delay = 5_000_000
    clock, broker, core, order, plan = single_order_setup(
        delays={OP_GET_BUY_CAPACITY: delay}
    )

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    record = report.order(1)
    engine_stage = record.stage(ORDER_ENGINE_PATH)

    # The synthetic delay shows up in the Broker/API round trip ...
    assert record.broker_api_round_trip_for(OP_GET_BUY_CAPACITY) >= delay
    assert record.broker_api_round_trip_ns >= delay
    assert engine_stage.duration_ns >= delay
    # ... and NOT in the application-side remainder of the same stage.
    assert record.application_side_ns < delay
    assert record.application_side_ns < record.broker_api_round_trip_ns


def test_slow_application_work_is_not_attributed_to_broker_api():
    delay = 5_000_000
    clock, broker, core, order, plan = single_order_setup()
    core.order_engine.validator = SlowValidator(
        core.order_engine.validator, clock, delay
    )

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    record = report.order(1)
    engine_stage = record.stage(ORDER_ENGINE_PATH)

    # Application-side work stays application-side ...
    assert engine_stage.duration_ns >= delay
    assert record.application_side_ns >= delay
    # ... and is NOT attributed to the Broker/API round trip.
    assert record.broker_api_round_trip_ns < delay


# ---------------------------------------------------------------------------
# Test B — multiple orders / accounts / brokers / instruments
# ---------------------------------------------------------------------------


def test_multiple_orders_keep_broker_timing_with_their_own_sequence():
    clock = FakeClock()
    brokers = {
        name: FakeBroker(name, clock=clock)
        for name in ("Broker-A", "Broker-B", "Broker-C")
    }
    core = shared_clock_core(make_manager(brokers), clock)

    orders = {code: make_order(code) for code in ("INS-1", "INS-2", "INS-3")}
    accounts = {aid: make_account(aid) for aid in ("ACC-1", "ACC-2", "ACC-3")}

    # Deliberately cross-aligned: any "current order" leak would be visible.
    pairs = [
        (orders["INS-1"], "ACC-3", "Broker-B"),
        (orders["INS-2"], "ACC-1", "Broker-C"),
        (orders["INS-3"], "ACC-2", "Broker-A"),
    ]
    plan = build_plan(pairs)
    plan.accounts = [accounts["ACC-3"], accounts["ACC-1"], accounts["ACC-2"]]

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    assert result.order_count == 3
    assert report.sequences() == [1, 2, 3]
    assert report.total_broker_api_calls() == 15

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
        assert record.broker_api_operations() == [
            OP_GET_INSTRUMENT,
            OP_GET_INSTRUMENT,
            OP_GET_TRADING_STATE,
            OP_GET_BUY_CAPACITY,
            OP_PLACE_ORDER,
        ]
        assert record.broker_api_round_trip_ns > 0
        assert record.broker_api_failures() == []
        assert record.application_before_broker_ns >= 0
        assert record.application_after_broker_ns >= 0

    # Each order owns a distinct timing container.
    records = [report.order(1), report.order(2), report.order(3)]
    assert len({id(r.broker_api_calls) for r in records}) == 3
    assert all(record.broker_api_calls for record in records)

    # The broker that actually executed each order matches that order's
    # measured operations (no cross-broker attribution).
    assert [c[0].nsc_id for c in brokers["Broker-B"].place_order_calls] == ["INS-1"]
    assert [c[0].nsc_id for c in brokers["Broker-C"].place_order_calls] == ["INS-2"]
    assert [c[0].nsc_id for c in brokers["Broker-A"].place_order_calls] == ["INS-3"]
    for name, broker in brokers.items():
        assert OP_PLACE_ORDER in broker.call_log

    # Per-sequence stage nesting is preserved for every order.
    for record in records:
        engine_stage = record.stage(ORDER_ENGINE_PATH)
        for call in record.broker_api_calls[1:]:
            assert_call_inside(call, engine_stage)


# ---------------------------------------------------------------------------
# Test C — broker exceptions / fail-closed paths
# ---------------------------------------------------------------------------


def test_raising_trading_state_closes_timing_and_keeps_fail_closed():
    clock, broker, core, order, plan = single_order_setup(
        raise_on={OP_GET_TRADING_STATE: TradingStateUnavailable("offline")}
    )

    result, report = core.dispatch_with_latency(plan)

    assert result.success is False
    assert result.mode == "BLOCKED"

    record = report.order(1)
    assert record.account_id == "ACC-1"
    assert record.broker_name == "Broker-A"
    assert record.ins_code == "INS-A"

    failures = record.broker_api_failures()
    assert [c.operation for c in failures] == [OP_GET_TRADING_STATE]
    assert failures[0].ok is False
    assert failures[0].duration_ns >= 0

    # No later broker call is fabricated, and nothing was submitted.
    assert OP_PLACE_ORDER not in record.broker_api_operations()
    assert broker.place_order_calls == []
    assert record.execution_result.mode == "BLOCKED"
    assert record.execution_result.sent is False

    # The order never reached the submission boundary.
    assert record.application_before_broker_ns is None
    assert record.application_after_broker_ns is None


def test_raising_capacity_closes_timing_and_keeps_fail_closed():
    clock, broker, core, order, plan = single_order_setup(
        raise_on={OP_GET_BUY_CAPACITY: RuntimeError("capacity api down")}
    )

    result, report = core.dispatch_with_latency(plan)

    assert result.success is False
    assert result.mode == "BLOCKED"
    record = report.order(1)
    assert [c.operation for c in record.broker_api_failures()] == [
        OP_GET_BUY_CAPACITY
    ]
    assert OP_PLACE_ORDER not in record.broker_api_operations()
    assert broker.place_order_calls == []
    assert record.execution_result.mode == "BLOCKED"


def test_raising_place_order_closes_timing_without_fabricating_a_response():
    # Measured run.
    clock, broker, core, order, plan = single_order_setup(
        raise_on={OP_PLACE_ORDER: RuntimeError("submit failed")}
    )
    result, report = core.dispatch_with_latency(plan)

    # Unmeasured reference run: same existing semantics.
    clock_ref, broker_ref, core_ref, order_ref, plan_ref = single_order_setup(
        raise_on={OP_PLACE_ORDER: RuntimeError("submit failed")}
    )
    reference = core_ref.dispatch(plan_ref)

    record = report.order(1)
    submission = record.broker_api_call(OP_PLACE_ORDER)
    assert submission is not None
    assert submission.ok is False
    assert submission.duration_ns >= 0

    # Engine-level mode is unchanged by the instrumentation (existing "ERROR"),
    # and the dispatch verdict stays fail-closed BLOCKED on both paths.
    assert record.execution_result.mode == "ERROR"
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert reference.success is False
    assert reference.mode == "BLOCKED"

    # No fabricated broker response is attached.
    assert record.execution_result.response is None

    # The submission boundary still closed, so the application windows exist.
    assert record.application_before_broker_ns >= 0
    assert record.application_after_broker_ns >= 0
    engine_stage = record.stage(ORDER_ENGINE_PATH)
    assert (
        record.application_before_broker_ns
        + submission.duration_ns
        + record.application_after_broker_ns
        == engine_stage.duration_ns
    )


# ---------------------------------------------------------------------------
# Test D — normal dispatch unchanged / measurement is opt-in
# ---------------------------------------------------------------------------


def test_normal_dispatch_is_unchanged_and_performs_no_measurement():
    clock, broker, core, order, plan = single_order_setup()

    result = core.dispatch(plan)

    assert isinstance(result, DispatchResult)
    assert not isinstance(result, tuple)
    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert result.sent is False
    normal_log = list(broker.call_log)

    # Same plan through the measured path: identical broker interaction and
    # identical result semantics.
    clock_m, broker_m, core_m, order_m, plan_m = single_order_setup()
    measured_result, report = core_m.dispatch_with_latency(plan_m)
    assert broker_m.call_log == normal_log
    assert (
        measured_result.success,
        measured_result.mode,
        measured_result.sent,
        measured_result.order_count,
    ) == (result.success, result.mode, result.sent, result.order_count)
    assert report.order(1).broker_api_operations() == normal_log

    # No clock read at all on the normal path.
    clock_n, broker_n, core_n, order_n, plan_n = single_order_setup()
    with patch(
        "core.latency_instrumentation.time.perf_counter_ns",
        wraps=time.perf_counter_ns,
    ) as clock_spy:
        normal_result = core_n.dispatch(plan_n)
    assert normal_result.mode == "ALL_PROCESSED"
    assert clock_spy.call_count == 0


def test_broker_timing_is_only_passed_when_measurement_is_enabled():
    seen = []

    def make_core_with_spy():
        clock, broker, core, order, plan = single_order_setup()
        real_execute = core.order_engine.execute_by_ins_code

        def spy(**kwargs):
            seen.append(kwargs)
            return real_execute(**kwargs)

        core.order_engine.execute_by_ins_code = spy
        return core, plan

    normal_core, normal_plan = make_core_with_spy()
    assert normal_core.dispatch(normal_plan).success is True
    assert "broker_timing" not in seen[0]

    measured_core, measured_plan = make_core_with_spy()
    measured_result, _ = measured_core.dispatch_with_latency(measured_plan)
    assert measured_result.success is True
    assert "broker_timing" in seen[1]
    assert isinstance(seen[1]["broker_timing"], BrokerCallRecorder)
    assert seen[1]["broker_timing"].sequence == 1

    # Same arguments either way apart from the measurement keyword.
    assert set(seen[0]) | {"broker_timing"} == set(seen[1])


# ---------------------------------------------------------------------------
# Test E — fully offline
# ---------------------------------------------------------------------------


def test_measured_dispatch_works_with_networking_disabled():
    clock, broker, core, order, plan = single_order_setup()

    with patch("socket.socket", side_effect=AssertionError("network access")):
        result, report = core.dispatch_with_latency(plan)
        normal = core.dispatch(plan)

    assert result.mode == "ALL_PROCESSED"
    assert normal.mode == "ALL_PROCESSED"
    assert report.order(1).broker_api_operations()[-1] == OP_PLACE_ORDER


# ---------------------------------------------------------------------------
# Architecture / model guards
# ---------------------------------------------------------------------------


def test_still_one_execution_implementation():
    core_source = inspect.getsource(dispatch_core_module)
    assert core_source.count("def _dispatch(") == 1
    assert core_source.count("def dispatch_with_latency(") == 1
    assert core_source.count("self.order_engine.execute_by_ins_code(") == 1
    assert "engine_kwargs[\"broker_timing\"] = broker_timing" in core_source

    # Measurement is attached around exactly five existing call sites.
    engine_source = inspect.getsource(order_engine_module)
    assert engine_source.count("measure_broker_call(") == 5
    # OrderEngine still delegates to its single existing execute().
    assert engine_source.count("def execute(") == 1
    assert engine_source.count("def prepare(") == 1


def test_broker_api_timing_does_not_consume_the_stage_clock():
    """
    The broker/API layer has its own clock. Injecting only the Task 8.2 stage
    clock must leave the stage windows exactly as Task 8.2 defined them (two
    reads per stage, two for the dispatch window), and the values that would
    require mixing the two clocks must stay unset rather than be fabricated.
    """
    stage_clock = FakeClock(step=10)
    broker = FakeBroker("Broker-A")  # no clock handle: real perf_counter_ns
    core = DispatchCore(
        broker_manager=make_manager({"Broker-A": broker}),
        latency_clock=stage_clock,
    )
    order = make_order("INS-A")
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]

    result, report = core.dispatch_with_latency(plan)

    assert result.success is True
    record = report.order(1)

    # Task 8.2 stage windows are untouched by the Task 8.3 measurement.
    assert [t.start for t in record.stages] == [20, 40, 60, 80]
    assert [t.end for t in record.stages] == [30, 50, 70, 90]
    assert [t.duration_ns for t in record.stages] == [10, 10, 10, 10]
    assert report.dispatch_start == 10
    assert report.dispatch_end == 100
    assert report.dispatch_duration == 90

    # Broker/API round trips are still measured (on the broker clock) ...
    assert len(record.broker_api_calls) == 5
    assert record.broker_api_round_trip_ns >= 0
    assert all(c.duration_ns >= 0 for c in record.broker_api_calls)

    # ... but cross-clock derived values are NOT fabricated.
    assert record.application_side_ns is None
    assert record.application_before_broker_ns is None
    assert record.application_after_broker_ns is None


def test_broker_api_call_timing_rejects_reversed_interval():
    with pytest.raises(ValueError):
        BrokerApiCallTiming(operation=OP_PLACE_ORDER, start=100, end=50)


def test_phase_b_whitelist_excludes_order_and_cancel_operations():
    # The Phase B operator tool may only measure read-only operations.
    assert OP_PLACE_ORDER not in READ_ONLY_OPERATIONS
    assert "cancel_order" not in READ_ONLY_OPERATIONS
    assert OP_GET_INSTRUMENT in READ_ONLY_OPERATIONS


def test_measurement_keeps_existing_engine_and_result_contracts():
    import dataclasses

    assert {f.name for f in dataclasses.fields(OrderExecutionResult)} == {
        "success",
        "sent",
        "mode",
        "order",
        "broker_name",
        "message",
        "response",
    }

    # prepare()/execute()/execute_by_ins_code() keep every existing parameter
    # and only gain an optional trailing measurement keyword.
    for method, expected in (
        (OrderEngine.execute_by_ins_code, "broker_timing"),
        (OrderEngine.prepare, "broker_timing"),
        (OrderEngine.execute, "broker_timing"),
    ):
        params = list(inspect.signature(method).parameters)
        assert params[-1] == expected
        assert expected in inspect.signature(method).parameters
        assert (
            inspect.signature(method).parameters[expected].default is None
        )
