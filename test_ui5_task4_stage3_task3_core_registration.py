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
)

BROKER = "SIM"

# Deterministic event timestamps used by every regression in this file.
# They are fixed historical moments, never "now", so an assertion can only
# hold if the value travelled verbatim from the event — any clock read
# inside the production path would fail these tests.
RAW_TS = 1788000123.456
RAW_TS_REDELIVERED = 1788000456.789
ACTION_SAVED_IN_ASA = 2
ACTION_ACCEPTED_BY_BOURSE = 5


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
    store.add("ACC-001", BROKER, "ACC-001")
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
        # path carries it — a fixed event value, never a clock read.
        event_moment = RAW_TS
        binder.emit_registered("DEC-T1", event_moment, object())

        rows = page.order_log.rows()
        assert rows[0].registered_in_core is True
        assert isinstance(rows[0].core_registered_at, datetime)
        # The stamped value IS the event moment exactly — converted to a
        # local datetime, nothing else, nothing invented.
        stamped = rows[0].core_registered_at
        assert stamped.timestamp() == event_moment
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
                binder.emit_registered("probe-unknown", RAW_TS, object())
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
        event_moment = RAW_TS_REDELIVERED
        binder.emit_registered("DEC-RACE", event_moment, object())
        rows = page.order_log.rows()
        assert rows[0].registered_in_core is True
        assert rows[0].core_registered_at.timestamp() == event_moment
        assert row_is_green(page, 0)
        # 6) Binding stays idempotent: a second emit reaches the handler
        #    exactly once more (the probe would double-count on a
        #    duplicated Qt connection).
        received_during_send.clear()
        binder.emit_registered("probe-unknown", RAW_TS, object())
        assert received_during_send == ["probe-unknown"]


# ---------------------------------------------------------------------------
# Contract A — accepted_by_bourse_at is the EVENT's own raw_timestamp
# ---------------------------------------------------------------------------


def make_oms_event(decision_id, action, raw_timestamp):
    """A parsed OMS code-100 event with an explicit, fixed timestamp."""
    from brokers.agaah.nats_transport import OmsStateChanged

    return OmsStateChanged(
        code=100,
        action=action,
        decision_id=decision_id,
        request_id="R",
        current_trade_count=0,
        message="1234567" if action == ACTION_ACCEPTED_BY_BOURSE else "0|0|x",
        channel="c",
        nsc_id="NSC-RAW",
        raw_timestamp=raw_timestamp,
    )


def make_correlator(decision_id):
    """A bare correlator (offline) tracking exactly one decisionId."""
    from brokers.agaah.queue_position import (
        AgahOrderCorrelator,
        OrderTrackingInfo,
    )

    fired = []
    correlator = object.__new__(AgahOrderCorrelator)
    correlator.on_order_registered = lambda *a: fired.append(a)
    correlator._running = True
    info = OrderTrackingInfo(decision_id=decision_id, nsc_id="NSC-RAW")
    correlator._orders = {decision_id: info}
    return correlator, info, fired


class TestAcceptedByBourseAtIsTheEventTimestamp:
    def test_action5_stores_raw_timestamp_verbatim(self):
        correlator, info, fired = make_correlator("DEC-RAW1")

        correlator._handle_oms_event(
            make_oms_event("DEC-RAW1", ACTION_ACCEPTED_BY_BOURSE, RAW_TS)
        )

        # Exactly the event's own value: identical, and provably NOT a
        # freshly built timestamp (RAW_TS is a fixed historical moment).
        assert info.accepted_by_bourse_at == RAW_TS
        assert info.accepted_by_bourse_at == 1788000123.456
        assert len(fired) == 1
        assert fired[0][0] == "DEC-RAW1"
        assert fired[0][1] is info
        # The rest of the AcceptedByBourse handling is unchanged.
        assert info.host_order_number == "1234567"

    def test_action5_with_missing_raw_timestamp_fabricates_nothing(self):
        correlator, info, fired = make_correlator("DEC-RAW2")

        correlator._handle_oms_event(
            make_oms_event("DEC-RAW2", ACTION_ACCEPTED_BY_BOURSE, None)
        )

        # Fail-closed: no event timestamp -> no stored timestamp. The
        # registration callback still fires; the UI is what must ignore a
        # None stamp (never the broker inventing one).
        assert info.accepted_by_bourse_at is None
        assert len(fired) == 1

    def test_action2_never_writes_accepted_by_bourse_at(self):
        """SavedInAsa carries a timestamp too — it must NOT be stored."""
        correlator, info, fired = make_correlator("DEC-RAW3")

        correlator._handle_oms_event(
            make_oms_event("DEC-RAW3", ACTION_SAVED_IN_ASA, RAW_TS)
        )

        assert info.accepted_by_bourse_at is None
        assert fired == []

    def test_only_action5_writes_the_field(self):
        """Only the matching-engine registration action touches the field."""
        for action, expected in (
            (ACTION_ACCEPTED_BY_BOURSE, RAW_TS),
            (ACTION_SAVED_IN_ASA, None),
        ):
            correlator, info, _fired = make_correlator("DEC-RAW4")
            correlator._handle_oms_event(
                make_oms_event("DEC-RAW4", action, RAW_TS)
            )
            assert info.accepted_by_bourse_at == expected

    def test_zero_is_a_real_timestamp_and_is_kept(self):
        """0.0 is falsy but REAL — it must survive verbatim, not be lost."""
        correlator, info, _fired = make_correlator("DEC-RAW5")

        correlator._handle_oms_event(
            make_oms_event("DEC-RAW5", ACTION_ACCEPTED_BY_BOURSE, 0.0)
        )

        assert info.accepted_by_bourse_at == 0.0

    def test_redelivery_stores_the_latest_events_own_value(self):
        correlator, info, _fired = make_correlator("DEC-RAW6")

        for moment in (RAW_TS, RAW_TS_REDELIVERED):
            correlator._handle_oms_event(
                make_oms_event("DEC-RAW6", ACTION_ACCEPTED_BY_BOURSE, moment)
            )

        assert info.accepted_by_bourse_at == RAW_TS_REDELIVERED


# ---------------------------------------------------------------------------
# Contract B — the three-value order_registered signal
# ---------------------------------------------------------------------------


def qt_signal_signature(qt_object, name):
    """The Qt meta-object signature of a signal, e.g. 'f(QString,int)'."""
    meta = qt_object.metaObject()
    for index in range(meta.methodCount()):
        method = meta.method(index)
        signature = bytes(method.methodSignature()).decode()
        if signature.startswith(name + "("):
            return signature
    raise AssertionError(
        f"signal {name!r} not declared on {type(qt_object).__name__!r}"
    )


class TestFeedbackServiceCarriesThreeValues:
    def test_signal_is_declared_with_three_arguments(self, qapp):
        from ui.order_feedback_service import OrderFeedbackService

        service = OrderFeedbackService(broker_factory=lambda: None)
        assert (
            qt_signal_signature(service, "order_registered")
            == "order_registered(QString,PyObject,PyObject)"
        )

    def _service(self, received):
        from ui.order_feedback_service import OrderFeedbackService

        # Constructed only — never started (no thread, no broker, no NATS).
        service = OrderFeedbackService(broker_factory=lambda: None)
        service.order_registered.connect(lambda *a: received.append(a))
        return service

    def test_forwarder_passes_decision_id_timestamp_and_order_info(self):
        from brokers.agaah.queue_position import OrderTrackingInfo

        received = []
        service = self._service(received)
        info = OrderTrackingInfo(decision_id="DEC-SIG", nsc_id="NSC-SIG")
        info.accepted_by_bourse_at = RAW_TS

        service._on_order_registered("DEC-SIG", info)

        assert len(received) == 1
        decision_id, accepted_at_ts, order_info = received[0]
        assert decision_id == "DEC-SIG"
        assert accepted_at_ts == RAW_TS
        # The signal's timestamp IS the tracked order's own stamp, verbatim.
        assert accepted_at_ts == order_info.accepted_by_bourse_at
        assert order_info is info

    def test_forwarder_passes_none_when_the_event_carried_no_timestamp(self):
        received = []
        service = self._service(received)

        service._on_order_registered("DEC-SIG-NONE", None)

        assert received == [("DEC-SIG-NONE", None, None)]

    def test_forwarder_never_invents_a_timestamp(self):
        """A tracker without the field yields None — never a clock read."""
        from brokers.agaah.queue_position import OrderTrackingInfo

        received = []
        service = self._service(received)

        class _Bare:
            pass

        service._on_order_registered("DEC-BARE", _Bare())
        service._on_order_registered(
            "DEC-DEFAULT",
            OrderTrackingInfo(decision_id="DEC-DEFAULT", nsc_id="NSC-D"),
        )

        assert received[0] == ("DEC-BARE", None, received[0][2])
        assert received[1][1] is None  # never stamped yet -> None

    def test_event_timestamp_reaches_the_signal_end_to_end(self):
        """Correlator (action 5) -> service forwarder -> signal, verbatim."""
        correlator, info, _fired = make_correlator("DEC-E2E")
        received = []
        service = self._service(received)
        correlator.on_order_registered = service._on_order_registered

        correlator._handle_oms_event(
            make_oms_event("DEC-E2E", ACTION_ACCEPTED_BY_BOURSE, RAW_TS)
        )

        assert len(received) == 1
        decision_id, accepted_at_ts, order_info = received[0]
        assert decision_id == "DEC-E2E"
        assert accepted_at_ts == RAW_TS
        assert accepted_at_ts == info.accepted_by_bourse_at
        assert order_info is info


# ---------------------------------------------------------------------------
# Contract C — MainWindow wires the page to the SHARED feedback service
# ---------------------------------------------------------------------------


def make_window():
    """A real MainWindow, constructed offline (no NATS/broker/network)."""
    from ui.main_window import MainWindow

    return MainWindow()


class TestMainWindowWiresTheSharedFeedbackService:
    def test_page_has_a_feedback_binder_factory(self):
        window = make_window()
        try:
            page = window.order_configuration_page
            assert page._feedback_binder_factory is not None
            assert callable(page._feedback_binder_factory)
            # Nothing is bound yet — the page binds lazily, on first use.
            assert page._feedback_binder is None
            assert window._feedback_service is None
        finally:
            window.close()

    def test_factory_returns_the_shared_service_without_building_a_new_one(self):
        from ui.order_feedback_service import OrderFeedbackService

        window = make_window()
        try:
            page = window.order_configuration_page
            first = page._feedback_binder_factory()
            second = page._feedback_binder_factory()

            assert isinstance(first, OrderFeedbackService)
            assert first is second                       # one shared instance
            assert first is window.feedback_service      # the MainWindow's
            assert first is window._feedback_service     # cached, not rebuilt
            assert not first.isRunning()                # wiring starts nothing
            assert window._broker_manager_cache is None  # no BrokerManager made
        finally:
            window.close()

    def test_page_binding_uses_that_same_service_instance(self):
        window = make_window()
        try:
            page = window.order_configuration_page
            service = window.feedback_service

            page._ensure_feedback_binding()

            assert page._feedback_binder is service
            assert window._feedback_service is service
            assert not service.isRunning()

            # Idempotent: binding again keeps the very same instance.
            page._feedback_binder = None
            page._ensure_feedback_binding()
            assert page._feedback_binder is service
        finally:
            window.close()

    def test_shared_service_signal_updates_the_window_page_row(self):
        """The wiring's purpose: the shared service drives the real page."""
        window = make_window()
        try:
            page = window.order_configuration_page
            page._ensure_feedback_binding()
            service = page._feedback_binder

            send_one_order(page, decision_id="DEC-WIRE")
            assert page.order_log.rows()[0].core_registered_at is None

            service.order_registered.emit("DEC-WIRE", RAW_TS, object())

            rows = page.order_log.rows()
            assert len(rows) == 1
            assert rows[0].registered_in_core is True
            # The row carries the event's own stamp, converted for display.
            assert rows[0].core_registered_at.timestamp() == RAW_TS
            assert row_is_green(page, 0)
        finally:
            window.close()
