"""
test_ui5_task4_stage3_task4_ui_table.py

UI-5 Task 4 — Stage 3 — Task 4: the user-facing order log TABLE.

The seven-column table the earlier stages fed is now fully displayed:

  T-cols — every one of the 7 columns renders its correct value:
      1 زماان ارسال     (the UI's wall-clock send moment)
      2 حساب            (the sent order's existing account)
      3 نماد            (the sent order's existing UI-layer symbol)
      4 توضیح           (the description the send already produced)
      5 زمان دریافت توسط کارگزاری (Stage 1 broker_registered_at_ns value)
      6 زمان ثبت در هسته معاملاتی (Task 3 registered_in_core / core_registered_at)
      7 وضعیت صف        (the value the EXISTING Stage 2 path computed)

  T-green — a real ``AcceptedByBourse`` event (action 5) greens the
       correct row and its timestamp lands in the correct column;
       ``SavedInAsa`` (action 2) never greens and never stamps.

  T-order — the send order of the rows is preserved through updates.

  T-queue — the queue-status cell is filled ONLY from the existing
       Stage 2 signal value; a duplicate delivery of the same value is a
       no-op; an unknown decisionId changes nothing.

  T-id   — the decisionId itself is NEVER rendered in any cell.

Everything is offline and deterministic: no feedback service is started,
no queue logic is implemented in the page — the tests inject the
EXISTING signal surfaces only.
"""

import time
from datetime import datetime

import pytest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from core.order_engine import OrderExecutionResult
from core.order_queue import OrderQueue
from models.order import BUY, Order

from ui.account_store import AccountStore
from ui.order_configuration_page import (
    CORE_REGISTERED_ROW_COLOR,
    OrderConfigurationPage,
)
from ui.user_log import (
    COLUMN_QUEUE_STATUS,
    ORDER_LOG_COLUMNS,
)

BROKER = "SIM"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _Binder(QObject):
    """
    The EXISTING feedback signal surface, offline: the same two signals
    the production feedback object exposes (order_registered — Task 3 —
    and queue_position — Stage 2).
    """

    order_registered = Signal(str, object, object)
    queue_position = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.connected_pages = []

    def emit_registered(self, decision_id, accepted_at_ts, order_info=None):
        self.order_registered.emit(decision_id, accepted_at_ts, order_info)

    def emit_queue_position(self, decision_id, position):
        self.queue_position.emit(decision_id, position)


def make_page(qapp, with_queue_signal=True):
    """A real page wired to an offline binder exposing the same signals."""
    store = AccountStore()
    store.add("ACC-001", BROKER)
    store.set_active("ACC-001")
    page = OrderConfigurationPage(store, order_queue=OrderQueue())
    binder = _Binder() if with_queue_signal else _BinderWithoutQueueSignal()
    page.set_feedback_binder_factory(lambda: binder)
    return page, binder


class _BinderWithoutQueueSignal(QObject):
    """A bound object carrying ONLY the registration signal."""

    order_registered = Signal(str, object, object)

    def emit_registered(self, decision_id, accepted_at_ts, order_info=None):
        self.order_registered.emit(decision_id, accepted_at_ts, order_info)


def _table_rows(table):
    return [
        tuple(
            table.item(r, c).text() if table.item(r, c) is not None else ""
            for c in range(table.columnCount())
        )
        for r in range(table.rowCount())
    ]


def _row_is_green(page, row_index):
    item = page.order_log_table.item(row_index, COLUMN_QUEUE_STATUS)
    if item is None:
        return False
    brush = item.background()
    if brush is None or brush.style().name == "NoBrush":
        return False
    return brush.color().name() == CORE_REGISTERED_ROW_COLOR


def _record_symbol(page, order, symbol):
    """Record the UI-layer symbol exactly as the Add-to-Queue action does."""
    page._order_symbols[id(order)] = symbol


def _stage1_result(order, decision_id, broker_registered_at_ns):
    """The Stage 1 shape: a live success carrying the receipt and decisionId."""
    return OrderExecutionResult(
        success=True,
        sent=True,
        mode="LIVE",
        order=order,
        broker_name=BROKER,
        message="sent",
        response={
            "isSuccess": True,
            "data": {
                "decisionId": decision_id,
                "brokerRegisteredAtNs": broker_registered_at_ns,
            },
        },
    )


def _correlated_entry(order, decision_id):
    """One sent entry whose real result carries ``decision_id``."""

    class _E:
        pass

    entry = _E()
    entry.order = order
    entry.account_id = "ACC-001"
    entry.broker_name = BROKER
    return entry, _stage1_result(order, decision_id, 1_000)


def _append(
    page, entries, results, sent_at, *, bind=True
):
    page._last_test_entries = list(entries)
    page._last_order_results = list(results)
    page._append_order_log_rows(
        page._last_test_entries, sent_at, page._last_order_results
    )
    # The send pass binds the page to the EXISTING feedback signals
    # (registration + queue position) — same convention as the Task 3 tests.
    if bind:
        page._ensure_feedback_binding()


# ---------------------------------------------------------------------------
# T-cols — every one of the 7 columns shows the correct value
# ---------------------------------------------------------------------------


class TestSevenColumnsRenderCorrectValues:
    def test_all_seven_columns_with_correct_data(self, qapp):
        page, binder = make_page(qapp)
        assert (
            list(page.order_log_table.horizontalHeaderItem(c).text() for c in range(7))
            == list(ORDER_LOG_COLUMNS)
        )

        order = Order(nsc_id="NSC-7", side=BUY, price=100, quantity=1)
        _record_symbol(page, order, "آکو")

        class _Entry:
            pass

        entry = _Entry()
        entry.order = order
        entry.account_id = "ACC-001"
        entry.broker_name = BROKER

        sent_at = datetime(2026, 9, 30, 10, 0, 0)
        broker_registered_at = datetime(2026, 9, 30, 10, 0, 0, 250_000)
        entry, result = _correlated_entry(order, "DEC-7")
        result.broker_received_at = broker_registered_at

        _append(page, [entry], [result], sent_at)

        # The registration event of Task 3 stamps the core column.
        core_moment = time.time()
        binder.emit_registered("DEC-7", core_moment, object())
        # The queue-status event of Stage 2 fills the last column.
        binder.emit_queue_position("DEC-7", 3)

        rows = _table_rows(page.order_log_table)
        assert len(rows) == 1
        cells = rows[0]
        assert cells[0] == "10:00:00.000"            # 1 زمان ارسال
        assert cells[1] == "ACC-001"                  # 2 حساب
        assert cells[2] == "آکو"                      # 3 نماد
        assert cells[3] != ""                         # 4 توضیح
        assert cells[4] == broker_registered_at.strftime(
            "%H:%M:%S.%f"
        )[:-3]                                        # 5 زمان دریافت کارگزاری
        assert cells[5] != ""                         # 6 زمان ثبت در هسته
        assert cells[6] == "3"                        # 7 وضعیت صف

    def test_queue_status_empty_until_stage2_value_arrives(self, qapp):
        page, binder = make_page(qapp)
        order = Order(nsc_id="NSC-E", side=BUY, price=10, quantity=1)

        class _Entry:
            pass

        entry = _Entry()
        entry.order = order
        entry.account_id = "ACC-001"
        entry.broker_name = BROKER
        _append(page, [entry], [], datetime(2026, 9, 30, 10, 0, 0))

        assert _table_rows(page.order_log_table)[0][COLUMN_QUEUE_STATUS] == "—"
        binder.emit_queue_position("DEC-NONE", 5)  # unknown id — no change
        assert _table_rows(page.order_log_table)[0][COLUMN_QUEUE_STATUS] == "—"


# ---------------------------------------------------------------------------
# T-green — AcceptedByBourse greens the correct row; SavedInAsa never does
# ---------------------------------------------------------------------------


class TestGreenRegistration:
    def test_accepted_by_bourse_greens_the_correct_row_and_column(self, qapp):
        page, binder = make_page(qapp)
        first = Order(nsc_id="NSC-G1", side=BUY, price=100, quantity=1)
        second = Order(nsc_id="NSC-G2", side=BUY, price=200, quantity=1)

        class _E:
            pass

        e1, e2 = _E(), _E()
        e1.order, e1.account_id, e1.broker_name = first, "ACC-001", BROKER
        e2.order, e2.account_id, e2.broker_name = second, "ACC-001", BROKER
        _append(
            page,
            [e1, e2],
            [
                _stage1_result(first, "DEC-G1", 1_000),
                _stage1_result(second, "DEC-G2", 2_000),
            ],
            datetime(2026, 9, 30, 10, 0, 0),
        )

        moment = time.time()
        binder.emit_registered("DEC-G2", moment, object())

        rows = page.order_log.rows()
        assert rows[0].registered_in_core is None       # first row untouched
        assert rows[1].registered_in_core is True
        assert abs(rows[1].core_registered_at.timestamp() - moment) < 1.0
        assert _row_is_green(page, 1)
        assert not _row_is_green(page, 0)
        # The core timestamp is rendered in the CORRECT column (6), not 5.
        core_cells = _table_rows(page.order_log_table)
        assert core_cells[1][5] == rows[1].core_registered_at.strftime(
            "%H:%M:%S.%f"
        )[:-3]

    def test_saved_in_asa_never_greens_or_stamps(self, qapp):
        from brokers.agaah.queue_position import AgahOrderCorrelator, OrderTrackingInfo
        from brokers.agaah.nats_transport import OmsStateChanged

        fired = []
        correlator = object.__new__(AgahOrderCorrelator)
        correlator.on_order_registered = lambda *a: fired.append(a)
        correlator._running = True
        info = OrderTrackingInfo(decision_id="DEC-S", nsc_id="NSC-S")
        correlator._orders = {"DEC-S": info}

        correlator._handle_oms_event(
            OmsStateChanged(
                code=100,
                action=2,
                decision_id="DEC-S",
                request_id="R",
                current_trade_count=0,
                message="0|0|...|2026-09-30 10:00:00|rest",
                channel="c",
                nsc_id="NSC-S",
                raw_timestamp=time.time(),
            )
        )

        assert fired == []  # no signal → the UI row can never green
        assert info.accepted_by_bourse_at is None


# ---------------------------------------------------------------------------
# T-order — the send order of the rows is preserved through updates
# ---------------------------------------------------------------------------


class TestRowOrderPreserved:
    def test_updates_keep_the_send_order(self, qapp):
        page, binder = make_page(qapp)
        o1 = Order(nsc_id="NSC-O1", side=BUY, price=1, quantity=1)
        o2 = Order(nsc_id="NSC-O2", side=BUY, price=2, quantity=1)

        class _E:
            pass

        e1, e2 = _E(), _E()
        e1.order, e1.account_id, e1.broker_name = o1, "ACC-001", BROKER
        e2.order, e2.account_id, e2.broker_name = o2, "ACC-001", BROKER
        _append(
            page,
            [e1, e2],
            [_stage1_result(o1, "DEC-O1", 1), _stage1_result(o2, "DEC-O2", 2)],
            datetime(2026, 9, 30, 10, 0, 0),
        )

        binder.emit_queue_position("DEC-O2", 2)
        binder.emit_registered("DEC-O1", time.time(), object())

        rows = page.order_log.rows()
        assert rows[0].key is o1 and rows[1].key is o2
        # The model stays untouched by queue feedback (Task 3 contract);
        # the value lives in the page's UI-layer display state and shows
        # in the rendered table of the EXACT row, in send order.
        assert rows[0].queue_status is None
        assert rows[1].queue_status is None
        rendered = _table_rows(page.order_log_table)
        assert rendered[0][COLUMN_QUEUE_STATUS] == "—"
        assert rendered[1][COLUMN_QUEUE_STATUS] == "2"


# ---------------------------------------------------------------------------
# T-queue — the queue-status value comes ONLY from the existing Stage 2 path
# ---------------------------------------------------------------------------


class TestQueueStatusFromExistingStage2Data:
    def test_position_value_is_displayed_and_idempotent(self, qapp):
        page, binder = make_page(qapp)
        order = Order(nsc_id="NSC-Q", side=BUY, price=5, quantity=1)
        entry, result = _correlated_entry(order, "DEC-Q")
        _append(page, [entry], [result], datetime(2026, 9, 30, 10, 0, 0))

        binder.emit_queue_position("DEC-Q", 4)
        assert _table_rows(page.order_log_table)[0][COLUMN_QUEUE_STATUS] == "4"

        # Duplicate delivery of the same value → a no-op (idempotent).
        row_before = page.order_log.rows()[0]
        binder.emit_queue_position("DEC-Q", 4)
        assert page.order_log.rows()[0] is row_before

    def test_unknown_or_invalid_queue_events_change_nothing(self, qapp):
        page, binder = make_page(qapp)
        order = Order(nsc_id="NSC-U", side=BUY, price=5, quantity=1)
        entry, result = _correlated_entry(order, "DEC-VALID?")
        _append(page, [entry], [result], datetime(2026, 9, 30, 10, 0, 0))

        before = _table_rows(page.order_log_table)
        snapshot = page.order_log.rows()

        binder.emit_queue_position("DEC-UNKNOWN", 1)   # unknown id
        binder.emit_queue_position("", 1)              # blank id
        binder.emit_queue_position(None, 1)            # non-string id

        # Non-integer positions cannot travel over Signal(str, int) (Qt
        # coerces them); the fail-closed guards are exercised directly.
        handler = page._on_queue_position_from_feedback
        handler("DEC-VALID?", True)                    # bool is not a position
        handler("DEC-VALID?", "2")                     # non-int position
        handler("DEC-VALID?", None)                    # None position
        handler(12345, 1)                              # non-string id, direct

        assert _table_rows(page.order_log_table) == before
        assert page.order_log.rows() == snapshot

    def test_a_binder_without_the_queue_signal_still_binds_registration(self, qapp):
        page, binder = make_page(qapp, with_queue_signal=False)
        order = Order(nsc_id="NSC-N", side=BUY, price=5, quantity=1)
        entry, result = _correlated_entry(order, "DEC-N")
        _append(page, [entry], [result], datetime(2026, 9, 30, 10, 0, 0))

        moment = time.time()
        binder.emit_registered("DEC-N", moment, object())

        rows = page.order_log.rows()
        assert rows[0].registered_in_core is True
        assert _row_is_green(page, 0)

    def test_queue_status_is_never_invented_by_the_page(self, qapp):
        """No new queue logic: the page never computes a position itself."""
        import ui.order_configuration_page as page_module

        source = page_module.__file__
        text = open(source, encoding="utf-8").read()
        # No polling / endpoint / position computation appears in the page.
        for forbidden in ("getorderposition", "poll", "asyncio", "sleep("):
            assert forbidden not in text


# ---------------------------------------------------------------------------
# T-id — the decisionId is NEVER rendered
# ---------------------------------------------------------------------------


class TestDecisionIdNeverRendered:
    def test_no_cell_contains_any_decision_id(self, qapp):
        page, binder = make_page(qapp)
        o1 = Order(nsc_id="NSC-D1", side=BUY, price=1, quantity=1)
        o2 = Order(nsc_id="NSC-D2", side=BUY, price=2, quantity=1)

        class _E:
            pass

        e1, e2 = _E(), _E()
        e1.order, e1.account_id, e1.broker_name = o1, "ACC-001", BROKER
        e2.order, e2.account_id, e2.broker_name = o2, "ACC-001", BROKER
        _append(
            page,
            [e1, e2],
            [_stage1_result(o1, "DEC-SECRET-1", 1), _stage1_result(o2, "DEC-SECRET-2", 2)],
            datetime(2026, 9, 30, 10, 0, 0),
        )

        binder.emit_queue_position("DEC-SECRET-1", 1)
        binder.emit_registered("DEC-SECRET-2", time.time(), object())

        joined = " ".join(
            cell for cells in _table_rows(page.order_log_table) for cell in cells
        )
        assert "DEC-SECRET-1" not in joined
        assert "DEC-SECRET-2" not in joined
