"""
test_ui8_task3_safety_modes_diagnostics.py

UI-8 Task 3 — Safety controls, Test/Diagnostic modes and diagnostic data,
verified over the REAL UI path, fully offline.

from ui import strings as STRINGS

Coverage review (what already exists, so nothing here duplicates it):

  * ``test_ui6_task1_diagnostic_mode.py`` covers the diagnostic boundary, the
    Trace ID line and the Block 8 latency rendering IN DETAIL — but every run
    in it is a pure-Python STUB runner with hand-written
    ``DispatchLatencyReport`` / ``DispatchResult`` fixtures ("the only 'run'
    is a pure-Python stub runner"). It therefore never proves that the
    diagnostics shown after a REAL execution are the real ones.
  * ``test_ui8_task1_single_broker_e2e.py`` proves a real single-order run is
    dry-run and safe, but says nothing about modes, Trace ID or latency.
  * ``test_ui8_task2_multi_account_multi_broker_e2e.py`` proves routing with
    two accounts/two brokers, not the safety/diagnostic surface.
  * ``test_block7_*`` / ``test_block9_*`` cover the M6-A … M6-E gates and the
    Block 8 latency instrumentation at the Core level; those gates are NOT
    bypassed here either — they are exercised through the normal dispatch
    path of the real page.

What this file adds (verification only, no production change):

  * Test 1 — Test mode stays dry-run over a REAL execution and the
    diagnostic section renders the REAL values of THIS run: the Core-built
    ``DispatchResult.trace_id`` verbatim (never a new/substituted id, never
    in the normal result rows or the order log), and the REAL Block 8
    ``DispatchLatencyReport`` of this very dispatch (total window, per-stage
    durations, per-Broker/API calls, application split) — every displayed
    number compared against the report's own field, never a fixture and
    never a fabricated one. Technical data stays hidden in NORMAL mode.
  * Test 2 — after a REAL failure (the dispatch entry point itself raising),
    no stale Trace ID or latency of the previous run is presented as the new
    run's, while the UI-5 result rows and the queue stay untouched.
  * Test 3 — a rejected input through the REAL M6 gates: the real M6-C fund
    gate blocks the order fail-closed, ZERO broker placements happen, the
    rejection is recorded with the existing contract (``BLOCKED``), the UI
    shows the blocked verdict, and no latency row is fabricated for a
    submission that never happened.

Safety throughout: ``SimulationHarness`` only, every ``place_order`` carries
``live=False``, no result ever reports a live send, and the real-broker /
network entry points are booby-trapped so any attempt fails the test.

Run:
    pytest -q test_ui8_task3_safety_modes_diagnostics.py
"""

import inspect
import socket
import urllib.request
from unittest.mock import patch

import pytest

from PySide6.QtWidgets import QApplication

from brokers.manager import BrokerManager
from core.dispatch_core import DispatchCore
from core.order_queue import OrderQueue
from core.simulation_harness import (
    SimulationBroker,
    SimulationHarness,
    build_simulation_catalog,
)
from models.instrument import Instrument
from models.order import BUY, SELL

from ui.account_store import AccountStore
from ui.main_window import ApplicationMode
from ui.order_configuration_page import (
    DIAGNOSTIC_LATENCY_APP_FIELDS,
    DIAGNOSTIC_LATENCY_STAGES,
    DIAGNOSTIC_LATENCY_STAGE_PREFIX,
    DIAGNOSTIC_TRACE_LABEL,
    DIAGNOSTIC_TRACE_UNAVAILABLE,
    DIAGNOSTIC_VALUE_UNAVAILABLE,
    RESULT_STATUS_BLOCKED,
    RESULT_STATUS_SUCCESS,
    OrderConfigurationPage,
)
from ui.test_runner import TestRunner


BROKER = "SIM"
ACCOUNT_ID = "ACC-3"
INS_CODE = "INS-SIM-3"
INSTRUMENT = Instrument(
    symbol="\u062f", name="SIM \u062f", ins_code=INS_CODE
)


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
    Cut the network and the real broker off for the whole test: any socket,
    host resolution, URL open, production ``BrokerManager`` construction or
    ``AgaahBroker`` construction fails the test immediately instead of
    silently reaching the outside.
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
    """Offline stand-in for the symbol-information seam (``get_nsc_id``)."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls = []

    def get_nsc_id(self, ins_code):
        self.calls.append(ins_code)
        return self.mapping.get(ins_code)


def _pulse(qapp, loops=30):
    for _ in range(loops):
        qapp.processEvents()
    qapp.processEvents()


def _ms(value):
    """Independent ns->ms formatting used to check what the UI rendered."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    return f"{value / 1_000_000:.3f} ms"


def _make_page(qapp, harness):
    """A real page wired to the REAL TestRunner over the harness manager."""
    store = AccountStore()
    store.add(ACCOUNT_ID, BROKER)
    store.set_active(ACCOUNT_ID)
    page = OrderConfigurationPage(store, order_queue=OrderQueue())
    runner = TestRunner(broker_manager=harness.manager)
    page.set_test_runner_factory(lambda: runner)
    return store, page, runner


def _add_order_via_real_ui(qapp, page, side):
    """Real form -> real Add-to-Queue for one order of the selected side."""
    seam = OfflineNscSeam({INS_CODE: INS_CODE})
    page.set_order_identity_factory(lambda: seam)
    page.config.select_instrument(INSTRUMENT)
    page.config.set_side(side)
    page.config.set_price(10_000)
    page.config.set_quantity(10)
    page._start_order_identity_resolution(INSTRUMENT)
    page.wait_for_order_identity_workers(timeout_ms=10_000)
    _pulse(qapp)
    assert page._on_add_to_queue() is True
    return page.order_queue.list_pending()[-1]


def _latency_rows(page):
    return [
        page.latency_detail_list.item(i).text()
        for i in range(page.latency_detail_list.count())
    ]


# ===========================================================================
# Test 1 — real execution: Test mode is dry-run, diagnostics show only the
#          REAL Trace ID / Block 8 timing of THIS run, hidden in NORMAL mode
# ===========================================================================


def test_task3_real_run_is_dry_run_and_diagnostics_show_real_data_only(
    qapp, no_real_broker_or_network
):
    harness = SimulationHarness(
        broker_name=BROKER, catalog=build_simulation_catalog((INS_CODE,))
    )
    broker = harness.broker
    assert isinstance(broker, SimulationBroker)
    store, page, runner = _make_page(qapp, harness)

    # NORMAL is the default boundary: nothing technical is visible yet.
    page.apply_mode(ApplicationMode.NORMAL)
    assert page.is_diagnostic_visible() is False

    entry = _add_order_via_real_ui(qapp, page, SELL)
    page.test_button.click()

    # ---- (1) Test mode is a dry run and produced ONE simulated result ----
    assert page._last_test_error is None
    plan, execution_id, result = page._last_test_run
    assert result.sent is False
    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    per_order = page._last_order_results[0]
    assert per_order.success is True
    assert per_order.sent is False
    assert per_order.mode == "DRY_RUN"
    assert per_order.order is entry.order
    assert page.result_list.count() == 1
    assert RESULT_STATUS_SUCCESS in page.result_list.item(0).text()

    # safety: the one broker call is a dry run and nothing reports live.
    assert broker.place_order_calls == [(entry.order, False)]
    assert all(live is False for _, live in broker.place_order_calls)
    assert broker.live_trading_enabled is False
    assert runner._dispatch_core.live_trading_enabled is False
    # The UI has no live-permission input at all: the runner's public API
    # takes no ``live`` argument, and any Safety Gate on the core it builds
    # (whatever this revision wires) denies Live.
    assert "live" not in inspect.signature(TestRunner.run).parameters
    gate = getattr(runner._dispatch_core, "safety_gate", None)
    if gate is not None:
        assert gate.evaluate().allowed is False

    # ---- the REAL Block 8 report of THIS very dispatch ------------------
    report = page._last_latency_report
    assert report is not None
    assert report is runner.last_report
    assert len(report.orders) == 1
    record = report.orders[0]
    assert record.execution_result is per_order   # the very same result
    assert record.execution_result.order is entry.order

    # ---- (4) Trace ID: this run's real Core-built id, verbatim ----------
    assert isinstance(result.trace_id, str) and result.trace_id.strip()
    trace_id = result.trace_id
    if report.trace_id is not None:
        assert report.trace_id == trace_id

    # NORMAL hides every technical line even though the data exists.
    assert page.is_diagnostic_visible() is False
    assert page.diagnostic_section.isVisibleTo(page) is False
    assert page.trace_id_label.isVisibleTo(page) is False
    assert page.latency_total_label.isVisibleTo(page) is False
    assert page.latency_detail_list.isVisibleTo(page) is False

    page.apply_mode(ApplicationMode.DIAGNOSTIC)
    assert page.is_diagnostic_visible() is True
    assert page.trace_id_label.text() == DIAGNOSTIC_TRACE_LABEL + trace_id
    # the trace id is a section-level line: never in the per-order
    # diagnostics, never in the result rows, never in the order log.
    for text in _latency_rows(page):
        assert trace_id not in text
    for index in range(page.result_list.count()):
        assert trace_id not in page.result_list.item(index).text()
    for row in range(page.order_log_table.rowCount()):
        for column in range(page.order_log_table.columnCount()):
            cell = page.order_log_table.item(row, column)
            assert cell is None or trace_id not in cell.text()

    # ---- (5) Latency: only this report's own real numbers --------------
    assert page.latency_total_label.text().endswith(
        _ms(report.dispatch_duration)
    )
    rows = _latency_rows(page)
    symbol = page._order_symbols[id(entry.order)]
    # the report really measured this run: stages, broker/API round trips and
    # the application split carry real values (so the checks below compare
    # real numbers, not just the unavailable marker).
    assert record.broker_api_calls
    assert any(
        record.duration_ns(stage) is not None
        for stage in DIAGNOSTIC_LATENCY_STAGES
    )
    assert any(
        getattr(record, field_name, None) is not None
        for _, field_name in DIAGNOSTIC_LATENCY_APP_FIELDS
    )
    for stage in DIAGNOSTIC_LATENCY_STAGES:
        duration = record.duration_ns(stage)
        expected = (
            DIAGNOSTIC_LATENCY_STAGE_PREFIX.format(order=symbol, stage=stage)
            + (_ms(duration) if duration is not None
               else DIAGNOSTIC_VALUE_UNAVAILABLE)
        )
        assert expected in rows, (stage, duration, rows)
    # every measured Broker/API round trip of this record is shown with its
    # OWN measured duration (never a sum, never a fabricated one) ...
    for number, call in enumerate(record.broker_api_calls, start=1):
        assert any(
            f"Broker/API {call.operation} #{number}" in text
            and text.endswith(_ms(call.duration_ns))
            for text in rows
        ), (call.operation, rows)
    # ... and the application/Broker split only as the report states it: a
    # value the report does not carry stays unavailable, never a 0.000 ms.
    for label, field_name in DIAGNOSTIC_LATENCY_APP_FIELDS:
        value = getattr(record, field_name, None)
        expected = (
            label.format(order=symbol)
            + (_ms(value) if value is not None
               else DIAGNOSTIC_VALUE_UNAVAILABLE)
        )
        assert expected in rows, (field_name, value, rows)
    assert not any(
        text.endswith(DIAGNOSTIC_VALUE_UNAVAILABLE + " 0.000 ms") for text in rows
    )
    # nothing on screen is labelled as network latency and no value is
    # invented outside this report's own numbers.
    assert not any("network" in text for text in rows)

    # ---- (3)+(6) switching modes changes display only -------------------
    broker_calls_before = list(broker.place_order_calls)
    order_log_before = page.order_log_table.rowCount()
    page.apply_mode(ApplicationMode.NORMAL)
    assert page.is_diagnostic_visible() is False
    page.apply_mode(ApplicationMode.DIAGNOSTIC)
    assert page.is_diagnostic_visible() is True
    assert page.trace_id_label.text() == DIAGNOSTIC_TRACE_LABEL + trace_id
    # no extra dispatch, no broker call, no new order-log row: mode changes
    # are display-only and leave UI-5 / UI-7 behavior untouched.
    assert broker.place_order_calls == broker_calls_before
    assert page.order_log_table.rowCount() == order_log_before
    assert page.result_list.count() == 1
    assert page.order_queue.list_pending() == [entry]


# ===========================================================================
# Test 2 — a REAL failed run never presents the previous run's trace/timings
# ===========================================================================


def test_task3_real_failure_hides_previous_trace_and_timing(
    qapp, no_real_broker_or_network
):
    harness = SimulationHarness(
        broker_name=BROKER, catalog=build_simulation_catalog((INS_CODE,))
    )
    broker = harness.broker
    store, page, runner = _make_page(qapp, harness)
    page.apply_mode(ApplicationMode.DIAGNOSTIC)

    entry = _add_order_via_real_ui(qapp, page, SELL)
    page.test_button.click()
    assert page._last_test_error is None
    good_trace = page._last_test_run[2].trace_id
    good_report = page._last_latency_report
    assert good_report is not None
    assert page.trace_id_label.text() == DIAGNOSTIC_TRACE_LABEL + good_trace

    # A REAL failure of the dispatch entry point itself (the Core raises —
    # not a stubbed result and not a fabricated report).
    def _boom(self, plan):
        raise RuntimeError("real dispatch failure")

    with patch.object(DispatchCore, "dispatch_with_latency", _boom):
        page.test_button.click()   # OFF -> no run
        page.test_button.click()   # ON  -> the failing run

    # the failure is surfaced with the existing UI-5 contract
    assert page._last_test_error == "real dispatch failure"
    assert STRINGS.TEST_ISSUE_FAILED.split("{", 1)[0] in page.queue_status_label.text()

    # (4)+(5) neither the previous run's trace id nor its timings are shown
    # as the new run's: both lines fall back to the unavailable marker.
    assert page.trace_id_label.text() == (
        DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
    )
    assert page.latency_total_label.text().endswith(
        DIAGNOSTIC_VALUE_UNAVAILABLE
    )
    assert page._last_latency_report is None
    assert page.latency_detail_list.count() == 0
    assert good_trace not in page.trace_id_label.text()

    # nothing new was sent: the failed run placed no order.
    assert broker.place_order_calls == [(entry.order, False)]


# ===========================================================================
# Test 3 — a rejected input is blocked by the REAL M6 gates, never sent
# ===========================================================================


def test_task3_real_m6_rejection_blocks_the_order_fail_closed(
    qapp, no_real_broker_or_network
):
    harness = SimulationHarness(
        broker_name=BROKER, catalog=build_simulation_catalog((INS_CODE,))
    )
    broker = harness.broker
    store, page, runner = _make_page(qapp, harness)
    page.apply_mode(ApplicationMode.DIAGNOSTIC)

    # BUY with the UI's real identity-only Account (no balance): the REAL
    # M6-C fund gate must stop it. The gates are exercised through the
    # normal dispatch path — none of them is bypassed or stubbed here.
    entry = _add_order_via_real_ui(qapp, page, BUY)
    page.test_button.click()

    assert page._last_test_error is None
    plan, execution_id, result = page._last_test_run
    assert result.sent is False
    assert result.success is False
    assert result.mode == "BLOCKED"
    per_order = page._last_order_results[0]
    assert per_order.success is False
    assert per_order.mode == "BLOCKED"
    assert per_order.order is entry.order
    assert per_order.sent is False

    # the rejection follows the existing Core contract (the real M6 reason)
    assert "T1" in result.message

    # (2) the order never reached the broker: no placement at all, and the
    # real M6-A trading-state read did run before the block.
    assert broker.place_order_calls == []
    assert all(live is False for _, live in broker.place_order_calls)
    ops = [call.op for call in broker.calls]
    assert "get_trading_state" in ops
    assert "get_buy_capacity" not in ops

    # (5) the report of THIS run carries the blocked result, and no timing
    # row is fabricated for a submission that never happened.
    report = page._last_latency_report
    assert report is not None
    assert len(report.orders) == 1
    assert report.orders[0].execution_result is per_order
    rows = _latency_rows(page)
    assert not any("place_order" in text for text in rows)

    # (5) the real trace id of this run is still shown (it is a real
    # dispatch), and it never leaks into the normal result row.
    assert isinstance(result.trace_id, str) and result.trace_id.strip()
    assert page.trace_id_label.text() == (
        DIAGNOSTIC_TRACE_LABEL + result.trace_id
    )
    row_text = page.result_list.item(0).text()
    assert RESULT_STATUS_BLOCKED in row_text
    assert result.trace_id not in row_text

from ui import strings as STRINGS