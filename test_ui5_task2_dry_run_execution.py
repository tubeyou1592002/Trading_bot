"""
test_ui5_task2_dry_run_execution.py

UI-5 Task 2 — Controlled Dry-Run Execution tests (fully offline).

The Test action (UI-5 Task 1 button) drives its pending ``QueueEntry``
objects through the EXISTING execution chain exactly once, stays strictly
dry-run (``live=False``), and never touches a real broker / the network.

Contract coverage:

    Runner (``ui.test_runner.TestRunner``, real chain against a test-double
    Dispatch Core, never a real broker):
      Test 1  — an empty selection fails closed (ValueError).
      Test 2  — mixed account or mixed broker entries fail closed
                (identity comes from the entries; no grouping/splitting).
      Test 3  — a run returns the bridge's exact triple
                ``(plan, execution_id, result)``; ``execution_id`` is the
                integration's registered id, never ``plan.plan_id``.
      Test 4  — exactly one dispatch per Test action; the runner builds no
                new DispatchCore/OrderEngine/BrokerManager itself.
      Test 5  — queue entries keep their exact identity after a run.
      Test 6  — a second Test action is a second, distinct execution.
      Test 7  — account/broker identity flows from the entries into the
                plan binding (no fallback inference).
      Test 7b — the runner rejects a missing Account (fail-closed).
      Test 7c — the runner rejects an Account whose account_id does not
                match the entries (fail-closed).
      Test 7d — the runner builds the EXISTING plan-builder output and
                attaches the supplied REAL Account object to
                ``plan.accounts``; the existing DispatchIntegration.dispatch
                is the single boundary that runs it.
      Test 8  — with a real DispatchCore, an Account that does not match
                the entries is still rejected fail-closed before anything
                is dispatched (never sent, never enabled live).
      Test 8b — POSITIVE regression: the CORRECTED production TestRunner
                path (no plan-builder patch, no injected Account) drives a
                valid order from the real UI AccountRecord through the real
                DispatchCore / real OrderEngine (real M6-A … M6-E) all the
                way in Dry-Run mode: the effective envelope reaches the
                broker boundary with live=False and exactly one dry-run
                ``place_order(order, live=False)`` is the sole broker call.
      Test 8c — NEGATIVE real-core regression: a valid-looking BUY order
                whose account carries no balance (the UI AccountStore's
                identity-only Account, verbatim) is BLOCKED fail-closed by
                the real M6-C gate — never sent, live stays False.

    Page wiring (``OrderConfigurationPage``, pytest + QApplication):
      Test 9  — with no runner wired, the Test toggle is a pure UI action
                (Task 1 behavior; nothing is dispatched).
      Test 10 — the OFF->ON Test transition runs exactly once, with the exact
                pending entry objects.
      Test 11 — the ON->OFF transition never runs.
      Test 12 — a later OFF->ON transition runs again exactly once.
      Test 13 — refresh / render / navigation / construct paths never run.
      Test 14 — an empty queue never reaches the runner.
      Test 15 — a failing run stays fail-closed: no retry, queue untouched,
                error surfaced.
      Test 16 — a successful run stores the result contract for Task 3.
      Test 16b — the page obtains the ACTIVE AccountRecord's existing
                Account and hands it to the runner for the pass (no
                inference, no broker/network resolution).
      Test 16c — a queue whose entries do not match the active account /
                broker never reaches the runner (fail-closed).

    Offline subprocess:
      Test 17 — the full Test action (UI click -> runner -> chain) performs
                no network / broker operation and issues exactly one
                dispatch.

Run:
    pytest -q test_ui5_task2_dry_run_execution.py
"""

import os
import subprocess
import sys

import pytest

from PySide6.QtWidgets import QApplication

from core.block5_task4 import DispatchIntegration
from core.dispatch_contracts import DispatchResult, ExecutionPlan
from core.dispatch_core import DispatchCore
from core.execution_tracker import ExecutionStatus
from core.order_queue import OrderQueue
from core.simulation_harness import (
    SimulationBroker,
    SimulationHarness,
    make_simulation_order,
)
from models.instrument import Instrument
from models.order import BUY, SELL, Order

from ui.account_store import AccountStore
from ui.main_window import MainWindow
from ui.order_configuration_page import OrderConfigurationPage
from ui.test_runner import TestRunner


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture(scope="module")
def qapp():
    """Reuse the process-wide QApplication if one exists, else create one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def store():
    return AccountStore()


# ---------------------------------------------------------------------------
# Shared doubles and helpers
# ---------------------------------------------------------------------------


def make_order(nsc_id="IRO1TEST0001", price=150, quantity=10):
    return Order(nsc_id=nsc_id, side=BUY, price=price, quantity=quantity)


def enqueue(queue, orders, account_id="ACC-001", broker_name="\u0622\u06af\u0627\u0647"):
    return [
        queue.enqueue(order, account_id=account_id, broker_name=broker_name)
        for order in orders
    ]


def make_queue_and_entries(orders, account_id="ACC-001", broker_name="\u0622\u06af\u0627\u0647"):
    queue = OrderQueue()
    for order in orders:
        queue.enqueue(order, account_id=account_id, broker_name=broker_name)
    return queue, queue.list_pending()


def make_account_record(account_id="ACC-001", broker_name="\u0622\u06af\u0627\u0647"):
    """
    Build the EXISTING UI account state: the active AccountRecord of an
    ``AccountStore``. ``runner.run(...)`` is always supplied with
    ``record.account`` — the store's real ``Account`` object (identity
    only; the UI-2.1 store keeps no balances), never a fabricated one.
    """
    store = AccountStore()
    store.add(account_id, broker_name)
    store.set_active(account_id)
    return store.get(account_id)


class FakeDispatchCore:
    """Test double for the Block 2 dispatch entry point (never a broker).

    Records every dispatch and returns a realistic dry-run ``DispatchResult``.
    """

    def __init__(self):
        self.calls = 0
        self.plans = []

    def dispatch(self, plan: ExecutionPlan) -> DispatchResult:
        self.calls += 1
        self.plans.append(plan)
        return DispatchResult(
            success=True,
            sent=False,
            mode="ALL_PROCESSED",
            message="fake dispatch: all processed (dry-run)",
            broker_name=None,
            order_count=len(plan.orders),
            trace_id="trace-ui5-task2",
        )


class StubRunner:
    """Duck-typed runner for page-wiring tests (no Core access at all)."""

    def __init__(self):
        self.calls = 0
        self.captured = []
        self.captured_accounts = []

    def run(self, entries, account=None):
        self.calls += 1
        self.captured.append(list(entries))
        self.captured_accounts.append(account)
        return (
            "stub-plan-id",
            "stub-exec-id",
            DispatchResult(
                success=True,
                sent=False,
                mode="ALL_PROCESSED",
                message="stub dry-run",
                order_count=len(entries),
            ),
        )


def make_failing_runner(exc):
    class _FailingRunner:
        def __init__(self, error):
            self.error = error
            self.calls = 0

        def run(self, entries, account=None):
            self.calls += 1
            raise self.error

    return _FailingRunner(exc)


def _make_valid_page(qapp, store, queue, runner_factory=None):
    """Build a page whose Test conditions are fully valid (enabled)."""
    store.add("ACC-001", "\u0622\u06af\u0627\u0647")
    store.set_active("ACC-001")
    page = OrderConfigurationPage(store, order_queue=queue)
    if runner_factory is not None:
        page.set_test_runner_factory(runner_factory)
    page.config.select_instrument(
        Instrument(symbol="\u0622\u06a9\u0648", name="\u0622\u06a9\u0648", ins_code="1")
    )
    order = make_order(nsc_id="NSC-1")
    queue.enqueue(order, account_id="ACC-001", broker_name="\u0622\u06af\u0627\u0647")
    page._refresh_test_button_state()
    assert page.test_button.isEnabled()
    return page, order


# ===========================================================================
# Runner — real chain against a test-double Dispatch Core
# ===========================================================================


def test_1_runner_empty_selection_fails_closed():
    runner = TestRunner(dispatch_core=FakeDispatchCore())
    with pytest.raises(ValueError):
        runner.run([])


def test_2_runner_rejects_mixed_account_and_mixed_broker_entries():
    queue, entries = make_queue_and_entries([make_order(), make_order()])
    queue2 = OrderQueue()
    queue2.enqueue(make_order(), account_id="ACC-002", broker_name="\u0622\u06af\u0627\u0647")
    other = queue2.list_pending()[0]

    runner = TestRunner(dispatch_core=FakeDispatchCore())
    account = make_account_record().account
    with pytest.raises(ValueError):
        runner.run([entries[0], other], account=account)


def test_3_runner_returns_bridge_triple(qapp):
    fake = FakeDispatchCore()
    runner = TestRunner(dispatch_core=fake)
    queue, entries = make_queue_and_entries([make_order()])
    account = make_account_record().account

    plan, execution_id, result = runner.run(entries, account=account)

    assert isinstance(plan, ExecutionPlan)
    assert plan.plan_id.startswith("ui5-test-")
    assert isinstance(execution_id, str) and execution_id
    assert isinstance(result, DispatchResult)
    assert result.success is True
    # execution id is the integration's registered one, never plan.plan_id
    assert execution_id != plan.plan_id
    assert execution_id == runner.last_execution_id
    assert runner._integration.last_execution_id == execution_id
    assert runner._integration.tracker.get_status(execution_id) == (
        ExecutionStatus.PENDING
    )


def test_3b_runner_rejects_missing_account(qapp):
    fake = FakeDispatchCore()
    runner = TestRunner(dispatch_core=fake)
    queue, entries = make_queue_and_entries([make_order()])

    with pytest.raises(ValueError):
        runner.run(entries)  # no Account supplied (fail-closed)
    assert fake.calls == 0  # nothing was ever dispatched


def test_3c_runner_rejects_account_that_does_not_match_entries(qapp):
    fake = FakeDispatchCore()
    runner = TestRunner(dispatch_core=fake)
    queue, entries = make_queue_and_entries([make_order()])
    other = make_account_record(account_id="ACC-999").account

    with pytest.raises(ValueError):
        runner.run(entries, account=other)  # account_id mismatch
    assert fake.calls == 0  # nothing was ever dispatched


def test_3d_runner_builds_existing_plan_and_attaches_real_account(qapp):
    fake = FakeDispatchCore()
    runner = TestRunner(dispatch_core=fake)
    queue, entries = make_queue_and_entries([make_order("NSC-3D")])
    account = make_account_record().account

    plan, execution_id, result = runner.run(entries, account=account)

    # (5) the plan is the EXISTING plan-builder output (Block 0 contract),
    # built by the EXISTING bridge — never a stub or a re-implementation.
    assert isinstance(plan, ExecutionPlan)
    assert plan.plan_id.startswith("ui5-test-")
    assert plan.orders[0] is entries[0].order
    # (6) the supplied REAL Account object is attached, unchanged.
    assert plan.accounts == [account]
    assert plan.accounts[0] is account
    assert plan.accounts[0].account_id == entries[0].account_id
    # (7) the existing DispatchIntegration.dispatch boundary ran it.
    assert runner._integration.dispatch_core is fake
    assert fake.calls == 1
    assert fake.plans[0] is plan
    # (8) execution id is the integration's registered id, never plan.plan_id.
    assert execution_id == runner._integration.last_execution_id
    assert execution_id != plan.plan_id


def test_4_runner_issues_exactly_one_dispatch_per_action(qapp):
    from unittest.mock import patch

    fake = FakeDispatchCore()
    runner = TestRunner(dispatch_core=fake)
    queue, entries = make_queue_and_entries([make_order()])
    account = make_account_record().account

    with patch("core.dispatch_core.DispatchCore") as mock_dispatch, \
         patch("core.order_engine.OrderEngine") as mock_engine, \
         patch("brokers.manager.BrokerManager") as mock_broker_manager:
        runner.run(entries, account=account)
        # no new Core object is ever created by the runner: the dispatch is
        # issued through the existing fake Dispatch Core only.
        assert mock_dispatch.call_count == 0
        assert mock_engine.call_count == 0
        assert mock_broker_manager.call_count == 0

    assert fake.calls == 1
    assert fake.plans[0] is runner.last_plan


def test_5_runner_keeps_entries_identity_after_run(qapp):
    orders = [make_order("A"), make_order("B"), make_order("C")]
    queue = OrderQueue()
    for order in orders:
        queue.enqueue(order, account_id="ACC-001", broker_name="\u0622\u06af\u0627\u0647")
    entries = queue.list_pending()
    before = list(entries)
    account = make_account_record().account

    runner = TestRunner(dispatch_core=FakeDispatchCore())
    runner.run(entries, account=account)

    pending = queue.list_pending()
    assert len(pending) == 3
    assert [e.order for e in pending] == orders
    assert [e for e in pending] == before
    assert all(queue.is_pending(o) for o in orders)
    assert all(e.account_id == "ACC-001" for e in pending)


def test_6_runner_second_action_is_second_distinct_execution(qapp):
    fake = FakeDispatchCore()
    runner = TestRunner(dispatch_core=fake)
    queue, entries = make_queue_and_entries([make_order(), make_order()])
    account = make_account_record().account

    plan1, exec1, _ = runner.run(entries, account=account)
    plan2, exec2, _ = runner.run(entries, account=account)

    assert fake.calls == 2  # one dispatch per Test action, exactly
    assert plan1.plan_id != plan2.plan_id
    assert exec1 != exec2
    assert plan1.plan_id == "ui5-test-1"
    assert plan2.plan_id == "ui5-test-2"


def test_7_runner_identity_flows_from_entries_into_plan_binding(qapp):
    order = make_order("NSC-7")
    queue, entries = make_queue_and_entries([order])
    fake = FakeDispatchCore()
    runner = TestRunner(dispatch_core=fake)
    account = make_account_record().account

    plan, _, _ = runner.run(entries, account=account)

    assert plan.orders[0] is order
    assert plan.conditions["binding"][0]["account_id"] == "ACC-001"
    assert plan.conditions["binding"][0]["broker_name"] == "\u0622\u06af\u0627\u0647"
    assert plan.account_routes["ACC-001"] == "\u0622\u06af\u0627\u0647"


def test_8_real_core_rejects_mismatched_account_fail_closed(qapp):
    from unittest.mock import Mock

    # Real DispatchCore; only the broker/provider boundary is a test double.
    broker = Mock()
    broker.name = "\u0622\u06af\u0627\u0647"
    provider = Mock()
    manager = Mock()
    manager.get.return_value = broker
    manager.get_instrument_provider.return_value = provider

    core = DispatchCore(broker_manager=manager)
    core.order_engine.execute_by_ins_code = Mock()
    runner = TestRunner(dispatch_core=core)

    queue, entries = make_queue_and_entries([make_order("NSC-LIVE")])
    other = make_account_record(account_id="ACC-777").account

    # An Account that does not match the entries is rejected by the runner
    # (ValueError, fail-closed) BEFORE any build/dispatch: the core is never
    # invoked, no engine call, no live flag, no Safety Gate.
    with pytest.raises(ValueError):
        runner.run(entries, account=other)

    assert core.order_engine.execute_by_ins_code.call_count == 0
    # The UI-5 chain attached no Safety Gate: the only source of a
    # ``live=True`` envelope (Block 10.3) is absent, so every envelope
    # stays ``live=False``; live trading stays disabled.
    assert core.safety_gate is None
    assert core.live_trading_enabled is False


def test_8b_valid_ui5_pass_reaches_order_engine_dry_run_with_real_core(qapp):
    """
    POSITIVE regression: the CORRECTED production TestRunner path executes a
    valid UI-5 Test pass in Dry-Run mode all the way to OrderEngine, with
    live=False — WITHOUT patching the plan builder and WITHOUT injecting an
    Account.

    The Account object is the EXISTING UI account state: the active
    AccountRecord's own ``Account`` (the store's real object, identity
    only). It is handed to ``runner.run(entries, account=account)`` exactly
    as the production page does; the runner itself attaches it to
    ``plan.accounts`` (the documented integration-layer convention of
    Blocks 6/9/10) and dispatches through the real DispatchCore +
    real OrderEngine (real M6-A … M6-E).
    """
    BROKER = "\u0622\u06af\u0627\u0647"
    harness = SimulationHarness(broker_name=BROKER)
    core = harness.dispatch_core

    # (1) the TestRunner drives THIS real DispatchCore (real OrderEngine
    # inside it); only the broker/provider pair is the offline simulation.
    assert isinstance(core, DispatchCore)
    runner = TestRunner(dispatch_core=core)

    # A valid order for the simulation catalog (passes M6-A … M6-E offline).
    # SELL side: the real engine's M6-D capacity gate does not need a fund,
    # so the pass stays valid with the UI store's identity-only Account
    # (no balance is fabricated anywhere).
    order = make_simulation_order(side=SELL, ins_code="INS-SIM-1")
    account = make_account_record(account_id="ACC-001", broker_name=BROKER).account
    queue = OrderQueue()
    queue.enqueue(order, account_id=account.account_id, broker_name=BROKER)
    entries = queue.list_pending()

    plan, execution_id, result = runner.run(entries, account=account)

    # (1) the real DispatchCore is the one that executed this pass.
    assert runner._dispatch_core is core
    assert runner._integration.dispatch_core is core

    # (8) the returned result remains the existing DispatchResult contract.
    assert isinstance(result, DispatchResult)
    assert result.success is True
    assert result.sent is False
    assert result.mode == "ALL_PROCESSED"
    assert "dry-run" in result.message

    # (9) execution id is the integration's registered id, never plan.plan_id.
    assert isinstance(execution_id, str) and execution_id
    assert execution_id != plan.plan_id
    assert execution_id == runner.last_execution_id

    # (2)+(3)+(5) the valid order travelled the REAL OrderEngine path to the
    # end, and the effective envelope reached the engine (and the broker
    # boundary) with live=False: exactly ONE dry-run ``place_order``, never
    # a live submission, on the simulation broker only.
    assert harness.broker.place_order_calls == [(order, False)]
    assert all(live is False for _, live in harness.broker.place_order_calls)

    # (7) M6-A … M6-E are NOT bypassed: the engine's real prepare() performed
    # its genuine trading-state read (M6-A) and SELL-capacity read (M6-D)
    # against the broker before the order was handed to place_order.
    ops = [c.op for c in harness.broker.calls]
    assert "get_trading_state" in ops
    assert "get_sell_capacity" in ops
    assert "place_order" in ops

    # (4) live trading stays disabled everywhere; the Safety Gate remains
    # unattached so every envelope stays the fail-closed Dry Run default.
    assert core.safety_gate is None
    assert core.live_trading_enabled is False
    assert harness.broker.live_trading_enabled is False

    # (5)+(6) the runner attached the SUPPLIED REAL account object to the
    # plan (the caller-supplied Account is never replaced or rebuilt).
    assert plan.accounts == [account]
    assert plan.accounts[0] is account

    # (5)+(6) only the simulation broker is registered: the real AgaahBroker
    # (and any HTTP session it would construct) is never created, so no real
    # broker.place_order() and no network activity can occur on this pass.
    assert isinstance(harness.broker, SimulationBroker)
    assert set(harness.manager.brokers) == {BROKER}


def test_8c_invalid_real_core_stays_blocked_fail_closed(qapp):
    """
    NEGATIVE real-core regression: with the same corrected production
    path, a valid-looking BUY order whose account has no balance is BLOCKED
    by the REAL M6-C gate — never sent, live stays False.

    The UI AccountStore's Account is identity-only (no balances), exactly as
    the store provides it; nothing is fabricated. The real OrderEngine
    therefore fails closed on the missing fund before any ``place_order``.
    """
    BROKER = "\u0622\u06af\u0627\u0647"
    harness = SimulationHarness(broker_name=BROKER)
    core = harness.dispatch_core
    runner = TestRunner(dispatch_core=core)

    order = make_simulation_order(side=BUY, ins_code="INS-SIM-1")
    account = make_account_record(account_id="ACC-001", broker_name=BROKER).account
    queue = OrderQueue()
    queue.enqueue(order, account_id=account.account_id, broker_name=BROKER)
    entries = queue.list_pending()

    plan, execution_id, result = runner.run(entries, account=account)

    assert isinstance(result, DispatchResult)
    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "T1" in result.message  # the real M6-C "fund" reason

    # The broker boundary was never reached and nothing was sent live.
    assert harness.broker.place_order_calls == []
    ops = [c.op for c in harness.broker.calls]
    assert "get_trading_state" in ops          # M6-A ran (state was groomed)
    assert "get_buy_capacity" not in ops        # M6-C blocked before capacity
    # live trading stays disabled everywhere.
    assert core.safety_gate is None
    assert core.live_trading_enabled is False
    assert harness.broker.live_trading_enabled is False
    assert isinstance(harness.broker, SimulationBroker)


# ===========================================================================
# Page wiring (pytest + QApplication)
# ===========================================================================


def test_9_page_toggle_without_runner_is_a_pure_ui_action(qapp, store):
    page, _ = _make_valid_page(qapp, store, OrderQueue())
    page.test_button.click()
    assert page._test_mode is True
    assert page._last_test_run is None
    assert page._last_test_error is None


def test_10_page_on_transition_runs_once_with_exact_entries(qapp, store):
    queue = OrderQueue()
    runner = StubRunner()
    page, order = _make_valid_page(
        qapp, store, queue, runner_factory=lambda: runner
    )
    entry = queue.list_pending()[0]

    page.test_button.click()

    assert page._test_mode is True
    assert runner.calls == 1
    assert len(runner.captured[0]) == 1
    assert runner.captured[0][0] is entry
    assert runner.captured[0][0].order is order


def test_11_page_off_transition_never_runs(qapp, store):
    queue = OrderQueue()
    runner = StubRunner()
    page, _ = _make_valid_page(
        qapp, store, queue, runner_factory=lambda: runner
    )
    page.test_button.click()   # ON -> one pass
    page.test_button.click()   # OFF -> no pass
    assert page._test_mode is False
    assert runner.calls == 1


def test_12_page_second_on_transition_runs_again_once(qapp, store):
    queue = OrderQueue()
    runner = StubRunner()
    page, _ = _make_valid_page(
        qapp, store, queue, runner_factory=lambda: runner
    )
    page.test_button.click()   # ON
    page.test_button.click()   # OFF
    page.test_button.click()   # ON
    assert runner.calls == 2  # one pass per ON transition, no retry/burst


def test_13_page_refresh_and_render_never_trigger_a_run(qapp, store):
    queue = OrderQueue()
    runner = StubRunner()
    page, _ = _make_valid_page(
        qapp, store, queue, runner_factory=lambda: runner
    )
    # pure UI flows: refresh state, re-mirror the account, process events
    for _ in range(3):
        page._refresh_test_button_state()
    page.refresh_active_account()
    qapp.processEvents()
    assert runner.calls == 0


def test_14_page_empty_queue_never_reaches_the_runner(qapp, store):
    store.add("ACC-001", "\u0622\u06af\u0627\u0647")
    store.set_active("ACC-001")
    runner = StubRunner()
    page = OrderConfigurationPage(store, order_queue=OrderQueue())
    page.set_test_runner_factory(lambda: runner)
    page.config.select_instrument(
        Instrument(symbol="\u0622\u06a9\u0648", name="\u0622\u06a9\u0648", ins_code="1")
    )
    page._refresh_test_button_state()
    assert page.test_button.isEnabled() is False

    page._run_test_pass()  # forced call with an empty queue
    assert runner.calls == 0
    assert page._last_test_error is None


def test_15_page_failing_run_fails_closed_no_retry(qapp, store):
    queue = OrderQueue()
    failing = make_failing_runner(ValueError("boom"))
    page, _ = _make_valid_page(
        qapp, store, queue, runner_factory=lambda: failing
    )
    order = queue.list_pending()[0].order
    page.test_button.click()

    assert failing.calls == 1  # exactly one attempt, never retried
    assert page._last_test_run is None
    assert page._last_test_error == "boom"
    assert queue.is_pending(order)  # the queue is never mutated


def test_16_page_successful_run_stores_result_contract(qapp, store):
    queue = OrderQueue()
    runner = StubRunner()
    page, order = _make_valid_page(
        qapp, store, queue, runner_factory=lambda: runner
    )
    page.test_button.click()

    plan, execution_id, result = page._last_test_run
    assert plan == "stub-plan-id"   # unchanged bridge triple
    assert execution_id == "stub-exec-id"
    assert execution_id != plan
    assert isinstance(result, DispatchResult)
    assert result.mode == "ALL_PROCESSED"
    assert page._last_test_error is None
    assert page._last_test_entries[0].order is order


def test_16b_page_passes_the_existing_active_account_object(qapp, store):
    """
    The pass obtains the ACTIVE AccountRecord's existing ``Account`` object
    (the UI-2.1 store's real Account — identity only) and hands it to the
    runner; nothing is resolved through a broker/network and nothing is
    fabricated inside the page.
    """
    queue = OrderQueue()
    runner = StubRunner()
    page, _ = _make_valid_page(
        qapp, store, queue, runner_factory=lambda: runner
    )
    page.test_button.click()

    record = store.get("ACC-001")
    assert runner.calls == 1
    # the very same Account object of the active record, verbatim.
    assert runner.captured_accounts[0] is record.account
    assert runner.captured_accounts[0].account_id == "ACC-001"
    assert page._last_test_entries[0].account_id == "ACC-001"
    assert page._last_test_error is None


def test_16c_page_rejects_entries_mismatching_the_active_account(qapp, store):
    """
    A queue whose entries are bound to a DIFFERENT account/broker than the
    active record never reaches the runner (fail-closed, no dispatch).
    """
    store.add("ACC-001", "\u0622\u06af\u0627\u0647")
    store.set_active("ACC-001")
    queue = OrderQueue()
    runner = StubRunner()
    page = OrderConfigurationPage(store, order_queue=queue)
    page.set_test_runner_factory(lambda: runner)
    page.config.select_instrument(
        Instrument(symbol="\u0622\u06a9\u0648", name="\u0622\u06a9\u0648", ins_code="1")
    )
    order = make_order(nsc_id="NSC-C")
    # the queue binding disagrees with the active record's broker
    queue.enqueue(order, account_id="ACC-001", broker_name="OTHER-BROKER")
    page._refresh_test_button_state()
    assert page.test_button.isEnabled()

    page.test_button.click()

    assert page._test_mode is True
    assert runner.calls == 0          # never reached the runner
    assert page._last_test_run is None
    assert page._last_test_error is None
    # the queue entry itself is untouched by the fail-closed guard
    entry = queue.list_pending()[0]
    assert entry.order is order
    assert entry.account_id == "ACC-001"
    assert entry.broker_name == "OTHER-BROKER"


# ===========================================================================
# Offline subprocess — a full Test action never touches the network
# ===========================================================================


def test_17_full_test_action_offline_subprocess():
    code = "\n".join(
        [
            "import sys",
            "import socket",
            "import urllib.request",
            "",
            "class _Boom:",
            "    def __init__(self, *a, **k):",
            "        raise AssertionError('network construct attempted')",
            "    def __getattr__(self, name):",
            "        raise AssertionError(f'network access attempted: {name}')",
            "",
            "socket.create_connection = _Boom",
            "socket.socket = _Boom",
            "socket.getaddrinfo = _Boom",
            "urllib.request.urlopen = _Boom",
            "",
            "from core.dispatch_contracts import DispatchResult, ExecutionPlan",
            "from core.order_queue import OrderQueue",
            "from models.account import Account",
            "from models.instrument import Instrument",
            "from models.order import BUY, Order",
            "from PySide6.QtWidgets import QApplication",
            "from ui.account_store import AccountStore",
            "from ui.order_configuration_page import OrderConfigurationPage",
            "from ui.test_runner import TestRunner",
            "",
            "class FakeDispatchCore:",
            "    def __init__(self):",
            "        self.calls = 0",
            "    def dispatch(self, plan):",
            "        assert isinstance(plan, ExecutionPlan)",
            "        assert len(plan.accounts) == 1",
            "        assert isinstance(plan.accounts[0], Account)",
            "        assert plan.accounts[0].account_id == 'ACC-001', plan.accounts",
            "        assert plan.orders[0].nsc_id == 'NSC-1'",
            "        self.calls += 1",
            "        return DispatchResult(",
            "            success=True, sent=False, mode='ALL_PROCESSED',",
            "            message='offline fake dry-run', order_count=len(plan.orders),",
            "            trace_id='ui5-offline',",
            "        )",
            "",
            "app = QApplication([])",
            "store = AccountStore()",
            "store.add('ACC-001', 'آگاه')",
            "store.set_active('ACC-001')",
            "queue = OrderQueue()",
            "page = OrderConfigurationPage(store, order_queue=queue)",
            "",
            "fake = FakeDispatchCore()",
            "page.set_test_runner_factory(lambda: TestRunner(dispatch_core=fake))",
            "page.config.select_instrument(",
            "    Instrument(symbol='آکو', name='آکو', ins_code='1')",
            ")",
            "order = Order(nsc_id='NSC-1', side=BUY, price=15000, quantity=500)",
            "queue.enqueue(order, account_id='ACC-001', broker_name='آگاه')",
            "page._refresh_test_button_state()",
            "assert page.test_button.isEnabled(), 'Test button must be enabled'",
            "",
            "page.test_button.click()  # one intentional Test action",
            "assert page._test_mode is True",
            "assert fake.calls == 1, 'exactly one dispatch per Test action'",
            "assert page._last_test_run is not None",
            "execution_id = page._last_test_run[1]",
            "plan = page._last_test_run[0]",
            "assert execution_id != plan.plan_id",
            "",
            "# a second Test action is a second, distinct execution",
            "page.test_button.click()   # OFF",
            "page.test_button.click()   # ON -> second pass",
            "assert fake.calls == 2",
            "print('TASK2_OFFLINE_OK')",
        ]
    )
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "TASK2_OFFLINE_OK" in result.stdout