"""
test_block9_account_aware_order_feedback.py

Block 9 — Task 9B: ACCOUNT-AWARE order feedback and lifecycle.

The order-feedback runtime (the OMS ``AcceptedByBourse`` -> green-row path)
must be scoped to ONE account, not to a broker name. Two accounts on the
same broker get two independent runtimes, each bound — through
``BrokerManager.get_for_account(account_id, broker_name)`` — to its own
account-scoped broker instance, never a name-only/global ``get(...)``.

Acceptance contracts proven here (all fully offline / deterministic):

  1. On a single broker, two accounts get two DISTINCT, independently
     cached ``OrderFeedbackService`` runtimes and two distinct broker
     instances resolved ONLY through ``get_for_account``.
  2. An account without a usable session/authorization never starts (and
     never even composes) a feedback runtime — fail-closed.
  3. Logout / account-deletion / broker-change STOP only the affected
     account's runtime; every other account keeps running. Switching the
     active account never stops the previous account's runtime.
  4. start / stop / restart of the same account reuses the SAME runtime and
     never registers a second copy of the broker listeners.
  5. The SAME ``decision_id`` on two accounts only ever updates its OWN
     account's row — an event of one account can never touch another row.
  6. ``AcceptedByBourse`` and queue-position feedback reach exactly the row
     of the sending account; an unknown/other-account event is a no-op.
  7. ``MainWindow`` construction stays offline/lazy and the order gate is
     unchanged.
  8. Starting feedback never sends an order — the send path stays Dry Run.

Every fake here is an offline double; no NATS, no network, no live order.
"""

import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from core.order_engine import OrderExecutionResult
from core.order_queue import OrderQueue
from models.order import BUY, Order

from ui.account_store import AccountStore
from ui.accounts_page import AccountsPage
from ui.order_authorization import AuthorizationResult
from ui.order_configuration_page import (
    CORE_REGISTERED_ROW_COLOR,
    OrderConfigurationPage,
)
from ui.session_manager import SessionState
from ui.user_log import COLUMN_CORE_REGISTERED_AT, COLUMN_QUEUE_STATUS, EMPTY_CELL


BROKER = "آگاه"
ACCOUNT_A = "ACC-9B-A"
ACCOUNT_B = "ACC-9B-B"
TOKEN_A = "offline-token-a"
TOKEN_B = "offline-token-b"
RAW_TS = 1788000123.456
SENT_AT = datetime(2026, 9, 30, 10, 0, 0)


# ---------------------------------------------------------------------------
# Qt scaffolding
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def wait_until(condition, qapp, timeout=5.0):
    """Pump the GUI event loop until ``condition`` holds (or timeout)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


# ---------------------------------------------------------------------------
# Offline doubles
# ---------------------------------------------------------------------------


class FakeAccountBroker:
    """A per-account broker double exposing the feedback listener surface."""

    def __init__(self, account_id, broker_name):
        self.account_id = account_id
        self.broker_name = broker_name
        self.registered_listeners = []
        self.queue_listeners = []
        self.error_listeners = []
        self._queue_position_provider = None
        self.tracking_started = 0
        self.tracking_stopped = 0
        self.send_calls = []

    # -- feedback wiring (the ONLY surface the service uses) ---------------
    def add_order_registered_listener(self, callback):
        self.registered_listeners.append(callback)

    def add_queue_position_listener(self, callback):
        self.queue_listeners.append(callback)

    def add_order_error_listener(self, callback):
        self.error_listeners.append(callback)

    def _ensure_queue_position_provider(self):
        self._queue_position_provider = object()

    async def start_queue_position_tracking(self):
        self.tracking_started += 1

    async def stop_queue_position_tracking(self):
        self.tracking_stopped += 1

    def get_queue_position(self, decision_id):
        return None

    # -- a real send must NEVER happen through the feedback path -----------
    def place_order(self, *args, **kwargs):
        self.send_calls.append((args, kwargs))
        raise AssertionError("the feedback path must never send an order")

    # -- test-side event injection -----------------------------------------
    def emit_registered(self, decision_id, accepted_at_ts):
        info = SimpleNamespace(accepted_by_bourse_at=accepted_at_ts)
        for callback in list(self.registered_listeners):
            callback(decision_id, info)

    def emit_queue(self, decision_id, position):
        for callback in list(self.queue_listeners):
            callback(decision_id, position)

    def emit_error(self, decision_id, error):
        for callback in list(self.error_listeners):
            callback(decision_id, error)


class FakeAccountBrokerManager:
    """Resolves ONLY account-scoped brokers; a name-only get() is forbidden."""

    def __init__(self):
        self.created = {}
        self.account_calls = []
        self.name_calls = []

    def get_for_account(self, account_id, broker_name):
        self.account_calls.append((account_id, broker_name))
        key = (account_id, broker_name)
        broker = self.created.get(key)
        if broker is None:
            broker = FakeAccountBroker(account_id, broker_name)
            self.created[key] = broker
        return broker

    def get(self, name):
        self.name_calls.append(name)
        raise AssertionError("name-only broker resolution is forbidden")


class _OfflineSession:
    def __init__(self, account_id, broker_name):
        self.account_id = account_id
        self.broker_name = broker_name
        self.state = SessionState.LOGGED_IN


class FakeSessionManager:
    def __init__(self):
        self._sessions = {}
        self._tokens = {}

    def login(self, account_id, broker_name, token):
        self._sessions[account_id] = _OfflineSession(account_id, broker_name)
        self._tokens[account_id] = token

    def logout(self, account_id):
        self._sessions.pop(account_id, None)
        self._tokens.pop(account_id, None)

    def get(self, account_id):
        return self._sessions.get(account_id)

    def get_token(self, account_id):
        return self._tokens.get(account_id)

    def is_logged_in(self, account_id):
        return account_id in self._tokens


class _OfflineAdapter:
    def __init__(self, broker_name, token):
        self.broker_name = broker_name
        self._token = token

    def is_authenticated(self):
        return True

    def get_authenticated_session(self):
        return SimpleNamespace(access_token=self._token)


class FakeAuthenticationService:
    def __init__(self):
        self._logged_in = {}
        self._adapters = {}

    def login(self, account_id, broker_name, token):
        self._logged_in[account_id] = True
        self._adapters[account_id] = _OfflineAdapter(broker_name, token)

    def is_logged_in(self, account_id):
        return bool(self._logged_in.get(account_id))

    def get_adapter(self, account_id):
        return self._adapters.get(account_id)


def build_window(monkeypatch, accounts, active, logged_in=()):
    """
    A real ``MainWindow`` over a fake, account-only broker manager.

    ``accounts`` is ``(account_id, broker_name)`` pairs to register;
    ``logged_in`` lists the accounts whose session/authorization is valid.
    """
    from ui.main_window import MainWindow

    store = AccountStore(repository=False)
    for account_id, broker_name in accounts:
        store.add(account_id, broker_name, account_id)
    if active is not None:
        store.set_active(active)

    manager = FakeAccountBrokerManager()
    auth = FakeAuthenticationService()
    sessions = FakeSessionManager()
    for account_id, broker_name in accounts:
        if account_id in logged_in:
            token = TOKEN_A if account_id == ACCOUNT_A else TOKEN_B
            auth.login(account_id, broker_name, token)
            sessions.login(account_id, broker_name, token)

    window = MainWindow(account_store=store)
    window._authentication_service = auth
    window._session_manager = sessions
    monkeypatch.setattr(window, "_shared_broker_manager", lambda: manager)
    return window, manager, auth, sessions


def stop_window(window, qapp):
    wait_until(
        lambda: not any(
            service.isRunning()
            for service in window._feedback_services.values()
        ),
        qapp,
        timeout=0.1,
    )
    window.close()


# ---------------------------------------------------------------------------
# Page-level doubles (account-scoped binders, no MainWindow)
# ---------------------------------------------------------------------------


class FakeBinder(QObject):
    order_registered = Signal(str, object, object)
    queue_position = Signal(str, int)

    def emit_registered(self, decision_id, accepted_at_ts):
        self.order_registered.emit(decision_id, accepted_at_ts, object())

    def emit_queue(self, decision_id, position):
        self.queue_position.emit(decision_id, position)


def make_page(store):
    page = OrderConfigurationPage(store, order_queue=OrderQueue())
    page.set_order_authorizer_factory(
        lambda: lambda account_id, broker_name: AuthorizationResult(
            True, "test"
        )
    )
    return page


def append_order_row(page, account_id, broker_name, decision_id, nsc_id):
    """Append exactly one sent-order row through the real page append path."""
    order = Order(nsc_id=nsc_id, side=BUY, price=100, quantity=1)
    entry = SimpleNamespace(
        order=order, account_id=account_id, broker_name=broker_name
    )
    result = OrderExecutionResult(
        success=True,
        sent=True,
        mode="LIVE",
        order=order,
        broker_name=broker_name,
        message="sent",
        response={"isSuccess": True, "data": {"decisionId": decision_id}},
    )
    page._last_test_entries = [entry]
    page._last_order_results = [result]
    page._append_order_log_rows([entry], SENT_AT, [result])
    return order


def row_is_green(page, row_index):
    item = page.order_log_table.item(row_index, COLUMN_CORE_REGISTERED_AT)
    if item is None:
        return False
    brush = item.background()
    if brush is None or brush.style().name == "NoBrush":
        return False
    return brush.color().name() == CORE_REGISTERED_ROW_COLOR


# ---------------------------------------------------------------------------
# 1. Account-scoped service registry
# ---------------------------------------------------------------------------


class TestAccountScopedServiceRegistry:
    def test_two_accounts_on_one_broker_get_distinct_cached_services(
        self, qapp, monkeypatch
    ):
        window, manager, _, _ = build_window(
            monkeypatch,
            [(ACCOUNT_A, BROKER), (ACCOUNT_B, BROKER)],
            active=ACCOUNT_A,
            logged_in={ACCOUNT_A, ACCOUNT_B},
        )
        try:
            service_a = window.start_feedback_for_account(ACCOUNT_A, BROKER)
            wait_until(lambda: service_a._running, qapp)
            # The real authorization gate binds an operation to the ACTIVE
            # account, so each account is activated before it is started —
            # exactly the real UI flow (choose account, then use it).
            window.account_store.set_active(ACCOUNT_B)
            service_b = window.start_feedback_for_account(ACCOUNT_B, BROKER)
            wait_until(lambda: service_b._running, qapp)

            assert service_a is not None and service_b is not None
            assert service_a is not service_b
            assert service_a.account_id == ACCOUNT_A
            assert service_b.account_id == ACCOUNT_B
            assert service_a.broker_name == service_b.broker_name == BROKER

            assert window.feedback_service_for_account(ACCOUNT_A, BROKER) is service_a
            assert window.feedback_service_for_account(ACCOUNT_B, BROKER) is service_b

            broker_a = manager.created[(ACCOUNT_A, BROKER)]
            broker_b = manager.created[(ACCOUNT_B, BROKER)]
            assert broker_a is not broker_b
            assert manager.name_calls == []
        finally:
            stop_window(window, qapp)

    def test_identity_is_resolved_only_through_get_for_account(
        self, qapp, monkeypatch
    ):
        window, manager, _, _ = build_window(
            monkeypatch,
            [(ACCOUNT_A, BROKER)],
            active=ACCOUNT_A,
            logged_in={ACCOUNT_A},
        )
        try:
            service = window.start_feedback_for_account(ACCOUNT_A, BROKER)
            wait_until(lambda: service._running, qapp)
            assert manager.account_calls == [(ACCOUNT_A, BROKER)]
            assert manager.name_calls == []
        finally:
            stop_window(window, qapp)

    def test_invalid_identity_builds_nothing(self, qapp, monkeypatch):
        window, _, _, _ = build_window(
            monkeypatch, [(ACCOUNT_A, BROKER)], active=ACCOUNT_A
        )
        try:
            assert window.feedback_service_for_account("", BROKER) is None
            assert window.feedback_service_for_account(ACCOUNT_A, "") is None
            assert window._feedback_services == {}
        finally:
            window.close()


# ---------------------------------------------------------------------------
# 2. Unauthorized account is fail-closed
# ---------------------------------------------------------------------------


class TestUnauthorizedAccountNeverStarts:
    def test_no_session_means_no_runtime_and_no_binding(self, qapp, monkeypatch):
        window, manager, _, _ = build_window(
            monkeypatch,
            [(ACCOUNT_A, BROKER)],
            active=ACCOUNT_A,
            logged_in=set(),
        )
        page = window.order_configuration_page
        try:
            assert window.start_feedback_for_account(ACCOUNT_A, BROKER) is None
            assert window._feedback_services == {}
            assert manager.account_calls == []

            page._ensure_feedback_binding(ACCOUNT_A, BROKER)
            assert page._feedback_binders == {}
        finally:
            window.close()

    def test_logged_out_after_login_does_not_start(self, qapp, monkeypatch):
        window, _, auth, sessions = build_window(
            monkeypatch,
            [(ACCOUNT_A, BROKER)],
            active=ACCOUNT_A,
            logged_in={ACCOUNT_A},
        )
        try:
            assert window.start_feedback_for_account(ACCOUNT_A, BROKER) is not None
            service = window._feedback_services[(ACCOUNT_A, BROKER)]
            window.stop_feedback_for_account(ACCOUNT_A, BROKER)

            auth._logged_in[ACCOUNT_A] = False
            sessions.logout(ACCOUNT_A)
            assert window.start_feedback_for_account(ACCOUNT_A, BROKER) is None
            assert not service.isRunning()
        finally:
            stop_window(window, qapp)


# ---------------------------------------------------------------------------
# 3. Lifecycle stops only the affected account
# ---------------------------------------------------------------------------


class TestLifecycleStopsOnlyTheAffectedAccount:
    @pytest.mark.parametrize("event", ["logout", "delete", "broker_changed"])
    def test_lifecycle_event_stops_only_that_account(
        self, qapp, monkeypatch, event
    ):
        window, _, _, _ = build_window(
            monkeypatch,
            [(ACCOUNT_A, BROKER), (ACCOUNT_B, BROKER)],
            active=ACCOUNT_A,
            logged_in={ACCOUNT_A, ACCOUNT_B},
        )
        try:
            service_a = window.start_feedback_for_account(ACCOUNT_A, BROKER)
            wait_until(lambda: service_a._running, qapp)
            window.account_store.set_active(ACCOUNT_B)
            service_b = window.start_feedback_for_account(ACCOUNT_B, BROKER)
            wait_until(lambda: service_b._running, qapp)

            window._on_account_lifecycle(event, ACCOUNT_A, BROKER)

            assert wait_until(lambda: not service_a.isRunning(), qapp)
            assert service_b.isRunning()
        finally:
            stop_window(window, qapp)

    def test_switching_active_account_keeps_the_previous_runtime(
        self, qapp, monkeypatch
    ):
        window, _, _, _ = build_window(
            monkeypatch,
            [(ACCOUNT_A, BROKER), (ACCOUNT_B, BROKER)],
            active=ACCOUNT_A,
            logged_in={ACCOUNT_A, ACCOUNT_B},
        )
        try:
            service_a = window.start_feedback_for_account(ACCOUNT_A, BROKER)
            wait_until(lambda: service_a._running, qapp)

            window.account_store.set_active(ACCOUNT_B)
            window.select_page("Order Configuration")
            service_b = window._feedback_services.get((ACCOUNT_B, BROKER))
            wait_until(lambda: service_b is not None and service_b._running, qapp)

            assert service_a.isRunning()  # the previous account keeps running
            assert service_b.isRunning()
        finally:
            stop_window(window, qapp)


# ---------------------------------------------------------------------------
# 4. Restart never duplicates listeners
# ---------------------------------------------------------------------------


class TestRestartDoesNotDuplicateListeners:
    def test_start_stop_restart_keeps_one_listener_per_broker(
        self, qapp, monkeypatch
    ):
        window, manager, _, _ = build_window(
            monkeypatch,
            [(ACCOUNT_A, BROKER)],
            active=ACCOUNT_A,
            logged_in={ACCOUNT_A},
        )
        try:
            service = window.start_feedback_for_account(ACCOUNT_A, BROKER)
            wait_until(lambda: service._running, qapp)

            broker = manager.created[(ACCOUNT_A, BROKER)]
            assert len(broker.registered_listeners) == 1
            assert len(broker.queue_listeners) == 1
            assert len(broker.error_listeners) == 1

            window.stop_feedback_for_account(ACCOUNT_A, BROKER)
            assert wait_until(lambda: not service.isRunning(), qapp)

            restarted = window.start_feedback_for_account(ACCOUNT_A, BROKER)
            wait_until(lambda: restarted._running, qapp)

            assert restarted is service  # the SAME (cached) runtime
            assert len(broker.registered_listeners) == 1
            assert len(broker.queue_listeners) == 1
            assert len(broker.error_listeners) == 1
        finally:
            stop_window(window, qapp)


# ---------------------------------------------------------------------------
# 5/6. Account-scoped row routing (page level)
# ---------------------------------------------------------------------------


class TestAccountScopedRowRouting:
    def make_two_account_page(self):
        store = AccountStore(repository=False)
        store.add(ACCOUNT_A, BROKER, ACCOUNT_A)
        store.add(ACCOUNT_B, BROKER, ACCOUNT_B)
        store.set_active(ACCOUNT_A)
        page = make_page(store)
        binders = {
            (ACCOUNT_A, BROKER): FakeBinder(),
            (ACCOUNT_B, BROKER): FakeBinder(),
        }
        page.set_feedback_binder_factory(
            lambda account_id, broker_name: binders.get(
                (account_id, broker_name)
            )
        )
        return page, binders

    def test_same_decision_id_only_updates_its_own_account_row(
        self, qapp
    ):
        page, binders = self.make_two_account_page()
        order_a = append_order_row(
            page, ACCOUNT_A, BROKER, "DEC-SHARED", "NSC-A"
        )
        order_b = append_order_row(
            page, ACCOUNT_B, BROKER, "DEC-SHARED", "NSC-B"
        )
        page._ensure_feedback_binding(ACCOUNT_A, BROKER)
        page._ensure_feedback_binding(ACCOUNT_B, BROKER)

        assert not row_is_green(page, 0)
        assert not row_is_green(page, 1)

        binders[(ACCOUNT_A, BROKER)].emit_registered("DEC-SHARED", RAW_TS)

        assert page.order_log.rows()[0].registered_in_core is True
        assert page.order_log.rows()[1].registered_in_core is None
        assert row_is_green(page, 0)
        assert not row_is_green(page, 1)
        assert order_a is not order_b

    def test_registration_and_queue_route_to_the_sending_account(
        self, qapp
    ):
        page, binders = self.make_two_account_page()
        order_a = append_order_row(page, ACCOUNT_A, BROKER, "DEC-A", "NSC-A")
        append_order_row(page, ACCOUNT_B, BROKER, "DEC-B", "NSC-B")
        page._ensure_feedback_binding(ACCOUNT_A, BROKER)
        page._ensure_feedback_binding(ACCOUNT_B, BROKER)

        binder_a = binders[(ACCOUNT_A, BROKER)]
        binder_a.emit_registered("DEC-A", RAW_TS)
        binder_a.emit_queue("DEC-A", 7)

        assert page.order_log.rows()[0].registered_in_core is True
        assert page.order_log.rows()[1].registered_in_core is None
        assert row_is_green(page, 0)
        assert not row_is_green(page, 1)

        rendered = [
            page.order_log_table.item(0, COLUMN_QUEUE_STATUS).text(),
            page.order_log_table.item(1, COLUMN_QUEUE_STATUS).text(),
        ]
        assert rendered[0] == "7"
        assert rendered[1] == EMPTY_CELL
        assert page._queue_status_text_by_order.get(id(order_a)) == "7"

    def test_unknown_and_other_account_events_are_noops(self, qapp):
        page, binders = self.make_two_account_page()
        append_order_row(page, ACCOUNT_A, BROKER, "DEC-A", "NSC-A")
        append_order_row(page, ACCOUNT_B, BROKER, "DEC-B", "NSC-B")
        page._ensure_feedback_binding(ACCOUNT_A, BROKER)
        page._ensure_feedback_binding(ACCOUNT_B, BROKER)

        before = [
            row.registered_in_core for row in page.order_log.rows()
        ]
        # Unknown decision id, and an event of account B for A's decision.
        binders[(ACCOUNT_A, BROKER)].emit_registered("DEC-UNKNOWN", RAW_TS)
        binders[(ACCOUNT_B, BROKER)].emit_registered("DEC-A", RAW_TS)
        binders[(ACCOUNT_A, BROKER)].emit_queue("DEC-UNKNOWN", 3)
        binders[(ACCOUNT_B, BROKER)].emit_queue("DEC-A", 3)

        after = [row.registered_in_core for row in page.order_log.rows()]
        assert after == before
        assert not row_is_green(page, 0)
        assert not row_is_green(page, 1)
        assert (
            page.order_log_table.item(0, COLUMN_QUEUE_STATUS).text()
            == EMPTY_CELL
        )


# ---------------------------------------------------------------------------
# 7/8. MainWindow end-to-end + offline/lazy + Dry Run
# ---------------------------------------------------------------------------


class TestMainWindowEndToEndFeedback:
    def test_binding_starts_the_runtime_and_routes_events(
        self, qapp, monkeypatch
    ):
        window, manager, _, _ = build_window(
            monkeypatch,
            [(ACCOUNT_A, BROKER), (ACCOUNT_B, BROKER)],
            active=ACCOUNT_A,
            logged_in={ACCOUNT_A, ACCOUNT_B},
        )
        page = window.order_configuration_page
        try:
            append_order_row(page, ACCOUNT_A, BROKER, "DEC-A", "NSC-A")
            append_order_row(page, ACCOUNT_B, BROKER, "DEC-B", "NSC-B")

            page._ensure_feedback_binding(ACCOUNT_A, BROKER)
            service_a = page._feedback_binders[(ACCOUNT_A, BROKER)]
            wait_until(lambda: service_a._running, qapp)

            window.account_store.set_active(ACCOUNT_B)
            page._ensure_feedback_binding(ACCOUNT_B, BROKER)
            service_b = page._feedback_binders[(ACCOUNT_B, BROKER)]
            wait_until(lambda: service_b._running, qapp)

            assert service_a is not service_b

            broker_a = manager.created[(ACCOUNT_A, BROKER)]
            broker_a.emit_registered("DEC-A", RAW_TS)

            assert wait_until(lambda: row_is_green(page, 0), qapp)
            assert not row_is_green(page, 1)
        finally:
            stop_window(window, qapp)


class TestOfflineLazyAndDryRun:
    def test_construction_composes_nothing_and_keeps_the_gate(
        self, qapp, monkeypatch
    ):
        import brokers.manager as manager_module
        import ui.authentication_service as auth_module
        import ui.credential_store as credential_module
        import ui.order_feedback_service as feedback_module
        import ui.session_manager as session_module

        constructions = []

        class Forbidden:
            def __init__(self, *args, **kwargs):
                constructions.append(type(self).__name__)
                raise AssertionError("construction must stay lazy")

        monkeypatch.setattr(feedback_module, "OrderFeedbackService", Forbidden)
        monkeypatch.setattr(manager_module, "BrokerManager", Forbidden)
        monkeypatch.setattr(auth_module, "AuthenticationService", Forbidden)
        monkeypatch.setattr(credential_module, "CredentialStore", Forbidden)
        monkeypatch.setattr(session_module, "SessionManager", Forbidden)

        window = MainWindow_offline()
        try:
            page = window.order_configuration_page
            assert constructions == []
            assert window._feedback_services == {}
            assert window._broker_manager_cache is None
            assert page._feedback_binders == {}
            # The order gate and the account-aware feedback factory stay wired.
            assert page._feedback_binder_factory is not None
            assert page._order_authorizer_factory is not None
        finally:
            window.close()

    def test_starting_feedback_never_sends_an_order(
        self, qapp, monkeypatch
    ):
        window, manager, _, _ = build_window(
            monkeypatch,
            [(ACCOUNT_A, BROKER)],
            active=ACCOUNT_A,
            logged_in={ACCOUNT_A},
        )
        try:
            service = window.start_feedback_for_account(ACCOUNT_A, BROKER)
            wait_until(lambda: service._running, qapp)
            broker = manager.created[(ACCOUNT_A, BROKER)]
            assert broker.send_calls == []
            assert not hasattr(service, "place_order")
        finally:
            stop_window(window, qapp)


def MainWindow_offline():
    """A real MainWindow over an in-memory store (no per-user database)."""
    from ui.main_window import MainWindow

    return MainWindow(account_store=AccountStore(repository=False))
