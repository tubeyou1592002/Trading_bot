"""Offline coverage for Live preflight/snapshots and optional NATS feedback."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from core.order_queue import OrderQueue
from core.safety_gate import SafetyGate
from models.order import Order
from ui import strings as STRINGS
from ui.account_store import AccountStore
from ui.live_order_gate import LiveReadiness, check_live_readiness
from ui.order_configuration_page import OrderConfigurationPage
from ui.session_manager import SessionState


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_page(qapp):
    store = AccountStore()
    store.add("ACC-1", "SIM", "Account One")
    store.set_active("ACC-1")
    queue = OrderQueue()
    page = OrderConfigurationPage(store, order_queue=queue)
    page.set_order_authorizer_factory(
        lambda: lambda *_: SimpleNamespace(authorized=True)
    )
    return page, store, queue


class _AllowedGate:
    def evaluate(self):
        return SimpleNamespace(allowed=True, reason="allowed")


def test_default_mode_is_dry_run_and_live_requires_confirmation(qapp):
    page, _, queue = make_page(qapp)
    try:
        assert page._run_mode == "dry_run"
        assert page.dry_run_mode_button.isChecked()
        assert not page.live_mode_button.isChecked()

        queue.enqueue(Order("N1", 1, 100, 1), "ACC-1", "SIM")
        page.live_mode_button.setChecked(True)
        assert page._run_mode == "live"
        prompts = []
        page.set_live_confirmation_handler(lambda summary: prompts.append(summary) or False)
        page._test_mode = True
        page._test_runner_factory = lambda **_: pytest.fail("must not build runner")
        page._run_test_pass()
        assert not prompts
        assert "آماده‌ساز واقعی" in page.queue_status_label.text()
    finally:
        page.close()


def test_live_missing_preparation_fails_closed_before_prompt(qapp):
    page, _, queue = make_page(qapp)
    try:
        queue.enqueue(Order("N1", 1, 100, 1), "ACC-1", "SIM")
        page.live_mode_button.setChecked(True)
        prompts = []
        page.set_live_confirmation_handler(lambda summary: prompts.append(summary) or True)
        page.set_test_runner_factory(lambda **_: pytest.fail("runner must not be built"))
        page._test_mode = True
        page._run_test_pass()
        assert prompts == []
        assert "آماده‌ساز واقعی" in page.queue_status_label.text()
    finally:
        page.close()


def test_snapshot_mutation_during_live_confirmation_aborts(qapp):
    page, store, queue = make_page(qapp)
    try:
        queue.enqueue(Order("N1", 1, 100, 1), "ACC-1", "SIM")
        entry = queue.list_pending()[0]
        page.live_mode_button.setChecked(True)
        page.set_live_readiness_factory(
            lambda *_args, **kwargs: LiveReadiness(
                kwargs["human_approval"],
                "ready",
                _AllowedGate() if kwargs["human_approval"] else None,
                ready_for_confirmation=not kwargs["human_approval"],
            )
        )

        def mutate_then_confirm(_summary):
            queue.remove(entry)
            queue.enqueue(Order("N2", 1, 100, 1), "ACC-1", "SIM")
            return True

        page.set_live_confirmation_handler(mutate_then_confirm)
        page.set_test_runner_factory(lambda **_: pytest.fail("stale snapshot dispatched"))
        page._test_mode = True
        page._run_test_pass()
        assert "آماده‌ساز واقعی" in page.queue_status_label.text()
    finally:
        page.close()


def test_snapshot_targets_do_not_follow_later_active_account_change(qapp):
    page, store, queue = make_page(qapp)
    try:
        queue.enqueue(Order("N1", 1, 100, 1), "ACC-1", "SIM")
        targets = page._frozen_dispatch_targets()
        frozen_entry = targets[0].entry
        store.add("ACC-2", "SIM", "Account Two")
        store.set_active("ACC-2")
        assert targets[0].entry is frozen_entry
        assert targets[0].account_id == "ACC-1"
        assert targets[0].account is store.get("ACC-1").account
    finally:
        page.close()


def test_live_is_rejected_while_schedule_is_active(qapp):
    page, _, queue = make_page(qapp)
    try:
        queue.enqueue(Order("N1", 1, 100, 1), "ACC-1", "SIM")
        page.live_mode_button.setChecked(True)
        page._schedule_locked = True
        page.set_live_readiness_factory(
            lambda *_args, **_kwargs: pytest.fail("scheduled Live must stop before readiness")
        )
        page._test_runner_factory = lambda **_: pytest.fail("scheduled Live must not build runner")
        page._test_mode = True
        page._run_test_pass()
        assert "زمان‌بندی‌شده غیرفعال است" in page.queue_status_label.text()
    finally:
        page.close()


def test_summary_counts_total_possible_sends(qapp):
    page, _, _ = make_page(qapp)
    try:
        timing = SimpleNamespace(
            start_time=datetime(2026, 1, 1, 10, 0),
            end_time=datetime(2026, 1, 1, 10, 1),
        )
        summary = page._live_schedule_summary(
            page.store.get("ACC-1"), 3, timing, 1000
        )
        assert "نوبت‌های برنامه‌ریزی‌شده: ۶۱" in summary
        assert "حداکثر ارسال احتمالی: ۱۸۳" in summary
        assert "همهٔ سفارش‌های صف دوباره ارسال می‌شوند" in summary
    finally:
        page.close()


def test_live_readiness_never_invents_m6_or_broker_status():
    class Store:
        def active_account_id(self):
            return "A"

        def get(self, _):
            return SimpleNamespace(
                account_id="A", broker_name="SIM",
                account=SimpleNamespace(account_id="A"),
            )

    class Auth:
        def is_logged_in(self, _): return True
        def get_adapter(self, _): return SimpleNamespace(
            is_authenticated=lambda: True,
            get_authenticated_session=lambda: SimpleNamespace(access_token="t"),
            broker_name="SIM",
        )

    class Sessions:
        def get(self, _): return SimpleNamespace(
            account_id="A", state=SessionState.LOGGED_IN, broker_name="SIM"
        )
        def get_token(self, _): return "t"

        def is_logged_in(self, _): return True

    # This fixture exercises a fully valid SafetyGate only through the
    # injected prerequisite provider; it never uses a real broker/network.
    broker = SimpleNamespace(live_trading_enabled=True)
    manager = SimpleNamespace(get_for_account=lambda *_: broker)
    result = check_live_readiness(
        account_store=Store(), authentication_service=Auth(),
        session_manager=Sessions(), broker_manager=manager,
        account_id="A", broker_name="SIM", explicit_live_request=True,
        human_approval=True,
    )
    assert not result.allowed
    assert "منبع معتبر وضعیت M6" in result.reason

    ready = check_live_readiness(
        account_store=Store(), authentication_service=Auth(),
        session_manager=Sessions(), broker_manager=manager,
        account_id="A", broker_name="SIM", explicit_live_request=True,
        human_approval=True,
        prerequisite_provider=lambda **_: {
            "m6_status": "ACTIVE", "broker_status": "READY",
            "acceptable_m6_statuses": ("ACTIVE",),
            "acceptable_broker_statuses": ("READY",),
        },
    )
    assert ready.allowed
    assert ready.gate.evaluate().allowed


def test_live_readiness_reports_missing_broker_lock_without_changing_it():
    # The application's actual broker lock is never toggled by readiness.
    broker = SimpleNamespace(live_trading_enabled=False)
    manager = SimpleNamespace(get_for_account=lambda *_: broker)
    # Reuse the fully authorized local fakes from the readiness test.
    class Store:
        def active_account_id(self): return "A"
        def get(self, _):
            return SimpleNamespace(account_id="A", broker_name="SIM")
    class Auth:
        def is_logged_in(self, _): return True
        def get_adapter(self, _):
            return SimpleNamespace(
                is_authenticated=lambda: True,
                get_authenticated_session=lambda: SimpleNamespace(access_token="t"),
                broker_name="SIM",
            )
    class Sessions:
        def get(self, _):
            return SimpleNamespace(account_id="A", state=SessionState.LOGGED_IN,
                                   broker_name="SIM")
        def get_token(self, _): return "t"
    result = check_live_readiness(
        account_store=Store(), authentication_service=Auth(),
        session_manager=Sessions(), broker_manager=manager,
        account_id="A", broker_name="SIM", explicit_live_request=True,
        human_approval=True,
    )
    assert not result.allowed
    assert "قفل ایمنی داخلی" in result.reason
    assert broker.live_trading_enabled is False


class FakeSignal:
    def __init__(self): self.callbacks = []
    def connect(self, callback): self.callbacks.append(callback)
    def emit(self, *args):
        for callback in self.callbacks: callback(*args)


class FakeBinder(QObject):
    order_registered = Signal(str, object, object)
    queue_position = Signal(str, int)
    feedback_unavailable = Signal()
    start_failed = Signal(str)


def test_nats_unavailable_is_display_only_and_does_not_replay(qapp):
    page, _, queue = make_page(qapp)
    try:
        queue.enqueue(Order("N1", 1, 100, 1), "ACC-1", "SIM")
        binder = FakeBinder()
        page.set_feedback_binder_factory(lambda *_: binder)
        calls = []

        class Runner:
            last_order_results = [None]
            def run(self, entries, account=None):
                calls.append(tuple(entries))
                return None, "exec", SimpleNamespace(
                    success=True, sent=False, mode="DRY_RUN"
                )

        page.set_test_runner_factory(lambda: Runner())
        page._test_mode = True
        page._run_test_pass()
        assert len(calls) == 1
        before = page._last_test_run
        binder.feedback_unavailable.emit()
        assert page.feedback_status_label.text() == STRINGS.FEEDBACK_UNAVAILABLE
        assert page._last_test_run is before
        assert len(calls) == 1
    finally:
        page.close()


def test_nats_start_failure_only_sets_feedback_unavailable(qapp):
    page, _, _ = make_page(qapp)
    try:
        binder = FakeBinder()
        page.set_feedback_binder_factory(lambda *_: binder)
        page._ensure_feedback_binding("ACC-1", "SIM")
        binder.feedback_unavailable.emit()
        assert page.feedback_status_label.text() == STRINGS.FEEDBACK_UNAVAILABLE
        assert "private transport detail" not in page.feedback_status_label.text()
    finally:
        page.close()


def test_initial_http_failure_stays_order_result_not_nats_status(qapp):
    page, _, queue = make_page(qapp)
    try:
        queue.enqueue(Order("N1", 1, 100, 1), "ACC-1", "SIM")
        calls = []

        class Runner:
            last_order_results = [SimpleNamespace(
                success=False, sent=False, mode="ERROR", response=None
            )]

            def run(self, entries, account=None):
                calls.append(tuple(entries))
                return None, "exec", SimpleNamespace(
                    success=False, sent=False, mode="ERROR", message="HTTP timeout"
                )

        page.set_test_runner_factory(lambda: Runner())
        page._test_mode = True
        page._run_test_pass()
        assert len(calls) == 1
        assert page._last_test_run[2].mode == "ERROR"
        assert page.feedback_status_label.text() == ""
        assert len(page.order_log.rows()) == 1
    finally:
        page.close()
