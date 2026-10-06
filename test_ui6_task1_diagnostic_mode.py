"""
test_ui6_task1_diagnostic_mode.py

UI-6 Task 1 — Diagnostic Mode Foundation + Task 2 — Trace ID
(fully offline tests).

Contract coverage:

    Test 1  — Default mode is NORMAL and the diagnostic section is hidden.
    Test 2  — NORMAL -> DIAGNOSTIC switch via the REAL UI toggle works.
    Test 3  — DIAGNOSTIC -> NORMAL switch back works.
    Test 4  — The diagnostic section is a REAL minimal section with REAL
              content (the last Test pass's per-order execution verdicts,
              built from the actual OrderExecutionResult objects), shown
              only in DIAGNOSTIC mode.
    Test 5  — No ordering behavior change: set_mode / apply_mode / the
              toggle never run, dispatch, or submit anything; queue
              entries, Test state, runner wiring and sent-order logging
              are untouched. Mode changes alone never populate the
              diagnostic section.

    Extra   — MainWindow.set_mode syncs the page's display boundary and
              the toggle; a page built without the window defaults to the
              hidden boundary; apply_mode is fail-closed against foreign
              values (an invalid value HIDES the section and syncs the
              internal state); no technical payload is attached to
              diagnostic items; MainWindow construction still imports no
              core/brokers/market module (UI-1 offline contract).

    Task 2  — the dispatch-level Trace ID line: the Core-built
              ``DispatchResult.trace_id`` of THIS run is shown verbatim
              inside the diagnostic section (DIAGNOSTIC only, section-level
              — never per order, never in the order log); NORMAL keeps it
              hidden; ONLY a real ``core.dispatch_contracts.DispatchResult``
              is accepted (a forged look-alike with a ``trace_id`` attribute
              is rejected); ``None``/blank/non-string/stale-after-failure/
              stopped-run render the unavailable marker and never fabricate
              or substitute an id; ``execution_id`` is never shown as the
              trace id; a failed issue attempt never presents the previous
              run's trace id as the new run's; display changes never touch
              send/UI-5 behavior.

    Task 3  — the latency/execution diagnostics of THIS run's EXISTING
              Block 8 ``DispatchLatencyReport`` (the runner's own
              ``last_report``): the total dispatch window, the four
              individual internal stage durations and Broker/API calls
              from each order record with explicit order/call labels
              (the FULL call — never labelled network latency, never
              summed with stages/total). Categories stay separate; ns ->
              ms is display-only with the unit stated; per-order detail
              is matched ONLY by the real ``Order`` object identity
              (never by list order or symbol); a missing report/stage,
              ``None``/cross-clock values render ناموجود — never a
              fabricated zero; a failed issue attempt never presents the
              previous run's timings as the new run's; NORMAL hides the
              whole section (Trace ID + latencies); display changes never
              touch send/UI-5 behavior; construction still imports no
              core.* module.

These tests are fully offline:
  - no network
  - no login
  - no broker API
  - no TSETMC call
  - no real order (the only "run" is a pure-Python stub runner with the
    runner's existing surface; ``live`` stays False everywhere)

Run:
    pytest -q test_ui6_task1_diagnostic_mode.py
"""

import os
import subprocess
import sys
import time

import pytest

from PySide6.QtWidgets import QApplication

from core.dispatch_contracts import DispatchResult
from core.order_engine import OrderExecutionResult
from core.order_queue import OrderQueue
from models.order import BUY, SELL, Order
from models.instrument import Instrument

from ui.account_store import AccountStore
from ui.main_window import ApplicationMode, MainWindow
from ui.order_configuration_page import (
    DIAGNOSTIC_EMPTY_STATE,
    DIAGNOSTIC_LATENCY_TOTAL_LABEL,
    DIAGNOSTIC_SECTION_TITLE,
    DIAGNOSTIC_LATENCY_BROKER_PREFIX,
    DIAGNOSTIC_LATENCY_STAGE_PREFIX,
    DIAGNOSTIC_TRACE_LABEL,
    DIAGNOSTIC_TRACE_UNAVAILABLE,
    DIAGNOSTIC_VALUE_UNAVAILABLE,
    OrderConfigurationPage,
)
from ui import strings as STRINGS


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

BROKER = "SIM"


@pytest.fixture(scope="module")
def qapp():
    """Reuse the process-wide QApplication if one exists, else create one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def make_page(qapp):
    """A real page with an active account and a real in-memory queue."""
    store = AccountStore()
    store.add("ACC-001", BROKER, "ACC-001")
    store.set_active("ACC-001")
    return OrderConfigurationPage(store, order_queue=OrderQueue())


class _Entry:
    """Minimal entry surface the page reads (same convention as UI-5)."""

    def __init__(self, order, account_id="ACC-001", broker_name=BROKER):
        self.order = order
        self.account_id = account_id
        self.broker_name = broker_name


class _StubRunner:
    """
    The existing runner surface, offline and pure-Python: run() returns
    real OrderExecutionResult models (dry-run shaped, never live) and
    exposes ``last_order_results`` exactly like the real runner. Task 3:
    it also exposes the runner's existing ``last_report`` contract — an
    OPTIONAL report of THIS run (``None`` on the plain/test-double path,
    exactly like the real runner).
    """

    last_order_results = None
    last_report = None

    def __init__(self, results, dispatch_result=None, report=None):
        self._results = results
        self._dispatch_result = dispatch_result
        self.report = report
        self.run_calls = []

    def run(self, entries, account=None):
        self.run_calls.append((list(entries), account))
        # Order identity: each result owns the SAME Order object the
        # queue entry carries — the per-order matching rule (Task 3).
        self.last_order_results = list(self._results)
        self.last_report = self.report
        # The existing runner returns (plan, execution_id, result); the
        # stub keeps that exact surface so the page's pass runs unchanged.
        # The third member is the run's real DispatchResult (it may carry
        # the Core-built trace_id — UI-6 Task 2).
        return None, "exec-ui5-1", self._dispatch_result


def _latency_report(result, application_side_ns=1_500_000):
    """
    A REAL Block 8 ``DispatchLatencyReport`` (offline — pure stdlib
    dataclasses, no dispatch, no clock, no broker): one measured order
    with the four recorded stages, one recorded Broker/API round trip
    and the collector's own application-side value. The record's
    ``execution_result`` owns the SAME ``Order`` the run dispatched (the
    per-order identity rule).
    """
    from core.latency_instrumentation import (
        BrokerApiCallTiming,
        DispatchLatencyReport,
        OrderLatency,
        StageTiming,
    )

    order = result.order
    record = OrderLatency(
        sequence=1,
        account_id="ACC-001",
        broker_name=BROKER,
        ins_code="1",
        stages=[
            StageTiming("plan_item", 0, 1_000_000),
            StageTiming("plan_account", 1_000_000, 2_500_000),
            StageTiming("instrument_resolution", 2_500_000, 4_000_000),
            StageTiming("order_engine_path", 4_000_000, 11_000_000),
        ],
        execution_result=result,
        broker_api_calls=[
            BrokerApiCallTiming("place_order", 4_500_000, 9_000_000)
        ],
        application_side_ns=application_side_ns,
    )
    return DispatchLatencyReport(
        trace_id="TRACE-UI6-0001",
        dispatch_start=0,
        dispatch_end=12_345_678,
        orders=[record],
    )


class _StubNscSeam:
    """
    Mimics the broker InstrumentProvider surface (``get_nsc_id``) — the
    same offline stub convention as the UI-4 queue tests. No network.
    """

    def __init__(self, nsc_id="NSC-ID-1"):
        self.nsc_id = nsc_id

    def get_nsc_id(self, ins_code):
        return self.nsc_id


def _dry_run_result(order, success=True):
    """A REAL core OrderExecutionResult in its existing dry-run shape."""
    return OrderExecutionResult(
        success=success,
        sent=True,
        mode="DRY_RUN" if success else "BLOCKED",
        order=order,
        broker_name=BROKER,
        message="dry-run" if success else "preflight blocked",
        response=None,
    )


def _dispatch_result(trace_id="TRACE-UI6-0001"):
    """The dispatch-level result shape the real runner returns (Task 8.2)."""
    return DispatchResult(
        success=True,
        sent=True,
        mode="DRY_RUN",
        message="offline dispatch",
        broker_name=BROKER,
        order_count=1,
        trace_id=trace_id,
    )


def _wire_and_run(page, orders, results, dispatch_result=None, report=None):
    """The EXISTING pass path: wire a stub runner, prepare the queue, run."""
    runner = _StubRunner(
        results, dispatch_result=dispatch_result, report=report
    )
    page.set_test_runner_factory(lambda: runner)
    page.config.select_instrument(
        Instrument(symbol="\u0622\u06a9\u0648", name="\u0622\u06a9\u0648", ins_code="1")
    )
    for order in orders:
        page.order_queue.enqueue(
            order, account_id="ACC-001", broker_name=BROKER
        )
    page._test_mode = True
    page._run_test_pass()
    return runner


# ============================================================
# Test 1 — default mode
# ============================================================


def test_1_default_mode_is_normal_and_section_hidden(qapp):
    window = MainWindow()
    page = window.order_configuration_page

    assert window.mode is ApplicationMode.NORMAL
    assert page.is_diagnostic_visible() is False
    # The real widget exists but is hidden (NORMAL is the shipped default).
    assert page.diagnostic_section.isVisibleTo(page) is False


# ============================================================
# Test 2 — NORMAL -> DIAGNOSTIC via the real toggle
# ============================================================


def test_2_switch_to_diagnostic_via_ui_toggle(qapp):
    window = MainWindow()
    page = window.order_configuration_page

    # A real user click on the toggle (unchecked -> checked).
    window.mode_toggle.click()

    assert window.mode is ApplicationMode.DIAGNOSTIC
    assert window.mode_toggle.isChecked() is True
    assert page.is_diagnostic_visible() is True


# ============================================================
# Test 3 — DIAGNOSTIC -> NORMAL via the real toggle
# ============================================================


def test_3_switch_back_to_normal_via_ui_toggle(qapp):
    window = MainWindow()
    page = window.order_configuration_page

    window.mode_toggle.click()   # -> DIAGNOSTIC
    window.mode_toggle.click()   # -> NORMAL

    assert window.mode is ApplicationMode.NORMAL
    assert window.mode_toggle.isChecked() is False
    assert page.is_diagnostic_visible() is False


# ============================================================
# Test 4 — the diagnostic section is real and mode-gated
# ============================================================


class TestDiagnosticSectionIsRealAndModeGated:
    def test_real_section_with_real_verdicts_shown_only_in_diagnostic(
        self, qapp
    ):
        page = make_page(qapp)
        order = Order(nsc_id="NSC-1", side=BUY, price=100, quantity=1)
        page._order_symbols[id(order)] = "\u0622\u06a9\u0648"
        _wire_and_run(page, [order], [_dry_run_result(order, success=True)])

        # Before any mode application: the shipped default (hidden).
        assert page.is_diagnostic_visible() is False
        # The content exists for real and comes from the REAL result model.
        assert page.diagnostic_list.count() == 1
        item_text = page.diagnostic_list.item(0).text()
        assert DIAGNOSTIC_SECTION_TITLE in page.diagnostic_section.title()
        assert STRINGS.DIAGNOSTIC_ENTRY_PREFIX.format(position=1) in item_text
        assert "\u0622\u06a9\u0648" in item_text
        assert "\u0645\u0648\u0641\u0642" in item_text

        # NORMAL: hidden — the section's real content is not disclosed.
        window = MainWindow()
        window.order_configuration_page.apply_mode = (
            page.apply_mode  # drive the SAME page object's boundary
        )
        window.set_mode(ApplicationMode.NORMAL)
        assert page.is_diagnostic_visible() is False
        assert page.diagnostic_section.isVisibleTo(page) is False

        # DIAGNOSTIC: the same real content may be shown.
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        assert page.diagnostic_section.isVisibleTo(page) is True
        assert page.diagnostic_list.count() == 1

    def test_empty_state_before_any_test_pass(self, qapp):
        page = make_page(qapp)
        window = MainWindow()
        # Bind the window's mode propagation to this standalone page.
        real_apply = window.order_configuration_page.apply_mode

        def _redirect(mode):
            page.apply_mode(mode)
            return None

        real_apply.__self__  # keep a reference alive (style only)
        window.order_configuration_page.apply_mode = _redirect

        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        # Real empty state: no Test pass has run — nothing is invented.
        assert page.diagnostic_list.count() == 0
        assert page.diagnostic_status_label.text() == DIAGNOSTIC_EMPTY_STATE

    def test_fail_closed_against_foreign_mode_values(self, qapp):
        page = make_page(qapp)

        class _Foreign:
            name = "DIAGNOSTIC"  # a duck that is NOT the real enum

        # Baseline: NORMAL keeps the section hidden.
        for bad in (_Foreign(), "DIAGNOSTIC", None, 1):
            page.apply_mode(bad)
            assert page.is_diagnostic_visible() is False

        # A valid mode enables the section (unchanged behavior).
        page.apply_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        assert page.diagnostic_section.isVisibleTo(page) is True

        # ANY non-valid value (foreign duck, raw string, None, int) HIDES
        # the section and syncs the internal visibility state with it —
        # an unknown value never leaves the section unmasked.
        for bad in (_Foreign(), "DIAGNOSTIC", None, 1):
            page.apply_mode(bad)
            assert page.is_diagnostic_visible() is False
            assert page.diagnostic_section.isVisibleTo(page) is False

        # Valid modes keep behaving exactly as before.
        page.apply_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        page.apply_mode(ApplicationMode.NORMAL)
        assert page.is_diagnostic_visible() is False
        assert page.diagnostic_section.isVisibleTo(page) is False


# ============================================================
# UI-6 Task 2 — the dispatch-level Trace ID line
# ============================================================


class TestDiagnosticTraceId:
    """
    The Trace ID shown is the Core-built ``DispatchResult.trace_id`` of
    THIS run — never created, defaulted or substituted by the UI, never
    attributed to a single order, and visible only inside the mode-gated
    diagnostic section.
    """

    def test_real_trace_id_of_this_run_shown_in_diagnostic(self, qapp):
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        order = Order(nsc_id="NSC-T1", side=BUY, price=100, quantity=1)
        page._order_symbols[id(order)] = "\u0622\u06a9\u0648"
        _wire_and_run(
            page,
            [order],
            [_dry_run_result(order, success=True)],
            dispatch_result=_dispatch_result("TRACE-UI6-0001"),
        )

        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        # The shown value is THIS run's real trace id, verbatim.
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + "TRACE-UI6-0001"
        )
        # The trace id is a SECTION-level line: not attached to any
        # per-order item and never rendered into the order-log table.
        for row in range(page.diagnostic_list.count()):
            assert "TRACE-UI6-0001" not in page.diagnostic_list.item(row).text()
        for r in range(page.order_log_table.rowCount()):
            for c in range(page.order_log_table.columnCount()):
                cell = page.order_log_table.item(r, c)
                assert cell is None or "TRACE-UI6-0001" not in cell.text()

    def test_trace_id_hidden_in_normal_mode(self, qapp):
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        order = Order(nsc_id="NSC-T2", side=BUY, price=10, quantity=1)
        _wire_and_run(
            page,
            [order],
            [_dry_run_result(order, success=True)],
            dispatch_result=_dispatch_result("TRACE-UI6-0002"),
        )
        # NORMAL: the whole section — and with it the trace id — stays
        # hidden even though the run's trace id exists. The label is
        # never visible to the page while its section is hidden.
        window.set_mode(ApplicationMode.NORMAL)
        assert page.is_diagnostic_visible() is False
        assert page.diagnostic_section.isVisibleTo(page) is False
        assert page.trace_id_label.isVisibleTo(page) is False
        assert page.trace_id_label.isVisible() is False
        # Switching to DIAGNOSTIC reveals the same run's real trace id.
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + "TRACE-UI6-0002"
        )

    def test_missing_blank_and_nodispatch_never_fabricate(self, qapp):
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        # 1) trace_id=None on a real dispatch result.
        order = Order(nsc_id="NSC-T3", side=BUY, price=1, quantity=1)
        _wire_and_run(
            page,
            [order],
            [_dry_run_result(order)],
            dispatch_result=_dispatch_result(trace_id=None),
        )
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )

        # 2) A blank trace id (whitespace only).
        page._last_test_run = (
            None,
            "exec-ui5-2",
            _dispatch_result(trace_id="   "),
        )
        page._refresh_diagnostic_display()
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )

        # 3) A result object WITHOUT a trace_id attribute at all.
        class _NoTrace:
            pass

        page._last_test_run = (None, "exec-ui5-3", _NoTrace())
        page._refresh_diagnostic_display()
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )

        # 4) A halted pre-dispatch pass: nothing was stored and NO id of
        #    any kind is invented.
        page._last_test_run = None
        page._refresh_diagnostic_display()
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )

        # 5) A non-string trace id is rejected the same way.
        page._last_test_run = (
            None,
            "exec-ui5-4",
            _dispatch_result(trace_id=12345),
        )
        page._refresh_diagnostic_display()
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )

    def test_execution_id_is_never_shown_as_trace_id(self, qapp):
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        order = Order(nsc_id="NSC-T4", side=BUY, price=5, quantity=1)
        # A run whose dispatch carries NO trace id, with a distinctive
        # execution id: the execution id must never appear in its place.
        _wire_and_run(
            page,
            [order],
            [_dry_run_result(order)],
            dispatch_result=_dispatch_result(trace_id=None),
        )
        assert page._diagnostic_trace_id() is None
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )
        assert "exec-ui5-1" not in page.trace_id_label.text()
        # The extractor itself never returns the execution id either.
        assert page._last_test_run[1] == "exec-ui5-1"
        assert page._diagnostic_trace_id() is None

    def test_invalid_result_carrying_trace_id_is_rejected(self, qapp):
        """
        ONLY a real ``DispatchResult`` is accepted: a look-alike object
        carrying a (forged) ``trace_id`` attribute is rejected and renders
        the unavailable marker — no look-alike ever unmasks the line.
        """
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        class _ForgedResult:  # a dict-like look-alike, NOT a DispatchResult
            trace_id = "forged-trace-should-never-show"

        page._last_test_run = (None, "exec-ui5-f", _ForgedResult())
        page._refresh_diagnostic_trace_display()
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )
        # The same behavior holds through the full display refresh.
        page._refresh_diagnostic_display()
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )

        # A real DispatchResult with the same id still renders verbatim.
        from core.dispatch_contracts import DispatchResult

        page._last_test_run = (
            None,
            "exec-ui5-f",
            DispatchResult(
                success=True,
                sent=True,
                mode="DRY_RUN",
                trace_id="forged-trace-should-never-show",
            ),
        )
        page._refresh_diagnostic_trace_display()
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + "forged-trace-should-never-show"
        )

    def test_stale_trace_of_failed_issue_never_shown_as_new_run(self, qapp):
        """
        A failed/halted issue attempt must never let the PREVIOUS run's
        trace id pass as the new run's: while ``_last_test_error`` is set
        the stored tuple is treated as stale and the line shows the
        unavailable marker; only a NEW completed run may show a trace id
        again.
        """
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        # 1) A first successful run with a real trace id.
        order = Order(nsc_id="NSC-T6", side=BUY, price=3, quantity=1)
        page._order_symbols[id(order)] = "\u0622\u06a9\u0648"

        class _FailingRunner:
            last_order_results = None

            def run(self, entries, account=None):
                raise RuntimeError("issue failed before dispatch")

        page.set_test_runner_factory(lambda: _FailingRunner())
        page.config.select_instrument(
            Instrument(symbol="\u0622\u06a9\u0648", name="\u0622\u06a9\u0648", ins_code="1")
        )
        page.order_queue.enqueue(
            order, account_id="ACC-001", broker_name=BROKER
        )
        page._test_mode = True
        page._run_test_pass()  # fails BEFORE dispatch (fail-closed path)
        assert page._last_test_error is not None
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        # No trace id of ANY run is shown for the failed pass.
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )

        # 2) The explicit stale-guard contract: a stored PREVIOUS run's
        #    result while an error is recorded is treated as stale.
        from core.dispatch_contracts import DispatchResult

        page._last_test_run = (
            None,
            "exec-ui5-old",
            DispatchResult(
                success=True,
                sent=True,
                mode="DRY_RUN",
                trace_id="PREVIOUS-RUN-TRACE",
            ),
        )
        page._refresh_diagnostic_trace_display()
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )
        assert "PREVIOUS-RUN-TRACE" not in page.trace_id_label.text()

        # 3) A real pre-dispatch STOPPED result carries trace_id=None:
        #    it renders unavailable — no fabricated id (same contract as
        #    test_missing_blank_and_nodispatch_never_fabricate case 1).
        page._last_test_error = None
        page._last_test_run = (
            None,
            "exec-ui5-stop",
            DispatchResult(
                success=False,
                sent=False,
                mode="STOPPED",
                trace_id=None,
            ),
        )
        page._refresh_diagnostic_trace_display()
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )

        # 4) Only a NEW completed run shows its own trace id again.
        page._last_test_error = None
        page._last_test_run = (
            None,
            "exec-ui5-new",
            DispatchResult(
                success=True,
                sent=True,
                mode="DRY_RUN",
                trace_id="NEW-RUN-TRACE",
            ),
        )
        page._refresh_diagnostic_trace_display()
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + "NEW-RUN-TRACE"
        )

    def test_stale_trace_cleared_immediately_after_failed_issue(self, qapp):
        """
        Required corrective scenario: with the section VISIBLE
        (DIAGNOSTIC), a successful run shows its trace id; the NEXT issue
        failing BEFORE dispatch must wipe that stale trace id from the
        screen IMMEDIATELY (no mode change, no extra action) — the old
        run's id is never left on display as the failed run's.
        """
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        # 1) A successful run with a known trace id, section visible.
        order = Order(nsc_id="NSC-T7", side=BUY, price=9, quantity=1)
        page._order_symbols[id(order)] = "\u0622\u06a9\u0648"
        _wire_and_run(
            page,
            [order],
            [_dry_run_result(order)],
            dispatch_result=_dispatch_result("GOOD-TRACE-0001"),
        )
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + "GOOD-TRACE-0001"
        )

        # 2) The next issue fails BEFORE dispatch (queue keeps its entry,
        #    exactly like the real pass path). The error handler itself —
        #    not a mode change — must refresh the trace line.
        class _FailingRunner:
            last_order_results = None

            def run(self, entries, account=None):
                raise RuntimeError("issue failed before dispatch")

        # The page caches its runner (existing UI-5 contract); the test
        # resets that cache to inject the failing runner for the NEXT pass.
        page._test_runner_instance = None
        page.set_test_runner_factory(lambda: _FailingRunner())
        page._test_mode = True
        page._run_test_pass()

        # 3) No mode change, no extra action: the stale id is already gone.
        assert page._last_test_error is not None
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
        )
        assert "GOOD-TRACE-0001" not in page.trace_id_label.text()

        # 4) Existing behavior intact: the error is surfaced, no new
        #    dispatch happened, and a completed NEW run shows its own id.
        assert (
            STRINGS.TEST_ISSUE_FAILED.split("{", 1)[0]
            in page.queue_status_label.text()
        )
        page._test_runner_instance = None
        page.set_test_runner_factory(
            lambda: _StubRunner(
                [_dry_run_result(order)],
                dispatch_result=_dispatch_result("GOOD-TRACE-0002"),
            )
        )
        page._run_test_pass()
        assert page._last_test_error is None
        assert page.trace_id_label.text() == (
            DIAGNOSTIC_TRACE_LABEL + "GOOD-TRACE-0002"
        )

    def test_trace_display_changes_no_send_behavior(self, qapp):
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        order = Order(nsc_id="NSC-T5", side=BUY, price=7, quantity=1)
        page._order_symbols[id(order)] = "\u0622\u06a9\u0648"
        runner = _wire_and_run(
            page,
            [order],
            [_dry_run_result(order)],
            dispatch_result=_dispatch_result("TRACE-UI6-0005"),
        )
        before = (
            len(page.order_log),
            len(runner.run_calls),
            len(page.order_queue.list_pending()),
        )
        # Every mode transition changes ONLY what is displayed.
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        shown = page.trace_id_label.text()
        assert shown == DIAGNOSTIC_TRACE_LABEL + "TRACE-UI6-0005"
        window.set_mode(ApplicationMode.NORMAL)
        assert page.is_diagnostic_visible() is False
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.trace_id_label.text() == shown
        # The run, log, queue and Test state are all untouched.
        assert (
            len(page.order_log),
            len(runner.run_calls),
            len(page.order_queue.list_pending()),
        ) == before
        assert page._test_mode is True
        page._test_mode = False


# ============================================================
# Test 5 — no ordering-behavior impact
# ============================================================


class TestNoOrderingBehaviorImpact:
    def test_mode_changes_never_run_or_dispatch_anything(self, qapp):
        page = make_page(qapp)
        runner = _StubRunner([])  # counts run() calls
        page.set_test_runner_factory(lambda: runner)

        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        for mode in (
            ApplicationMode.DIAGNOSTIC,
            ApplicationMode.NORMAL,
            ApplicationMode.DIAGNOSTIC,
        ):
            window.set_mode(mode)
        # The runner was never invoked by any mode change.
        assert runner.run_calls == []
        # The queue is still empty and the Test toggle is OFF by default.
        assert page.order_queue.list_pending() == []
        assert page.test_button.isChecked() is False
        assert page._test_mode is False

    def test_full_send_pass_and_mode_change_are_orthogonal(self, qapp):
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        # 1) A real (offline, stubbed) dry-run pass in NORMAL mode.
        order = Order(nsc_id="NSC-2", side=BUY, price=50, quantity=2)
        page._order_symbols[id(order)] = "\u0622\u06a9\u0648"
        runner = _wire_and_run(
            page, [order], [_dry_run_result(order, success=True)]
        )
        assert len(runner.run_calls) == 1
        sent_at = runner.run_calls[0][1]  # account object handed to runner
        assert sent_at is not None
        # The order log got its one row (existing send behavior unchanged).
        assert len(page.order_log) == 1

        # 2) Mode changes around the pass change ONLY the boundary.
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        assert len(page.order_log) == 1
        window.set_mode(ApplicationMode.NORMAL)
        assert page.is_diagnostic_visible() is False
        assert len(page.order_log) == 1
        # The pass itself: still exactly one, queue still holds no extra
        # entries, and no retry happened.
        assert len(runner.run_calls) == 1
        assert page._test_mode is True  # Test Mode state untouched by mode
        page._test_mode = False  # restore the UI-5 toggle convention
        assert page.test_button.isChecked() is False

    def test_send_pass_with_blocked_result_stays_blocked_in_both_modes(
        self, qapp
    ):
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        order = Order(nsc_id="NSC-3", side=SELL, price=10, quantity=1)
        page._order_symbols[id(order)] = "\u0622\u06a9\u0648"
        _wire_and_run(page, [order], [_dry_run_result(order, success=False)])

        # The verdict mirrors the REAL result model in both modes.
        for mode in (ApplicationMode.NORMAL, ApplicationMode.DIAGNOSTIC):
            window.set_mode(mode)
            assert page.diagnostic_list.count() == 1
            text = page.diagnostic_list.item(0).text()
            assert "\u0645\u0633\u062f\u0648\u062f\u0634\u062f\u0647" in text


# ============================================================
# Extra — mode-state consistency and UI-1 offline contracts
# ============================================================


def test_extra_set_mode_syncs_toggle_and_boundary(qapp):
    window = MainWindow()
    page = window.order_configuration_page

    window.set_mode(ApplicationMode.DIAGNOSTIC)
    assert window.mode_toggle.isChecked() is True
    assert page.is_diagnostic_visible() is True
    window.set_mode(ApplicationMode.NORMAL)
    assert window.mode_toggle.isChecked() is False
    assert page.is_diagnostic_visible() is False


def test_extra_standalone_page_defaults_hidden_and_diagnostic_items_carry_no_payload(
    qapp,
):
    page = make_page(qapp)
    assert page.is_diagnostic_visible() is False

    order = Order(nsc_id="NSC-4", side=BUY, price=1, quantity=1)
    _wire_and_run(page, [order], [_dry_run_result(order, success=True)])
    for row in range(page.diagnostic_list.count()):
        item = page.diagnostic_list.item(row)
        # No technical payload rides on the display items.
        assert item.data(0x20) in (None, "")  # Qt.UserRole stays empty
        assert "DEC-" not in item.text()      # no decisionId-like value


def test_extra_main_window_construction_stays_offline():
    code = "\n".join(
        [
            "import sys",
            "import ui.app as ui_app",
            "from ui.main_window import MainWindow",
            "app = ui_app.create_app([])",
            "window = MainWindow()",
            "banned = ('brokers', 'market', 'core', 'main')",
            "leaked = sorted(m for m in sys.modules if m.split('.')[0] in banned)",
            "assert not leaked, f'UI imported trading modules: {leaked}'",
            "assert window.mode_toggle is not None",
            "assert window.order_configuration_page.is_diagnostic_visible() is False",
            "print('UI6_OFFLINE_OK')",
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
    assert "UI6_OFFLINE_OK" in result.stdout

# ============================================================
# UI-6 Task 3 — latency & execution diagnostics (Block 8 report)
# ============================================================


class TestDiagnosticLatencyDisplay:
    """
    The latency/execution diagnostics are THIS run's EXISTING Block 8
    ``DispatchLatencyReport`` — consumed (rendered), never re-measured or
    re-derived: the total dispatch window, individual internal stage
    durations and Broker/API calls from each order record with explicit
    order/call labels (the FULL call — never network latency, never
    combined across orders or summed with the other categories), and
    the application split ONLY as the report itself states it. Categories
    stay separate; ns->ms is display-only; the per-order identity is the
    real ``Order`` object; missing stages/values and a missing report or
    failed issue render ناموجود — never a fabricated zero — and the
    previous run's data is never presented as the new run's.
    """

    STAGE_MS = {
        "plan_item": "1.000 ms",
        "plan_account": "1.500 ms",
        "instrument_resolution": "1.500 ms",
        "order_engine_path": "7.000 ms",
    }

    def _diag_texts(self, page):
        return [
            page.latency_detail_list.item(i).text()
            for i in range(page.latency_detail_list.count())
        ]

    def _stage_rows(self, page):
        return {
            (text.split("مرحله ", 1)[1].split(":", 1)[0]): text
            for text in self._diag_texts(page)
            if "مرحله " in text
        }

    def _run_with_report(self, qapp, order=None, application_side_ns=1500000):
        order = order or Order(nsc_id="NSC-L1", side=BUY, price=7, quantity=1)
        result = _dry_run_result(order)
        report = _latency_report(
            result, application_side_ns=application_side_ns
        )
        page = make_page(qapp)
        _wire_and_run(
            page,
            [order],
            [result],
            dispatch_result=_dispatch_result(),
            report=report,
        )
        page.apply_mode(ApplicationMode.DIAGNOSTIC)
        return page

    def test_1_this_runs_report_shown_in_diagnostic(self, qapp):
        # The REAL Add-to-Queue path records the identity-keyed symbol for
        # THIS exact Order object (the per-order identity rule — never a
        # list-position or symbol guess).
        page = make_page(qapp)
        page.set_order_identity_factory(lambda: _StubNscSeam("NSC-ID-1"))
        page.config.select_instrument(
            Instrument(
                symbol="آکو",
                name="آکو",
                ins_code="1",
            )
        )
        page.config.set_side(BUY)
        page.config.set_price(7)
        page.config.set_quantity(1)
        page._start_order_identity_resolution(
            page.config.selected_instrument
        )
        page.wait_for_order_identity_workers(timeout_ms=10000)
        # The same event-loop pulse convention as the UI-4 queue tests:
        # the identity signal is delivered through the queued connection.
        for _ in range(30):
            qapp.processEvents()
            time.sleep(0.005)
        qapp.processEvents()
        assert page._on_add_to_queue() is True
        order = page.order_queue.list_pending()[0].order
        result = _dry_run_result(order)
        report = _latency_report(result)
        runner = _StubRunner(
            [result],
            dispatch_result=_dispatch_result(),
            report=report,
        )
        page.set_test_runner_factory(lambda: runner)
        page._test_mode = True
        page._run_test_pass()
        page.apply_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        # The report of THIS run, converted for display only.
        assert page.latency_total_label.text().endswith("12.346 ms")
        stage_rows = self._stage_rows(page)
        for stage, ms in self.STAGE_MS.items():
            assert stage_rows[stage].endswith(ms), stage_rows
        assert any(
            "Broker/API place_order #1" in t and t.endswith("4.500 ms")
            for t in self._diag_texts(page)
        )
        # The order label is the IDENTITY-KEYED symbol of THIS run's own
        # Order object.
        assert any(
            "Order آکو" in t
            and t.endswith("1.500 ms")   # application_side_ns of THIS record
            for t in self._diag_texts(page)
        )

    def test_2_normal_mode_hides_all_latency_data(self, qapp):
        page = self._run_with_report(qapp)
        assert page.latency_total_label.text().endswith("12.346 ms")
        assert page.latency_detail_list.count() > 0
        page.apply_mode(ApplicationMode.NORMAL)
        assert page.is_diagnostic_visible() is False
        # The latency widgets live INSIDE the mode-gated section: the
        # boundary hides them all (the run's data stays rendered on the
        # widgets, but nothing is visible in NORMAL).
        assert page.diagnostic_section.isVisibleTo(page) is False
        assert page.latency_detail_list.isVisibleTo(page) is False
        assert page.latency_total_label.isVisibleTo(page) is False
        assert page.latency_detail_list.count() > 0

    def test_3_categories_rendered_separately_not_summed(self, qapp):
        page = self._run_with_report(qapp)
        texts = self._diag_texts(page)
        total = page.latency_total_label.text()
        # Every value is its own category's own measurement (exact ms of
        # the report's own numbers) — never the total or another
        # category's sum.
        assert total.endswith("12.346 ms")           # dispatch window
        assert self._stage_rows(page)["order_engine_path"].endswith(
            "7.000 ms"                                # engine stage alone
        )
        assert any(
            "Broker/API place_order #1" in t and t.endswith("4.500 ms")
            for t in texts
        )  # individual broker call
        assert any(t.endswith("1.500 ms") for t in texts)   # app-side value
        # No display line carries an artificial sum (e.g. the 11.500 ms of
        # stage + broker) and no line is labelled network latency.
        assert not any("11.500" in t or "15.500" in t for t in texts)
        assert not any(
            "network" in t or "\u0634\u0628\u06a9\u0647" in t for t in texts
        )

    def test_4_missing_values_and_missing_report_stay_unavailable(self, qapp):
        # (a) missing application values on the record: the split lines
        # render the unavailable marker (never 0, never estimated).
        page = self._run_with_report(qapp, application_side_ns=None)
        app_rows = [t for t in self._diag_texts(page) if "application" in t]
        assert len(app_rows) == 3
        assert all(t.endswith(DIAGNOSTIC_VALUE_UNAVAILABLE) for t in app_rows)
        assert not any(
            ".000 ms" in t and "application" in t
            for t in self._diag_texts(page)
        )
        # A missing named stage is explicit rather than omitted or zero.
        report = page._last_latency_report
        report.orders[0].stages = [
            timing for timing in report.orders[0].stages
            if timing.stage_name != "plan_account"
        ]
        page._refresh_diagnostic_latency_display()
        missing_stage = next(
            t for t in self._diag_texts(page)
            if "مرحله plan_account" in t
        )
        assert missing_stage.endswith(DIAGNOSTIC_VALUE_UNAVAILABLE)
        assert ".000 ms" not in missing_stage
        # (b) NO report at all (plain/test-double runner path): the total
        # shows ناموجود and the detail list stays empty — no fabricated
        # zero anywhere.
        order = Order(nsc_id="NSC-L2", side=BUY, price=3, quantity=1)
        result = _dry_run_result(order)
        page2 = make_page(qapp)
        _wire_and_run(
            page2,
            [order],
            [result],
            dispatch_result=_dispatch_result(),
            report=None,
        )
        page2.apply_mode(ApplicationMode.DIAGNOSTIC)
        assert page2.latency_total_label.text() == (
            DIAGNOSTIC_LATENCY_TOTAL_LABEL + DIAGNOSTIC_VALUE_UNAVAILABLE
        )
        assert page2.latency_detail_list.count() == 0

    def test_8_multiple_orders_and_calls_are_individually_labeled(self, qapp):
        from core.latency_instrumentation import BrokerApiCallTiming

        order_a = Order(nsc_id="NSC-A", side=BUY, price=7, quantity=1)
        order_b = Order(nsc_id="NSC-B", side=BUY, price=8, quantity=1)
        result_a = _dry_run_result(order_a)
        result_b = _dry_run_result(order_b)
        report = _latency_report(result_a)
        record_b = _latency_report(result_b).orders[0]
        record_b.stages[0] = type(record_b.stages[0])(
            "plan_item", 0, 3_000_000
        )
        record_b.broker_api_calls = [
            BrokerApiCallTiming("place_order", 0, 2_000_000),
            BrokerApiCallTiming("place_order", 2_000_000, 5_000_000),
        ]
        report.orders.append(record_b)

        page = make_page(qapp)
        page._order_symbols[id(order_a)] = "ORDER-A"
        page._order_symbols[id(order_b)] = "ORDER-B"
        _wire_and_run(
            page,
            [order_a, order_b],
            [result_a, result_b],
            dispatch_result=_dispatch_result(),
            report=report,
        )
        page.apply_mode(ApplicationMode.DIAGNOSTIC)
        texts = self._diag_texts(page)

        assert any(
            DIAGNOSTIC_LATENCY_STAGE_PREFIX.format(
                order="ORDER-A", stage="plan_item"
            ) in t
            and t.endswith("1.000 ms") for t in texts
        )
        assert any(
            DIAGNOSTIC_LATENCY_STAGE_PREFIX.format(
                order="ORDER-B", stage="plan_item"
            ) in t
            and t.endswith("3.000 ms") for t in texts
        )
        # Same operation name is not collapsed into a cross-order sum;
        # each measured call has its own order and call number.
        assert any(
            DIAGNOSTIC_LATENCY_BROKER_PREFIX.format(
                order="ORDER-A", operation="place_order", call_number=1
            ) in t
            and t.endswith("4.500 ms") for t in texts
        )
        assert any(
            DIAGNOSTIC_LATENCY_BROKER_PREFIX.format(
                order="ORDER-B", operation="place_order", call_number=1
            ) in t
            and t.endswith("2.000 ms") for t in texts
        )
        assert any(
            DIAGNOSTIC_LATENCY_BROKER_PREFIX.format(
                order="ORDER-B", operation="place_order", call_number=2
            ) in t
            and t.endswith("3.000 ms") for t in texts
        )
        assert not any(t.endswith("9.500 ms") for t in texts)

    def test_5_failed_issue_never_shows_previous_run_data(self, qapp):
        page = self._run_with_report(qapp)   # run 1: full data on display
        assert page.latency_total_label.text().endswith("12.346 ms")
        assert page.latency_detail_list.count() > 0

        class _FailingRunner:
            last_order_results = None
            last_report = None

            def run(self, entries, account=None):
                raise RuntimeError("issue failed before dispatch")

        # The page caches its runner (existing UI-5 contract); the test
        # resets the cache to inject the failing runner for the NEXT pass.
        page._test_runner_instance = None
        page.set_test_runner_factory(lambda: _FailingRunner())
        page._test_mode = True
        page._run_test_pass()

        # No mode change, no extra action: the previous run's timings are
        # gone immediately — total ناموجود, detail list empty, and none of
        # run 1's values anywhere on display.
        assert page._last_test_error is not None
        assert page.latency_total_label.text() == (
            DIAGNOSTIC_LATENCY_TOTAL_LABEL + DIAGNOSTIC_VALUE_UNAVAILABLE
        )
        assert page.latency_detail_list.count() == 0
        assert "12.346" not in page.latency_total_label.text()
        for i in range(page.latency_detail_list.count()):
            assert "12.346" not in page.latency_detail_list.item(i).text()
        # Existing failure behavior intact: the error is surfaced, no new
        # dispatch happened, and a completed NEW run shows its own data.
        assert (
            STRINGS.TEST_ISSUE_FAILED.split("{", 1)[0]
            in page.queue_status_label.text()
        )
        order2 = Order(nsc_id="NSC-L3", side=BUY, price=2, quantity=1)
        result2 = _dry_run_result(order2)
        page._order_symbols[id(order2)] = "\u0641\u0648\u0644\u0627\u062f"
        page._test_runner_instance = None
        page.set_test_runner_factory(
            lambda: _StubRunner(
                [result2],
                dispatch_result=_dispatch_result(),
                report=_latency_report(result2, application_side_ns=2000000),
            )
        )
        page._test_mode = True
        page._run_test_pass()
        assert page.latency_total_label.text().endswith("12.346 ms")
        assert page.latency_detail_list.count() > 0

    def test_6_display_changes_touch_no_send_behavior(self, qapp):
        order = Order(nsc_id="NSC-L4", side=BUY, price=5, quantity=1)
        result = _dry_run_result(order)
        page = make_page(qapp)
        runner = _wire_and_run(
            page,
            [order],
            [result],
            dispatch_result=_dispatch_result(),
            report=_latency_report(result),
        )
        calls_before = len(runner.run_calls)
        entries_before = len(page.order_queue.list_pending())
        for mode in (ApplicationMode.DIAGNOSTIC, ApplicationMode.NORMAL):
            page.apply_mode(mode)
            page.latency_detail_list.clear()
            page._refresh_diagnostic_latency_display()
        # Mode/display changes never re-run or re-dispatch anything, never
        # touch the queue, the Test state or the order log (UI-5).
        assert len(runner.run_calls) == calls_before == 1
        assert len(page.order_queue.list_pending()) == entries_before == 1
        assert page._test_mode is True
        assert len(page.order_log.rows()) == 1
        assert page.latency_detail_list.count() > 0

    def test_7_construction_imports_no_core_module(self):
        code = "\n".join(
            [
                "import sys",
                "import ui.app as ui_app",
                "from ui.main_window import MainWindow",
                "app = ui_app.create_app([])",
                "window = MainWindow()",
                "banned = ('brokers', 'market', 'core', 'main')",
                "leaked = sorted(m for m in sys.modules if m.split('.')[0] in banned)",
                "assert not leaked, f'UI imported trading modules: {leaked}'",
                "page = window.order_configuration_page",
                "assert page.latency_total_label.text().endswith(",
                "    '\u0646\u0627\u0645\u0648\u062c\u0648\u062f'",
                ")",
                "assert page.latency_detail_list.count() == 0",
                "print('UI6_T3_OFFLINE_OK')",
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
        assert "UI6_T3_OFFLINE_OK" in result.stdout
