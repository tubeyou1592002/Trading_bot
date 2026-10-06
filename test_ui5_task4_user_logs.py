"""
test_ui5_task4_user_logs.py

UI-5 Task 4 (Stage 3, base display) — the user-facing order-log table.

The Order Configuration page carries one read-only seven-column log table:

    زمان ارسال | حساب | نماد | توضیح | زمان دریافت توسط کارگزاری |
    زمان ثبت در هسته معاملاتی | وضعیت صف

Exactly ONE row is appended per SENT order, in send order, rendered only
from the in-memory ``ui.user_log.OrderLog``. Everything the send already
produced is shown; everything that does not exist yet is rendered ``—`` and
is never invented:

    * زمان ارسال — the UI's wall-clock send moment (millisecond precision);
    * حساب      — the exact queued entry's account id;
    * نماد      — the symbol the user picked (never a broker nscId / tseId);
    * توضیح     — the fixed user-facing reason of the REAL per-order result
                  of that same send (empty when no per-order result exists);
    * the three feedback columns — no NATS/OMS consumer, no asynchronous
      feedback and no queue-status logic is wired in this base display, so
      they always stay ``—``.

Contract coverage (the four required contracts):

    R1 — the table has exactly SEVEN columns, with the exact titles, in order.
    R2 — one row per sent order, created in SEND order (never reordered).
    R3 — the base information of each row is shown correctly and comes from
         real project data only.
    R4 — the not-yet-received fields render empty (``—``) without an error.

Extra contracts:

    E1 — before any send the table is empty (queueing alone creates no row).
    E2 — two sends append two batches; earlier rows are never touched.
    E3 — the appended rows are immutable (append-only, never updated).
    E4 — the three feedback columns stay ``—`` even after a real full send.
    E5 — no technical value (nscId / tseId / Trace ID / latency / raw result
         message) ever reaches a log cell.
    E6 — this base display wires no aware-feedback connection at all.
    E7 — model-level: column order, millisecond formatting and the fail-closed
         rendering of an absent/blank value.

Run:
    pytest -q test_ui5_task4_user_logs.py
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication, QTableWidgetItem

from core.order_engine import OrderExecutionResult
from core.order_queue import OrderQueue
from core.simulation_harness import (
    SimulationHarness,
    build_simulation_catalog,
)
from models.instrument import Instrument
from models.order import BUY, SELL, Order

from ui.account_store import AccountStore
from ui.order_configuration_page import (
    RESULT_REASON_BLOCKED,
    RESULT_REASON_FAILED,
    RESULT_REASON_SUCCESS,
    OrderConfigurationPage,
)
from ui.test_runner import TestRunner
from ui.user_log import (
    COLUMN_ACCOUNT,
    COLUMN_BROKER_RECEIVED_AT,
    COLUMN_CORE_REGISTERED_AT,
    COLUMN_DESCRIPTION,
    COLUMN_QUEUE_STATUS,
    COLUMN_SENT_AT,
    COLUMN_SYMBOL,
    EMPTY_CELL,
    ORDER_LOG_COLUMNS,
    OrderLog,
    OrderLogRow,
    format_text,
    format_timestamp,
)


# ---------------------------------------------------------------------------
# Deterministic offline fixtures
# ---------------------------------------------------------------------------

CATALOG = ("INS-SIM-1", "INS-SIM-2", "INS-SIM-3")
BROKER = "SIM"

INSTR_SIM1 = Instrument(symbol="آکو", name="SSIM آکو", ins_code="INS-SIM-1")
INSTR_SIM2 = Instrument(symbol="فولاد", name="SSIM فولاد", ins_code="INS-SIM-2")
INSTR_SIM3 = Instrument(symbol="ذوب", name="SSIM ذوب", ins_code="INS-SIM-3")

EXPECTED_COLUMNS = (
    "زمان ارسال",
    "حساب",
    "نماد",
    "توضیح",
    "زمان دریافت توسط کارگزاری",
    "زمان ثبت در هسته معاملاتی",
    "وضعیت صف",
)


@pytest.fixture(scope="module")
def qapp():
    """Reuse the process-wide QApplication if one exists, else create one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def make_harness():
    """One offline harness over the REAL DispatchCore/OrderEngine path."""
    return SimulationHarness(
        broker_name=BROKER,
        catalog=build_simulation_catalog(ins_codes=CATALOG),
    )


def make_page(qapp, harness=None, queue=None):
    """A real page, optionally wired to the REAL runner over a harness core."""
    store = AccountStore()
    store.add("ACC-001", BROKER, "ACC-001")
    store.set_active("ACC-001")
    page = OrderConfigurationPage(store, order_queue=queue or OrderQueue())
    if harness is not None:
        page.set_test_runner_factory(
            lambda: TestRunner(dispatch_core=harness.dispatch_core)
        )
    return store, page


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


def enqueue_via_page(qapp, page, seam, instrument, side, price, quantity):
    """
    Drive the REAL UI path up to (not including) the send: select the
    instrument, resolve its broker nscId off-thread and press Add-to-Queue.
    The page's UI-layer symbol map is populated by the real action.
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


def send_via_page(page):
    """Press the real Test button: the page's one and only send action."""
    page.test_button.click()


def cell(table, row, column):
    """The rendered text of one table cell (``""`` when no item)."""
    item = table.item(row, column)
    assert isinstance(item, QTableWidgetItem)
    return item.text()


def table_rows(table):
    """Every row of the log table as a tuple of its seven cell strings."""
    return [
        tuple(cell(table, r, c) for c in range(table.columnCount()))
        for r in range(table.rowCount())
    ]


def craft_result(order, success, mode, message="crafted"):
    return OrderExecutionResult(
        success=success,
        sent=False,
        mode=mode,
        order=order,
        broker_name=BROKER,
        message=message,
    )


def seconds_of_day(moment):
    return (
        moment.hour * 3600
        + moment.minute * 60
        + moment.second
        + moment.microsecond / 1_000_000
    )


def parse_sent_at(text):
    """Parse a rendered ``HH:MM:SS.mmm`` cell back into seconds of the day."""
    parsed = datetime.strptime(text, "%H:%M:%S.%f")
    return parsed.hour * 3600 + parsed.minute * 60 + parsed.second + (
        parsed.microsecond / 1_000_000
    )


def sent_at_between(text, before, after, tolerance=2.0):
    """
    True when the rendered send stamp falls inside the send window.

    Compared as seconds-of-the-day with a small tolerance for the millisecond
    truncation and a midnight wrap, so the assertion is about the real send
    moment and never about an exact (unstable) clock value.
    """
    start = seconds_of_day(before)
    stop = seconds_of_day(after)
    stamp = parse_sent_at(text)
    if stop < start:  # the window wrapped around midnight
        start -= 86_400
        stop += 86_400
    return start - tolerance <= stamp <= stop + tolerance


# ===========================================================================
# R1 — exactly seven columns with the exact titles
# ===========================================================================


def test_r1_table_has_exactly_seven_columns_with_exact_titles(qapp):
    _store, page = make_page(qapp)

    table = page.order_log_table
    assert table.columnCount() == 7
    assert len(ORDER_LOG_COLUMNS) == 7

    headers = [
        table.horizontalHeaderItem(c).text()
        for c in range(table.columnCount())
    ]
    assert headers == list(EXPECTED_COLUMNS)
    assert headers == list(ORDER_LOG_COLUMNS)

    # The column constants of the model address those same seven positions.
    assert [COLUMN_SENT_AT, COLUMN_ACCOUNT, COLUMN_SYMBOL, COLUMN_DESCRIPTION,
            COLUMN_BROKER_RECEIVED_AT, COLUMN_CORE_REGISTERED_AT,
            COLUMN_QUEUE_STATUS] == list(range(7))


# ===========================================================================
# R2 — one row per sent order, created in send order
# ===========================================================================


def test_r2_one_row_per_sent_order_in_send_order(qapp):
    harness = make_harness()
    # One run yielding three outcomes in this exact send order:
    # blocked (BUY, no fund) -> failed (SELL, injected error) -> success.
    _store, page = make_page(qapp, harness)
    seam = NscSeam(
        mapping={
            "INS-SIM-1": "INS-SIM-1",
            "INS-SIM-2": "INS-SIM-2",
            "INS-SIM-3": "INS-SIM-3",
        }
    )
    enqueue_via_page(qapp, page, seam, INSTR_SIM1, BUY, 10_000, 10)
    harness.broker.configure_failure(
        fail_on_nsc_id="INS-SIM-2", fail_mode="exception"
    )
    enqueue_via_page(qapp, page, seam, INSTR_SIM2, SELL, 10_000, 20)
    enqueue_via_page(qapp, page, seam, INSTR_SIM3, SELL, 10_000, 30)

    assert page.order_log_table.rowCount() == 0  # E1 — queueing creates no row

    send_via_page(page)

    entries = page.order_queue.list_pending()
    assert len(entries) == 3
    rows = page.order_log.rows()
    assert len(rows) == 3                      # exactly one row per sent order
    assert page.order_log_table.rowCount() == 3

    # Send order preserved — the log follows the send, never a sort or a
    # re-render order of its own.
    assert [row.symbol for row in rows] == ["آکو", "فولاد", "ذوب"]
    rendered = table_rows(page.order_log_table)
    assert [cells[COLUMN_SYMBOL] for cells in rendered] == [
        "آکو",
        "فولاد",
        "ذوب",
    ]


def test_r2_log_rows_follow_two_sends_in_order(qapp):
    """E2 — a second send appends; the earlier rows are never touched."""
    harness = make_harness()
    _store, page = make_page(qapp, harness)
    seam = NscSeam(mapping={"INS-SIM-1": "INS-SIM-1"})

    first_entry = enqueue_via_page(
        qapp, page, seam, INSTR_SIM1, SELL, 10_000, 10
    )
    send_via_page(page)
    first_rows = page.order_log.rows()
    assert len(first_rows) == 1
    assert first_rows[0].description == RESULT_REASON_SUCCESS

    send_via_page(page)  # toggle Test Mode OFF again (never executes)
    assert len(page.order_log.rows()) == 1
    page.order_queue.remove(first_entry)
    enqueue_via_page(qapp, page, seam, INSTR_SIM1, BUY, 12_000, 40)
    send_via_page(page)

    rows = page.order_log.rows()
    assert len(rows) == 2
    # The first row is the very same immutable row, still first, unchanged.
    assert rows[0] is first_rows[0]
    assert rows[0].description == RESULT_REASON_SUCCESS
    assert rows[1].description == RESULT_REASON_BLOCKED
    assert page.order_log_table.rowCount() == 2
    rendered = table_rows(page.order_log_table)
    assert [cells[COLUMN_DESCRIPTION] for cells in rendered] == [
        RESULT_REASON_SUCCESS,
        RESULT_REASON_BLOCKED,
    ]


def test_r2_display_layer_rows_use_the_exact_send_sequence(qapp):
    """Row order follows the given send sequence, never an alphabetical sort."""
    _store, page = make_page(qapp)
    orders = [
        Order(nsc_id="NSC-Z", side=BUY, price=100, quantity=1),
        Order(nsc_id="NSC-A", side=SELL, price=200, quantity=2),
        Order(nsc_id="NSC-M", side=BUY, price=300, quantity=3),
    ]
    queue = OrderQueue()
    for index, order in enumerate(orders, start=1):
        queue.enqueue(order, account_id=f"ACC-00{index}", broker_name=BROKER)
    entries = queue.list_pending()

    page._order_symbols = {
        id(orders[0]): "آکو",
        id(orders[1]): "فولاد",
        id(orders[2]): "ذوب",
    }
    sent_at = datetime(2026, 9, 30, 10, 11, 12, 345_000)
    page._append_order_log_rows(
        entries,
        sent_at,
        [
            craft_result(orders[0], False, "BLOCKED"),
            craft_result(orders[1], True, "DRY_RUN"),
            craft_result(orders[2], False, "ERROR"),
        ],
    )

    rendered = table_rows(page.order_log_table)
    assert [cells[COLUMN_ACCOUNT] for cells in rendered] == [
        "ACC-001",
        "ACC-002",
        "ACC-003",
    ]
    assert [cells[COLUMN_SYMBOL] for cells in rendered] == [
        "آکو",
        "فولاد",
        "ذوب",
    ]
    assert [cells[COLUMN_DESCRIPTION] for cells in rendered] == [
        RESULT_REASON_BLOCKED,
        RESULT_REASON_SUCCESS,
        RESULT_REASON_FAILED,
    ]


# ===========================================================================
# R3 — the base information of each row is correct and real
# ===========================================================================


def test_r3_base_information_of_a_real_send(qapp):
    harness = make_harness()
    _store, page = make_page(qapp, harness)
    seam = NscSeam(mapping={"INS-SIM-3": "INS-SIM-3"})
    entry = enqueue_via_page(qapp, page, seam, INSTR_SIM3, SELL, 10_000, 30)

    before = datetime.now()
    send_via_page(page)
    after = datetime.now()

    rendered = table_rows(page.order_log_table)
    assert len(rendered) == 1
    cells = rendered[0]

    # زمان ارسال — the real send moment of THIS send, millisecond precision.
    assert cells[COLUMN_SENT_AT] != EMPTY_CELL
    assert sent_at_between(cells[COLUMN_SENT_AT], before, after)

    # حساب — the exact account the order was sent for.
    assert cells[COLUMN_ACCOUNT] == entry.account_id == "ACC-001"

    # نماد — the symbol the user picked.
    assert cells[COLUMN_SYMBOL] == "ذوب"

    # توضیح — the fixed user-facing reason of the REAL per-order result.
    per_order = page._last_order_results[0]
    assert per_order.order is entry.order
    assert per_order.success is True
    assert cells[COLUMN_DESCRIPTION] == RESULT_REASON_SUCCESS


def test_r3_send_stamp_is_the_send_moment_not_the_queue_moment(qapp):
    """The stamp belongs to the send, never to the Add-to-Queue action."""
    harness = make_harness()
    _store, page = make_page(qapp, harness)
    seam = NscSeam(mapping={"INS-SIM-1": "INS-SIM-1"})
    enqueue_via_page(qapp, page, seam, INSTR_SIM1, SELL, 10_000, 10)

    queued_at = datetime.now()
    page.order_log_table.setRowCount(0)  # only a no-op re-render of the table
    send_via_page(page)
    after = datetime.now()

    cells = table_rows(page.order_log_table)[0]
    assert sent_at_between(cells[COLUMN_SENT_AT], queued_at, after)


def test_r3_no_result_for_an_order_keeps_the_row_and_its_data(qapp):
    """
    A sent order without a per-order result still has its own row; only the
    description is empty (fail-closed — never a guessed verdict).
    """
    _store, page = make_page(qapp)
    order = Order(nsc_id="NSC-A", side=BUY, price=100, quantity=5)
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-009", broker_name=BROKER)
    page._order_symbols = {id(order): "آکو"}
    sent_at = datetime(2026, 9, 30, 1, 2, 3, 4_000)

    page._append_order_log_rows(queue.list_pending(), sent_at, None)

    cells = table_rows(page.order_log_table)[0]
    assert cells[COLUMN_SENT_AT] == "01:02:03.004"
    assert cells[COLUMN_ACCOUNT] == "ACC-009"
    assert cells[COLUMN_SYMBOL] == "آکو"
    assert cells[COLUMN_DESCRIPTION] == EMPTY_CELL


# ===========================================================================
# R4 — the not-yet-received fields stay empty, without an error
# ===========================================================================


def test_r4_not_yet_received_columns_render_empty_after_a_real_send(qapp):
    """E4 — a full real dry-run send still leaves the feedback columns empty."""
    harness = make_harness()
    _store, page = make_page(qapp, harness)
    seam = NscSeam(
        mapping={"INS-SIM-1": "INS-SIM-1", "INS-SIM-2": "INS-SIM-2"}
    )
    enqueue_via_page(qapp, page, seam, INSTR_SIM1, SELL, 10_000, 10)
    enqueue_via_page(qapp, page, seam, INSTR_SIM2, BUY, 10_000, 20)

    send_via_page(page)

    rows = table_rows(page.order_log_table)
    assert len(rows) == 2
    for cells in rows:
        assert cells[COLUMN_BROKER_RECEIVED_AT] == EMPTY_CELL
        assert cells[COLUMN_CORE_REGISTERED_AT] == EMPTY_CELL
        assert cells[COLUMN_QUEUE_STATUS] == EMPTY_CELL
        assert all(cell_text != "" for cell_text in cells)  # never blank cells


def test_r4_missing_and_blank_values_never_raise(qapp):
    """Fail-closed rendering of every absent / unexpected value."""
    _store, page = make_page(qapp)
    queue = OrderQueue()
    first = Order(nsc_id="NSC-A", side=BUY, price=100, quantity=1)
    second = Order(nsc_id="NSC-B", side=SELL, price=200, quantity=2)
    queue.enqueue(first, account_id="ACC-001", broker_name=BROKER)
    queue.enqueue(second, account_id="", broker_name=BROKER)
    # No symbol recorded for the first order, a blank one for the second.
    page._order_symbols = {id(second): "   "}
    entries = queue.list_pending()

    # A missing sent stamp, a non-datetime stamp and a wrong-typed account
    # must all render empty instead of raising.
    page._append_order_log_rows(entries, None, [])
    page._append_order_log_rows(entries, "not-a-timestamp", [])

    rendered = table_rows(page.order_log_table)
    assert len(rendered) == 4
    for cells in rendered:
        assert cells[COLUMN_SENT_AT] == EMPTY_CELL
        assert cells[COLUMN_BROKER_RECEIVED_AT] == EMPTY_CELL
        assert cells[COLUMN_CORE_REGISTERED_AT] == EMPTY_CELL
        assert cells[COLUMN_QUEUE_STATUS] == EMPTY_CELL
        assert cells[COLUMN_DESCRIPTION] == EMPTY_CELL
    assert rendered[0][COLUMN_SYMBOL] == EMPTY_CELL       # no symbol known
    assert rendered[1][COLUMN_SYMBOL] == EMPTY_CELL       # blank symbol
    assert rendered[2][COLUMN_ACCOUNT] == "ACC-001"       # never None-crash
    assert rendered[3][COLUMN_ACCOUNT] == EMPTY_CELL      # blank account


# ===========================================================================
# E3 / E5 / E6 — append-only, user-facing only, no feedback connection
# ===========================================================================


def test_e3_rows_are_immutable_and_never_updated(qapp):
    _store, page = make_page(qapp)
    order = Order(nsc_id="NSC-A", side=BUY, price=100, quantity=1)
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name=BROKER)
    page._append_order_log_rows(queue.list_pending(), datetime.now(), [])

    row = page.order_log.rows()[0]
    with pytest.raises(Exception):
        row.description = "changed"
    assert page.order_log.rows()[0] is row


def test_e5_no_technical_value_reaches_a_log_cell(qapp):
    """E5 — never an nscId / tseId, Trace ID, latency or raw result message."""
    harness = make_harness()
    harness.broker.configure_failure(
        fail_on_nsc_id="INS-SIM-2", fail_mode="exception"
    )
    _store, page = make_page(qapp, harness)
    seam = NscSeam(
        mapping={"INS-SIM-1": "INS-SIM-1", "INS-SIM-2": "INS-SIM-2"}
    )
    enqueue_via_page(qapp, page, seam, INSTR_SIM1, SELL, 10_000, 10)
    enqueue_via_page(qapp, page, seam, INSTR_SIM2, SELL, 10_000, 20)

    send_via_page(page)

    forbidden = (
        "INS-SIM-1",
        "INS-SIM-2",
        "NSC",
        "DRY_RUN",
        "BLOCKED",
        "ERROR",
        "trace",
        "latency",
        "endpoint",
        "crafted",
        "exec-ui5",
    )
    for cells in table_rows(page.order_log_table):
        joined = " ".join(cells)
        for token in forbidden:
            assert token not in joined


def test_e6_base_display_wires_no_aware_feedback(qapp):
    """E6 — no NATS/OMS listener or feedback service in this display."""
    import ui.order_configuration_page as page_module

    source = Path(page_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("OrderFeedbackService", "nats", "AcceptedByBourse"):
        assert forbidden not in source

    _store, page = make_page(qapp)
    assert isinstance(page.order_log, OrderLog)
    assert page.order_log.rows() == []


# ===========================================================================
# E7 — the in-memory log model itself
# ===========================================================================


def test_e7_row_cells_follow_the_column_order():
    row = OrderLogRow(
        sent_at=datetime(2026, 9, 30, 7, 8, 9, 10_000),
        account_id="ACC-001",
        symbol="آکو",
        description=RESULT_REASON_SUCCESS,
        broker_received_at=datetime(2026, 9, 30, 7, 8, 9, 500_000),
        core_registered_at=datetime(2026, 9, 30, 7, 8, 9, 750_000),
        queue_status="1",
    )
    cells = row.cells()
    assert len(cells) == 7
    assert cells == (
        "07:08:09.010",
        "ACC-001",
        "آکو",
        RESULT_REASON_SUCCESS,
        "07:08:09.500",
        "07:08:09.750",
        "1",
    )


def test_e7_formatters_are_fail_closed():
    assert format_timestamp(None) == EMPTY_CELL
    assert format_timestamp("2026-09-30") == EMPTY_CELL
    assert format_timestamp(datetime(2026, 9, 30, 23, 59, 59, 999_999)) == (
        "23:59:59.999"
    )
    assert format_text(None) == EMPTY_CELL
    assert format_text("") == EMPTY_CELL
    assert format_text("   ") == EMPTY_CELL
    assert format_text(" آکو ") == "آکو"


def test_e7_log_keeps_send_order_and_rejects_foreign_rows():
    log = OrderLog()
    assert len(log) == 0

    first = log.append(OrderLogRow(account_id="ACC-003"))
    second = log.append(OrderLogRow(account_id="ACC-001"))
    assert log.append(first) is first  # appended, never merged or reordered

    assert [row.account_id for row in log.rows()] == [
        "ACC-003",
        "ACC-001",
        "ACC-003",
    ]
    assert len(log) == 3

    snapshot = log.rows()
    snapshot.clear()
    assert len(log) == 3  # the returned list is a copy, never the storage

    with pytest.raises(TypeError):
        log.append("not-a-row")
    with pytest.raises(TypeError):
        OrderLog(rows=[object()])