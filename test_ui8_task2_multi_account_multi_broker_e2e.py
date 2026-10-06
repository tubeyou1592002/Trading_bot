"""
test_ui8_task2_multi_account_multi_broker_e2e.py

UI-8 Task 2 — multiple accounts and multiple brokers over the REAL order
page, fully offline.

Coverage review (UI-5 + UI-8 Task 1 + Block 9), so nothing here duplicates
what already exists:

  * ``test_ui5_task2_dry_run_execution.py`` test_2 rejects MIXED account /
    mixed broker entries, but against a FAKE Dispatch Core, so it cannot
    show what happens at the broker boundary.
  * ``test_ui5_task3_order_results.py`` covers one account / one broker only.
  * ``test_ui8_task1_single_broker_e2e.py`` (Task 1) covers ONE order / ONE
    account / ONE broker end to end, including that nothing live is sent.
  * ``test_block9_task9_4.py`` / ``test_block9_task9_5.py`` cover multi-account
    and multi-broker isolation at the CORE level, but their plans are built
    directly by the harness — they never go through the real UI queue, the
    real Test button or ``ui.test_runner.TestRunner``.
  * ``test_ui4_task7_selected_queue_entries.py`` tests_7/8 reject mixed
    selections at the plan-builder API, again without the UI and without a
    broker boundary.

So the UI-level multi-account / multi-broker evidence is missing, and this
file adds it. What is proven here:

  * Test 1 (routing proof) — three orders built by the REAL page, split over
    two accounts and two brokers (one account owning two orders), executed by
    the REAL Test button through the REAL ``TestRunner`` / ``DispatchCore`` /
    ``OrderEngine`` to the TWO independent offline simulation pairs. Every
    order reaches only its own destination simulator, with exactly matching
    call counts/identities (no duplicate, missing or partial order), every
    call with ``live=False``, and every result attributed to its own order
    and account and visible in the Test Results area.

  * Test 2 (current product behavior, recorded not bypassed) — a queue that
    MIXES accounts/brokers is rejected fail-closed by the current page and
    runner: nothing is dispatched, neither simulator is called, the queue is
    not silently split, and the exact user-facing message is asserted.

  Both facts are asserted in both directions: what the product does today is
  recorded as-is (criterion 6), and no production, Core, Block 8, UI-7 or
    order-execution code is touched to make anything pass.

Test data (the mapping this file proves):

    ACC-1 / SIM-A :  order INS-SIM-1 (symbol الف)
                     order INS-SIM-2 (symbol ب)
    ACC-2 / SIM-B :  order INS-SIM-3 (symbol ج)

Run:
    pytest -q test_ui8_task2_multi_account_multi_broker_e2e.py
"""

import socket
import urllib.request
from unittest.mock import patch

import pytest

from PySide6.QtWidgets import QApplication

from brokers.manager import BrokerManager
from core.dispatch_contracts import DispatchResult
from core.order_queue import OrderQueue
from core.simulation_harness import (
    SimulationBroker,
    SimulationInstrumentProvider,
    build_dual_broker_harness,
)
from models.instrument import Instrument
from models.order import SELL

from ui import strings as STRINGS
from ui.account_store import AccountStore
from ui.order_configuration_page import (
    RESULT_STATUS_SUCCESS,
    OrderConfigurationPage,
)
from ui.test_runner import TestRunner


BROKER_A = "SIM-A"
BROKER_B = "SIM-B"
ACCOUNT_A = "ACC-1"
ACCOUNT_B = "ACC-2"

INS_1 = "INS-SIM-1"
INS_2 = "INS-SIM-2"
INS_3 = "INS-SIM-3"

INSTRUMENTS = {
    INS_1: Instrument(
        symbol="\u0627\u0644\u0641", name="SIM \u0627\u0644\u0641", ins_code=INS_1
    ),
    INS_2: Instrument(
        symbol="\u0628", name="SIM \u0628", ins_code=INS_2
    ),
    INS_3: Instrument(
        symbol="\u062c", name="SIM \u062c", ins_code=INS_3
    ),
}

PRICE = 10_000
QUANTITY = 10


@pytest.fixture(scope="module")
def qapp():
    """Reuse the process-wide QApplication if one exists, else create one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def no_real_broker_or_network():
    """
    Make every real-broker / network entry point fail loudly for the whole
    test. Nothing here may construct an HTTP session, open a socket,
    resolve a host, or build the production broker binding; the two
    simulation pairs are registered through the existing ``register()``
    seam on a manager built with ``BrokerManager.__new__``, so the
    production ``__init__`` binding (which creates the real AgaahBroker)
    must never run.
    """

    def _boom(*args, **kwargs):
        raise AssertionError("real broker / network access attempted")

    with patch.object(socket, "socket", _boom), patch.object(
        socket, "create_connection", _boom
    ), patch.object(socket, "getaddrinfo", _boom), patch.object(
        urllib.request, "urlopen", _boom
    ), patch.object(BrokerManager, "__init__", _boom):
        from brokers.agaah.broker import AgaahBroker

        with patch.object(AgaahBroker, "__init__", _boom):
            yield


class OfflineNscSeam:
    """
    Offline stand-in for the broker ``InstrumentProvider`` symbol seam
    (``get_nsc_id``): it supplies the symbol information Add-to-Queue needs,
    without any broker, session or network call.
    """

    def __init__(self, ins_codes):
        self.mapping = {ins_code: ins_code for ins_code in ins_codes}
        self.calls = []

    def get_nsc_id(self, ins_code):
        self.calls.append(ins_code)
        return self.mapping.get(ins_code)


def _pulse(qapp, loops=30):
    """A fixed number of event-loop wakeups for the queued off-thread signal."""
    for _ in range(loops):
        qapp.processEvents()
    qapp.processEvents()


def _add_order_via_real_ui(qapp, page, seam, ins_code):
    """
    Drive the REAL UI order flow for one order: select the instrument and
    the order fields, resolve the broker nscId off-thread through the
    offline seam, then press Add-to-Queue. Returns the exact ``QueueEntry``
    the page created, bound to the page's ACTIVE account/broker.
    """
    instrument = INSTRUMENTS[ins_code]
    page.set_order_identity_factory(lambda: seam)
    page.config.select_instrument(instrument)
    page.config.set_side(SELL)
    page.config.set_price(PRICE)
    page.config.set_quantity(QUANTITY)
    page._start_order_identity_resolution(instrument)
    page.wait_for_order_identity_workers(timeout_ms=10_000)
    _pulse(qapp)
    assert page._on_add_to_queue() is True
    return page.order_queue.list_pending()[-1]


def _make_dual_harness():
    """Two independent offline simulation pairs on ONE shared manager."""
    harness = build_dual_broker_harness(
        broker_a_name=BROKER_A,
        broker_b_name=BROKER_B,
        ins_codes=(INS_1, INS_2, INS_3),
    )
    return harness, harness.broker, harness.manager.get(BROKER_B)


# ===========================================================================
# Test 1 — every order reaches ONLY its own destination broker, with the
#          result attributed to its own order/account and shown in the UI
# ===========================================================================


def test_task2_each_order_reaches_only_its_own_broker_and_is_shown_in_ui(
    qapp, no_real_broker_or_network
):
    """
    Three orders, two accounts, two brokers, executed through the REAL page
    and the REAL Test button: ``ACC-1/SIM-A`` owns two orders, ``ACC-2/SIM-B``
    owns one. Each pass goes through the REAL ``TestRunner`` ->
    ``DispatchIntegration`` -> ``DispatchCore`` -> ``OrderEngine`` over the
    shared dual-broker manager (the production wiring shape: the runner
    builds the Dispatch Core itself around the shared manager).
    """
    harness, broker_a, broker_b = _make_dual_harness()
    assert set(harness.manager.brokers) == {BROKER_A, BROKER_B}
    assert isinstance(broker_a, SimulationBroker)
    assert isinstance(broker_b, SimulationBroker)
    # two genuinely independent simulation pairs
    assert broker_a is not broker_b
    assert harness.manager.get(BROKER_A) is broker_a
    assert harness.manager.get(BROKER_B) is broker_b
    provider_a = harness.manager.get_instrument_provider(BROKER_A)
    provider_b = harness.manager.get_instrument_provider(BROKER_B)
    assert isinstance(provider_a, SimulationInstrumentProvider)
    assert isinstance(provider_b, SimulationInstrumentProvider)
    assert provider_a is not provider_b

    store = AccountStore()
    store.add(ACCOUNT_A, BROKER_A)
    store.add(ACCOUNT_B, BROKER_B)
    store.set_active(ACCOUNT_A)
    seam = OfflineNscSeam((INS_1, INS_2, INS_3))

    # ---- Pass A: the two ACC-1 / SIM-A orders ---------------------------
    queue_a = OrderQueue()
    page_a = OrderConfigurationPage(store, order_queue=queue_a)
    runner_a = TestRunner(broker_manager=harness.manager)
    page_a.set_test_runner_factory(lambda: runner_a)

    entry_a1 = _add_order_via_real_ui(qapp, page_a, seam, INS_1)
    entry_a2 = _add_order_via_real_ui(qapp, page_a, seam, INS_2)

    # (1) each queued order is bound to the account/broker it was created
    # for — the real Add-to-Queue action, the real active selection.
    assert [e.account_id for e in queue_a.list_pending()] == [
        ACCOUNT_A,
        ACCOUNT_A,
    ]
    assert [e.broker_name for e in queue_a.list_pending()] == [
        BROKER_A,
        BROKER_A,
    ]
    assert entry_a1.order.nsc_id == INS_1
    assert entry_a2.order.nsc_id == INS_2
    assert page_a.test_button.isEnabled()

    page_a.test_button.click()

    assert page_a._last_test_error is None
    plan_a, execution_a, result_a = page_a._last_test_run

    # (2) the plan and the dispatch path keep each binding exactly as the
    # queue had it — no re-binding, no cross-swapping.
    assert plan_a.orders == [entry_a1.order, entry_a2.order]
    assert plan_a.orders[0] is entry_a1.order
    assert plan_a.orders[1] is entry_a2.order
    assert plan_a.account_routes == {ACCOUNT_A: BROKER_A}
    assert plan_a.conditions["binding"][0]["account_id"] == ACCOUNT_A
    assert plan_a.conditions["binding"][0]["broker_name"] == BROKER_A
    assert plan_a.conditions["binding"][1]["account_id"] == ACCOUNT_A
    assert plan_a.conditions["binding"][1]["broker_name"] == BROKER_A
    assert plan_a.accounts == [store.get(ACCOUNT_A).account]
    assert execution_a == runner_a.last_execution_id
    assert execution_a != plan_a.plan_id

    # (3)+(4) BOTH orders landed on SIM-A only, in exact queue order, with
    # exactly matching identity/count — and SIM-B was never touched.
    assert broker_a.place_order_calls == [
        (entry_a1.order, False),
        (entry_a2.order, False),
    ]
    assert broker_b.place_order_calls == []

    # safety: every call is a dry run and nothing reports a live send
    assert all(live is False for _, live in broker_a.place_order_calls)
    assert all(live is False for _, live in broker_b.place_order_calls)
    assert isinstance(result_a, DispatchResult)
    assert result_a.sent is False
    assert result_a.success is True
    assert result_a.mode == "ALL_PROCESSED"
    assert result_a.order_count == 2
    assert harness.broker.live_trading_enabled is False
    assert broker_b.live_trading_enabled is False

    # (5) each result is attributed to its OWN order and account and is
    # visible in the page's Test Results area.
    results_a = page_a._last_order_results
    assert len(results_a) == 2
    assert results_a[0].order is entry_a1.order
    assert results_a[1].order is entry_a2.order
    assert [r.sent for r in results_a] == [False, False]
    assert [r.success for r in results_a] == [True, True]
    assert [r.mode for r in results_a] == ["DRY_RUN", "DRY_RUN"]
    assert page_a.result_list.count() == 2
    rows_a = [page_a.result_list.item(i).text() for i in range(2)]
    assert rows_a == [
        f"حساب {ACCOUNT_A} | الف | فروش | "
        f"{RESULT_STATUS_SUCCESS} | سفارش با موفقیت شبیه‌سازی شد",
        f"حساب {ACCOUNT_A} | ب | فروش | "
        f"{RESULT_STATUS_SUCCESS} | سفارش با موفقیت شبیه‌سازی شد",
    ]
    assert page_a.result_status_label.text() == "2 result(s)"

    # ---- Pass B: the single ACC-2 / SIM-B order -------------------------
    store.set_active(ACCOUNT_B)
    queue_b = OrderQueue()
    page_b = OrderConfigurationPage(store, order_queue=queue_b)
    runner_b = TestRunner(broker_manager=harness.manager)
    page_b.set_test_runner_factory(lambda: runner_b)

    entry_b1 = _add_order_via_real_ui(qapp, page_b, seam, INS_3)
    assert entry_b1.account_id == ACCOUNT_B
    assert entry_b1.broker_name == BROKER_B
    assert entry_b1.order.nsc_id == INS_3
    assert page_b.test_button.isEnabled()

    page_b.test_button.click()

    assert page_b._last_test_error is None
    plan_b, execution_b, result_b = page_b._last_test_run
    assert plan_b.orders == [entry_b1.order]
    assert plan_b.orders[0] is entry_b1.order
    assert plan_b.account_routes == {ACCOUNT_B: BROKER_B}
    assert plan_b.accounts == [store.get(ACCOUNT_B).account]
    assert execution_b == runner_b.last_execution_id
    assert execution_b != plan_b.plan_id

    # (3) the order reached ONLY its own destination broker...
    assert broker_b.place_order_calls == [(entry_b1.order, False)]
    # (4) ...and SIM-A received no additional order: exactly its own two,
    # in the same order, with no duplicate and no partial order anywhere.
    assert broker_a.place_order_calls == [
        (entry_a1.order, False),
        (entry_a2.order, False),
    ]

    # safety for the second pass as well
    assert result_b.sent is False
    assert result_b.success is True
    assert result_b.order_count == 1

    # (5) its own result, on its own order/account, visible in its own page.
    per_b = page_b._last_order_results[0]
    assert per_b.order is entry_b1.order
    assert per_b.sent is False
    assert per_b.success is True
    assert per_b.mode == "DRY_RUN"
    assert page_b.result_list.count() == 1
    assert page_b.result_list.item(0).text() == (
        f"حساب {ACCOUNT_B} | ج | فروش | "
        f"{RESULT_STATUS_SUCCESS} | سفارش با موفقیت شبیه‌سازی شد"
    )
    assert page_b.result_status_label.text() == "1 result(s)"

    # (4) whole-run accounting: three distinct orders, each delivered
    # exactly once, to exactly one simulator, none missing or duplicated.
    delivered = [order for order, _ in broker_a.place_order_calls]
    delivered += [order for order, _ in broker_b.place_order_calls]
    assert len(delivered) == 3
    assert len({id(order) for order in delivered}) == 3
    assert set(id(order) for order in delivered) == {
        id(entry_a1.order),
        id(entry_a2.order),
        id(entry_b1.order),
    }
    assert plan_a is runner_a.last_plan
    assert plan_b is runner_b.last_plan
    assert plan_a is not plan_b


# ===========================================================================
# Test 2 — current product behavior for a MIXED queue, recorded as-is
# ===========================================================================


def test_task2_mixed_account_broker_queue_is_rejected_fail_closed(
    qapp, no_real_broker_or_network
):
    """
    A queue that mixes accounts/brokers cannot be executed by the current
    product path, and this test records that behavior exactly as it is —
    no silent splitting, no bypass, no production change:

      * the REAL page builds the mixed queue (ACC-1/SIM-A order, then two
        ACC-2/SIM-B orders after selecting the second account);
      * one press of the REAL Test button is refused fail-closed by the page
        (the active account does not match every entry);
      * the REAL ``TestRunner`` refuses a mixed selection too — with the
        REAL Dispatch Core over the dual-broker manager it raises
        ``ValueError`` BEFORE building or dispatching anything;
      * neither simulation broker is called, nothing is sent live, and the
        queue keeps every entry untouched.
    """
    harness, broker_a, broker_b = _make_dual_harness()

    store = AccountStore()
    store.add(ACCOUNT_A, BROKER_A)
    store.add(ACCOUNT_B, BROKER_B)
    store.set_active(ACCOUNT_A)
    seam = OfflineNscSeam((INS_1, INS_2, INS_3))

    queue = OrderQueue()
    page = OrderConfigurationPage(store, order_queue=queue)
    runner = TestRunner(broker_manager=harness.manager)
    page.set_test_runner_factory(lambda: runner)

    entry_a1 = _add_order_via_real_ui(qapp, page, seam, INS_1)
    # the user selects the second account and adds two more orders: the queue
    # now mixes two accounts and two brokers, one account owning two orders.
    store.set_active(ACCOUNT_B)
    entry_b1 = _add_order_via_real_ui(qapp, page, seam, INS_2)
    entry_b2 = _add_order_via_real_ui(qapp, page, seam, INS_3)

    # (1) the mixed queue really is mixed, in the exact expected mapping.
    entries = queue.list_pending()
    assert [
        (e.account_id, e.broker_name) for e in entries
    ] == [
        (ACCOUNT_A, BROKER_A),
        (ACCOUNT_B, BROKER_B),
        (ACCOUNT_B, BROKER_B),
    ]
    assert [e.order.nsc_id for e in entries] == [INS_1, INS_2, INS_3]
    assert len(store.all_accounts()) == 2

    # ---- one press of the real Test button: refused, nothing dispatched --
    assert page.test_button.isEnabled()
    page.test_button.click()

    assert page._test_mode is True
    # the page refused BEFORE the runner: no run contract is written and the
    # reason is shown to the user (exact current wording).
    assert page._last_test_run is None
    assert page._last_test_error is None
    # UI-9 Task 3: the message is Persian and centralized in ui.strings.
    assert page.queue_status_label.text() == (
        STRINGS.TEST_SKIPPED_ACCOUNT_MISMATCH
    )
    # the runner was never reached: no run counter, no plan, no dispatch.
    assert runner._run_counter == 0
    assert runner.last_plan is None
    assert runner.last_order_results is None
    assert runner.last_report is None
    # no result row is rendered for a pass that never ran.
    assert page.result_list.count() == 0

    # (3)+(4) no simulator received anything at all — and nothing live.
    assert broker_a.place_order_calls == []
    assert broker_b.place_order_calls == []
    assert [c.op for c in broker_a.calls] == []
    assert [c.op for c in broker_b.calls] == []

    # the queue is untouched: no silent splitting, no de-queueing, no
    # re-binding of any entry.
    assert queue.list_pending() == entries
    assert entries[0].order is entry_a1.order
    assert entries[1].order is entry_b1.order
    assert entries[2].order is entry_b2.order

    # ---- the runner's own guard, with the REAL core and REAL simulators --
    # Even when the mixed selection reaches the runner itself (the API the
    # page and the scheduler use), it fails closed before any build or
    # dispatch: nothing is sent to either broker.
    with pytest.raises(ValueError) as excinfo:
        runner.run(entries, account=store.get(ACCOUNT_B).account)
    message = str(excinfo.value)
    assert "mix accounts or brokers" in message

    assert runner.last_plan is None
    assert runner.last_order_results is None
    assert broker_a.place_order_calls == []
    assert broker_b.place_order_calls == []

    # safety invariants for this rejected path
    assert broker_a.live_trading_enabled is False
    assert broker_b.live_trading_enabled is False
    assert page._last_test_run is None
    assert page.result_list.count() == 0