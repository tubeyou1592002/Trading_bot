"""
Block 8 — Task 8.4: latency report & attribution tests.

Read-only reporting over the existing Task 8.2/8.3 measurements. Nothing
here dispatches differently, sends an order, or touches a broker contract;
``core/dispatch_core.py`` is not even imported.

  A. one execution   -> one factual attribution;
  B. many executions -> per-sequence attribution, no cross-order leak;
  C. min/median/mean/max + Broker/API aggregates;
  D. application-side attribution — computed only on a shared clock,
     ``None`` when the clocks differ (never fabricated);
  E. zero/very small latencies stay non-negative and intact;
  F. failed executions / failed Broker/API calls stay visible in the
     report (timing preserved, nothing lost);
  G. missing data (no engine stage, empty report) stays ``None``/0-valued,
     never invented;
  H. sequence identity survives into the analysis;
  I. the ordinary ``dispatch()`` path is unchanged (regression, no clock,
     no measurement keyword).

All offline: deterministic fake clocks, no ``sleep()``, no network
(``socket.socket`` patched to raise), no credentials.
"""

import inspect
import statistics
from unittest.mock import patch

from brokers.manager import BrokerManager
from core import latency_instrumentation as li
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
    PLAN_ACCOUNT,
    PLAN_ITEM,
    BrokerApiCallTiming,
    BrokerApiFailureInfo,
    DispatchLatencyReport,
    LatencyAnalysis,
    LatencyDistribution,
    OrderLatency,
    OrderLatencyAttribution,
    StageTiming,
    analyze_latency_report,
)
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, SELL, Order
from models.trading_state import VERIFIED_TRADABLE, TradingStateUnavailable


# ---------------------------------------------------------------------------
# Deterministic clocks
# ---------------------------------------------------------------------------


class FakeClock:
    """Monotonic fake clock: every read advances by ``step``."""

    def __init__(self, step=1):
        self._value = 0
        self._step = step

    def __call__(self):
        self._value += self._step
        return self._value

    def advance(self, ns):
        self._value += ns


# ---------------------------------------------------------------------------
# Offline fakes (same shape as the Task 8.3 suite)
# ---------------------------------------------------------------------------


class FakeBroker:
    def __init__(self, name, clock=None, delays=None, raise_on=None):
        self.name = name
        self.clock = clock
        self.delays = dict(delays or {})
        self.raise_on = dict(raise_on or {})
        self.call_log = []
        self.place_order_calls = []

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
        return {"mode": "DRY_RUN", "sent": False, "order_id": f"{self.name}-order"}

    def cancel_order(self, order_id):
        return {"canceled": True, "order_id": order_id}

    def get_trading_state(self, nsc_id):
        self.touch(OP_GET_TRADING_STATE)
        return VERIFIED_TRADABLE

    def get_buy_capacity(self, nsc_id, side_code, fund, price):
        self.touch(OP_GET_BUY_CAPACITY)
        return 1_000_000

    def get_sell_capacity(self, nsc_id, side_code, fund, price):
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
    """Application-side work: delay inside ``prepare``, not a broker call."""

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


def build_plan(pairs, plan_id="task8.4-plan"):
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
    """Measured DispatchCore with BOTH layers on the same injectable clock."""
    from core.dispatch_core import DispatchCore

    return DispatchCore(
        broker_manager=manager,
        latency_clock=clock,
        broker_clock=clock,
    )


def split_clock_core(manager, stage_clock):
    """Measured DispatchCore whose broker layer keeps the default clock."""
    from core.dispatch_core import DispatchCore

    return DispatchCore(
        broker_manager=manager,
        latency_clock=stage_clock,
    )


def single_order_setup(core_factory=shared_clock_core, **broker_kwargs):
    """(clock, broker, core, order, plan) for one BUY order on Broker-A."""
    clock = broker_kwargs.pop("clock", None) or FakeClock()
    broker = FakeBroker("Broker-A", clock=clock, **broker_kwargs)
    core = core_factory(make_manager({"Broker-A": broker}), clock)
    order = make_order("INS-A")
    plan = build_plan([(order, "ACC-1", "Broker-A")])
    plan.accounts = [make_account("ACC-1")]
    return clock, broker, core, order, plan


def measured_dispatch(core_factory=shared_clock_core, **broker_kwargs):
    clock, broker, core, order, plan = single_order_setup(
        core_factory=core_factory, **broker_kwargs
    )
    result, report = core.dispatch_with_latency(plan)
    return result, report, broker


# ---------------------------------------------------------------------------
# A — one execution
# ---------------------------------------------------------------------------


def test_single_execution_report_is_factual():
    result, report, broker = measured_dispatch()

    assert result.success is True  # the dispatch path itself is untouched
    assert broker.place_order_calls[0][1] is False  # still dry-run

    analysis = analyze_latency_report(report)

    assert isinstance(analysis, LatencyAnalysis)
    assert analysis.trace_id == result.trace_id
    assert analysis.total_orders == 1
    assert analysis.successful_orders == 1
    assert analysis.failed_orders == 0

    # One attribution entry, carrying the order's own identity.
    assert len(analysis.attributions) == 1
    attr = analysis.attributions[0]
    assert isinstance(attr, OrderLatencyAttribution)
    assert attr.sequence == 1
    assert attr.broker_name == "Broker-A"
    assert attr.order_success is True
    assert attr.engine_stage_failed is False
    assert attr.broker_api_failure_count == 0

    record = report.order(1)
    engine_stage = record.stage(ORDER_ENGINE_PATH)

    # total execution latency = the record's own measured engine window
    assert attr.total_execution_latency_ns == engine_stage.duration_ns
    assert attr.total_execution_latency_ns > 0

    # Engine-scoped Broker/API time covers exactly the calls nested in the
    # engine window (all but the pre-engine instrument resolution).
    pre_engine = record.broker_api_calls[0]
    assert attr.broker_api_calls_within_engine == 4
    assert attr.broker_api_time_ns == (
        record.broker_api_round_trip_ns - pre_engine.duration_ns
    )
    assert attr.broker_api_time_ns > 0
    # The sequence-wide sum keeps ALL five calls, under its own name.
    assert attr.broker_api_time_sequence_wide_ns == record.broker_api_round_trip_ns
    assert attr.broker_api_time_sequence_wide_ns > attr.broker_api_time_ns

    # Application side: measured (shared clock), non-negative, strictly less
    # than the total because broker calls are nested inside the stage.
    assert attr.application_side_ns == record.application_side_ns
    assert attr.application_side_ns >= 0
    assert attr.application_side_ns < attr.total_execution_latency_ns

    # Aggregate totals agree with the record.
    assert analysis.broker_api_total_ns == record.broker_api_round_trip_ns
    assert analysis.dispatch_duration_ns == report.dispatch_duration
    assert analysis.dispatch_duration_ns > 0

    # The five dry-run operations are the ones Task 8.3 measured.
    assert record.broker_api_operations() == [
        OP_GET_INSTRUMENT,
        OP_GET_INSTRUMENT,
        OP_GET_TRADING_STATE,
        OP_GET_BUY_CAPACITY,
        OP_PLACE_ORDER,
    ]


def test_single_execution_stage_distributions_present():
    result, report, _ = measured_dispatch()
    analysis = analyze_latency_report(report)

    assert set(analysis.stage_durations_ns) == {
        PLAN_ITEM,
        PLAN_ACCOUNT,
        INSTRUMENT_RESOLUTION,
        ORDER_ENGINE_PATH,
    }
    record = report.order(1)
    for stage in record.stages:
        dist = analysis.stage_durations_ns[stage.stage_name]
        assert dist.count == 1
        assert dist.min_ns == dist.max_ns == stage.duration_ns
        assert dist.median_ns == dist.mean_ns == stage.duration_ns


# ---------------------------------------------------------------------------
# B — multiple executions
# ---------------------------------------------------------------------------


def test_multiple_executions_reported_per_sequence():
    clock = FakeClock()
    brokers = {
        name: FakeBroker(name, clock=clock)
        for name in ("Broker-A", "Broker-B", "Broker-C")
    }
    from core.dispatch_core import DispatchCore

    core = DispatchCore(
        broker_manager=make_manager(brokers),
        latency_clock=clock,
        broker_clock=clock,
    )
    orders = {code: make_order(code) for code in ("INS-1", "INS-2", "INS-3")}
    accounts = {aid: make_account(aid) for aid in ("ACC-1", "ACC-2", "ACC-3")}
    pairs = [
        (orders["INS-1"], "ACC-3", "Broker-B"),
        (orders["INS-2"], "ACC-1", "Broker-C"),
        (orders["INS-3"], "ACC-2", "Broker-A"),
    ]
    plan = build_plan(pairs)
    plan.accounts = [accounts["ACC-3"], accounts["ACC-1"], accounts["ACC-2"]]

    result, report = core.dispatch_with_latency(plan)
    assert result.success is True

    analysis = analyze_latency_report(report)

    assert analysis.total_orders == 3
    assert analysis.successful_orders == 3
    assert analysis.failed_orders == 0
    assert [a.sequence for a in analysis.attributions] == [1, 2, 3]
    assert [a.broker_name for a in analysis.attributions] == [
        "Broker-B",
        "Broker-C",
        "Broker-A",
    ]

    # Each attribution matches ITS OWN record — no cross-order leak.
    for attr in analysis.attributions:
        record = report.order(attr.sequence)
        assert attr.total_execution_latency_ns == (
            record.duration_ns(ORDER_ENGINE_PATH)
        )
        assert attr.broker_api_time_ns == (
            record.broker_api_round_trip_ns
            - record.broker_api_calls[0].duration_ns  # pre-engine call
        )
        assert attr.broker_api_time_sequence_wide_ns == (
            record.broker_api_round_trip_ns
        )
        assert attr.application_side_ns == record.application_side_ns
        assert attr.order_success is True

    # Aggregates cover all three orders (each has 5 measured calls).
    assert analysis.broker_api_time_ns.count == 3
    assert analysis.broker_api_total_ns == sum(
        r.broker_api_round_trip_ns for r in report.orders
    )
    assert analysis.broker_api_by_operation_ns[OP_PLACE_ORDER].count == 3
    assert analysis.execution_latency_ns.count == 3


def test_aggregate_statistics_match_hand_computed_values():
    clock = FakeClock()
    # One broker per distinct delay so every per-order total is unique.
    delays = {"Broker-A": 100, "Broker-B": 300, "Broker-C": 200}
    brokers = {
        name: FakeBroker(name, clock=clock, delays={op: delay for op in (
            OP_GET_INSTRUMENT,
            OP_GET_TRADING_STATE,
            OP_GET_BUY_CAPACITY,
            OP_PLACE_ORDER,
        )})
        for name, delay in delays.items()
    }
    from core.dispatch_core import DispatchCore

    core = DispatchCore(
        broker_manager=make_manager(brokers),
        latency_clock=clock,
        broker_clock=clock,
    )
    pairs = [
        (make_order("INS-1"), "ACC-1", "Broker-A"),
        (make_order("INS-2"), "ACC-2", "Broker-B"),
        (make_order("INS-3"), "ACC-3", "Broker-C"),
    ]
    plan = build_plan(pairs)
    plan.accounts = [make_account(a) for a in ("ACC-1", "ACC-2", "ACC-3")]

    result, report = core.dispatch_with_latency(plan)
    assert result.success is True

    analysis = analyze_latency_report(report)
    totals = sorted(r.broker_api_round_trip_ns for r in report.orders)

    assert analysis.broker_api_time_ns.count == 3
    assert analysis.broker_api_time_ns.min_ns == totals[0]
    assert analysis.broker_api_time_ns.max_ns == totals[2]
    assert analysis.broker_api_time_ns.median_ns == int(statistics.median(totals))
    assert analysis.broker_api_time_ns.mean_ns == int(statistics.mean(totals))


# ---------------------------------------------------------------------------
# C — min / median / mean / max distributions
# ---------------------------------------------------------------------------


def test_distribution_computed_over_stage_durations():
    result, report, _ = measured_dispatch()
    analysis = analyze_latency_report(report)

    durations = [
        r.duration_ns(ORDER_ENGINE_PATH) for r in report.orders
    ]
    dist = analysis.stage_durations_ns[ORDER_ENGINE_PATH]
    assert dist.count == len(durations)
    assert dist.min_ns == min(durations)
    assert dist.max_ns == max(durations)
    assert dist.median_ns == int(statistics.median(durations))
    assert dist.mean_ns == int(statistics.mean(durations))
    assert analysis.execution_latency_ns == dist


def test_distribution_of_synthetic_values():
    values = (5, 1, 9, 3, 7)
    dist = li._ns_stats(values)
    assert dist.count == 5
    assert dist.min_ns == 1
    assert dist.max_ns == 9
    assert dist.median_ns == 5
    assert dist.mean_ns == 5

    two = li._ns_stats((10, 20))  # even count -> averaged median
    assert two.median_ns == 15
    assert two.min_ns == 10 and two.max_ns == 20


# ---------------------------------------------------------------------------
# D — Broker/API aggregates
# ---------------------------------------------------------------------------


def test_broker_api_aggregates_by_operation():
    result, report, _ = measured_dispatch()
    analysis = analyze_latency_report(report)

    expected_totals = report.broker_api_totals_by_operation()
    assert set(analysis.broker_api_by_operation_ns) == set(expected_totals)
    for operation, dist in analysis.broker_api_by_operation_ns.items():
        assert dist.count == 1
        assert dist.min_ns == expected_totals[operation]

    # place_order aggregate equals the measured submission round trip.
    record = report.order(1)
    submission = record.broker_api_call(OP_PLACE_ORDER)
    assert (
        analysis.broker_api_by_operation_ns[OP_PLACE_ORDER].min_ns
        == submission.duration_ns
    )
    assert analysis.broker_api_failure_count == 0
    assert analysis.broker_api_failures == ()


# ---------------------------------------------------------------------------
# E — application-side attribution
# ---------------------------------------------------------------------------


def test_application_side_attribution_separates_broker_time():
    delay = 5_000_000
    result, report, _ = measured_dispatch(
        delays={OP_GET_BUY_CAPACITY: delay}
    )
    analysis = analyze_latency_report(report)

    attr = analysis.attributions[0]
    record = report.order(1)

    # The injected delay lands on the Broker/API side ...
    assert record.broker_api_round_trip_for(OP_GET_BUY_CAPACITY) >= delay
    assert attr.broker_api_time_ns >= delay
    # ... and stays out of the application-side remainder.
    assert attr.application_side_ns < delay

    # Aggregate application-side distribution has exactly this one value.
    assert analysis.application_side_time_ns.count == 1
    assert analysis.application_side_time_ns.min_ns == attr.application_side_ns


def test_application_side_work_not_attributed_to_broker():
    delay = 5_000_000
    clock, broker, core, order, plan = single_order_setup()
    core.order_engine.validator = SlowValidator(
        core.order_engine.validator, clock, delay
    )
    result, report = core.dispatch_with_latency(plan)

    analysis = analyze_latency_report(report)
    attr = analysis.attributions[0]

    assert attr.application_side_ns >= delay
    assert attr.broker_api_time_ns < delay


def test_mixed_clock_orders_report_none_application_side():
    """
    Orders whose record has no derived application-side value (different
    clocks) are reported as ``None`` — never guessed, and they are excluded
    from the aggregate distribution instead of being fabricated.
    """
    # Manually built mixed report: shared-clock order + cross-clock order.
    shared = OrderLatency(
        sequence=1,
        broker_name="Broker-A",
        stages=[StageTiming(ORDER_ENGINE_PATH, 0, 100)],
        broker_api_calls=[BrokerApiCallTiming(OP_PLACE_ORDER, 10, 60)],
        application_side_ns=50,
    )
    cross = OrderLatency(
        sequence=2,
        broker_name="Broker-B",
        stages=[StageTiming(ORDER_ENGINE_PATH, 0, 100)],
        broker_api_calls=[BrokerApiCallTiming(OP_PLACE_ORDER, 10, 60)],
        application_side_ns=None,  # clocks not shared -> never derived
    )
    report = DispatchLatencyReport(
        trace_id="t",
        dispatch_start=0,
        dispatch_end=200,
        orders=[shared, cross],
    )

    analysis = analyze_latency_report(report)

    assert [a.sequence for a in analysis.attributions] == [1, 2]
    assert analysis.attributions[0].application_side_ns == 50
    assert analysis.attributions[1].application_side_ns is None

    # Aggregate covers only the value that actually exists.
    assert analysis.application_side_time_ns.count == 1
    assert analysis.application_side_time_ns.min_ns == 50


def test_stage_clock_only_injection_yields_none_application_side():
    """End-to-end: injecting only the stage clock leaves attribution None."""
    result, report, _ = measured_dispatch(
        core_factory=split_clock_core,
    )

    assert result.success is True
    analysis = analyze_latency_report(report)

    attr = analysis.attributions[0]
    assert attr.application_side_ns is None
    # Containment is not inferable across clocks: the engine-scoped value
    # stays 0, while the sequence-wide sum keeps every measured round trip.
    assert attr.broker_api_time_ns == 0
    assert attr.broker_api_time_sequence_wide_ns > 0
    assert attr.total_execution_latency_ns > 0
    assert analysis.application_side_time_ns.count == 0
    assert analysis.application_side_time_ns.min_ns is None


# ---------------------------------------------------------------------------
# F — zero / very small latencies
# ---------------------------------------------------------------------------


def test_zero_latency_values_stay_non_negative_and_intact():
    shared = OrderLatency(
        sequence=1,
        broker_name="Broker-A",
        stages=[StageTiming(ORDER_ENGINE_PATH, 7, 7)],  # zero-length window
        broker_api_calls=[BrokerApiCallTiming(OP_PLACE_ORDER, 7, 7)],
        application_side_ns=0,
    )
    report = DispatchLatencyReport(
        trace_id="t",
        dispatch_start=7,
        dispatch_end=7,
        orders=[shared],
    )

    analysis = analyze_latency_report(report)

    attr = analysis.attributions[0]
    assert attr.total_execution_latency_ns == 0
    assert attr.broker_api_time_ns == 0
    assert attr.application_side_ns == 0
    assert analysis.execution_latency_ns.count == 1
    assert analysis.execution_latency_ns.min_ns == 0
    assert analysis.execution_latency_ns.max_ns == 0
    assert analysis.broker_api_total_ns == 0
    assert analysis.dispatch_duration_ns == 0
    # No negative value anywhere in the analysis.
    def _walk(value):
        if isinstance(value, int):
            yield value
        elif isinstance(value, LatencyDistribution):
            for field in (value.min_ns, value.median_ns, value.mean_ns, value.max_ns):
                if field is not None:
                    yield field
    assert all(v >= 0 for v in _walk(analysis.execution_latency_ns))
    assert all(v >= 0 for v in _walk(analysis.broker_api_time_ns))


def test_one_tick_latencies_survive_aggregation():
    result, report, _ = measured_dispatch()
    analysis = analyze_latency_report(report)

    for record in report.orders:
        for call in record.broker_api_calls:
            assert call.duration_ns >= 1  # fake clock: every window >= 1 tick
    dist = analysis.broker_api_time_ns
    assert dist.min_ns >= 1
    assert dist.mean_ns == int(statistics.mean(
        [r.broker_api_round_trip_ns for r in report.orders]
    ))


# ---------------------------------------------------------------------------
# G — failed execution
# ---------------------------------------------------------------------------


def test_failed_execution_stays_visible_in_report():
    # TradingStateUnavailable -> engine BLOCKED (success=False, sent=False).
    result, report, broker = measured_dispatch(
        raise_on={OP_GET_TRADING_STATE: TradingStateUnavailable("offline")}
    )

    assert result.success is False
    assert broker.place_order_calls == []  # nothing was submitted

    analysis = analyze_latency_report(report)

    assert analysis.total_orders == 1
    assert analysis.successful_orders == 0
    assert analysis.failed_orders == 1

    attr = analysis.attributions[0]
    assert attr.order_success is False
    assert attr.engine_stage_failed is True  # the failure happened in-stage
    assert attr.broker_api_failure_count == 1
    assert attr.broker_api_time_ns > 0  # failing call kept its timing

    # The engine stage still exists (the engine ran and returned BLOCKED),
    # so the total is reported — and the failure info carries the real
    # measured duration of the failing call.
    assert attr.total_execution_latency_ns is not None
    failures = analysis.broker_api_failures
    assert len(failures) == 1
    assert isinstance(failures[0], BrokerApiFailureInfo)
    assert failures[0].sequence == 1
    assert failures[0].operation == OP_GET_TRADING_STATE
    record = report.order(1)
    assert failures[0].duration_ns == (
        record.broker_api_call(OP_GET_TRADING_STATE).duration_ns
    )
    assert analysis.broker_api_failure_count == 1


def test_blocked_before_account_still_counted_and_attributed():
    """An order blocked fail-closed BEFORE the engine stage (id-only account
    binding) stays in the report with total=None (the engine window was
    never measured — not invented) and zero broker time (no broker call was
    reached)."""
    from core.dispatch_core import DispatchCore

    clock = FakeClock()
    broker = FakeBroker("Broker-A", clock=clock)
    core = DispatchCore(
        broker_manager=make_manager({"Broker-A": broker}),
        latency_clock=clock,
        broker_clock=clock,
    )
    plan = build_plan([(make_order("INS-A"), "ACC-1", "Broker-A")])
    # id-only binding -> _plan_account returns None -> fail-closed BLOCKED
    # with a per-order result, before instrument resolution / engine path.
    plan.accounts = ["ACC-1"]

    result, report = core.dispatch_with_latency(plan)
    assert result.success is False
    assert result.mode == "BLOCKED"

    analysis = analyze_latency_report(report)

    assert analysis.total_orders == 1
    assert analysis.failed_orders == 1

    attr = analysis.attributions[0]
    assert attr.order_success is False
    assert attr.total_execution_latency_ns is None  # engine stage absent
    assert attr.broker_api_time_ns == 0             # no broker call reached
    assert attr.engine_stage_failed is None         # no stage -> no claim
    assert analysis.execution_latency_ns.count == 0
    assert analysis.execution_latency_ns.min_ns is None


# ---------------------------------------------------------------------------
# H — Broker/API failure inside an otherwise successful flow
# ---------------------------------------------------------------------------


def test_raising_place_order_keeps_failure_visible_and_semantics_unchanged():
    result, report, broker = measured_dispatch(
        raise_on={OP_PLACE_ORDER: RuntimeError("submit failed")}
    )

    # Existing semantics: engine ERROR, dispatch fail-closed BLOCKED.
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert report.order(1).execution_result.mode == "ERROR"

    analysis = analyze_latency_report(report)

    attr = analysis.attributions[0]
    assert attr.order_success is False
    assert attr.engine_stage_failed is True
    assert attr.broker_api_failure_count == 1

    failure = analysis.broker_api_failures[0]
    assert failure.operation == OP_PLACE_ORDER
    assert failure.duration_ns >= 0

    submission = report.order(1).broker_api_call(OP_PLACE_ORDER)
    assert submission.ok is False
    assert failure.duration_ns == submission.duration_ns

    # The failed submission still counts in the Broker/API aggregate.
    assert analysis.broker_api_total_ns >= failure.duration_ns
    assert analysis.broker_api_by_operation_ns[OP_PLACE_ORDER].count == 1


# ---------------------------------------------------------------------------
# I — missing data / empty report
# ---------------------------------------------------------------------------


def test_empty_report_produces_zero_valued_no_data_analysis():
    report = DispatchLatencyReport(
        trace_id="empty",
        dispatch_start=0,
        dispatch_end=0,
        orders=[],
    )

    analysis = analyze_latency_report(report)

    assert analysis.total_orders == 0
    assert analysis.successful_orders == 0
    assert analysis.failed_orders == 0
    assert analysis.dispatch_duration_ns == 0
    assert analysis.attributions == ()
    assert analysis.broker_api_total_ns == 0
    assert analysis.broker_api_failure_count == 0
    assert analysis.broker_api_failures == ()
    # Empty distributions report count=0 and None values — nothing invented.
    for dist in (
        analysis.execution_latency_ns,
        analysis.application_side_time_ns,
        analysis.broker_api_time_ns,
    ):
        assert isinstance(dist, LatencyDistribution)
        assert dist.count == 0
        assert dist.min_ns is None
        assert dist.median_ns is None
        assert dist.mean_ns is None
        assert dist.max_ns is None
    for stage in (PLAN_ITEM, PLAN_ACCOUNT, INSTRUMENT_RESOLUTION, ORDER_ENGINE_PATH):
        dist = analysis.stage_durations_ns[stage]
        assert dist.count == 0 and dist.min_ns is None


def test_record_without_engine_stage_has_none_total():
    shared = OrderLatency(
        sequence=9,
        broker_name="Broker-B",
        stages=[StageTiming(PLAN_ITEM, 0, 5)],  # no ORDER_ENGINE_PATH stage
        broker_api_calls=[],
    )
    report = DispatchLatencyReport(
        trace_id="t",
        dispatch_start=0,
        dispatch_end=50,
        orders=[shared],
    )

    analysis = analyze_latency_report(report)

    attr = analysis.attributions[0]
    assert attr.sequence == 9
    assert attr.total_execution_latency_ns is None  # not fabricated
    assert attr.broker_api_time_ns == 0
    assert attr.application_side_ns is None
    assert analysis.execution_latency_ns.count == 0
    # The recorded stage is still aggregated where it exists.
    assert analysis.stage_durations_ns[PLAN_ITEM].count == 1


# ---------------------------------------------------------------------------
# J — sequence identity
# ---------------------------------------------------------------------------


def test_sequence_identity_survives_into_analysis():
    clock = FakeClock()
    brokers = {
        name: FakeBroker(name, clock=clock)
        for name in ("Broker-A", "Broker-B")
    }
    from core.dispatch_core import DispatchCore

    core = DispatchCore(
        broker_manager=make_manager(brokers),
        latency_clock=clock,
        broker_clock=clock,
    )
    pairs = [
        (make_order("INS-1", side=SELL), "ACC-2", "Broker-B"),
        (make_order("INS-2", side=BUY), "ACC-1", "Broker-A"),
    ]
    plan = build_plan(pairs)
    plan.accounts = [make_account("ACC-2"), make_account("ACC-1")]

    result, report = core.dispatch_with_latency(plan)
    assert result.success is True

    analysis = analyze_latency_report(report)
    assert [a.sequence for a in analysis.attributions] == [1, 2]
    assert [a.broker_name for a in analysis.attributions] == ["Broker-B", "Broker-A"]

    # No global/current-order state: each attribution equals its own record.
    for attr in analysis.attributions:
        record = report.order(attr.sequence)
        assert attr.broker_name == record.broker_name
        assert attr.broker_api_time_sequence_wide_ns == (
            record.broker_api_round_trip_ns
        )
        assert attr.broker_api_time_ns == (
            record.broker_api_round_trip_ns
            - record.broker_api_calls[0].duration_ns  # pre-engine call
        )
        assert attr.total_execution_latency_ns == (
            record.duration_ns(ORDER_ENGINE_PATH)
        )


def test_analysis_is_read_only_over_the_report():
    result, report, _ = measured_dispatch()

    before = [
        (r.sequence, list(r.broker_api_calls), r.application_side_ns,
         r.duration_ns(ORDER_ENGINE_PATH))
        for r in report.orders
    ]
    analyze_latency_report(report)
    analyze_latency_report(report)

    after = [
        (r.sequence, list(r.broker_api_calls), r.application_side_ns,
         r.duration_ns(ORDER_ENGINE_PATH))
        for r in report.orders
    ]
    assert before == after
    assert len(analyze_latency_report(report).attributions) == len(report.orders)


# ---------------------------------------------------------------------------
# K — regression: ordinary dispatch unchanged
# ---------------------------------------------------------------------------


def test_normal_dispatch_path_unchanged_and_measurement_free():
    # Reference run on the ordinary (unmeasured) dispatch path.
    _, broker, core, order, plan = single_order_setup()

    result = core.dispatch(plan)

    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    normal_log = list(broker.call_log)
    # Same interaction as the measured path (Task 8.3): the provider lookup
    # happens once in DispatchCore and once inside the engine path.
    assert normal_log == [
        OP_GET_INSTRUMENT,
        OP_GET_INSTRUMENT,
        OP_GET_TRADING_STATE,
        OP_GET_BUY_CAPACITY,
        OP_PLACE_ORDER,
    ]

    # Same plan through the measured path: identical broker interaction and
    # result semantics.
    clock_m, broker_m, core_m, _, plan_m = single_order_setup()
    measured_result, report = core_m.dispatch_with_latency(plan_m)
    assert broker_m.call_log == normal_log
    assert measured_result.mode == result.mode
    assert analyze_latency_report(report).attributions[0].order_success is True

    # The Task 8.4 layer adds nothing to the normal path.
    import time as time_module

    with patch(
        "core.latency_instrumentation.time.perf_counter_ns",
        wraps=time_module.perf_counter_ns,
    ) as clock_spy:
        core.dispatch(plan)
    assert clock_spy.call_count == 0


def test_task84_layer_is_separate_and_additive():
    source = inspect.getsource(li)
    # The new layer is appended at the end of the module.
    assert source.index("def analyze_latency_report(") > source.index(
        "class LatencyCollector"
    )
    # It adds no new dispatch entry point and no clock of its own.
    assert "def dispatch" not in source[source.index("# Task 8.4"):]
    assert "perf_counter" not in source[source.index("# Task 8.4"):]

    # Task 8.4 works purely as a function of the existing report.
    import dataclasses

    names = {f.name for f in dataclasses.fields(OrderLatency)}
    assert "application_side_ns" in names  # Task 8.3 field still intact


def test_task84_analysis_is_fully_offline():
    with patch("socket.socket", side_effect=AssertionError("network access")):
        result, report, _ = measured_dispatch()
        analysis = analyze_latency_report(report)

    assert result.mode == "ALL_PROCESSED"
    assert analysis.total_orders == 1
    assert analysis.attributions[0].order_success is True


# ---------------------------------------------------------------------------
# L — review fix 1: clock-safe stage containment (stage_failed)
# ---------------------------------------------------------------------------


def test_stage_failed_shared_clock_still_detects_in_stage_failure():
    # Shared clock: containment by timestamp comparison is valid.
    record = OrderLatency(
        sequence=1,
        stages=[StageTiming(ORDER_ENGINE_PATH, 0, 100)],
        broker_api_calls=[
            BrokerApiCallTiming(OP_GET_TRADING_STATE, 10, 20, ok=False),
            BrokerApiCallTiming(OP_PLACE_ORDER, 40, 60),
        ],
        clocks_shared=True,
    )
    assert record.stage_failed(ORDER_ENGINE_PATH) is True
    assert [
        c.operation for c in record.broker_api_calls_within(ORDER_ENGINE_PATH)
    ] == [OP_GET_TRADING_STATE, OP_PLACE_ORDER]


def test_stage_failed_shared_clock_false_when_all_nested_calls_ok():
    record = OrderLatency(
        sequence=1,
        stages=[StageTiming(ORDER_ENGINE_PATH, 0, 100)],
        broker_api_calls=[BrokerApiCallTiming(OP_PLACE_ORDER, 40, 60)],
        clocks_shared=True,
    )
    assert record.stage_failed(ORDER_ENGINE_PATH) is False


def test_stage_failed_different_clock_never_claims_containment():
    # The failing call's timestamps come from the broker clock while the
    # stage window comes from the stage clock: no containment claim may be
    # fabricated, and the raw failure stays visible.
    record = OrderLatency(
        sequence=1,
        stages=[StageTiming(ORDER_ENGINE_PATH, 0, 100)],
        broker_api_calls=[
            BrokerApiCallTiming(OP_GET_TRADING_STATE, 10, 20, ok=False)
        ],
        clocks_shared=False,
    )
    assert record.stage_failed(ORDER_ENGINE_PATH) is None
    assert record.broker_api_calls_within(ORDER_ENGINE_PATH) == []
    assert [c.operation for c in record.broker_api_failures()] == [
        OP_GET_TRADING_STATE
    ]


def test_stage_failed_absent_stage_is_none_even_across_clocks():
    record = OrderLatency(
        sequence=1,
        stages=[],
        broker_api_calls=[
            BrokerApiCallTiming(OP_GET_TRADING_STATE, 10, 20, ok=False)
        ],
        clocks_shared=False,
    )
    # Nothing can belong to a stage that was never recorded -> no claim.
    assert record.stage_failed(ORDER_ENGINE_PATH) is None


def test_end_to_end_split_clock_engine_stage_failed_is_none_failures_visible():
    result, report, _ = measured_dispatch(
        core_factory=split_clock_core,
        raise_on={OP_GET_TRADING_STATE: TradingStateUnavailable("offline")},
    )

    assert result.success is False  # existing fail-closed semantics intact
    analysis = analyze_latency_report(report)
    attr = analysis.attributions[0]

    assert attr.engine_stage_failed is None   # no cross-clock claim made
    assert attr.broker_api_failure_count == 1  # failure is NOT lost
    failure = analysis.broker_api_failures[0]
    assert failure.operation == OP_GET_TRADING_STATE
    assert failure.duration_ns >= 0
    assert attr.broker_api_time_ns == 0               # no containment claim
    assert attr.broker_api_time_sequence_wide_ns > 0  # round trips remain valid


def test_records_stamp_their_collectors_clock_configuration():
    shared_result, shared_report, _ = measured_dispatch()
    assert all(r.clocks_shared is True for r in shared_report.orders)

    split_result, split_report, _ = measured_dispatch(
        core_factory=split_clock_core,
    )
    assert all(r.clocks_shared is False for r in split_report.orders)


# ---------------------------------------------------------------------------
# M — review fix 2: explicit attribution boundary (engine window)
# ---------------------------------------------------------------------------


def test_pre_engine_instrument_call_recorded_but_outside_engine_attribution():
    result, report, _ = measured_dispatch(
        delays={OP_GET_INSTRUMENT: 1_000_000}
    )
    record = report.order(1)

    # 1) The pre-engine get_instrument call REMAINS recorded.
    assert record.broker_api_operations() == [
        OP_GET_INSTRUMENT,      # pre-engine (instrument_resolution stage)
        OP_GET_INSTRUMENT,      # inside the engine path
        OP_GET_TRADING_STATE,
        OP_GET_BUY_CAPACITY,
        OP_PLACE_ORDER,
    ]
    instrument_stage = record.stage(INSTRUMENT_RESOLUTION)
    pre_engine = record.broker_api_calls[0]
    assert pre_engine.start >= instrument_stage.start
    assert pre_engine.end <= instrument_stage.end

    analysis = analyze_latency_report(report)
    attr = analysis.attributions[0]

    # 2) NOT folded into the ORDER_ENGINE_PATH decomposition:
    assert attr.broker_api_calls_within_engine == 4
    assert attr.broker_api_time_ns == sum(
        c.duration_ns for c in record.broker_api_calls[1:]
    )

    # 3) Calls INSIDE the engine window ARE included:
    assert attr.broker_api_time_ns > 0
    # The injected pre-engine delay stays out of the engine-scoped value...
    assert (
        attr.broker_api_time_sequence_wide_ns - attr.broker_api_time_ns
        >= 1_000_000
    )
    # ...while the sequence-wide value keeps ALL five calls.
    assert attr.broker_api_time_sequence_wide_ns == record.broker_api_round_trip_ns

    # 4) Application-side attribution stays non-negative and consistent
    #    with the chosen boundary (engine window).
    assert attr.application_side_ns >= 0
    assert attr.total_execution_latency_ns == record.duration_ns(
        ORDER_ENGINE_PATH
    )
    assert (
        attr.broker_api_time_ns + attr.application_side_ns
        == attr.total_execution_latency_ns
    )

    # 6) Existing aggregate Broker/API reporting remains intact — the
    #    pre-engine call still counts everywhere.
    assert analysis.broker_api_total_ns == record.broker_api_round_trip_ns
    assert analysis.broker_api_time_ns.count == 1
    assert analysis.broker_api_by_operation_ns[OP_GET_INSTRUMENT].count == 1
    assert analysis.broker_api_failure_count == 0


def test_cross_clock_within_engine_fields_are_not_fabricated():
    result, report, _ = measured_dispatch(core_factory=split_clock_core)
    analysis = analyze_latency_report(report)
    attr = analysis.attributions[0]

    # Containment is not inferable across clocks: the engine-scoped value
    # is not fabricated (stays 0); the sequence-wide sum keeps every call
    # under its own explicit name.
    assert attr.broker_api_calls_within_engine == 0
    assert attr.broker_api_time_ns == 0
    assert attr.broker_api_time_sequence_wide_ns == (
        report.order(1).broker_api_round_trip_ns
    )
    assert attr.broker_api_time_sequence_wide_ns > 0
    assert analysis.broker_api_total_ns == attr.broker_api_time_sequence_wide_ns


def test_attribution_boundary_does_not_leak_between_sequences():
    clock = FakeClock()
    delays = {"Broker-A": 400, "Broker-B": 100}
    brokers = {
        name: FakeBroker(
            name,
            clock=clock,
            delays={
                op: delay
                for op in (
                    OP_GET_INSTRUMENT,
                    OP_GET_TRADING_STATE,
                    OP_GET_BUY_CAPACITY,
                    OP_PLACE_ORDER,
                )
            },
        )
        for name, delay in delays.items()
    }
    core = shared_clock_core(make_manager(brokers), clock)
    plan = build_plan(
        [
            (make_order("INS-1"), "ACC-1", "Broker-A"),
            (make_order("INS-2"), "ACC-2", "Broker-B"),
        ]
    )
    plan.accounts = [make_account("ACC-1"), make_account("ACC-2")]

    result, report = core.dispatch_with_latency(plan)
    assert result.success is True

    analysis = analyze_latency_report(report)
    for attr in analysis.attributions:
        record = report.order(attr.sequence)
        engine_stage = record.stage(ORDER_ENGINE_PATH)
        assert attr.broker_api_calls_within_engine == 4
        assert attr.broker_api_time_ns == sum(
            c.duration_ns for c in record.broker_api_calls[1:]
        )
        assert attr.application_side_ns >= 0
        assert (
            attr.broker_api_time_ns + attr.application_side_ns
            == attr.total_execution_latency_ns
            == engine_stage.duration_ns
        )

    # Each sequence decomposes its OWN window — no timing swapped/leaked.
    first, second = analysis.attributions
    assert first.broker_api_time_ns > second.broker_api_time_ns
    assert first.total_execution_latency_ns > second.total_execution_latency_ns
