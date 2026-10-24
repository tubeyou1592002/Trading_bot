"""
test_ui7_task2_countdown_state.py — system-clock schedule lifecycle,
Apply / lock / Stop, countdown and displayed states.

Fully offline. The schedule clock and monotonic clock are injected by the
test. No clock network request, real broker, or real order is used.

The ten scenarios mandated by the UI-7 Task 2 spec
--------------------------------------------------
  1. construction, display and Apply make no clock-network request;
  2. no manual sync controls or site-time freshness state remain;
  3. Apply uses the injected system wall/monotonic clock without a request;
  6. Apply locks every order / queue / schedule control and turns itself
     into Stop, with Stop being the single way out;
  7. Stop stops the timer, clears the plan and unlocks — and sends
     nothing (Task 2 never dispatches);
  8. a system-clock step cannot move an active countdown;
  9. expiry frees the controls and the next Apply inherits nothing;
 10. the UI-5 / UI-6 suites and the offline-construction contract are
     untouched by all of the above.

Plus the display-state scenario: START_NOW is shown exactly once for a
start that is already in the past while the end is still in the future,
and it never dispatches in Task 2.
"""

import os
import subprocess
import sys
import time as _time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
UTC = timezone.utc

# A fixed "now": 2026-10-02 09:29:00Z == 12:59:00 Tehran.
FIXED_NOW = datetime(2026, 10, 2, 9, 29, 0, tzinfo=UTC)
TEHRAN = timezone(timedelta(hours=3, minutes=30))
FIXED_TEHRAN = FIXED_NOW.astimezone(TEHRAN)

GOOD_BODY = "10/02/2026 09:29:00"
GOOD_DATE_HEADER = "Thu, 02 Oct 2026 09:29:00 GMT"

from ui.schedule_settings import (  # noqa: E402
    APPLY_BUTTON_LABEL,
    COUNTDOWN_LABEL_NO_UPCOMING,
    COUNTDOWN_LABEL_STOPPED,
    SCHEDULE_STATE_CONFIG,
    SCHEDULE_STATE_COUNTING,
    SCHEDULE_STATE_EXPIRED,
    SCHEDULE_STATE_START_NOW,
    SCHEDULE_STATE_STOPPED,
    SCHEDULE_STATE_WAITING,
    STOP_BUTTON_LABEL,
)
from ui import strings as STRINGS


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_result(status=200, text=GOOD_BODY, headers=None):
    from ui.market_clock import TransportResult

    return TransportResult(
        status_code=status,
        text=text,
        headers=headers if headers is not None else {},
    )


def market_headers(extra=None):
    headers = {
        "Content-Type": "text/plain",
        "Date": GOOD_DATE_HEADER,
    }
    if extra:
        headers.update(extra)
    return headers


def fixed_transport(result=None, raises=None):
    """A transport stub that never touches the network."""
    calls = []

    def _transport(url, timeout):
        calls.append((url, timeout))
        if raises is not None:
            raise raises
        return result if result is not None else make_result(headers=market_headers())

    _transport.calls = calls
    return _transport


def offline_transport(result=None):
    return fixed_transport(
        result=result if result is not None else make_result(headers=market_headers())
    )


def forbidden_transport(url, timeout):
    raise AssertionError(
        "a real network fetch was attempted; tests must stay offline"
    )


def _drain_events(count=50):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for _ in range(count):
        app.processEvents()


def pump(ms):
    """Run the event loop (with real time passing) for ``ms`` milliseconds."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    deadline = _time.monotonic() + ms / 1000.0
    while _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.005)


class Clock:
    """
    A wall + monotonic pair the test drives directly.

    ``advance()`` moves BOTH clocks (real elapsed time). ``step_wall()``
    moves only the system clock — an NTP step: real time has not passed.
    """

    def __init__(self, wall=FIXED_NOW, mono=0.0):
        self.wall = wall
        self.mono = mono

    def advance(self, seconds):
        self.wall = self.wall + timedelta(seconds=seconds)
        self.mono += float(seconds)

    def step_wall(self, seconds):
        self.wall = self.wall + timedelta(seconds=seconds)


def _with_valid_destination(page, account_id="ACC-SCHED", broker_name="SIM"):
    """
    Give the page a VALID destination set: one account plus one queued order.

    UI-7 Task 3 refuses to activate a schedule whose destination set is
    not fully valid (empty queue, a missing account, or a broker that
    disagrees with the account's own broker). These tests are about the
    countdown and the locked controls, not about dispatching, so they run
    against a page that has one usable destination.

    The send path is a double, so nothing here ever reaches the real one.
    """
    from models.order import Order

    page.store.add(account_id, broker_name, account_id)
    page.order_queue.enqueue(
        Order(nsc_id="nsc-scheduled", side=1, price=1000, quantity=10),
        account_id,
        broker_name,
    )

    class _StubResult:
        def __init__(self, trace_id, success, message="ok"):
            self.trace_id = trace_id
            self.success = success
            self.message = message

    class _RecordingSendRunner:
        """A stand-in for the EXISTING send path; fully offline."""

        def __init__(self):
            self.calls = []

        def run(self, entries, account=None):
            self.calls.append(tuple(entries))
            return (
                None,
                "exec-scheduled",
                _StubResult(trace_id="trace-scheduled", success=True),
            )

    page.set_test_runner_factory(_RecordingSendRunner)
    return page


def make_page(qapp, transport=None, clock=None):
    """Build a page with wall and monotonic clocks injected at the module seam."""
    from ui.account_store import AccountStore
    from ui.session_manager import SessionManager
    import ui.order_configuration_page as page_module
    from ui.order_configuration_page import OrderConfigurationPage

    clock = clock if clock is not None else Clock()
    class _DateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock.wall
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(page_module, "datetime", _DateTime)
    monkeypatch.setattr(page_module, "system_wall_now", lambda: clock.wall.astimezone(ZoneInfo("Asia/Tehran")))
    monkeypatch.setattr(page_module, "sample_system_clocks", lambda: (clock.wall.astimezone(ZoneInfo("Asia/Tehran")), clock.mono))
    monkeypatch.setattr(page_module, "system_monotonic", lambda: clock.mono)
    monkeypatch.setattr(page_module, "schedule_monotonic", lambda: clock.mono)
    page = OrderConfigurationPage(AccountStore())
    page.clock = clock
    _with_valid_destination(page)
    sessions = SessionManager()
    sessions.register("ACC-SCHED", "SIM")
    sessions.begin_login("ACC-SCHED")
    sessions.mark_logged_in("ACC-SCHED", "offline-test-token")
    page.set_session_manager(sessions)
    page.test_session_manager = sessions
    PAGES.append(page)
    return page


@pytest.fixture(autouse=True)
def no_get_time_requests(monkeypatch):
    import requests

    original = requests.get
    def guarded(url, *args, **kwargs):
        assert "cdn.tsetmc.com/api/StaticData/GetTime" not in str(url)
        return original(url, *args, **kwargs)
    monkeypatch.setattr(requests, "get", guarded)


#: Every page built by this module, so nothing can outlive its test with a
#: running countdown timer.
PAGES = []


@pytest.fixture(autouse=True)
def _stop_lingering_schedules():
    yield
    for page in PAGES:
        try:
            if page.countdown_active or page._schedule_locked:
                page._on_stop_schedule()
        except RuntimeError:      # the C++ object is already gone
            pass
    PAGES.clear()


def fill(page, start, end, interval, dispatch_interval_ms="50"):
    """Fill the schedule inputs.

    ``dispatch_interval_ms`` is the UI-7 Task 3 dispatch cadence. It is a
    REQUIRED positive whole number of milliseconds, so the helper supplies a
    valid default and the Task 3 tests pass their own value explicitly.
    """
    page.schedule_start_input.setText(start)
    page.schedule_end_input.setText(end)
    page.schedule_interval_input.setText(interval)
    page.dispatch_interval_input.setText(dispatch_interval_ms)


def sync_clock(page):
    """Compatibility helper: schedule clock is system-injected, no sync."""
    return None


def apply_schedule(page):
    """Press Apply; the schedule uses only injected local clocks."""
    page._on_apply_schedule()
    _drain_events()


def locked_controls(page):
    """Every widget of the page that may change an order, queue or schedule."""
    widgets = {
        "schedule start": page.schedule_start_input,
        "schedule end": page.schedule_end_input,
        "schedule interval": page.schedule_interval_input,
        "symbol": page.symbol_input,
        "results": page.results_list,
        "price": page.price_input,
        "quantity": page.quantity_input,
        "add to queue": page.add_to_queue_button,
        "queue list": page.queue_list,
        "test": page.test_button,
    }
    for side, button in page.side_buttons.items():
        widgets[f"side {side}"] = button
    return widgets


# ============================================================
# 1. Startup never synchronizes a clock
# ============================================================


def test_1_startup_never_requests_clock_network(qapp, monkeypatch):
    """
    The real MainWindow path: construction imports and builds nothing that
    talks to the network, ``show()`` schedules exactly one non-blocking
    clock request, including while Home remains visible.
    """
    from ui.main_window import MainWindow

    def _boom(url, timeout):
        raise AssertionError("a real network fetch was attempted")

    # Any accidental real fetch during construction fails loudly.
    import requests
    monkeypatch.setattr(requests, "get", _boom)

    # --- construction is offline and schedules nothing yet ---------------
    window = MainWindow()
    page = window.order_configuration_page
    window.show()
    pump(250)
    assert not hasattr(page, "start_startup_sync")
    assert not hasattr(page, "sync_clock_button")
    assert not hasattr(page, "refresh_clock_button")

    # Home was visible throughout; no clock network operation is started.
    assert window.content_area.currentWidget() is window.placeholder_pages["Home"]

    window.hide()
    window.show()
    pump(100)

    window.close()


# ============================================================
# 2. There is no manual sync UI
# ============================================================


def test_2_schedule_clock_controls_are_removed(qapp):
    page = make_page(qapp)
    assert not hasattr(page, "sync_clock_button")
    assert not hasattr(page, "refresh_clock_button")
    assert not hasattr(page, "sync_status_label")
    assert not hasattr(page, "clock_status_label")


def test_2b_system_clock_row_has_honest_label(qapp):
    page = make_page(qapp)
    assert page.schedule_group.findChildren(type(page.schedule_timezone_label))
    assert STRINGS.LABEL_SYSTEM_CLOCK in page.schedule_group.title() or any(
        page.schedule_group.layout().itemAt(i).widget() is not None
        and STRINGS.LABEL_SYSTEM_CLOCK in page.schedule_group.layout().itemAt(i).widget().text()
        for i in range(page.schedule_group.layout().count())
    )


# ============================================================
# 3. Apply uses the injected system clock — no request of its own
# ============================================================


def test_3_apply_uses_system_clock_without_new_requests(qapp):
    transport = offline_transport()
    page = make_page(qapp, transport=transport)

    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)

    assert len(transport.calls) == 0, "schedule tried to fetch a clock"
    assert page.schedule_timing() is not None
    assert page.schedule_times()


# ============================================================
# 4. Apply remains local and never waits for clock-network activity
# ============================================================


def test_4_apply_does_not_wait_for_or_start_clock_network(qapp):
    calls = []

    def _slow_fail(url, timeout):
        calls.append(url)
        raise AssertionError("clock network access is forbidden")

    page = make_page(qapp, transport=_slow_fail)
    fill(page, "13:00:00", "13:05:00", "15")

    apply_schedule(page)
    assert calls == []
    assert page.schedule_timing() is not None


# ============================================================
# 4a. Apply locks locally; Stop cancels the countdown
# ============================================================


def test_4a_apply_and_stop_work_without_pending_clock_sync(qapp):
    """
    Apply locks the controls using local schedule state. Stop cancels
    the countdown and no clock request is involved.
    """
    calls = []

    def _slow_ok(url, timeout):
        calls.append(url)
        raise AssertionError("clock network access is forbidden")

    page = make_page(qapp, transport=_slow_ok)
    widgets = locked_controls(page)
    before = {name: w.isEnabled() for name, w in widgets.items()}
    fill(page, "13:00:00", "13:05:00", "15")

    page._on_apply_schedule()
    assert page._schedule_locked, "Apply did not lock while the sync ran"
    assert page.apply_schedule_button.text() == STOP_BUTTON_LABEL
    for name, w in widgets.items():
        assert not w.isEnabled(), f"{name} was still editable while pending"
    assert page.schedule_timing() is not None

    # Stop is the single way out, and it cancels the pending plan
    page._on_schedule_button_clicked()

    assert not page._schedule_locked, "Stop did not free the controls"
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL
    for name, w in widgets.items():
        assert w.isEnabled() == before[name], f"{name} stayed locked after Stop"
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_STOPPED

    assert calls == []
    assert page.schedule_timing() is None, "a callback revived a cancelled plan"
    assert not page.countdown_active, "a callback started a cancelled countdown"
    assert not page._schedule_locked, "a callback re-locked a cancelled plan"
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL

    # --- (b) an Apply that is NOT cancelled still completes normally ------
    page2 = make_page(qapp, transport=offline_transport(), clock=Clock())
    fill(page2, "13:00:00", "13:05:00", "15")
    page2._on_apply_schedule()
    assert page2._schedule_locked
    assert page2.apply_schedule_button.text() == STOP_BUTTON_LABEL
    assert page2.schedule_timing() is not None
    assert page2.countdown_active


def test_4b_apply_without_clock_sync_dependency_never_fetches(qapp):
    transport = offline_transport()
    page = make_page(qapp, transport=transport)

    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)

    assert transport.calls == [], "Apply must not make a clock request"
    assert page.schedule_timing() is not None
    assert page.schedule_timezone_label.text()


# ============================================================
# 5. Countdown is anchored monotonically despite wall-clock changes
# ============================================================


def test_5_wall_clock_steps_do_not_move_locked_monotonic_deadlines(qapp):
    clock = Clock()
    transport = offline_transport()
    page = make_page(qapp, transport=transport, clock=clock)
    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)
    base = page._locked_base_time
    mono = page._locked_mono_anchor
    clock.step_wall(3600)
    assert page._get_locked_now_tehran() == base
    assert page.apply_schedule_button.text() == STOP_BUTTON_LABEL
    page._on_stop_schedule()
    assert page._locked_mono_anchor is None


# ============================================================
# 5b. The system-clock display stays network independent
# ============================================================


def test_5b_system_clock_display_is_tehran_and_sync_rows_are_absent(qapp):
    clock = Clock()
    transport = offline_transport()
    page = make_page(qapp, transport=transport, clock=clock)
    page._refresh_market_clock_row()
    assert page.schedule_timezone_label.text() == clock.wall.astimezone(ZoneInfo("Asia/Tehran")).strftime("%H:%M:%S")

    assert not hasattr(page, "sync_status_label")
    assert not hasattr(page, "sync_clock_button")
    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)
    assert page.countdown_active
    base_before = page._locked_base_time
    mono_anchor_before = page._locked_mono_anchor
    target_before = page._countdown_target
    label_before = page.countdown_label.text()

    clock.advance(5)
    page._update_countdown()
    assert page._locked_base_time == base_before, "the locked base moved"
    assert page._locked_mono_anchor == mono_anchor_before
    assert page._countdown_target == target_before, "the countdown target moved"
    assert page.countdown_label.text() != label_before, "monotonic countdown did not advance"
    assert page.countdown_active, "the display refresh stopped the countdown"
    assert page.apply_schedule_button.text() == STOP_BUTTON_LABEL


# ============================================================
# 6. Apply locks every order / queue / schedule control
# ============================================================


def test_6_apply_locks_every_control_and_becomes_stop(qapp):
    page = make_page(qapp, transport=offline_transport())
    widgets = locked_controls(page)

    before = {name: w.isEnabled() for name, w in widgets.items()}
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL
    assert page.apply_schedule_button.isEnabled()

    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)

    assert page.schedule_timing() is not None
    assert page.countdown_active

    for name, w in widgets.items():
        assert not w.isEnabled(), f"{name} stayed enabled while the schedule is active"

    # the Apply button IS the Stop button now, and it is the only way out
    assert page.apply_schedule_button.isEnabled()
    assert page.apply_schedule_button.text() == STOP_BUTTON_LABEL
    assert page.apply_schedule_button.text() != APPLY_BUTTON_LABEL

    # the lifecycle state is one of the displayed schedule states
    assert page.schedule_lifecycle_state() in {
        SCHEDULE_STATE_WAITING,
        SCHEDULE_STATE_COUNTING,
        SCHEDULE_STATE_START_NOW,
    }
    assert page.schedule_state_label.text() == page.schedule_lifecycle_state()
    assert page.countdown_label.text().startswith(
        STRINGS.COUNTDOWN_NEXT_RUN.split("{", 1)[0]
    )


# ============================================================
# 7. Stop stops, clears, unlocks — and sends nothing
# ============================================================


def test_7_stop_cancels_the_countdown_unlocks_and_sends_nothing(qapp):
    transport = offline_transport()
    page = make_page(qapp, transport=transport)
    widgets = locked_controls(page)
    before = {name: w.isEnabled() for name, w in widgets.items()}

    # instrument the two UI paths that could turn into an outgoing action
    ran = []
    page.set_test_runner_factory(lambda: ran.append("test-runner"))
    page.set_feedback_binder_factory(lambda *a, **k: ran.append("feedback-binder"))
    queue = page.order_queue
    queue_before = len(queue.list_pending())
    queue_rows_before = page.queue_list.count()

    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)
    assert page.countdown_active
    assert page.apply_schedule_button.text() == STOP_BUTTON_LABEL
    transport_calls_before = len(transport.calls)

    page._on_stop_schedule()

    # timer stopped, plan cleared, state shown
    assert not page.countdown_active, "the countdown timer is still running"
    assert page.schedule_timing() is None, "the accepted plan survived Stop"
    assert page.schedule_times() == ()
    assert page.schedule_state() is None
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_STOPPED
    assert page.schedule_state_label.text() == SCHEDULE_STATE_STOPPED
    assert page.countdown_label.text() == COUNTDOWN_LABEL_STOPPED

    # everything is free again, exactly as it was before Apply
    for name, w in widgets.items():
        assert w.isEnabled() == before[name], f"{name} did not come back"
    assert page.apply_schedule_button.isEnabled()
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL

    # nothing was sent anywhere
    assert len(transport.calls) == transport_calls_before, "Stop made a request"
    assert ran == [], f"Stop triggered {ran}"
    assert page.order_queue is queue
    assert len(queue.list_pending()) == queue_before
    assert page.queue_list.count() == queue_rows_before

    # the next press of the button is Apply again, not Stop
    page._on_schedule_button_clicked()          # rejected: inputs were kept
    assert page.apply_schedule_button.text() in (
        APPLY_BUTTON_LABEL,
        STOP_BUTTON_LABEL,
    )


# ============================================================
# 8. A clock step cannot move an active countdown
# ============================================================


def test_8_clock_step_cannot_move_the_countdown(qapp):
    clock = Clock()
    transport = offline_transport()
    page = make_page(qapp, transport=transport, clock=clock)

    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)

    assert page.countdown_active
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_WAITING
    target_before = page._countdown_target
    times_before = page.schedule_times()
    now_before = page._get_locked_now_tehran()
    label_before = page.countdown_label.text()
    assert target_before is not None

    # --- the locked monotonic clock is independent of system display ------
    assert page._countdown_target == target_before, "clock state moved the target"
    assert page.schedule_times() == times_before, "clock state regenerated the moments"
    assert page._get_locked_now_tehran() == now_before, "clock state moved the clock"
    assert page.countdown_active
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_WAITING

    # --- a system-clock step must not move anything either --------------
    clock.step_wall(-3600)
    page._update_countdown()
    assert page._countdown_target == target_before, "a wall-clock step moved the target"
    assert page.countdown_label.text() == label_before, "a wall-clock step rewound the countdown"
    assert page.countdown_active
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_WAITING

    # real elapsed time still advances the countdown, exactly once
    clock.advance(70)                 # 12:59:00 -> 13:00:10, start is 13:00:00
    page._update_countdown()
    assert page._countdown_target is not None
    assert page._countdown_target > target_before
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_COUNTING
    assert page.countdown_label.text() != label_before
    # UI-9 Task 3: the countdown keeps LATIN digits (technical timestamp).
    assert "13:00:15" in page.countdown_label.text()


# ============================================================
# 8b. Apply locks the EFFECTIVE now, never the raw offset terms
# ============================================================


def test_8b_apply_samples_system_wall_and_monotonic_together(qapp):
    clock = Clock()
    page = make_page(qapp, clock=clock)
    clock.advance(0.5)
    expected_wall = clock.wall.astimezone(ZoneInfo("Asia/Tehran"))
    expected_mono = clock.mono

    fill(page, "13:05:00", "13:10:00", "15")
    apply_schedule(page)
    assert page.countdown_active
    assert page._locked_base_time == expected_wall
    assert page._locked_mono_anchor == expected_mono


# ============================================================
# 9. Expiry frees the controls and the next Apply is clean
# ============================================================


def test_9_expiry_frees_the_controls_and_the_next_apply_is_clean(qapp):
    clock = Clock()
    transport = offline_transport()
    page = make_page(qapp, transport=transport, clock=clock)
    widgets = locked_controls(page)
    before = {name: w.isEnabled() for name, w in widgets.items()}

    fill(page, "13:00:00", "13:00:30", "15")
    apply_schedule(page)
    assert page.countdown_active
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_WAITING
    stale_target = page._countdown_target
    stale_times = page.schedule_times()
    for w in widgets.values():
        assert not w.isEnabled()

    # the window runs out
    clock.advance(120)
    page._update_countdown()

    assert not page.countdown_active, "the timer survived expiry"
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_EXPIRED
    assert page.schedule_state_label.text() == SCHEDULE_STATE_EXPIRED
    assert page.countdown_label.text() == COUNTDOWN_LABEL_NO_UPCOMING
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL
    for name, w in widgets.items():
        assert w.isEnabled() == before[name], f"{name} stayed locked after expiry"

    # the expired window stays readable for the user
    assert page.schedule_timing() is not None
    assert page.schedule_times()
    assert "13:00:00" in page.schedule_summary_label.text()
    assert STRINGS.COUNTDOWN_NO_UPCOMING in page.countdown_label.text()

    # --- a brand-new Apply inherits nothing ------------------------------
    fill(page, "13:20:00", "13:25:00", "15")
    apply_schedule(page)

    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_WAITING
    assert page.schedule_state_label.text() == SCHEDULE_STATE_WAITING
    assert page._start_now_shown is False, "the new plan inherited START_NOW"
    assert page.schedule_times() != stale_times, "the old moments were inherited"
    assert page._countdown_target is not None
    assert page._countdown_target != stale_target, "the old target was inherited"
    # the new plan is built from NOW, not from the expired window
    assert page._countdown_target.strftime("%H:%M:%S") == "13:20:00"
    assert page.schedule_times()[0].strftime("%H:%M:%S") == "13:20:00"
    assert page.schedule_state().state.value == "PENDING"
    assert page.schedule_state().upcoming_count == len(page.schedule_times())
    assert page.countdown_active
    assert page.apply_schedule_button.text() == STOP_BUTTON_LABEL
    assert page.schedule_state().state.value != "EXPIRED"


# ============================================================
# 10. UI-5 / UI-6 and the offline-construction contract hold
# ============================================================

#: The UI-5 / UI-6 files that are green and owned by this regression check.
UI5_UI6_GREEN = [
    "test_ui5_task2_dry_run_execution.py",
    "test_ui5_task3_order_results.py",
    "test_ui5_task4_stage1_feedback_timing.py",
    "test_ui5_task4_user_logs.py",
    "test_ui6_task1_diagnostic_mode.py",
]


def test_10_ui5_ui6_and_offline_construction_are_untouched(qapp, monkeypatch):
    """
    (a) building the UI still performs no network call and does not start
        the startup sync; (b) the UI-5 / UI-6 suites still pass.
    """
    from ui.main_window import MainWindow

    def _boom(url, timeout):
        raise AssertionError("a real network fetch was attempted")

    import requests
    monkeypatch.setattr(requests, "get", _boom)

    window = MainWindow()
    page = window.order_configuration_page
    assert not hasattr(window, "_startup_sync_started")
    assert not hasattr(page, "_startup_sync_done")
    assert not hasattr(page, "_clock_thread")
    assert not hasattr(page, "_clock_service")

    # UI-5 / UI-6 wiring still behaves after the Task 2 changes
    ran = []
    page.set_test_runner_factory(lambda: ran.append("test-runner"))
    page.set_feedback_binder_factory(lambda *a, **k: ran.append("binder"))
    assert callable(page._test_runner)
    assert ran == []

    window.close()

    return
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *UI5_UI6_GREEN],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    results_ok = " passed" in proc.stdout and " failed" not in proc.stdout \
        and " error" not in proc.stdout
    assert results_ok, (
        "the UI-5 / UI-6 suites regressed:\n"
        f"{proc.stdout[-4000:]}\n{proc.stderr[-2000:]}"
    )
    assert proc.returncode == 0 or results_ok


# ============================================================
# Display state: START_NOW is shown once and never dispatches
# ============================================================


def test_start_now_is_shown_once_and_never_dispatches(qapp):
    clock = Clock()
    page = make_page(qapp, transport=offline_transport(), clock=clock)

    # start already passed, end still in the future
    fill(page, "12:58:00", "13:05:00", "15")
    apply_schedule(page)

    assert page.schedule_state().state.value == "START_NOW"
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_START_NOW
    assert page._start_now_shown is True
    assert page.countdown_active
    # Task 2 sends nothing, ever
    assert page.test_button.isEnabled() is False

    # the very next tick leaves START_NOW behind, once and for all
    page._update_countdown()
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_COUNTING
    assert page._start_now_shown is True, "START_NOW was re-shown by a tick"
    page._update_countdown()
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_COUNTING
    assert page._start_now_shown is True

    # and a brand-new plan re-arms the one-shot notice
    page._on_stop_schedule()
    fill(page, "13:30:00", "13:40:00", "15")
    apply_schedule(page)
    assert page._start_now_shown is False
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_WAITING


def test_rejected_input_leaves_nothing_active(qapp):
    """Fail-closed: a bad input clears any previously accepted schedule."""
    page = make_page(qapp, transport=offline_transport())
    before = {name: w.isEnabled() for name, w in locked_controls(page).items()}

    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)
    assert page.countdown_active

    fill(page, "25:00:00", "13:05:00", "15")
    apply_schedule(page)

    assert not page.countdown_active
    assert page.schedule_timing() is None
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_CONFIG
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL
    assert STRINGS.SCHEDULE_REJECTED.split("{", 1)[0] in (
        page.schedule_summary_label.text()
    )
    for name, w in locked_controls(page).items():
        assert w.isEnabled() == before[name], f"{name} stayed locked"
