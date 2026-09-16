"""
Block 6 — Task 6.5: Account-Aware Execution Tracking tests.

Architectural principle under test:

    one ExecutionPlan
        -> many orders, each bound to its own account (plan binding)
        -> DispatchCore executes each order through the existing OrderEngine path
        -> each per-order OrderExecutionResult is tracked on its OWN record

An order of one account keeps its own execution record and its own status, so
``REGISTERED`` for the order of Account 1 can never be confused with the
status of the order of Account 2 — not for the same account, not for the same
broker, not for the same symbol.

Rules verified here:

  * The per-order record reuses the EXISTING dispatch execution_id together
    with the order's own plan sequence: no parallel execution id is created
    in ``DispatchIntegration`` (one dispatch = one execution id, as before).
  * ``account_id`` comes ONLY from ``plan.conditions["binding"][sequence]
    ["account_id"]``. There is no fallback to ``plan.accounts[0]``, the
    symbol / ``nsc_id``, the broker, the order index, or a default.
  * A result of one order changes the status of that order ONLY, in any
    arrival order.
  * An invalid / incomplete account binding is fail-closed: nothing is
    registered and nothing is dispatched.
  * The Block 5 dispatch-level path and the Stop Signal semantics are
    unchanged (Stop / Brake policy is Task 6.6), and every dispatch stays
    dry-run (``live=False``).

Proven scenarios (offline, stubs only):

    S1  Two orders + two accounts            -> two independent trackings
    S2  Two orders + one account             -> two independent trackings
    S3  One symbol + two accounts            -> independent
    S4  One broker + two accounts            -> independent
    S5  Changing one status -> the other one is untouched
    S6  Each order result changes only its own order status (arrival order
        is irrelevant)
    S7  Invalid / incomplete account binding -> fail-closed
    S8  Account identity comes only from the binding (no accounts[0] /
        symbol / broker / index fallback)
    S9  No parallel execution id: order records reuse the existing dispatch
        execution id; two dispatches stay independent
    S10 Dry-run + Stop Signal untouched by per-order tracking

No network, no real broker, no real order.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import Mock

from core.block5_task3 import StopSignal
from core.block5_task4 import (
    STOPPED_MODE,
    DispatchIntegration,
    DispatchIntegrationError,
    bound_account_id,
)
from core.dispatch_core import DispatchCore
from core.dispatch_contracts import DispatchResult
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
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACC1 = "ACC-1"
ACC2 = "ACC-2"
DECOY = "ACC-DECOY"
BROKER_A = "broker-a"
BROKER_B = "broker-b"
SYM_A = "SYM-A"
SYM_B = "SYM-B"
SYM_C = "SYM-C"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_order(nsc_id=SYM_A, side=BUY, price=150, quantity=10):
    return Order(nsc_id=nsc_id, side=side, price=price, quantity=quantity)


def make_account(account_id):
    return Account(
        account_id=account_id,
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


def build_plan(orders, account_ids, broker_names, plan_id="t65-plan"):
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


def attach_accounts(plan, accounts_by_id):
    """Attach resolved Account objects in the order of the plan binding."""
    seen = []
    for seq in plan.execution_order:
        acc_id = plan.conditions["binding"][seq]["account_id"]
        if acc_id not in seen:
            seen.append(acc_id)
    plan.accounts = [accounts_by_id[a] for a in seen]
    return plan


def _mock_broker(name):
    broker = Mock()
    broker.name = name
    return broker


def _mock_provider(nsc_id=SYM_A):
    provider = Mock()
    provider.get_instrument.return_value = (
        Mock(),
        BrokerInstrument(nsc_id=nsc_id),
    )
    return provider


def make_broker_manager(broker_names):
    available = {name: _mock_broker(name) for name in broker_names}
    providers = {name: _mock_provider() for name in broker_names}

    manager = Mock()
    manager.get.side_effect = lambda name, _a=available: _a[name]
    manager.get_instrument_provider.side_effect = (
        lambda name, _p=providers: _p[name]
    )
    return manager


def ok_order_result(order, broker_name=None):
    """A real per-order ``OrderExecutionResult`` for a successful order."""
    return OrderExecutionResult(
        success=True,
        sent=False,
        mode="READY",
        order=order,
        broker_name=broker_name,
    )


def blocked_order_result(order, broker_name=None):
    """A real per-order ``OrderExecutionResult`` for a blocked order."""
    return OrderExecutionResult(
        success=False,
        sent=False,
        mode="BLOCKED",
        order=order,
        broker_name=broker_name,
    )


def make_core(result_fn=None, broker_names=(BROKER_A, BROKER_B)):
    """Real DispatchCore with the broker/provider/OrderEngine boundary mocked.

    ``result_fn(order, account)`` returns the per-order ``OrderExecutionResult``
    the engine path produces for that order (default: a successful one).
    Returns ``(core, calls)``; each call records the order, its account,
    ``live`` and the produced result.
    """
    core = DispatchCore()
    core.broker_manager = make_broker_manager(list(broker_names))
    calls = []

    def fake_execute(broker, provider, ins_code, order, account, live):
        result = (
            result_fn(order, account)
            if result_fn is not None
            else ok_order_result(order)
        )
        calls.append(
            {
                "broker": broker,
                "order": order,
                "account": account,
                "live": live,
                "result": result,
            }
        )
        return result

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)
    return core, calls


def sequence_of(plan, order_obj):
    """The plan sequence of ``order_obj`` (planner sorts orders ascending)."""
    index = next(
        i for i, candidate in enumerate(plan.orders) if candidate is order_obj
    )
    return sorted(plan.execution_order)[index]


def results_by_sequence(plan, calls):
    """Map the per-order results of the DispatchCore path to their sequence."""
    mapping = {}
    for call in calls:
        mapping[sequence_of(plan, call["order"])] = call["result"]
    return mapping


def record_all(integration, execution_id, plan, calls):
    """Feed every per-order result of the DispatchCore path to the tracker."""
    statuses = {}
    for sequence, result in results_by_sequence(plan, calls).items():
        statuses[sequence] = integration.record_order_result(
            execution_id, sequence, result
        )
    return statuses


def statuses(integration, execution_id, sequences):
    """Current per-order statuses of one dispatch execution."""
    return {
        sequence: integration.tracker.get_order_status(execution_id, sequence)
        for sequence in sequences
    }


def accounts_of(integration, execution_id, sequences):
    """Account identity tracked for each order of one execution."""
    return {
        sequence: integration.tracker.get_order_record(
            execution_id, sequence
        ).account_id
        for sequence in sequences
    }


def snapshot(integration, execution_id, sequences):
    """Identity snapshot of the per-order records (to prove no mutation)."""
    return {
        sequence: integration.tracker.get_order_record(execution_id, sequence)
        for sequence in sequences
    }


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
# S1 — Two orders + two accounts -> two independent trackings
# ---------------------------------------------------------------------------


def test_s1_two_orders_two_accounts():
    print("S1: order@ACC-1/broker-a and order@ACC-2/broker-b -> two trackings")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)

    plan = build_plan([order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_B])
    attach_accounts(
        plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )

    core, calls = make_core(
        result_fn=lambda order, account: (
            ok_order_result(order)
            if order is order_a
            else blocked_order_result(order)
        )
    )
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    integration.dispatch(plan, execution_id="exec-s1")
    results = record_all(integration, "exec-s1", plan, calls)

    assert len(calls) == 2, "one engine call per order"
    assert all(call["live"] is False for call in calls), "dry-run only"

    # ONE execution id for the dispatch (no parallel execution ids).
    assert set(tracker._records) == {"exec-s1"}
    # TWO independent order records, one per order/account.
    assert set(tracker.order_records("exec-s1")) == {0, 1}
    assert accounts_of(integration, "exec-s1", (0, 1)) == {0: ACC1, 1: ACC2}

    # Each per-order result reached exactly its own order record.
    assert results == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.FAILED,
    }
    assert statuses(integration, "exec-s1", (0, 1)) == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.FAILED,
    }

    # The dispatch-level record of Block 5 is NOT touched by per-order results.
    assert tracker.get_status("exec-s1") == ExecutionStatus.PENDING
    print()


# ---------------------------------------------------------------------------
# S2 — Two orders + ONE account -> two independent trackings
# ---------------------------------------------------------------------------


def test_s2_two_orders_one_account():
    print("S2: two orders of ACC-1 -> two independent trackings")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=9)

    plan = build_plan([order_a, order_b], [ACC1, ACC1], [BROKER_A, BROKER_A])
    attach_accounts(plan, {ACC1: make_account(ACC1)})

    core, calls = make_core(
        broker_names=(BROKER_A,),
        result_fn=lambda order, account: (
            ok_order_result(order)
            if order is order_b
            else blocked_order_result(order)
        ),
    )
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    integration.dispatch(plan, execution_id="exec-s2")
    record_all(integration, "exec-s2", plan, calls)

    # Two orders of the SAME account still own two separate records...
    assert set(tracker.order_records("exec-s2")) == {0, 1}
    record_0 = tracker.get_order_record("exec-s2", 0)
    record_1 = tracker.get_order_record("exec-s2", 1)
    assert record_0 is not record_1
    assert (record_0.account_id, record_1.account_id) == (ACC1, ACC1)

    # ...and two independent statuses.
    assert statuses(integration, "exec-s2", (0, 1)) == {
        0: ExecutionStatus.FAILED,
        1: ExecutionStatus.REGISTERED,
    }
    print()


# ---------------------------------------------------------------------------
# S3 — ONE symbol, two accounts -> independent
# ---------------------------------------------------------------------------


def test_s3_one_symbol_two_accounts():
    print("S3: same symbol SYM-A on ACC-1 and ACC-2 -> independent")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_A, price=250, quantity=3)  # SAME symbol

    plan = build_plan([order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_B])
    attach_accounts(
        plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )

    core, calls = make_core(
        result_fn=lambda order, account: (
            ok_order_result(order)
            if order is order_b
            else blocked_order_result(order)
        )
    )
    integration = DispatchIntegration(core, tracker=ExecutionTracker())

    integration.dispatch(plan, execution_id="exec-s3")
    record_all(integration, "exec-s3", plan, calls)

    assert plan.orders[0].nsc_id == plan.orders[1].nsc_id == SYM_A
    assert len(calls) == 2, "both orders dispatched despite the shared symbol"

    tracked = accounts_of(integration, "exec-s3", (0, 1))
    assert tracked == {0: ACC1, 1: ACC2}, "binding account per order"
    # The account identity is NEVER the symbol.
    assert set(tracked.values()).isdisjoint({SYM_A, SYM_B, SYM_C})

    assert statuses(integration, "exec-s3", (0, 1)) == {
        0: ExecutionStatus.FAILED,
        1: ExecutionStatus.REGISTERED,
    }
    print()


# ---------------------------------------------------------------------------
# S4 — ONE broker, two accounts -> independent
# ---------------------------------------------------------------------------


def test_s4_one_broker_two_accounts():
    print("S4: two accounts on the same broker-a -> independent")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)

    plan = build_plan([order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_A])
    attach_accounts(
        plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )

    core, calls = make_core(
        broker_names=(BROKER_A,),
        result_fn=lambda order, account: (
            ok_order_result(order)
            if order is order_a
            else blocked_order_result(order)
        ),
    )
    integration = DispatchIntegration(core, tracker=ExecutionTracker())

    integration.dispatch(plan, execution_id="exec-s4")
    record_all(integration, "exec-s4", plan, calls)

    assert plan.account_routes == {ACC1: BROKER_A, ACC2: BROKER_A}
    assert len(calls) == 2
    assert {call["broker"].name for call in calls} == {BROKER_A}

    tracked = accounts_of(integration, "exec-s4", (0, 1))
    assert tracked == {0: ACC1, 1: ACC2}
    # The account identity is NEVER the broker.
    assert set(tracked.values()).isdisjoint({BROKER_A, BROKER_B})

    assert statuses(integration, "exec-s4", (0, 1)) == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.FAILED,
    }
    print()


# ---------------------------------------------------------------------------
# S5 — Changing one status never touches the other
# ---------------------------------------------------------------------------


def test_s5_status_isolation():
    print("S5: changing one order status never touches the other")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)

    plan = build_plan([order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_B])
    attach_accounts(
        plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )

    core, calls = make_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    integration.dispatch(plan, execution_id="exec-s5")
    record_all(integration, "exec-s5", plan, calls)

    assert statuses(integration, "exec-s5", (0, 1)) == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.REGISTERED,
    }

    # --- change ONLY order 0 ---------------------------------------------
    before_1 = tracker.get_order_record("exec-s5", 1)
    tracker.update_order_status("exec-s5", 0, ExecutionStatus.CANCELLED)

    assert tracker.get_order_status("exec-s5", 0) == ExecutionStatus.CANCELLED
    assert tracker.get_order_status("exec-s5", 1) == ExecutionStatus.REGISTERED
    assert tracker.get_order_record("exec-s5", 1) is before_1, (
        "the other order record was not even replaced"
    )
    assert accounts_of(integration, "exec-s5", (0, 1)) == {0: ACC1, 1: ACC2}

    # --- change ONLY order 1 (through the per-order result path) ---------
    integration.record_order_result(
        "exec-s5", 1, blocked_order_result(order_b)
    )

    assert statuses(integration, "exec-s5", (0, 1)) == {
        0: ExecutionStatus.CANCELLED,
        1: ExecutionStatus.FAILED,
    }
    # The dispatch-level Block 5 record is untouched by any per-order change.
    assert tracker.get_status("exec-s5") == ExecutionStatus.PENDING
    print()


# ---------------------------------------------------------------------------
# S6 — Each order result changes only its own order status
# ---------------------------------------------------------------------------


def test_s6_each_result_only_touches_its_own_order():
    print("S6: per-order results arriving out of order touch only their own order")
    order_a = make_order(SYM_A, price=100, quantity=5)  # sequence 0 -> ACC-1
    order_b = make_order(SYM_B, price=200, quantity=7)  # sequence 1 -> ACC-2
    order_c = make_order(SYM_C, price=300, quantity=9)  # sequence 2 -> ACC-1

    plan = build_plan(
        [order_a, order_b, order_c],
        [ACC1, ACC2, ACC1],
        [BROKER_A, BROKER_B, BROKER_A],
    )
    attach_accounts(
        plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )

    core, calls = make_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    integration.dispatch(plan, execution_id="exec-s6")

    results = results_by_sequence(plan, calls)
    assert set(results) == {0, 1, 2}, "one result per order"
    assert accounts_of(integration, "exec-s6", (0, 1, 2)) == {
        0: ACC1,
        1: ACC2,
        2: ACC1,
    }, "each order keeps its own bound account"

    # Failed result for the middle order; the others succeed.
    results[1] = blocked_order_result(order_b)

    # Results arrive out of order: 2, then 0, then 1.
    expected = {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.FAILED,
        2: ExecutionStatus.REGISTERED,
    }
    for sequence in (2, 0, 1):
        others = [s for s in (0, 1, 2) if s != sequence]
        before = snapshot(integration, "exec-s6", others)
        before_statuses = {s: before[s].status for s in others}

        integration.record_order_result(
            "exec-s6", sequence, results[sequence]
        )

        after = snapshot(integration, "exec-s6", others)
        for other in others:
            assert after[other] is before[other], (
                "the record of another order must not be replaced"
            )
            assert after[other].status == before_statuses[other], (
                "the status of another order must not change"
            )
            assert after[other].account_id == before[other].account_id

        assert tracker.get_order_status("exec-s6", sequence) == expected[sequence]

    assert statuses(integration, "exec-s6", (0, 1, 2)) == expected
    # Two orders of the same account (0 and 2) still hold distinct records.
    assert (
        tracker.get_order_record("exec-s6", 0)
        is not tracker.get_order_record("exec-s6", 2)
    )
    print()


# ---------------------------------------------------------------------------
# S7 — Invalid / incomplete account binding -> fail-closed
# ---------------------------------------------------------------------------


def _fresh_s7_single_order():
    """One-order plan + real core + integration, all freshly built."""
    order = make_order(SYM_A, price=100, quantity=5)
    plan = build_plan([order], [ACC1], [BROKER_A])
    attach_accounts(plan, {ACC1: make_account(ACC1)})
    core, calls = make_core(broker_names=(BROKER_A,))
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)
    return order, plan, calls, tracker, integration


def test_s7_invalid_account_binding_fails_closed():
    print("S7: invalid / incomplete Account binding -> fail-closed")

    cases = [
        (
            "binding key missing",
            lambda plan: plan.conditions.pop("binding"),
        ),
        (
            "conditions not a mapping",
            lambda plan: setattr(plan, "conditions", []),
        ),
        (
            "binding not a mapping",
            lambda plan: plan.conditions.__setitem__("binding", "nope"),
        ),
        (
            "sequence not bound",
            lambda plan: plan.conditions["binding"].pop(0),
        ),
        (
            "binding entry not a mapping",
            lambda plan: plan.conditions["binding"].__setitem__(0, "acc-1"),
        ),
        (
            "account_id missing",
            lambda plan: plan.conditions["binding"][0].pop("account_id"),
        ),
        (
            "account_id empty",
            lambda plan: plan.conditions["binding"][0].__setitem__(
                "account_id", ""
            ),
        ),
        (
            "account_id blank",
            lambda plan: plan.conditions["binding"][0].__setitem__(
                "account_id", "   "
            ),
        ),
        (
            "account_id None",
            lambda plan: plan.conditions["binding"][0].__setitem__(
                "account_id", None
            ),
        ),
        (
            "account_id non-string",
            lambda plan: plan.conditions["binding"][0].__setitem__(
                "account_id", 123
            ),
        ),
    ]

    for label, mutate in cases:
        _, plan, calls, tracker, integration = _fresh_s7_single_order()
        mutate(plan)

        expect_raises(
            DispatchIntegrationError,
            lambda p=plan, i=integration: i.dispatch(
                p, execution_id="exec-s7"
            ),
            f"S7 {label}: dispatch",
        )

        assert calls == [], f"S7 {label}: nothing may be dispatched"
        assert tracker._records == {}, f"S7 {label}: no dispatch record"
        assert tracker._order_records == {}, f"S7 {label}: no order record"
        assert integration.last_execution_id is None, (
            f"S7 {label}: no execution id may be exposed"
        )

    # --- one bad binding among two orders blocks the WHOLE plan ----------
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)
    plan = build_plan([order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_B])
    attach_accounts(
        plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )
    plan.conditions["binding"][1]["account_id"] = None

    core, calls = make_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    expect_raises(
        DispatchIntegrationError,
        lambda: integration.dispatch(plan, execution_id="exec-s7-partial"),
        "S7 partial binding: dispatch",
    )
    assert calls == [], "S7 partial binding: no order dispatched"
    assert tracker._records == {}, "S7 partial binding: no dispatch record"
    assert tracker._order_records == {}, "S7 partial binding: no order record"

    # --- the resolver itself never falls back ----------------------------
    ok_plan = build_plan([make_order(SYM_A)], [ACC1], [BROKER_A])
    attach_accounts(ok_plan, {ACC1: make_account(ACC1)})
    assert bound_account_id(ok_plan, 0) == ACC1

    ok_plan.conditions["binding"][0]["account_id"] = ""
    expect_raises(
        DispatchIntegrationError,
        lambda: bound_account_id(ok_plan, 0),
        "S7 resolver: blank binding is never replaced by plan.accounts[0]",
    )
    expect_raises(
        DispatchIntegrationError,
        lambda: bound_account_id(ok_plan, 5),
        "S7 resolver: unbound sequence",
    )
    print()


# ---------------------------------------------------------------------------
# S7b — The per-order result path is fail-closed too
# ---------------------------------------------------------------------------


def test_s7b_result_path_fails_closed():
    print("S7b: unknown execution / order, wrong result type -> fail-closed")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)

    plan = build_plan([order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_B])
    attach_accounts(
        plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )

    core, calls = make_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)
    integration.dispatch(plan, execution_id="exec-s7b")

    before = snapshot(integration, "exec-s7b", (0, 1))

    expect_raises(
        ExecutionTrackerError,
        lambda: integration.record_order_result(
            "never-issued", 0, ok_order_result(order_a)
        ),
        "S7b unknown execution",
    )
    expect_raises(
        ExecutionTrackerError,
        lambda: integration.record_order_result(
            "exec-s7b", 7, ok_order_result(order_a)
        ),
        "S7b unknown order sequence",
    )
    expect_raises(
        ExecutionTrackerError,
        lambda: integration.record_order_result(
            "exec-s7b", "0", ok_order_result(order_a)
        ),
        "S7b non-integer sequence",
    )
    expect_raises(
        ExecutionTrackerError,
        lambda: integration.record_order_result(
            None, 0, ok_order_result(order_a)
        ),
        "S7b invalid execution id",
    )

    wrong_results = (
        None,
        "READY",
        DispatchResult(success=True, sent=False, mode="ALL_PROCESSED"),
        Mock(),
    )
    for bad in wrong_results:
        expect_raises(
            DispatchIntegrationError,
            lambda b=bad: integration.record_order_result("exec-s7b", 0, b),
            f"S7b wrong result type {bad!r}",
        )

    # Nothing was recorded and no status moved.
    after = snapshot(integration, "exec-s7b", (0, 1))
    assert after == before
    assert all(
        tracker.get_order_status("exec-s7b", s) == ExecutionStatus.PENDING
        for s in (0, 1)
    )
    assert tracker.get_status("exec-s7b") == ExecutionStatus.PENDING

    # The tracker itself rejects an order re-bound to another account.
    expect_raises(
        ExecutionTrackerError,
        lambda: tracker.register_order("exec-s7b", 0, ACC2),
        "S7b re-binding order 0 to another account",
    )
    expect_raises(
        ExecutionTrackerError,
        lambda: tracker.register_order("exec-s7b", 0, ACC1),
        "S7b duplicate order 0",
    )
    expect_raises(
        ExecutionTrackerError,
        lambda: tracker.register_order("never-issued", 0, ACC1),
        "S7b order under an unregistered execution",
    )
    expect_raises(
        ExecutionTrackerError,
        lambda: tracker.register_order("exec-s7b", 5, "  "),
        "S7b blank account identity",
    )
    expect_raises(
        ExecutionTrackerError,
        lambda: tracker.register_order("exec-s7b", -1, ACC1),
        "S7b negative sequence",
    )
    # ...and the two real records survived all of that untouched.
    assert tracker.get_order_record("exec-s7b", 0) is before[0]
    assert tracker.get_order_record("exec-s7b", 1) is before[1]
    assert accounts_of(integration, "exec-s7b", (0, 1)) == {0: ACC1, 1: ACC2}

    # The good path still works after the failed attempts.
    assert (
        integration.record_order_result("exec-s7b", 0, ok_order_result(order_a))
        == ExecutionStatus.REGISTERED
    )
    assert tracker.get_order_status("exec-s7b", 1) == ExecutionStatus.PENDING

    # A dispatch bypassed by the Stop Signal has no execution and no orders.
    stopped_integration = DispatchIntegration(
        core, tracker=ExecutionTracker(), stop_signal=StopSignal(enabled=True)
    )
    stopped_integration.stop_signal.observe(
        DispatchResult(success=True, sent=False, mode="ALL_PROCESSED")
    )
    stopped_result = stopped_integration.dispatch(plan)
    assert stopped_result.mode == STOPPED_MODE
    assert stopped_integration.last_execution_id is None
    assert stopped_integration.tracker._order_records == {}
    expect_raises(
        ExecutionTrackerError,
        lambda: stopped_integration.record_order_result(
            None, 0, ok_order_result(order_a)
        ),
        "S7b no order result for a bypassed dispatch",
    )
    print()


# ---------------------------------------------------------------------------
# S8 — Account identity comes ONLY from the binding
# ---------------------------------------------------------------------------


def test_s8_account_identity_comes_only_from_binding():
    print("S8: decoy accounts[0] never becomes the tracked account")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)

    # Binding: order 0 -> ACC-2, order 1 -> ACC-1 (NOT the list order).
    plan = build_plan([order_a, order_b], [ACC2, ACC1], [BROKER_A, BROKER_B])
    assert plan.account_routes == {ACC2: BROKER_A, ACC1: BROKER_B}

    # A decoy account sits FIRST in plan.accounts, i.e. accounts[0].
    plan.accounts = [
        make_account(DECOY),
        make_account(ACC1),
        make_account(ACC2),
    ]

    core, calls = make_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    integration.dispatch(plan, execution_id="exec-s8")

    tracked = accounts_of(integration, "exec-s8", (0, 1))
    assert tracked == {0: ACC2, 1: ACC1}, (
        "each order keeps the account of ITS OWN binding"
    )
    assert DECOY not in set(tracked.values()), "accounts[0] is never used"
    assert set(tracked.values()).isdisjoint({SYM_A, SYM_B, BROKER_A, BROKER_B})

    # The dispatch itself used the bound Account objects (no re-selection).
    assert {call["account"].account_id for call in calls} == {ACC1, ACC2}
    assert set(tracked.values()) == {
        plan.conditions["binding"][s]["account_id"] for s in (0, 1)
    }
    print()


# ---------------------------------------------------------------------------
# S9 — No parallel execution id: the existing execution id is reused
# ---------------------------------------------------------------------------


def test_s9_no_parallel_execution_id():
    print("S9: order records reuse the existing execution id (no parallel ids)")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)

    plan_1 = build_plan([order_a], [ACC1], [BROKER_A], plan_id="p1")
    plan_2 = build_plan(
        [order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_B], plan_id="p2"
    )
    attach_accounts(plan_1, {ACC1: make_account(ACC1)})
    attach_accounts(
        plan_2, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )

    core, calls = make_core()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(core, tracker=tracker)

    integration.dispatch(plan_1, execution_id="exec-1")
    assert set(tracker._records) == {"exec-1"}, "one dispatch = one execution id"
    assert set(tracker._order_records) == {("exec-1", 0)}

    integration.dispatch(plan_2, execution_id="exec-2")
    # Exactly the caller-provided (existing) execution ids: nothing extra.
    assert set(tracker._records) == {"exec-1", "exec-2"}
    assert set(tracker._order_records) == {
        ("exec-1", 0),
        ("exec-2", 0),
        ("exec-2", 1),
    }

    # The same order object in two executions keeps two independent records.
    record_a1 = tracker.get_order_record("exec-1", 0)
    record_a2 = tracker.get_order_record("exec-2", 0)
    assert record_a1 is not record_a2
    assert record_a1.execution_id == "exec-1"
    assert record_a2.execution_id == "exec-2"
    assert record_a1.sequence == record_a2.sequence == 0

    # A result of one execution never touches the other execution.
    integration.record_order_result(
        "exec-2", 0, blocked_order_result(order_a)
    )
    assert tracker.get_order_status("exec-2", 0) == ExecutionStatus.FAILED
    assert tracker.get_order_status("exec-1", 0) == ExecutionStatus.PENDING

    # Auto-generated ids stay the Block 5 scheme: ONE id per dispatch.
    integration.dispatch(plan_1)
    auto = integration.last_execution_id
    assert auto is not None and auto.startswith("exec-")
    assert set(tracker._records) == {"exec-1", "exec-2", auto}
    assert set(tracker._order_records) == {
        ("exec-1", 0),
        ("exec-2", 0),
        ("exec-2", 1),
        (auto, 0),
    }
    assert tracker.get_order_status(auto, 0) == ExecutionStatus.PENDING
    print()


# ---------------------------------------------------------------------------
# S10 — Dry-run + Stop Signal untouched by per-order tracking
# ---------------------------------------------------------------------------


def test_s10_dry_run_and_stop_signal_untouched():
    print("S10: per-order tracking is dry-run and never drives the Stop Signal")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)

    plan = build_plan([order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_B])
    attach_accounts(
        plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )

    core, calls = make_core()
    tracker = ExecutionTracker()
    signal = StopSignal(enabled=True)  # would activate on the first success
    integration = DispatchIntegration(core, tracker=tracker, stop_signal=signal)

    # Two dispatches are issued back-to-back: per-order tracking never gates
    # or waits for anything.
    integration.dispatch(plan, execution_id="exec-s10-1")
    integration.dispatch(plan, execution_id="exec-s10-2")

    assert len(calls) == 4, "2 orders x 2 dispatches"
    assert all(call["live"] is False for call in calls), "dry-run only"
    assert core.live_trading_enabled is False

    first_batch = calls[:2]
    assert all(call["result"].success for call in first_batch)
    record_all(integration, "exec-s10-1", plan, first_batch)

    # Per-order successes must NOT activate the Stop Signal (Task 6.6 owns
    # the stop / brake policy; Task 6.5 is pure tracking).
    assert signal.is_active is False
    assert integration.is_stopped is False
    assert statuses(integration, "exec-s10-1", (0, 1)) == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.REGISTERED,
    }

    # The Block 5 dispatch-level path is unchanged: a successful dispatch
    # result still activates the signal.
    assert (
        integration.record_result(
            "exec-s10-1",
            DispatchResult(success=True, sent=False, mode="ALL_PROCESSED"),
        )
        == ExecutionStatus.REGISTERED
    )
    assert signal.is_active is True

    # ...and a later dispatch is then bypassed: no execution, no order records.
    order_records_before = dict(tracker._order_records)
    stopped = integration.dispatch(plan, execution_id="exec-s10-3")

    assert stopped.mode == STOPPED_MODE
    assert ("exec-s10-3", 0) not in tracker._order_records
    assert ("exec-s10-3", 1) not in tracker._order_records
    assert tracker._order_records == order_records_before
    assert "exec-s10-3" not in tracker._records

    # The already tracked orders keep their own statuses.
    assert statuses(integration, "exec-s10-1", (0, 1)) == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.REGISTERED,
    }
    assert statuses(integration, "exec-s10-2", (0, 1)) == {
        0: ExecutionStatus.PENDING,
        1: ExecutionStatus.PENDING,
    }
    assert tracker.get_status("exec-s10-2") == ExecutionStatus.PENDING
    print()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main():
    tests = [
        test_s1_two_orders_two_accounts,
        test_s2_two_orders_one_account,
        test_s3_one_symbol_two_accounts,
        test_s4_one_broker_two_accounts,
        test_s5_status_isolation,
        test_s6_each_result_only_touches_its_own_order,
        test_s7_invalid_account_binding_fails_closed,
        test_s7b_result_path_fails_closed,
        test_s8_account_identity_comes_only_from_binding,
        test_s9_no_parallel_execution_id,
        test_s10_dry_run_and_stop_signal_untouched,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {test.__name__}: {exc}")
        except Exception:
            failed += 1
            print(f"  ERROR {test.__name__}")
            import traceback

            traceback.print_exc()

    print()
    print("=" * 50)
    print(f"SCENARIOS PASSED: {passed}")
    print(f"SCENARIOS FAILED: {failed}")
    print("=" * 50)

    if failed:
        sys.exit(1)

    print(
        f"\nAll Block 6 Task 5 Account-Aware Tracking tests passed. "
        f"({len(tests)} scenarios)"
    )


if __name__ == "__main__":
    main()