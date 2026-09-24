"""
test_ui5_task3_order_results.py

UI-5 Task 3 — Per-Order Test Result display (fully offline, deterministic).

After ONE Test action, the Order Configuration page renders exactly ONE
result row per queued order, in exact queue order. Each row carries only
user-facing data:

    حساب {account_id} | {symbol} | {خرید/فروش} | {status} | {reason}

Only three statuses may ever appear: موفق / ناموفق / مسدودشده. Nothing
except an actually-successful per-order result may ever render as موفق
(fail-closed). No technical information is ever shown in a result row
(Trace ID, latency, M6-A…M6-E, endpoint, nscId / tseId, raw Broker
response, exception / stack trace, internal mode or object id).

Result source: the ACTUAL per-order result of the same single Test
dispatch — the existing ``DispatchCore.dispatch_with_latency(plan)``
contract (Task 8.2), which runs the exact same ``_dispatch`` and returns
one ``OrderExecutionResult`` per sequence. There is NEVER a re-execution
or a second dispatch, and no fabricating of a verdict.

Contract coverage (mapped to the Task 3 requirements):

    1  — one successful order renders موفق.
    2  — one failed order renders ناموفق.
    3  — one blocked order renders مسدودشده.
    4  — three orders keep their exact queue order (per-order results and
         rows) with different accounts/symbols.
    5  — every row shows the correct Account, Symbol and Buy/Sell.
    6  — no result that is not actually successful can render as موفق.
    7  — exactly ONE dispatch per Test run (measured path, no re-run).
    8  — exactly ONE final result refresh per Test run (and none on
         construction / OFF transition / plain refresh paths).
    9  — a second Test run fully replaces the first run's rows (no
         history is kept).
    10 — no technical information appears anywhere in a result row.

Extra contracts:

    E1 — before the first run the results area shows the empty state.
    E2 — the UI keeps the user-selected symbol (its own layer) for the
         exact queued Order at Add-to-Queue time; technical nscIds never
         reach a result row.
    E3 — a missing / unknown per-order result fails closed to ناموفق.

Run:
    pytest -q test_ui5_task3_order_results.py
"""

import pytest

from PySide6.QtWidgets import QApplication

from core.dispatch_contracts import DispatchResult
from core.order_engine import OrderExecutionResult
from core.order_queue import OrderQueue
from core.simulation_harness import (
    SimulationHarness,
    build_simulation_catalog,
    make_simulation_order,
)
from models.instrument import Instrument
from models.order import BUY, SELL, Order

from ui.account_store import AccountStore
from ui.order_configuration_page import (
    RESULT_EMPTY_STATE,
    RESULT_STATUS_BLOCKED,
    RESULT_STATUS_FAILED,
    RESULT_STATUS_SUCCESS,
    _result_status_label,
    OrderConfigurationPage,
)
from ui.test_runner import TestRunner


# ---------------------------------------------------------------------------
# Deterministic offline fixtures
# ---------------------------------------------------------------------------

CATALOG = ("INS-SIM-1", "INS-SIM-2", "INS-SIM-3")
BROKER = "SIM"

INSTR_SIM1 = Instrument(symbol="آکو", name="SSIM آکو", ins_code="INS-SIM-1")
INSTR_SIM2 = Instrument(symbol="فولاد", name="SSIM فولاد", ins_code="INS-SIM-2")
INSTR_SIM3 = Instrument(symbol="ذوب", name="SSIM ذوب", ins_code="INS-SIM-3")


@pytest.fixture(scope="module")
def qapp():
    """Reuse the process-wide QApplication if one exists, else create one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def make_harness():
    """One offline harness over the REAL DispatchCore/OrderEngine path."""
    harness = SimulationHarness(
        broker_name=BROKER,
        catalog=build_simulation_catalog(ins_codes=CATALOG),
    )
    return harness


def make_identity_account():
    """The EXISTING UI account state: identity-only Account, no balances."""
    store = AccountStore()
    store.add("ACC-001", BROKER)
    store.set_active("ACC-001")
    return store.get("ACC-001").account


class NscSeam:
    """Mimics the broker InstrumentProvider seam (get_nsc_id)."""

    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.calls = []

    def get_nsc_id(self, ins_code):
        self.calls.append(ins_code)
        return self.mapping.get(ins_code)


def _pulse(qapp, loops=30):
    """A fixed number of event-loop wakeups for queued signal deliveries."""
    for _ in range(loops):
        qapp.processEvents()
    qapp.processEvents()


def make_page(qapp, harness, queue=None):
    """A real page wired to the REAL runner over the harness core."""
    store = AccountStore()
    store.add("ACC-001", BROKER)
    store.set_active("ACC-001")
    page = OrderConfigurationPage(store, order_queue=queue or OrderQueue())
    page.set_test_runner_factory(lambda: TestRunner(dispatch_core=harness.dispatch_core))
    return store, page


def enqueue_via_page(qapp, page, seam, instrument, side, price, quantity):
    """
    Drive the REAL UI path: select the instrument, resolve its broker nscId
    off-thread, press Add-to-Queue, and return the exact QueueEntry. The
    page's UI-layer symbol map is populated by the real Add-to-Queue action.
    """
    page.set_order_identity_factory(lambda: seam)
    page.config.select_instrument(instrument)
    page.config.set_side(side)
    page.config.set_price(price)
    page.config.set_quantity(quantity)
    page._start_order_identity_resolution(instrument)
    page.wait_for_order_identity_workers(timeout_ms=10000)
    _pulse(qapp)
    assert page._on_add_to_queue() is True
    return page.order_queue.list_pending()[-1]


def craft_result(order, success, mode, message="crafted"):
    return OrderExecutionResult(
        success=success,
        sent=False,
        mode=mode,
        order=order,
        broker_name=BROKER,
        message=message,
    )


class _StubResult:
    """Minimal stand-in for a per-order result in mapper-only checks."""

    def __init__(self, success, mode=None):
        self.success = success
        self.mode = mode


# ===========================================================================
# Required 1 — one successful order renders موفق (exact task row format)
# ===========================================================================


def test_1_one_successful_order_renders_success(qapp):
    harness = make_harness()
    store, page = make_page(qapp, harness)
    seam = NscSeam(mapping={"INS-SIM-1": "INS-SIM-1"})
    entry = enqueue_via_page(qapp, page, seam, INSTR_SIM1, SELL, 10_000, 10)

    page.test_button.click()

    assert page.result_list.count() == 1
    row = page.result_list.item(0).text()
    assert "| موفق |" in row
    assert row == (
        "حساب ACC-001 | آکو | فروش | موفق | "
        "سفارش با موفقیت شبیه\u200cسازی شد"
    )
    per = page._last_order_results[0]
    assert per.success is True
    assert per.order is entry.order


# ===========================================================================
# Required 2 — one failed order renders ناموفق
# ===========================================================================


def test_2_one_failed_order_renders_failed(qapp):
    harness = make_harness()
    harness.broker.configure_failure(
        fail_on_nsc_id="INS-SIM-1", fail_mode="exception"
    )
    store, page = make_page(qapp, harness)
    seam = NscSeam(mapping={"INS-SIM-1": "INS-SIM-1"})
    entry = enqueue_via_page(qapp, page, seam, INSTR_SIM1, SELL, 10_000, 10)

    page.test_button.click()

    assert page.result_list.count() == 1
    row = page.result_list.item(0).text()
    assert RESULT_STATUS_FAILED in row
    assert "اجرای سفارش ناموفق بود" in row
    per = page._last_order_results[0]
    assert per.success is False
    assert per.mode == "ERROR"          # the real engine failure outcome


# ===========================================================================
# Required 3 — one blocked order renders مسدودشده
# ===========================================================================


def test_3_one_blocked_order_renders_blocked(qapp):
    harness = make_harness()
    store, page = make_page(qapp, harness)
    seam = NscSeam(mapping={"INS-SIM-1": "INS-SIM-1"})
    # BUY with the UI's identity-only Account (no balance): the REAL M6-C
    # gate blocks it fail-closed before any broker placement.
    entry = enqueue_via_page(qapp, page, seam, INSTR_SIM1, BUY, 10_000, 10)

    page.test_button.click()

    assert page.result_list.count() == 1
    row = page.result_list.item(0).text()
    assert RESULT_STATUS_BLOCKED in row
    assert "اجرا متوقف شد" in row
    per = page._last_order_results[0]
    assert per.success is False
    assert per.mode == "BLOCKED"
    assert harness.broker.place_order_calls == []   # never sent


# ===========================================================================
# Required 4 + 5 — three orders: queue order preserved, correct per-row
#                 Account / Symbol / Buy-Sell (real chain, three statuses)
# ===========================================================================


def test_4_and_5_mixed_three_order_run_identity_and_order(qapp):
    harness = make_harness()
    store, page = make_page(qapp, harness)
    seam = NscSeam(
        mapping={"INS-SIM-1": "INS-SIM-1", "INS-SIM-2": "INS-SIM-2",
                 "INS-SIM-3": "INS-SIM-3"}
    )
    # One run yielding all three outcomes, in this exact queue order:
    # blocked (BUY, no fund) -> failed (SELL, injected exception) -> success.
    enqueue_via_page(qapp, page, seam, INSTR_SIM1, BUY, 10_000, 10)
    harness.broker.configure_failure(
        fail_on_nsc_id="INS-SIM-2", fail_mode="exception"
    )
    enqueue_via_page(qapp, page, seam, INSTR_SIM2, SELL, 10_000, 10)
    enqueue_via_page(qapp, page, seam, INSTR_SIM3, SELL, 10_000, 10)

    assert page.order_queue.list_pending()[0].order.nsc_id == "INS-SIM-1"
    assert page.order_queue.list_pending()[1].order.nsc_id == "INS-SIM-2"
    assert page.order_queue.list_pending()[2].order.nsc_id == "INS-SIM-3"

    page.test_button.click()

    # queue order preserved, one row per order
    assert page.result_list.count() == 3
    rows = [page.result_list.item(i).text() for i in range(3)]
    assert RESULT_STATUS_BLOCKED in rows[0]
    assert RESULT_STATUS_FAILED in rows[1]
    assert RESULT_STATUS_SUCCESS in rows[2]

    # per-row Account / Symbol / Buy-Sell identity
    assert "حساب ACC-001 | آکو | خرید" in rows[0]
    assert "حساب ACC-001 | فولاد | فروش" in rows[1]
    assert "حساب ACC-001 | ذوب | فروش" in rows[2]

    # the rows are fed by the REAL per-order results of THIS one run
    results = page._last_order_results
    assert len(results) == 3
    assert [r.success for r in results] == [False, False, True]
    assert [r.mode for r in results] == ["BLOCKED", "ERROR", "DRY_RUN"]
    pending = page.order_queue.list_pending()
    assert [r.order for r in results] == [e.order for e in pending]


# ===========================================================================
# Required 5 (display layer) — different accounts/symbols/sides per row
# ===========================================================================


def test_5_per_row_account_symbol_side_display_layer(qapp):
    page = OrderConfigurationPage(AccountStore(), order_queue=OrderQueue())

    o1 = Order(nsc_id="NSC-A", side=BUY, price=100, quantity=10)
    o2 = Order(nsc_id="NSC-B", side=SELL, price=200, quantity=20)
    o3 = Order(nsc_id="NSC-C", side=BUY, price=300, quantity=30)
    queue = OrderQueue()
    queue.enqueue(o1, account_id="ACC-001", broker_name=BROKER)
    queue.enqueue(o2, account_id="ACC-002", broker_name=BROKER)
    queue.enqueue(o3, account_id="ACC-003", broker_name=BROKER)
    entries = queue.list_pending()

    # the UI-layer symbol map (kept at Add-to-Queue time for the exact order)
    page._order_symbols = {id(o1): "آکو", id(o2): "فولاد", id(o3): "ذوب"}
    page._last_test_entries = entries
    page._last_order_results = [
        craft_result(o1, True, "DRY_RUN"),
        craft_result(o2, False, "BLOCKED"),
        craft_result(o3, False, "ERROR"),
    ]
    page._refresh_result_display()

    rows = [page.result_list.item(i).text() for i in range(3)]
    assert rows[0] == (
        "حساب ACC-001 | آکو | خرید | موفق | "
        "سفارش با موفقیت شبیه\u200cسازی شد"
    )
    assert rows[1] == (
        "حساب ACC-002 | فولاد | فروش | مسدودشده | اجرا متوقف شد"
    )
    assert rows[2] == (
        "حساب ACC-003 | ذوب | خرید | ناموفق | اجرای سفارش ناموفق بود"
    )
    assert page.result_status_label.text() == "3 result(s)"


# ===========================================================================
# Required 6 — no false موفق: nothing but a truly successful result may
#              render as موفق
# ===========================================================================


def test_6_no_false_success(qapp):
    # fail-closed mapper: only success=True renders موفق
    assert _result_status_label(_StubResult(True, "READY")) == RESULT_STATUS_SUCCESS
    assert _result_status_label(_StubResult(True, "DRY_RUN")) == RESULT_STATUS_SUCCESS

    assert _result_status_label(None) == RESULT_STATUS_FAILED
    assert _result_status_label(_StubResult(False, "BLOCKED")) == RESULT_STATUS_BLOCKED
    assert _result_status_label(_StubResult(False, "ERROR")) == RESULT_STATUS_FAILED
    assert _result_status_label(_StubResult(False, "DRY_RUN")) == RESULT_STATUS_FAILED
    assert _result_status_label(_StubResult(None, "BLOCKED")) == RESULT_STATUS_BLOCKED
    assert _result_status_label(_StubResult(None, None)) == RESULT_STATUS_FAILED

    # display layer: a row with NO per-order result fails closed to ناموفق
    page = OrderConfigurationPage(AccountStore(), order_queue=OrderQueue())
    o1 = Order(nsc_id="NSC-1", side=BUY, price=100, quantity=10)
    queue = OrderQueue()
    queue.enqueue(o1, account_id="ACC-001", broker_name=BROKER)
    page._last_test_entries = queue.list_pending()
    page._last_order_results = [None]          # missing per-order result
    page._order_symbols = {id(o1): "آکو"}
    page._refresh_result_display()
    row = page.result_list.item(0).text()
    assert RESULT_STATUS_FAILED in row
    assert "| موفق |" not in row


# ===========================================================================
# Required 7 — exactly ONE dispatch per Test run (measured path)
# ===========================================================================


class SpyDispatchCore:
    """Records which single dispatch entry point is used; never a broker."""

    def __init__(self, core):
        self._core = core
        self.dispatch_calls = 0
        self.latency_calls = 0

    def dispatch(self, plan):
        self.dispatch_calls += 1
        return self._core.dispatch(plan)

    def dispatch_with_latency(self, plan):
        self.latency_calls += 1
        return self._core.dispatch_with_latency(plan)


def test_7_runner_issues_exactly_one_dispatch_per_run(qapp):
    harness = make_harness()
    spy = SpyDispatchCore(harness.dispatch_core)
    runner = TestRunner(dispatch_core=spy)

    order = make_simulation_order(side=SELL, ins_code="INS-SIM-1")
    account = make_identity_account()
    queue = OrderQueue()
    queue.enqueue(order, account_id=account.account_id, broker_name=BROKER)
    entries = queue.list_pending()

    plan, execution_id, result = runner.run(entries, account=account)

    # exactly ONE dispatch through the existing measured contract; the plain
    # entry point was never called (no double dispatch, no re-execution)
    assert spy.latency_calls == 1
    assert spy.dispatch_calls == 0
    assert runner.last_report is not None
    assert execution_id.startswith("exec-ui5-")
    assert execution_id != plan.plan_id
    assert execution_id == runner.last_execution_id

    # the per-order result is THE result of this very dispatch
    per = runner.last_order_results[0]
    assert per.order is order
    assert per.success is True
    assert per.mode == "DRY_RUN"
    assert harness.broker.place_order_calls == [(order, False)]


def test_7b_page_issues_exactly_one_dispatch_per_action(qapp):
    harness = make_harness()
    store, page = make_page(qapp, harness)
    seam = NscSeam(mapping={"INS-SIM-1": "INS-SIM-1"})
    entry = enqueue_via_page(qapp, page, seam, INSTR_SIM1, SELL, 10_000, 10)

    page.test_button.click()                  # ON  -> run 1
    first_exec = page._last_test_run[1]
    page.test_button.click()                  # OFF -> no run
    page.test_button.click()                  # ON  -> run 2

    assert harness.broker.place_order_calls == [(entry.order, False)] * 2
    assert page._last_test_run[1].startswith("exec-ui5-")
    # a second Test action is a second, DISTINCT execution id
    assert page._last_test_run[1] != first_exec


# ===========================================================================
# Required 8 — exactly ONE final result refresh per Test run
# ===========================================================================


def test_8_one_final_refresh_per_run(qapp):
    from unittest.mock import patch

    harness = make_harness()
    store, page = make_page(qapp, harness)
    seam = NscSeam(mapping={"INS-SIM-1": "INS-SIM-1"})
    enqueue_via_page(qapp, page, seam, INSTR_SIM1, SELL, 10_000, 10)

    original = page._refresh_result_display
    refreshes = {"count": 0}

    def counting():
        refreshes["count"] += 1
        original()

    with patch.object(page, "_refresh_result_display", counting):
        page.test_button.click()                     # ON  -> one refresh
        first_exec = page._last_test_run[1]
        page.test_button.click()                     # OFF -> no refresh
        for _ in range(3):
            page._refresh_test_button_state()        # plain refresh paths
        page.refresh_active_account()
        qapp.processEvents()
        page.test_button.click()                     # ON  -> one refresh

    assert refreshes == {"count": 2}          # exactly one per Test run
    assert page.result_list.count() == 1
    assert page.result_status_label.text() == "1 result(s)"

    # a second official run produced its own single final refresh
    assert page._last_test_run[1] != first_exec


# ===========================================================================
# Required 9 — a second Test run fully replaces the previous rows
# ===========================================================================


def test_9_second_run_fully_replaces_first(qapp):
    harness = make_harness()
    store, page = make_page(qapp, harness)
    seam = NscSeam(mapping={"INS-SIM-1": "INS-SIM-1"})
    entry1 = enqueue_via_page(qapp, page, seam, INSTR_SIM1, SELL, 10_000, 10)

    page.test_button.click()                  # run 1 — success
    assert page.result_list.count() == 1
    first_exec = page._last_test_run[1]
    assert RESULT_STATUS_SUCCESS in page.result_list.item(0).text()

    page.test_button.click()                  # OFF
    page.order_queue.remove(entry1)
    entry2 = enqueue_via_page(qapp, page, seam, INSTR_SIM1, BUY, 10_000, 10)

    page.test_button.click()                  # run 2 — blocked
    assert page.result_list.count() == 1
    row = page.result_list.item(0).text()
    assert RESULT_STATUS_BLOCKED in row
    assert "| موفق |" not in row   # old run fully gone
    assert page._last_test_entries[0] is entry2
    assert page._last_test_run[1] != first_exec
    assert page._last_order_results[0].order is entry2.order
    assert harness.broker.place_order_calls == [(entry1.order, False)]


# ===========================================================================
# Required 10 — no technical information in any result row
# ===========================================================================

FORBIDDEN_TOKENS = (
    "INS-SIM",            # broker nsc_id values / tse ids
    "NSC-",               # any order identity
    "M6-",                # any M6 gate label
    "BLOCKED", "DRY_RUN", "ALL_PROCESSED", "READY", "ERROR",
    "trace", "exec-ui5-", "ui5-test",
    "tradableBalance", "T1", "T2",
    "latency", "perf_counter", "place_order",
    "RuntimeError", "exception", "endpoint",
)


def test_10_no_technical_info_in_result_rows(qapp):
    harness = make_harness()
    store, page = make_page(qapp, harness)
    seam = NscSeam(
        mapping={"INS-SIM-1": "INS-SIM-1", "INS-SIM-2": "INS-SIM-2",
                 "INS-SIM-3": "INS-SIM-3"}
    )
    enqueue_via_page(qapp, page, seam, INSTR_SIM1, BUY, 10_000, 10)
    harness.broker.configure_failure(
        fail_on_nsc_id="INS-SIM-2", fail_mode="exception"
    )
    enqueue_via_page(qapp, page, seam, INSTR_SIM2, SELL, 10_000, 10)
    enqueue_via_page(qapp, page, seam, INSTR_SIM3, SELL, 10_000, 10)

    page.test_button.click()

    rows = [page.result_list.item(i).text() for i in range(page.result_list.count())]
    blob = "\n".join(rows) + "\n" + page.result_status_label.text()
    assert len(rows) == 3
    for token in FORBIDDEN_TOKENS:
        assert token not in blob, f"technical token leaked: {token!r}"
    # the raw per-order messages never surface either (fixed reasons only)
    for result in page._last_order_results:
        assert result.message not in blob


# ===========================================================================
# Extra 3 — a plain dispatch-only core keeps the no-per-order fallback: the
#           single dispatch still happens once and no result is invented
# ===========================================================================


class PlainDispatchCore:
    """Exposes only the plain ``dispatch(plan)`` contract (like Task 2)."""

    def __init__(self):
        self.calls = 0

    def dispatch(self, plan):
        self.calls += 1
        return DispatchResult(
            success=True,
            sent=False,
            mode="ALL_PROCESSED",
            message="fake dispatch: all processed (dry-run)",
            order_count=len(plan.orders),
        )


def test_e3_dispatch_only_core_falls_back_without_invented_results(qapp):
    fake = PlainDispatchCore()
    runner = TestRunner(dispatch_core=fake)
    order = make_simulation_order(side=SELL, ins_code="INS-SIM-1")
    account = make_identity_account()
    queue = OrderQueue()
    queue.enqueue(order, account_id=account.account_id, broker_name=BROKER)
    entries = queue.list_pending()

    plan, execution_id, result = runner.run(entries, account=account)

    assert fake.calls == 1                       # exactly one dispatch
    assert runner.last_report is None
    assert runner.last_order_results is None     # nothing fabricated
    assert execution_id != plan.plan_id


# ===========================================================================
# Extra 1 — empty state before the first Test run
# ===========================================================================


def test_e1_empty_state_before_first_run(qapp):
    store = AccountStore()
    page = OrderConfigurationPage(store, order_queue=OrderQueue())
    assert page.result_status_label is not None
    assert page.result_list is not None
    assert page.result_status_label.text() == RESULT_EMPTY_STATE
    assert page.result_list.count() == 0
    assert page.result_list.parent().title() == "Test Results"


# ===========================================================================
# Extra 2 — the UI keeps the selected symbol (its own layer) at enqueue time
# ===========================================================================


def test_e2_ui_keeps_display_symbol_at_enqueue_time(qapp):
    harness = make_harness()
    store, page = make_page(qapp, harness)
    seam = NscSeam(mapping={"INS-SIM-1": "INS-SIM-1"})
    entry = enqueue_via_page(qapp, page, seam, INSTR_SIM1, SELL, 10_000, 10)

    # the symbol the user picked is kept for THIS exact order object only,
    # and the technical nsc id stays out of the UI layer's result mapping
    assert page._order_symbols[id(entry.order)] == "آکو"
    assert len(page._order_symbols) == 1
    assert isinstance(entry.order, Order)

    page.test_button.click()
    row = page.result_list.item(0).text()
    assert "آکو" in row
    assert "INS-SIM-1" not in row