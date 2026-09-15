"""Block 5 — Task 4: Real Dispatch Integration tests.

Tests for the connection between the Block 5 tracking components
(``ExecutionTracker`` / ``collect_result`` / ``StopSignal``) and the real,
existing dispatch path (Block 2 ``DispatchCore.dispatch`` and the Block 4
connector ``connect_plan_to_dispatch``), plus the Block 3 Timed / Burst
dispatch moments.

Covered:
  - Send path: only the Stop Signal is consulted; inactive -> dispatch.
  - Send path: active Stop Signal -> DispatchCore.dispatch NOT called,
    mode="STOPPED", no execution registered, prior orders untouched.
  - Send path never waits for results (burst of dispatches stays PENDING).
  - Result path: results may arrive out of order, per execution.
  - Late results after the Stop Signal activated are still recorded.
  - StopSignal semantics unchanged (disabled never activates; enabled
    activates on the first success only).
  - Fail-closed: invalid plan / invalid or duplicate execution_id /
    unknown execution_id / invalid constructor arguments.
  - Block 4 connector used unchanged (with and without the integration).
  - Block 3 Timed / Burst path (deterministic scheduler moments) dispatches
    without waiting for any result.

No scheduler loop, timer, polling, broker API, or real order execution.
The broker/provider/OrderEngine boundary is mocked, exactly like
``test_dispatch_core.py`` / ``test_block4_task3.py``.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timedelta
from unittest.mock import Mock

from core.block4_task2 import connect_trigger_to_planner
from core.block4_task3 import connect_plan_to_dispatch
from core.block5_task3 import StopSignal
from core.block5_task4 import (
    STOPPED_MODE,
    DispatchIntegration,
    DispatchIntegrationError,
    GuardDecision,
    stop_guard,
)
from core.dispatch_contracts import DispatchResult, ExecutionPlan
from core.dispatch_core import DispatchCore
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from core.execution_tracker import (
    ExecutionStatus,
    ExecutionTracker,
    ExecutionTrackerError,
)
from core.order_engine import OrderExecutionResult
from core.timed_dispatch_scheduler import TimedDispatchScheduler
from core.timed_dispatch_trigger import TimedDispatchTrigger
from core.timing_contracts import DispatchTiming
from core.trading_state_event_trigger import TradingStateEventTrigger
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order
from models.trading_state import VERIFIED_BLOCKED, VERIFIED_TRADABLE


NOW = datetime(2026, 9, 15, 9, 0, 0)


# ---------------------------------------------------------------------------
# Helpers (same conventions as test_dispatch_core.py / test_block4_task3.py)
# ---------------------------------------------------------------------------


def make_order(nsc_id="IRO1TEST0001", side=BUY, price=150, quantity=10):
    return Order(nsc_id=nsc_id, side=side, price=price, quantity=quantity)


def make_account(account_id="acc-1"):
    acc = Account(
        last_balance=0,
        adjusted_balance_t2=0,
        tradable_balance_t1=1_000_000,
        tradable_balance_t2=1_000_000,
        payable_balance_with_agah_credit_t0=0,
        payable_balance_with_agah_credit_t1=0,
        payable_balance_with_agah_credit_t2=0,
        payable_balance_without_agah_credit_t0=0,
        block=0,
        credit=0,
        settlement_date_t0=None,
        settlement_date_t1=None,
        settlement_date_t2=None,
    )
    acc.account_id = account_id
    return acc


def build_plan(orders, account_ids, broker_names, plan_id="plan-b5t4"):
    """Build an ExecutionPlan through the REAL Block 1 planner."""
    pos = [
        PlannedOrder(
            order=order,
            account_id=account_ids[i],
            broker_name=broker_names[i],
            sequence=i,
        )
        for i, order in enumerate(orders)
    ]
    return ExecutionPlanner().build_plan(
        LogicalOrderInstruction(plan_id=plan_id, orders=pos)
    )


def simple_plan(plan_id="plan-b5t4", broker_name="broker-a", account_id="acc-1"):
    """One-order plan (bound account/broker) built by the real planner."""
    return build_plan(
        [make_order()], [account_id], [broker_name], plan_id=plan_id
    )


def attach_accounts(plan, accounts_by_id):
    """Attach resolved Account objects to a planner-produced plan."""
    seen = []
    for seq in plan.execution_order:
        acc_id = plan.conditions["binding"][seq]["account_id"]
        if acc_id not in seen:
            seen.append(acc_id)
    plan.accounts = [accounts_by_id[a] for a in seen]
    return plan


def make_mock_broker(name="broker-a"):
    broker = Mock()
    broker.name = name
    return broker


def make_mock_provider():
    provider = Mock()
    provider.get_instrument.return_value = (
        Mock(),
        BrokerInstrument(nsc_id="IRO1TEST0001"),
    )
    return provider


def make_broker_manager(broker_names):
    """Return a Mock BrokerManager wired to unique broker/provider mocks."""
    available = {name: make_mock_broker(name) for name in broker_names}
    providers = {name: make_mock_provider() for name in broker_names}

    manager = Mock()
    manager.get.side_effect = lambda name, _a=available: _a[name]
    manager.get_instrument_provider.side_effect = (
        lambda name, _p=providers: _p[name]
    )
    return manager


def make_spy_core(result=None):
    """DispatchCore whose dispatch() is replaced by a recording stub.

    Returns (core, calls, sentinel): ``calls`` records every plan passed to
    ``dispatch`` and ``sentinel`` is the DispatchResult returned.
    """
    core = DispatchCore()
    sentinel = result if result is not None else ok_result()
    calls = []

    def fake_dispatch(plan):
        calls.append(plan)
        return sentinel

    core.dispatch = fake_dispatch  # type: ignore[method-assign]
    return core, calls, sentinel


def make_real_core(broker_names=("broker-a",)):
    """Real DispatchCore with only the broker/provider/OrderEngine mocked."""
    core = DispatchCore()
    core.broker_manager = make_broker_manager(list(broker_names))

    def fake_execute(broker, provider, ins_code, order, account, live):
        return OrderExecutionResult(
            success=True, sent=False, mode="READY", order=order
        )

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)
    return core


def ok_result():
    """A real DispatchResult for a successful dispatch."""
    return DispatchResult(success=True, sent=False, mode="ALL_PROCESSED")


def fail_result():
    """A real DispatchResult for a failed / blocked dispatch."""
    return DispatchResult(success=False, sent=False, mode="BLOCKED")


def active_signal():
    """A StopSignal(enabled=True) already activated (no dispatch involved)."""
    signal = StopSignal(enabled=True)
    signal.observe(ok_result())
    return signal


def expect_raises(exc_type, func, label):
    """Assert that ``func()`` raises ``exc_type``."""
    try:
        func()
    except exc_type:
        return
    except Exception as exc:  # pragma: no cover - diagnostic path
        raise AssertionError(
            f"{label}: expected {exc_type.__name__}, got {exc!r}"
        )
    raise AssertionError(f"{label}: expected {exc_type.__name__}, nothing raised")


# ---------------------------------------------------------------------------
# Guard / send path
# ---------------------------------------------------------------------------


def test_guard_decision_allow_then_stop():
    """stop_guard: ALLOW while inactive, STOP once the Stop Signal is active."""
    signal = StopSignal(enabled=True)
    assert stop_guard(signal) is GuardDecision.ALLOW
    assert signal.is_active is False

    signal.observe(ok_result())

    assert stop_guard(signal) is GuardDecision.STOP
    assert GuardDecision.ALLOW.value == "ALLOW"
    assert GuardDecision.STOP.value == "STOP"


def test_guard_invalid_signal_type_fail_closed():
    """A non-StopSignal argument -> DispatchIntegrationError (fail-closed)."""
    for bad in (None, "signal", 1, object()):
        expect_raises(
            DispatchIntegrationError,
            lambda b=bad: stop_guard(b),
            f"stop_guard({bad!r})",
        )


def test_default_construction_is_fail_open():
    """Default integration: disabled StopSignal, empty tracker, not stopped."""
    core, calls, sentinel = make_spy_core()
    integration = DispatchIntegration(core)

    assert isinstance(integration.tracker, ExecutionTracker)
    assert integration.tracker._records == {}
    assert isinstance(integration.stop_signal, StopSignal)
    assert integration.stop_signal.enabled is False
    assert integration.is_stopped is False
    assert integration.last_execution_id is None
    assert integration.dispatch_core is core


def test_dispatch_allowed_when_signal_inactive():
    """Inactive Stop Signal -> the plan reaches the existing dispatch path."""
    core, calls, sentinel = make_spy_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    plan = simple_plan()
    result = integration.dispatch(plan)

    assert result is sentinel, "the Dispatch Core result is returned as-is"
    assert calls == [plan], "the exact plan is delegated once"
    exec_id = integration.last_execution_id
    assert exec_id is not None
    assert tracker.get_status(exec_id) == ExecutionStatus.PENDING


def test_dispatch_allowed_when_enabled_but_not_activated():
    """enabled=True but not yet active -> still ALLOW (no result seen yet)."""
    core, calls, _ = make_spy_core()
    signal = StopSignal(enabled=True)
    integration = DispatchIntegration(core, stop_signal=signal)

    integration.dispatch(simple_plan(), execution_id="exec-1")

    assert signal.is_active is False
    assert len(calls) == 1
    assert integration.is_stopped is False


def test_guard_stops_new_dispatch_when_active():
    """Active Stop Signal -> the dispatch is bypassed entirely (fail-closed)."""
    core, calls, _ = make_spy_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(
        core, tracker=tracker, stop_signal=active_signal()
    )

    result = integration.dispatch(simple_plan(), execution_id="exec-stopped")

    assert calls == [], "DispatchCore.dispatch must NOT be called"
    assert result.mode == STOPPED_MODE
    assert result.success is False
    assert result.sent is False
    assert result.order_count == 0
    assert result.trace_id is None
    assert tracker._records == {}, "no execution for a bypassed dispatch"
    assert integration.last_execution_id is None
    assert integration.is_stopped is True


def test_connector_reports_entry_point_for_stopped_dispatch():
    """Block 4 connector unchanged: it reports the entry point was reached.

    With the integration, ``dispatch_called=True`` means the dispatch entry
    point was reached; ``mode=STOPPED`` says no order was actually sent.
    """
    core, calls, _ = make_spy_core()
    integration = DispatchIntegration(core, stop_signal=active_signal())

    outcome = connect_plan_to_dispatch(simple_plan(), integration)

    assert outcome["dispatched"] is True
    assert outcome["dispatch_called"] is True
    assert outcome["dispatch_result"].mode == STOPPED_MODE
    assert calls == [], "Dispatch Core never invoked while stopped"


def test_stopped_dispatch_does_not_touch_prior_executions():
    """Stopping only affects NEW dispatches: prior records stay untouched."""
    core, calls, _ = make_spy_core()
    tracker = ExecutionTracker()
    signal = StopSignal(enabled=True)
    integration = DispatchIntegration(core, tracker=tracker, stop_signal=signal)

    # --- two dispatches issued and recorded before the stop -------------
    integration.dispatch(simple_plan(plan_id="plan-1"), execution_id="exec-1")
    integration.dispatch(simple_plan(plan_id="plan-2"), execution_id="exec-2")
    integration.record_result("exec-1", ok_result())  # activates the stop
    integration.record_result("exec-2", fail_result())

    assert signal.is_active is True
    snapshot = dict(tracker._records)
    calls_before = list(calls)

    # --- a new dispatch after the stop ----------------------------------
    result = integration.dispatch(
        simple_plan(plan_id="plan-3"), execution_id="exec-3"
    )

    assert calls == calls_before, "no new dispatch may reach the Dispatch Core"
    assert result.mode == STOPPED_MODE
    assert tracker._records == snapshot, "prior records must be untouched"
    assert tracker.get_status("exec-1") == ExecutionStatus.REGISTERED
    assert tracker.get_status("exec-2") == ExecutionStatus.FAILED
    assert "exec-3" not in tracker._records


# ---------------------------------------------------------------------------
# SEND PATH / RESULT PATH independence
# ---------------------------------------------------------------------------


def test_send_path_never_waits_for_results():
    """A burst of 4 dispatches is issued without any result being recorded."""
    core, calls, _ = make_spy_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    for i in range(1, 5):
        integration.dispatch(
            simple_plan(plan_id=f"plan-{i}"), execution_id=f"exec-{i}"
        )

    assert len(calls) == 4, "all 4 dispatches issued back-to-back"
    for i in range(1, 5):
        assert tracker.get_status(f"exec-{i}") == ExecutionStatus.PENDING, (
            "no result was needed to keep dispatching"
        )


def test_results_may_arrive_out_of_order():
    """Results 3, 1, 4, 2 for dispatches 1..4 are recorded independently."""
    core, calls, _ = make_spy_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    for i in range(1, 5):
        integration.dispatch(
            simple_plan(plan_id=f"plan-{i}"), execution_id=f"exec-{i}"
        )

    integration.record_result("exec-3", ok_result())
    integration.record_result("exec-1", fail_result())
    integration.record_result("exec-4", ok_result())
    integration.record_result("exec-2", ok_result())

    assert tracker.get_status("exec-1") == ExecutionStatus.FAILED
    assert tracker.get_status("exec-2") == ExecutionStatus.REGISTERED
    assert tracker.get_status("exec-3") == ExecutionStatus.REGISTERED
    assert tracker.get_status("exec-4") == ExecutionStatus.REGISTERED
    assert integration.stop_signal.is_active is False, (
        "disabled rule never activates, whatever the result order"
    )


def test_late_results_after_stop_are_still_recorded():
    """After the stop: no new dispatch, but late results still land."""
    core, calls, _ = make_spy_core()
    tracker = ExecutionTracker()
    signal = StopSignal(enabled=True)
    integration = DispatchIntegration(core, tracker=tracker, stop_signal=signal)

    for name in ("a", "b", "c"):
        integration.dispatch(
            simple_plan(plan_id=f"plan-{name}"), execution_id=f"exec-{name}"
        )
    assert len(calls) == 3

    # --- the first success activates the stop (Task 3 semantics) --------
    integration.record_result("exec-b", ok_result())
    assert signal.is_active is True
    assert signal.activation_count == 1

    # --- new dispatches are stopped -------------------------------------
    blocked = integration.dispatch(
        simple_plan(plan_id="plan-d"), execution_id="exec-d"
    )
    assert blocked.mode == STOPPED_MODE
    assert len(calls) == 3
    assert "exec-d" not in tracker._records

    # --- late results of already-sent dispatches are still recorded -----
    integration.record_result("exec-a", fail_result())
    integration.record_result("exec-c", ok_result())

    assert tracker.get_status("exec-a") == ExecutionStatus.FAILED
    assert tracker.get_status("exec-c") == ExecutionStatus.REGISTERED
    assert signal.is_active is True, "an activated signal stays active"
    assert len(tracker._records) == 3


def test_stopped_result_cannot_reach_a_prior_execution():
    """A synthetic STOPPED result can never be attributed to an execution.

    ``last_execution_id`` still points at the last dispatch that was really
    issued. Feeding the STOPPED result of a bypassed dispatch to that id
    must be fail-closed: the status of the previously issued execution must
    not change, and the Stop Signal must not observe the synthetic result.
    """
    core, calls, _ = make_spy_core()
    tracker = ExecutionTracker()
    signal = StopSignal(enabled=True)
    integration = DispatchIntegration(core, tracker=tracker, stop_signal=signal)

    # --- dispatch 1 was issued and recorded as REGISTERED ---------------
    integration.dispatch(simple_plan(plan_id="plan-1"), execution_id="exec-1")
    integration.record_result("exec-1", ok_result())
    issued_id = integration.last_execution_id
    assert issued_id == "exec-1"
    assert tracker.get_status(issued_id) == ExecutionStatus.REGISTERED
    snapshot = dict(tracker._records)
    activation_count = signal.activation_count

    # --- dispatch 2 is bypassed by the Stop Signal ----------------------
    outcome = connect_plan_to_dispatch(simple_plan(plan_id="plan-2"), integration)
    stopped = outcome["dispatch_result"]
    assert stopped.mode == STOPPED_MODE

    # last_execution_id still points at the previously issued execution...
    assert integration.last_execution_id == issued_id

    # ...but the STOPPED result must never be recordable against it.
    expect_raises(
        DispatchIntegrationError,
        lambda: integration.record_result(issued_id, stopped),
        "record_result(prior id, STOPPED result)",
    )
    expect_raises(
        DispatchIntegrationError,
        lambda: integration.record_result(integration.last_execution_id, stopped),
        "record_result(last_execution_id, STOPPED result)",
    )

    assert tracker._records == snapshot, "prior execution record unchanged"
    assert tracker.get_status(issued_id) == ExecutionStatus.REGISTERED
    assert len(tracker._records) == 1, "no execution created for the STOPPED result"
    assert signal.is_active is True
    assert signal.activation_count == activation_count, (
        "the synthetic result was not observed by the Stop Signal"
    )
    assert len(calls) == 1, "no new dispatch reached the Dispatch Core"

    # A real late result for an issued execution is still recordable.
    integration.record_result("exec-1", fail_result())
    assert tracker.get_status("exec-1") == ExecutionStatus.FAILED


def test_stop_semantics_unchanged_disabled_never_activates():
    """enabled=False: successes never activate; dispatch always continues."""
    core, calls, _ = make_spy_core()
    integration = DispatchIntegration(core, stop_signal=StopSignal(enabled=False))

    integration.dispatch(simple_plan(plan_id="p1"), execution_id="e1")
    integration.record_result("e1", ok_result())
    integration.dispatch(simple_plan(plan_id="p2"), execution_id="e2")
    integration.record_result("e2", ok_result())
    integration.dispatch(simple_plan(plan_id="p3"), execution_id="e3")

    assert integration.stop_signal.is_active is False
    assert integration.stop_signal.should_continue() is True
    assert len(calls) == 3


def test_stop_semantics_unchanged_enabled_failure_then_success():
    """enabled=True: failures continue, the first success stops new sends."""
    core, calls, _ = make_spy_core()
    signal = StopSignal(enabled=True)
    integration = DispatchIntegration(core, stop_signal=signal)

    integration.dispatch(simple_plan(plan_id="p1"), execution_id="e1")
    integration.record_result("e1", fail_result())
    assert signal.is_active is False

    integration.dispatch(simple_plan(plan_id="p2"), execution_id="e2")
    integration.record_result("e2", fail_result())
    assert signal.is_active is False
    assert len(calls) == 2

    integration.dispatch(simple_plan(plan_id="p3"), execution_id="e3")
    integration.record_result("e3", ok_result())
    assert signal.is_active is True

    stopped = integration.dispatch(simple_plan(plan_id="p4"), execution_id="e4")
    assert stopped.mode == STOPPED_MODE
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# Fail-closed behavior
# ---------------------------------------------------------------------------


def test_unknown_execution_id_fail_closed():
    """A result for an execution the integration never issued -> fail-closed.

    The ordered result pipeline stops at the tracker stage: the tracker is
    unchanged and the Stop Signal is NOT observed.
    """
    core, calls, _ = make_spy_core()
    tracker = ExecutionTracker()
    signal = StopSignal(enabled=True)
    integration = DispatchIntegration(core, tracker=tracker, stop_signal=signal)

    expect_raises(
        ExecutionTrackerError,
        lambda: integration.record_result("never-issued", ok_result()),
        "record_result(unknown id)",
    )

    assert tracker._records == {}
    assert signal.is_active is False, "the Stop Signal was not observed"

    # The send path still works: dispatch is allowed while not stopped.
    integration.dispatch(simple_plan(), execution_id="exec-1")
    assert len(calls) == 1


def test_invalid_plan_fail_closed():
    """A non-ExecutionPlan plan is rejected before anything is dispatched."""
    core, calls, _ = make_spy_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    for bad in (None, "plan", 42, object(), {"orders": []}):
        expect_raises(
            DispatchIntegrationError,
            lambda b=bad: integration.dispatch(b),
            f"dispatch({bad!r})",
        )

    assert calls == []
    assert tracker._records == {}
    assert integration.last_execution_id is None


def test_invalid_execution_id_fail_closed():
    """A blank / non-string execution_id is rejected before dispatch."""
    core, calls, _ = make_spy_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    for bad in ("", "   ", 123, ["exec"], object()):
        expect_raises(
            DispatchIntegrationError,
            lambda b=bad: integration.dispatch(simple_plan(), execution_id=b),
            f"dispatch(execution_id={bad!r})",
        )

    assert calls == []
    assert tracker._records == {}


def test_duplicate_execution_id_fail_closed():
    """Re-using an execution_id is rejected before the second dispatch."""
    core, calls, _ = make_spy_core()
    integration = DispatchIntegration(core, tracker=ExecutionTracker())
    plan = simple_plan()

    integration.dispatch(plan, execution_id="exec-dup")
    assert len(calls) == 1

    expect_raises(
        ExecutionTrackerError,
        lambda: integration.dispatch(plan, execution_id="exec-dup"),
        "duplicate execution_id",
    )

    assert len(calls) == 1, "the duplicate dispatch never reached the core"
    assert len(integration.tracker._records) == 1


def test_auto_execution_ids_are_unique():
    """Two dispatches without an explicit id get distinct execution records."""
    core, calls, _ = make_spy_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    integration.dispatch(simple_plan(plan_id="plan-1"))
    first = integration.last_execution_id
    integration.dispatch(simple_plan(plan_id="plan-2"))
    second = integration.last_execution_id

    assert first is not None and second is not None
    assert first != second
    assert set(tracker._records) == {first, second}
    assert tracker.get_status(first) == ExecutionStatus.PENDING
    assert tracker.get_status(second) == ExecutionStatus.PENDING


def test_constructor_validation_fail_closed():
    """Invalid integration arguments -> DispatchIntegrationError."""
    core, _, _ = make_spy_core()

    expect_raises(
        DispatchIntegrationError,
        lambda: DispatchIntegration(object()),
        "dispatch_core without dispatch()",
    )
    expect_raises(
        DispatchIntegrationError,
        lambda: DispatchIntegration(core, tracker="tracker"),
        "tracker wrong type",
    )
    expect_raises(
        DispatchIntegrationError,
        lambda: DispatchIntegration(core, stop_signal="signal"),
        "stop_signal wrong type",
    )

    tracker = ExecutionTracker()
    signal = StopSignal(enabled=True)
    integration = DispatchIntegration(core, tracker=tracker, stop_signal=signal)
    assert integration.tracker is tracker
    assert integration.stop_signal is signal


# ---------------------------------------------------------------------------
# Block 4 connector / Block 3 Timed-Burst / without-integration regression
# ---------------------------------------------------------------------------


def test_without_integration_behaviour_unchanged():
    """Existing callers keep passing a raw DispatchCore to the connector."""
    core, calls, sentinel = make_spy_core()
    plan = simple_plan()

    outcome = connect_plan_to_dispatch(plan, core)

    assert outcome["dispatched"] is True
    assert outcome["dispatch_called"] is True
    assert outcome["execution_plan"] is plan
    assert outcome["dispatch_result"] is sentinel
    assert calls == [plan]

    # No stop / tracking coupling is added to the Dispatch Core itself.
    assert not hasattr(core, "stop_signal")
    assert not hasattr(core, "tracker")
    assert not hasattr(core, "record_result")

    # Without an integration, nothing gates repeated dispatches.
    for _ in range(3):
        assert connect_plan_to_dispatch(plan, core)["dispatch_result"] is sentinel
    assert len(calls) == 4


def test_block4_connector_with_integration_end_to_end():
    """EventTrigger -> Planner -> connector -> integration -> DispatchCore."""
    planner = ExecutionPlanner()
    instruction = LogicalOrderInstruction(
        plan_id="plan-b5t4-e2e",
        orders=[
            PlannedOrder(
                order=make_order(),
                account_id="acc-1",
                broker_name="broker-a",
                sequence=0,
            )
        ],
    )

    task2 = connect_trigger_to_planner(
        TradingStateEventTrigger(state=VERIFIED_TRADABLE),
        planner,
        instruction,
        NOW,
    )
    assert task2["fired"] is True
    plan = task2["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    attach_accounts(plan, {"acc-1": make_account("acc-1")})

    core = make_real_core(["broker-a"])
    tracker = ExecutionTracker()
    signal = StopSignal(enabled=True)
    integration = DispatchIntegration(core, tracker=tracker, stop_signal=signal)

    outcome = connect_plan_to_dispatch(plan, integration)

    assert outcome["dispatch_called"] is True
    assert outcome["execution_plan"] is plan
    dispatch_result = outcome["dispatch_result"]
    assert dispatch_result.success is True
    assert dispatch_result.mode == "ALL_PROCESSED"
    assert dispatch_result.sent is False, "still dry-run only"

    exec_id = integration.last_execution_id
    assert exec_id is not None
    assert tracker.get_status(exec_id) == ExecutionStatus.PENDING

    # RESULT PATH: independent recording of the dispatch result.
    assert (
        integration.record_result(exec_id, dispatch_result)
        == ExecutionStatus.REGISTERED
    )
    assert tracker.get_status(exec_id) == ExecutionStatus.REGISTERED
    assert signal.is_active is True, "enabled rule activates on the first success"

    # A blocked trading state builds no plan -> no dispatch, no new record.
    blocked = connect_trigger_to_planner(
        TradingStateEventTrigger(state=VERIFIED_BLOCKED),
        planner,
        instruction,
        NOW,
    )
    assert blocked["fired"] is False
    outcome2 = connect_plan_to_dispatch(blocked["execution_plan"], integration)
    assert outcome2["dispatch_called"] is False
    assert len(tracker._records) == 1


def test_block3_timed_burst_path_never_waits_for_results():
    """Block 3 Timed / Burst moments dispatch without waiting for results."""
    start = datetime(2026, 9, 15, 9, 0, 0)
    timing = DispatchTiming(
        start_time=start,
        end_time=start + timedelta(seconds=3),
        interval=timedelta(seconds=1),
    )
    trigger = TimedDispatchTrigger(timing=timing)
    scheduler = TimedDispatchScheduler(timing=timing)

    moments = scheduler.generate()
    assert len(moments) == 4, "deterministic burst moments (Block 3 unchanged)"
    for moment in moments:
        assert trigger.evaluate(moment) is True
    assert trigger.evaluate(start - timedelta(milliseconds=1)) is False
    assert trigger.evaluate(start + timedelta(seconds=4)) is False

    core, calls, _ = make_spy_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    # The Timed/Burst caller owns the loop; the integration adds no timer.
    for index, _moment in enumerate(moments, start=1):
        integration.dispatch(
            simple_plan(plan_id=f"burst-plan-{index}"),
            execution_id=f"burst-exec-{index}",
        )

    assert len(calls) == 4, "every burst moment dispatched without a result"
    for index in range(1, 5):
        assert (
            tracker.get_status(f"burst-exec-{index}") == ExecutionStatus.PENDING
        )

    # Results arrive later, in a different order.
    integration.record_result("burst-exec-4", ok_result())
    integration.record_result("burst-exec-2", fail_result())
    integration.record_result("burst-exec-1", ok_result())
    integration.record_result("burst-exec-3", ok_result())

    assert tracker.get_status("burst-exec-1") == ExecutionStatus.REGISTERED
    assert tracker.get_status("burst-exec-2") == ExecutionStatus.FAILED
    assert tracker.get_status("burst-exec-3") == ExecutionStatus.REGISTERED
    assert tracker.get_status("burst-exec-4") == ExecutionStatus.REGISTERED


def main():
    tests = [
        # Guard / send path
        test_guard_decision_allow_then_stop,
        test_guard_invalid_signal_type_fail_closed,
        test_default_construction_is_fail_open,
        test_dispatch_allowed_when_signal_inactive,
        test_dispatch_allowed_when_enabled_but_not_activated,
        test_guard_stops_new_dispatch_when_active,
        test_connector_reports_entry_point_for_stopped_dispatch,
        test_stopped_dispatch_does_not_touch_prior_executions,
        # Send path / result path independence
        test_send_path_never_waits_for_results,
        test_results_may_arrive_out_of_order,
        test_late_results_after_stop_are_still_recorded,
        test_stopped_result_cannot_reach_a_prior_execution,
        test_stop_semantics_unchanged_disabled_never_activates,
        test_stop_semantics_unchanged_enabled_failure_then_success,
        # Fail-closed
        test_unknown_execution_id_fail_closed,
        test_invalid_plan_fail_closed,
        test_invalid_execution_id_fail_closed,
        test_duplicate_execution_id_fail_closed,
        test_auto_execution_ids_are_unique,
        test_constructor_validation_fail_closed,
        # Block 4 connector / Block 3 Timed-Burst / without integration
        test_without_integration_behaviour_unchanged,
        test_block4_connector_with_integration_end_to_end,
        test_block3_timed_burst_path_never_waits_for_results,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS  {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {test.__name__}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"  ERROR {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()

    print()
    print("=" * 50)
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    print("=" * 50)

    if failed:
        sys.exit(1)

    print(
        f"\nAll Block 5 Task 4 dispatch integration tests passed. "
        f"({len(tests)} tests)"
    )


if __name__ == "__main__":
    main()