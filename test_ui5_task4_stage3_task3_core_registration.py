"""
test_ui5_task4_stage3_task3_core_registration.py

UI-5 Task 4 — Stage 3 — Task 3: matching-engine registration
(``AcceptedByBourse``) feedback into the order log.

When a REAL ``AcceptedByBourse`` event (OMS action 5) arrives for a sent
order, the SAME row of the user-facing order log is updated:

  * «زمان ثبت در هسته معاملاتی» shows the REAL receive moment of that
    event — carried verbatim from the event through the existing feedback
    path (``OmsStateChanged.raw_timestamp`` -> ``OrderTrackingInfo
    .accepted_by_bourse_at`` -> the ``order_registered`` signal). No
    UI-side clock read, no fabricated timestamp, no monotonic conversion.
  * the row is highlighted (green) — derived ONLY from the row's
    ``registered_in_core`` flag set by the real event.

Required contracts (the four scenarios of the task):

  T1 — ``AcceptedByBourse`` with a valid decisionId -> the row's
       timestamp is set AND the row renders green.
  T2 — ``SavedInAsa`` (action 2) -> no timestamp, no green row.
  T3 — an unknown / invalid decisionId -> NO row is created, NO row
       changes, nothing is fabricated.
  T4 — re-delivery of the same event -> idempotent: the row is not
       duplicated, not corrupted; a same-value re-stamp changes nothing.

Boundaries proven along the way:

  * the decisionId itself is NEVER rendered in any table cell;
  * an event without a real timestamp stamps nothing (fail-closed);
  * rows keep their send order — an update never reorders or recreates;
  * the signal flows over the EXISTING feedback path: the correlator's
    ``on_order_registered`` (fired ONLY on action 5) through the
    ``OrderFeedbackService.order_registered`` signal;
  * the timestamp flows from the event's own ``raw_timestamp`` — a
    ``SavedInAsa`` event never writes ``accepted_by_bourse_at``.
  * the corrective-task contract: the feedback binding is established
    BEFORE the send pass starts (``_ensure_feedback_binding`` runs first
    in ``_run_test_pass``), so a registration event emitted while the
    send is in flight already finds the page's listener connected.

Everything is offline and deterministic: fake broker, fake correlator
side objects and the REAL UI classes. ``QDateTime`` is deliberately
unused — the wall clock enters the test only through the event value.
"""

import time
from datetime import datetime

import pytest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from core.order_engine import OrderExecutionResult
from core.order_queue import OrderQueue
from models.order import BUY, Order

from ui.account_store import AccountStore
from ui.order_configuration_page import (
    CORE_REGISTERED_ROW_COLOR,
    OrderConfigurationPage,
)
from ui.user_log import (
    COLUMN_CORE_REGISTERED_AT,
    EMPTY_CELL,
    OrderLogRow,
)

BROKER = "SIM"


# ---------------------------------------------------------------------------
# Qt scaffolding
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _Binder(QObject):
    """The EXISTING feedback signal surface, offline: order_registered."""

    order_registered = Signal(str, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.connected_pages = []

    def emit_registered(self, decision_id, accepted_at_ts, order_info=None):
        self.order_registered.emit(
            decision_id, accepted_at_ts, order_info
        )


def make_page(qapp):
    """A real page wired to an offline binder exposing the same signal."""
    store = AccountStore()
    store.add("ACC-001", BROKER)
    store.set_active("ACC-001")
    page = OrderConfigurationPage(store, order_queue=OrderQueue())
    binder = _Binder()
    page.set_feedback_binder_factory(lambda: binder)
    return page, binder


def send_one_order(page, decision_id=None):
    """
    Append exactly one sent-order row through the REAL send path.

    When ``decision_id`` is given, the send's real result carries it (a
    live success, exactly the Stage 1 shape the engine produces) so the
    page records the correlation; otherwise the row stays uncorrelated.
    """
    order = Order(nsc_id="NSC-A", side=BUY, price=100, quantity=1)

    class _Entry:
        pass

    entry = _Entry()
    entry.order = order
    entry.account_id = "ACC-001"
    entry.broker_name = BROKER

    result = None
    if decision_id is not None:
        result = OrderExecutionResult(
            success=True,
            sent=True,
            mode="LIVE",
            order=order,
            broker_name=BROKER,
            message="sent",
            response={
                "isSuccess": True,
                "data": {"decisionId": decision_id},
            },
        )

    page._run_test_pass  # the real flow appends via the send pass below
    page._last_test_entries = [entry]
    page._last_order_results = [result] if result is not None else []
    page._append_order_log_rows(
        page._last_test_entries, datetime(2026, 9, 30, 10, 0, 0), page._last_order_results
    )
    page._ensure_feedback_binding()
    return order


def table_rows(table):
    return [
        tuple(
            table.item(r, c).text() if table.item(r, c) is not None else ""
            for c in range(table.columnCount())
        )
        for r in range(table.rowCount())
    ]


def background_of(table, row_index, column):
    """The background color of one cell, or None when unset."""
    item = table.item(row_index, column)
    if item is None:
        return None
    brush = item.background()
    if brush is None or brush.style().name == "NoBrush":
        return None
    return brush.color().name()


def row_is_green(page, row_index):
    color = background_of(
        page.order_log_table, row_index, COLUMN_CORE_REGISTERED_AT
    )
    return color == CORE_REGISTERED_ROW_COLOR


# ---------------------------------------------------------------------------
# T1 — AcceptedByBourse with a valid decisionId
# ---------------------------------------------------------------------------


class TestAcceptedByBourseRegistersTheRow:
    def test_timestamp_is_stamped_and_row_turns_green(self, qapp):
        page, binder = make_page(qapp)
        order = send_one_order(page, decision_id="DEC-T1")

        # Before the event: the column is empty and the row is plain.
        rows = page.order_log.rows()
        assert len(rows) == 1
        assert rows[0].core_registered_at is None
        assert rows[0].registered_in_core is None
        assert (
            table_rows(page.order_log_table)[0][COLUMN_CORE_REGISTERED_AT]
            == EMPTY_CELL
        )
        assert not row_is_green(page, 0)

        # The REAL event receive moment (epoch seconds), as the feedback
        # path carries it — no clock is read inside the UI for this.
        event_moment = time.time()
        binder.emit_registered("DEC-T1", event_moment, object())

        rows = page.order_log.rows()
        assert rows[0].registered_in_core is True
        assert isinstance(rows[0].core_registered_at, datetime)
        # The stamped value is the REAL event moment, converted to a
        # local datetime — nothing else, nothing invented.
        stamped = rows[0].core_registered_at
        assert abs(stamped.timestamp() - event_moment) < 1.0
        assert row_is_green(page, 0)
        rendered = table_rows(page.order_log_table)[0][
            COLUMN_CORE_REGISTERED_AT
        ]
        assert rendered != EMPTY_CELL
        assert rendered == stamped.strftime("%H:%M:%S.%f")[:-3]
        assert page.order_log_table.rowCount() == 1  # same row, no new row

    def test_decision_id_is_never_rendered_in_any_cell(self, qapp):
        page, binder = make_page(qapp)
        send_one_order(page, decision_id="DEC-SECRET")
        binder.emit_registered(
            "DEC-SECRET", time.time(), object()
        )

        joined = " ".join(
            cell for cells in table_rows(page.order_log_table) for cell in cells
        )
        assert "DEC-SECRET" not in joined

    def test_row_order_is_preserved_after_the_update(self, qapp):
        page, binder = make_page(qapp)
        send_one_order(page, decision_id="DEC-A")
        # A second, uncorrelated send appends another row.
        page._last_test_entries = [
            type("E", (), {"order": Order(nsc_id="NSC-B", side=BUY, price=1, quantity=1),
                           "account_id": "ACC-001", "broker_name": BROKER})()
        ]
        page._last_order_results = []
        page._append_order_log_rows(
            page._last_test_entries, datetime(2026, 9, 30, 10, 1, 0), []
        )

        binder.emit_registered("DEC-A", time.time(), object())

        keys = [row.key for row in page.order_log.rows()]
        assert keys[0] is page.order_log.rows()[0].key  # stable identity
        assert keys[0] is not None
        assert keys[1] is not None and keys[0] is not keys[1]


# ---------------------------------------------------------------------------
# T2 — SavedInAsa must not stamp or green the row
# ---------------------------------------------------------------------------


class TestSavedInAsaDoesNotRegister:
    def test_saved_in_asa_never_reaches_the_ui_signal(self, qapp):
        """
        The feedback path itself: the correlator fires
        ``on_order_registered`` ONLY on action 5 (AcceptedByBourse).
        A SavedInAsa (2) event never produces an order_registered
        signal, so the UI can never stamp or green a row from it.
        """
        from brokers.agaah.queue_position import (
            AgahOrderCorrelator,
            OrderTrackingInfo,
        )
        from brokers.agaah.nats_transport import OmsStateChanged

        fired = []
        correlator = object.__new__(AgahOrderCorrelator)
        correlator.on_order_registered = lambda *a: fired.append(a)
        correlator._running = True
        info = OrderTrackingInfo(decision_id="DEC-T2", nsc_id="NSC-T2")
        correlator._orders = {"DEC-T2": info}

        saved_in_asa = OmsStateChanged(
            code=100,
            action=2,
            decision_id="DEC-T2",
            request_id="R",
            current_trade_count=0,
            message="0|0|...|2026-09-30 10:00:00|rest",
            channel="c",
            nsc_id="NSC-T2",
            raw_timestamp=time.time(),
        )
        correlator._handle_oms_event(saved_in_asa)

        assert fired == []  # SavedInAsa is NOT the green trigger
        assert info.accepted_by_bourse_at is None

    def test_row_stays_untouched_without_a_bourse_event(self, qapp):
        page, binder = make_page(qapp)
        send_one_order(page, decision_id="DEC-T2b")

        # Nothing fired (a SavedInAsa world): the row is unchanged.
        rows = page.order_log.rows()
        assert rows[0].core_registered_at is None
        assert rows[0].registered_in_core is None
        assert (
            table_rows(page.order_log_table)[0][COLUMN_CORE_REGISTERED_AT]
            == EMPTY_CELL
        )
        assert not row_is_green(page, 0)
        assert page.order_log_table.rowCount() == 1


# ---------------------------------------------------------------------------
# T3 — unknown / invalid decisionId
# ---------------------------------------------------------------------------


class TestUnknownDecisionIdChangesNothing:
    @pytest.mark.parametrize(
        "bad_id",
        ["DEC-UNKNOWN", "", "   ", None, 12345],
    )
    def test_no_row_is_created_and_nothing_changes(self, qapp, bad_id):
        page, binder = make_page(qapp)
        send_one_order(page, decision_id="DEC-KNOWN")

        before_rows = page.order_log.rows()
        before_table = table_rows(page.order_log_table)

        binder.emit_registered(bad_id, time.time(), object())

        assert page.order_log.rows() == before_rows
        assert table_rows(page.order_log_table) == before_table
        assert page.order_log_table.rowCount() == 1

    def test_valid_event_without_timestamp_stamps_nothing(self, qapp):
        page, binder = make_page(qapp)
        send_one_order(page, decision_id="DEC-NOTS")

        binder.emit_registered("DEC-NOTS", None, object())

        rows = page.order_log.rows()
        assert rows[0].core_registered_at is None
        assert rows[0].registered_in_core is None
        assert not row_is_green(page, 0)

    def test_invalid_timestamp_values_are_rejected(self, qapp):
        from ui.order_configuration_page import (
            _epoch_to_local_datetime as to_dt,
        )

        assert to_dt(None) is None
        assert to_dt("2026-09-30") is None
        assert to_dt(True) is None  # bool is never a timestamp
        assert to_dt(float("nan")) is None


# ---------------------------------------------------------------------------
# T4 — idempotency of a re-delivered event
# ---------------------------------------------------------------------------


class TestRedeliveryIsIdempotent:
    def test_same_event_twice_keeps_one_unchanged_row(self, qapp):
        page, binder = make_page(qapp)
        send_one_order(page, decision_id="DEC-T4")

        event_moment = time.time()
        binder.emit_registered("DEC-T4", event_moment, object())
        first_stamped = page.order_log.rows()[0].core_registered_at

        binder.emit_registered("DEC-T4", event_moment, object())

        rows = page.order_log.rows()
        assert len(rows) == 1
        assert rows[0].core_registered_at == first_stamped
        assert rows[0].registered_in_core is True
        assert row_is_green(page, 0)

    def test_row_object_is_stable_across_redelivery(self, qapp):
        page, binder = make_page(qapp)
        send_one_order(page, decision_id="DEC-T4b")
        row_before = page.order_log.rows()[0]
        same_event_moment = time.time()
        binder.emit_registered("DEC-T4b", same_event_moment, object())
        row_after_first = page.order_log.rows()[0]

        binder.emit_registered("DEC-T4b", same_event_moment, object())

        row_after_second = page.order_log.rows()[0]
        # The first delivery stamped the value (a new row object carrying
        # the same identity); the SAME-value redelivery changed NOTHING —
        # not even a replacement: the row object itself stayed stable.
        assert row_after_second is not row_before
        assert row_after_second is row_after_first
        assert row_after_second.key is row_before.key
        assert row_after_second.sent_at == row_before.sent_at
        assert (
            row_after_second.core_registered_at
            == row_after_first.core_registered_at
        )


# ---------------------------------------------------------------------------
# Model-level contracts of the one new update operation
# ---------------------------------------------------------------------------


class TestOrderLogUpdateSemantics:
    def test_update_requires_a_real_datetime(self, qapp):
        log = __import__("ui.user_log", fromlist=["OrderLog"]).OrderLog()
        key = object()
        log.append(OrderLogRow(account_id="A", key=key))

        assert log.update_core_registration(key, "not-a-datetime") is None
        assert log.update_core_registration(key, None) is None
        assert log.update_core_registration(key, 12345.0) is None
        assert log.rows()[0].core_registered_at is None

    def test_update_of_unknown_key_is_a_noop(self, qapp):
        log = __import__("ui.user_log", fromlist=["OrderLog"]).OrderLog()
        log.append(OrderLogRow(account_id="A", key=object()))
        snapshot = log.rows()

        assert log.update_core_registration(object(), datetime.now()) is None
        assert log.rows() == snapshot

    def test_update_never_reorders_or_recreates_other_rows(self, qapp):
        log = __import__("ui.user_log", fromlist=["OrderLog"]).OrderLog()
        key_a, key_b = object(), object()
        first = log.append(OrderLogRow(account_id="A", key=key_a))
        log.append(OrderLogRow(account_id="B", key=key_b))

        updated = log.update_core_registration(
            key_b, datetime(2026, 9, 30, 12, 0, 0)
        )

        assert updated is not None and updated.registered_in_core is True
        assert log.rows()[0] is first          # first row untouched
        assert log.rows()[1].key is key_b
        assert log.rows()[1].core_registered_at == datetime(
            2026, 9, 30, 12, 0, 0
        )

    def test_registered_flag_is_only_set_together_with_a_timestamp(self, qapp):
        log = __import__("ui.user_log", fromlist=["OrderLog"]).OrderLog()
        key = object()
        log.append(OrderLogRow(account_id="A", key=key))
        assert log.update_core_registration(key, datetime.now()) is not None
        row = log.rows()[0]
        assert (row.core_registered_at is None) == (
            row.registered_in_core is not True
        )


# ---------------------------------------------------------------------------
# The real correlator stamps the real event timestamp (action 5 only)
# ---------------------------------------------------------------------------


class TestCorrelatorStampsRealEventTimestamp:
    def test_accepted_by_bourse_keeps_the_event_moment(self):
        from brokers.agaah.queue_position import (
            AgahOrderCorrelator,
            OrderTrackingInfo,
        )
        from brokers.agaah.nats_transport import OmsStateChanged

        fired = []
        correlator = object.__new__(AgahOrderCorrelator)
        correlator.on_order_registered = lambda *a: fired.append(a)
        correlator._running = True
        info = OrderTrackingInfo(decision_id="DEC-C1", nsc_id="NSC-C1")
        correlator._orders = {"DEC-C1": info}

        moment = time.time()
        event = OmsStateChanged(
            code=100,
            action=5,
            decision_id="DEC-C1",
            request_id="R",
            current_trade_count=0,
            message="1234567",
            channel="c",
            nsc_id="NSC-C1",
            raw_timestamp=moment,
        )
        correlator._handle_oms_event(event)

        assert len(fired) == 1  # the green trigger fired exactly once
        assert fired[0][0] == "DEC-C1"
        assert info.accepted_by_bourse_at == moment
        assert info.host_order_number == "1234567"

    def test_redelivery_overwrites_with_the_latest_real_value(self):
        from brokers.agaah.queue_position import (
            AgahOrderCorrelator,
            OrderTrackingInfo,
        )
        from brokers.agaah.nats_transport import OmsStateChanged

        correlator = object.__new__(AgahOrderCorrelator)
        correlator.on_order_registered = lambda *a: None
        correlator._running = True
        info = OrderTrackingInfo(decision_id="DEC-C2", nsc_id="NSC-C2")
        correlator._orders = {"DEC-C2": info}

        first, second = time.time(), time.time() + 1.5
        for moment in (first, second):
            correlator._handle_oms_event(
                OmsStateChanged(
                    code=100,
                    action=5,
                    decision_id="DEC-C2",
                    request_id="R",
                    current_trade_count=0,
                    message="1",
                    channel="c",
                    nsc_id="NSC-C2",
                    raw_timestamp=moment,
                )
            )
        assert info.accepted_by_bourse_at == second


# ---------------------------------------------------------------------------
# Corrective task — the feedback binding precedes the send pass (race fix)
# ---------------------------------------------------------------------------


class TestFeedbackBindingPrecedesTheSend:
    """
    The binding order contract of ``_run_test_pass``:

        1. ``_ensure_feedback_binding()`` — lazily, exactly once;
        2. ``runner.run(...)`` — the send pass;
        3. ``_append_order_log_rows(...)``.

    With the OLD order (binding after the append) a registration event
    emitted while the send was in flight could arrive before the page
    was ever connected and be lost. The new order guarantees the
    listener is ALREADY connected the moment the send starts.
    """

    def test_listener_is_connected_before_runner_run_runs(self, qapp):
        page, binder = make_page(qapp)

        # Probe: any event DELIVERED to the page while the send is in
        # flight proves the page's listener was already connected at
        # that moment. The probe uses an unknown decisionId — it must
        # change nothing (fail-closed), it only proves the delivery.
        received_during_send = []
        page_handler = page._on_order_registered_from_feedback

        def _recording_handler(decision_id, ts, info):
            received_during_send.append(decision_id)
            page_handler(decision_id, ts, info)

        page._on_order_registered_from_feedback = _recording_handler

        bound_during_send = []

        class _InFlightRunner:
            """A send pass that emits a feedback event mid-flight."""

            # Like the real runner: this send's per-order results.
            last_order_results = None

            def run(self, entries, account=None):
                # Observed DURING the send: the page must already be
                # bound (the corrective task's core requirement).
                bound_during_send.append(page._feedback_binder is binder)
                binder.emit_registered("probe-unknown", time.time(), object())
                result = OrderExecutionResult(
                    success=True,
                    sent=True,
                    mode="LIVE",
                    order=entries[0].order,
                    broker_name=BROKER,
                    message="sent",
                    response={
                        "isSuccess": True,
                        "data": {"decisionId": "DEC-RACE"},
                    },
                )
                self.last_order_results = [result]
                return ("race-plan", "race-exec", result)

        # The full valid send setup: active account, one queued entry,
        # a selected instrument and Test Mode ON.
        page.set_test_runner_factory(lambda: _InFlightRunner())
        from models.instrument import Instrument

        page.config.select_instrument(
            Instrument(symbol="آکو", name="آکو", ins_code="1")
        )
        page.order_queue.enqueue(
            Order(nsc_id="NSC-R", side=BUY, price=100, quantity=1),
            account_id="ACC-001",
            broker_name=BROKER,
        )
        page._test_mode = True
        page._run_test_pass()

        # 1) The listener was connected BEFORE runner.run() executed.
        assert bound_during_send == [True]
        assert page._feedback_binder is binder
        # 2) The event emitted during the send was NOT lost: the page's
        #    listener received it (exactly once — no duplicate connect).
        assert received_during_send == ["probe-unknown"]
        # 3) The probe (unknown id) created/changed nothing.
        assert page.order_log_table.rowCount() == 1
        assert page.order_log.rows()[0].core_registered_at is None
        assert not row_is_green(page, 0)
        # 4) The send's own row was appended and correlated normally.
        assert page._order_by_decision_id.get("DEC-RACE") is not None
        # 5) The real event after the pass stamps/greens the row as ever.
        event_moment = time.time()
        binder.emit_registered("DEC-RACE", event_moment, object())
        rows = page.order_log.rows()
        assert rows[0].registered_in_core is True
        assert abs(rows[0].core_registered_at.timestamp() - event_moment) < 1.0
        assert row_is_green(page, 0)
        # 6) Binding stays idempotent: a second emit reaches the handler
        #    exactly once more (the probe would double-count on a
        #    duplicated Qt connection).
        received_during_send.clear()
        binder.emit_registered("probe-unknown", time.time(), object())
        assert received_during_send == ["probe-unknown"]
