"""
test_ui7_task1_schedule_clock.py — UI-7 Task 1 schedule on the system clock.

Fully offline. The page reads the Windows system wall clock and injects it
into this test, so nothing here touches the network, a real broker, or the
real system clock. The obsolete TSETMC market-clock path (clock service,
sync/refresh buttons, transport, uncertainty/correction) is intentionally
absent: scheduling uses ONLY the system clock.

Task 1 scope under test
-----------------------
  * Start Time / End Time / Interval inputs + Apply Schedule action
  * validation and moment generation delegated to the EXISTING Block 3
    ``DispatchTiming`` and ``TimedDispatchScheduler`` (no parallel logic)
  * Tehran (``Asia/Tehran``) interpretation of the window
  * the three-line summary: window, real dispatch cadence, planned turns
  * no network access from the schedule path

Explicitly NOT tested here (other UI-7 tasks): the countdown and schedule
lifecycle (Task 2), and connecting due times to the order-send path
(Task 3). No test asserts that anything is dispatched.
"""

import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from ui import strings as STRINGS
from ui.account_store import AccountStore
from ui.order_configuration_page import OrderConfigurationPage
from ui.session_manager import SessionManager

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
UTC = timezone.utc
TEHRAN = timezone(timedelta(hours=3, minutes=30))

# A fixed "now" used everywhere: 2026-10-02 09:29:00Z == 12:59:00 Tehran.
FIXED_NOW = datetime(2026, 10, 2, 9, 29, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _with_valid_destination(page, account_id="ACC-SCHED", broker_name="SIM"):
    """Give the page a VALID destination set: one account + one queued order."""
    from models.order import Order

    try:
        page.store.get(account_id)
    except ValueError:
        page.store.add(account_id, broker_name, account_id)
    try:
        page._session_manager.register(account_id, broker_name)
        page._session_manager.begin_login(account_id)
        page._session_manager.mark_logged_in(account_id, "offline-test-token")
    except Exception:
        pass
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


def make_page(qapp, now=FIXED_NOW):
    """A real page whose system clock is frozen to ``now``."""
    import ui.order_configuration_page as page_module

    tehran_now = now.astimezone(ZoneInfo("Asia/Tehran"))
    page_module.system_wall_now = lambda: tehran_now
    page_module.sample_system_clocks = lambda: (tehran_now, 0.0)
    page_module.system_monotonic = lambda: 0.0
    page = OrderConfigurationPage(AccountStore())
    sessions = SessionManager()
    sessions.register("ACC-SCHED", "SIM")
    sessions.begin_login("ACC-SCHED")
    sessions.mark_logged_in("ACC-SCHED", "offline-test-token")
    page.set_session_manager(sessions)
    page = _with_valid_destination(page)
    page.store.set_active("ACC-SCHED")
    return page


def fill(page, start, end, interval, dispatch_interval_ms="50"):
    page.schedule_start_input.setText(start)
    page.schedule_end_input.setText(end)
    page.schedule_interval_input.setText(interval)
    page.dispatch_interval_input.setText(dispatch_interval_ms)


def apply_schedule(page):
    page._on_apply_schedule()
    _drain_events()


def _drain_events():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for _ in range(50):
        app.processEvents()


# ============================================================
# 1. Incomplete / invalid input is rejected, never repaired
# ============================================================

@pytest.mark.parametrize(
    "start,end,interval",
    [
        ("", "10:00:00", "30"),
        ("09:00:00", "", "30"),
        ("09:00:00", "10:00:00", ""),
        ("   ", "10:00:00", "30"),
        ("25:00:00", "10:00:00", "30"),
        ("9:00", "10:00:00", "30"),
        ("09:60:00", "10:00:00", "30"),
        ("09:00:00", "10:00:00", "0"),
        ("09:00:00", "10:00:00", "-5"),
        ("09:00:00", "10:00:00", "1.5"),
        ("09:00:00", "10:00:00", "30s"),
        ("09:00:00", "10:00:00", "abc"),
        ("10:00:00", "09:00:00", "30"),
        ("2026-10-02 09:00", "10:00:00", "30"),
        ("09:00:00", "24:00:00", "30"),
        ("09:00:00 PM", "10:00:00", "30"),
    ],
)
def test_invalid_inputs_are_rejected(qapp, start, end, interval):
    page = make_page(qapp)
    fill(page, start, end, interval)
    apply_schedule(page)

    summary = page.schedule_summary_label.text()
    assert (
        STRINGS.SCHEDULE_REJECTED.split("{", 1)[0].strip() in summary
    ), summary
    assert page.schedule_timing() is None
    assert page.schedule_state() is None
    assert page.schedule_times() == ()


def test_rejection_does_not_rewrite_the_user_input(qapp):
    """A rejected value is never silently corrected in the field."""
    page = make_page(qapp)
    fill(page, "25:00", "99:99", "0")
    apply_schedule(page)

    assert page.schedule_start_input.text() == "25:00"
    assert page.schedule_end_input.text() == "99:99"
    assert page.schedule_interval_input.text() == "0"


def test_rejection_after_a_valid_apply_does_not_leave_a_stale_schedule(qapp):
    page = make_page(qapp)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)
    assert page.schedule_timing() is not None

    fill(page, "nonsense", "", "")
    apply_schedule(page)
    assert page.schedule_timing() is None
    assert page.schedule_times() == ()
    assert (
        STRINGS.SCHEDULE_REJECTED.split("{", 1)[0].strip()
        in page.schedule_summary_label.text()
    )


# ============================================================
# 2. Valid input is accepted through the EXISTING Block 3 contracts
# ============================================================

def test_valid_input_builds_a_real_dispatch_timing(qapp):
    from core.timing_contracts import DispatchTiming

    page = make_page(qapp)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    timing = page.schedule_timing()
    assert isinstance(timing, DispatchTiming)
    assert timing.interval == timedelta(seconds=15)


def test_run_moments_come_from_the_real_scheduler_not_a_parallel_one(qapp):
    from core.timed_dispatch_scheduler import TimedDispatchScheduler

    page = make_page(qapp)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    timing = page.schedule_timing()
    expected = TimedDispatchScheduler(timing=timing).generate()
    assert list(page.schedule_times()) == list(expected)
    assert len(page.schedule_times()) == 5


def test_summary_has_exactly_the_three_requested_facts(qapp):
    page = make_page(qapp)
    fill(page, "13:00:00", "13:01:00", "15", dispatch_interval_ms="100")
    apply_schedule(page)

    summary = page.schedule_summary_label.text()
    lines = summary.splitlines()
    assert len(lines) == 3, summary
    # 1) window, 2) real dispatch cadence, 3) planned turn count.
    assert STRINGS.SUMMARY_WINDOW.format(
        start="13:00:00", end="13:01:00"
    ) == lines[0]
    assert STRINGS.SUMMARY_DISPATCH_INTERVAL.format(
        interval=STRINGS.format_persian_digits(100)
    ) == lines[1]
    # 60 s at 100 ms inclusive of both ends is 601 turns.
    assert STRINGS.SUMMARY_PLANNED_TURNS.format(
        count=STRINGS.format_persian_digits(601)
    ) == lines[2]

    # No state, clock, countdown, skipped/immediate notice, internal
    # interval or explanatory note is repeated inside the summary.
    for forbidden in (
        STRINGS.LABEL_STATE,
        STRINGS.LABEL_COUNTDOWN,
        STRINGS.SUMMARY_CLOCK.split("{", 1)[0].strip(),
        STRINGS.SUMMARY_SKIPPED.split("{", 1)[0].strip(),
        STRINGS.SUMMARY_IMMEDIATE_START,
        STRINGS.SUMMARY_PER_TURN,
        STRINGS.SUMMARY_PLANNED_TURNS_NOTE,
        STRINGS.SUMMARY_INTERNAL_INTERVAL.split("{", 1)[0].strip(),
        STRINGS.CLOCK_SOURCE_DESCRIPTION,
        "TSETMC",
    ):
        assert forbidden not in summary, summary


def test_window_too_large_is_not_truncated_silently(qapp):
    page = make_page(qapp)
    fill(page, "13:00:00", "14:00:00", "1")
    apply_schedule(page)

    assert page.schedule_timing() is not None
    assert len(page.schedule_times()) == 3601


# ============================================================
# 3. Tehran timezone applied
# ============================================================

def test_window_times_are_tehran_aware(qapp):
    page = make_page(qapp)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    timing = page.schedule_timing()
    assert timing.start_time.utcoffset() == timedelta(hours=3, minutes=30)
    assert timing.start_time.astimezone(TEHRAN).strftime("%H:%M:%S") == "13:00:00"


def test_schedule_is_assessed_against_tehran_now_not_utc_now(qapp):
    """FIXED_NOW is 09:29Z == 12:59 Tehran, so 13:00 is still ahead."""
    page = make_page(qapp)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    state = page.schedule_state()
    assert state.state.value == "PENDING"
    assert state.fire_now is False


# ============================================================
# 4. System clock only — no network, no sync path
# ============================================================

def test_system_clock_tehran_display_and_no_network(qapp, monkeypatch):
    import requests
    import ui.order_configuration_page as page_module

    now = FIXED_NOW.astimezone(ZoneInfo("Asia/Tehran"))
    monkeypatch.setattr(page_module, "system_wall_now", lambda: now)
    calls = []
    monkeypatch.setattr(requests, "get", lambda url, *a, **k: calls.append(url))
    page = OrderConfigurationPage(AccountStore())
    page._refresh_market_clock_row()

    assert page.schedule_timezone_label.text() == "12:59:00"
    assert not hasattr(page, "sync_clock_button")
    assert not hasattr(page, "refresh_clock_button")
    assert not hasattr(page, "clock_status_label")
    assert not hasattr(page, "clock_service")
    assert calls == []


def test_clock_row_advances_from_the_system_clock(qapp, monkeypatch):
    import ui.order_configuration_page as page_module

    wall = [FIXED_NOW.astimezone(ZoneInfo("Asia/Tehran"))]
    monkeypatch.setattr(page_module, "system_wall_now", lambda: wall[0])
    page = OrderConfigurationPage(AccountStore())
    page._refresh_market_clock_row()
    assert page.schedule_timezone_label.text() == "12:59:00"

    wall[0] = wall[0] + timedelta(seconds=3)
    page._refresh_market_clock_row()
    assert page.schedule_timezone_label.text() == "12:59:03"


def test_no_schedule_path_touches_the_real_network(qapp, monkeypatch):
    import requests
    import ui.order_configuration_page as page_module
    from ui.session_manager import SessionManager

    now = FIXED_NOW.astimezone(ZoneInfo("Asia/Tehran"))
    monkeypatch.setattr(page_module, "system_wall_now", lambda: now)
    monkeypatch.setattr(
        page_module,
        "sample_system_clocks",
        lambda: (now, 0.0),
    )
    monkeypatch.setattr(page_module, "system_monotonic", lambda: 0.0)

    def _boom(*_args, **_kwargs):
        raise AssertionError("a real network fetch was attempted")

    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(requests, "post", _boom)

    page = _with_valid_destination(OrderConfigurationPage(AccountStore()))
    sessions = SessionManager()
    sessions.register("ACC-SCHED", "SIM")
    sessions.begin_login("ACC-SCHED")
    sessions.mark_logged_in("ACC-SCHED", "offline-test-token")
    page.set_session_manager(sessions)
    page.store.set_active("ACC-SCHED")
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    assert page.schedule_timing() is not None


def test_start_already_past_begins_once_and_skips_missed_moments(qapp):
    """13:00:40 Tehran, window 13:00:00-13:01:00 at 15s: 3 moments missed."""
    from ui.schedule_settings import ScheduleState

    later = FIXED_NOW + timedelta(seconds=100)
    assert later.astimezone(TEHRAN).strftime("%H:%M:%S") == "13:00:40"

    page = make_page(qapp, now=later)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    state = page.schedule_state()
    assert state.state is ScheduleState.START_NOW
    assert state.fire_now is True
    assert state.missed_count == 3
    assert state.upcoming_count == 2

    now_tehran = later.astimezone(TEHRAN)
    for moment in state.upcoming:
        assert moment.astimezone(TEHRAN) > now_tehran
    # Missed/immediate notices are no longer repeated inside the summary.
    summary = page.schedule_summary_label.text()
    assert len(summary.splitlines()) == 3
    assert STRINGS.SUMMARY_SKIPPED.split("{", 1)[0].strip() not in summary
    assert STRINGS.SUMMARY_IMMEDIATE_START not in summary


def test_expired_window_dispatches_nothing(qapp):
    from ui.schedule_settings import ScheduleState

    page = make_page(qapp)
    fill(page, "09:00:00", "09:01:00", "15")
    apply_schedule(page)

    state = page.schedule_state()
    assert state.state is ScheduleState.EXPIRED
    assert state.fire_now is False
    assert state.upcoming == ()
    assert state.is_expired is True
    assert page.schedule_state_label.text() == STRINGS.STATE_EXPIRED
    assert "09:00:00" in page.schedule_summary_label.text()


def test_missed_moments_are_never_replayed_in_order(qapp):
    later = FIXED_NOW + timedelta(seconds=100)
    page = make_page(qapp, now=later)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    upcoming = list(page.schedule_state().upcoming)
    assert upcoming == sorted(upcoming)
    assert len(set(upcoming)) == len(upcoming)
    assert upcoming[0].astimezone(TEHRAN).strftime("%H:%M:%S") == "13:00:45"


# ============================================================
# 5. No system-clock write
# ============================================================

def test_no_module_writes_the_system_clock():
    """The schedule module may read the clock but must never write it."""
    banned = (
        r"\bsettimeofday\b",
        r"\bclock_settime\b",
        r"\bw32tm\b",
        r"\bSetSystemTime\b",
        r"\bntplib\b",
        r"\bsntp\b",
        r"\bimport\s+ctypes\b",
    )
    for name in ("ui/schedule_settings.py", "ui/order_configuration_page.py"):
        with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as handle:
            body = handle.read()
        for pattern in banned:
            assert re.search(pattern, body) is None, f"{name} contains {pattern}"


# ============================================================
# 6. Offline tests only
# ============================================================

def test_page_module_import_pulls_no_network_or_trading_module():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys;"
            "import ui.order_configuration_page, ui.schedule_settings;"
            "leaked=sorted(m for m in sys.modules "
            "if m.split('.')[0] in ('brokers','market','core','main','requests'));"
            "print(leaked)",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", result.stdout


def test_main_window_construction_stays_offline_with_the_schedule_group():
    code = "\n".join(
        [
            "import sys",
            "import ui.app as ui_app",
            "from ui import strings as STRINGS",
            "from ui.main_window import MainWindow",
            "app = ui_app.create_app([])",
            "window = MainWindow()",
            "page = window.order_configuration_page",
            "banned = ('brokers', 'market', 'core', 'main')",
            "leaked = sorted(m for m in sys.modules if m.split('.')[0] in banned)",
            "assert not leaked, f'UI imported trading modules: {leaked}'",
            "assert page.apply_schedule_button.text() == STRINGS.BUTTON_APPLY_SCHEDULE",
            "assert page.schedule_timing() is None",
            "print('UI7_OFFLINE_OK')",
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
    assert "UI7_OFFLINE_OK" in result.stdout


# ============================================================
# 7. UI-5 and UI-6 behaviour unchanged
# ============================================================

def test_applying_a_schedule_sends_nothing_and_touches_no_order(qapp):
    """Apply starts NO send - and with a real queued order in place."""
    from core.order_queue import OrderQueue

    queue = OrderQueue()
    store = AccountStore()
    store.add("ACC-001", "SIM", "ACC-001")
    store.set_active("ACC-001")

    page = OrderConfigurationPage(store, order_queue=queue)
    sessions = SessionManager()
    sessions.register("ACC-001", "SIM")
    sessions.begin_login("ACC-001")
    sessions.mark_logged_in("ACC-001", "offline-test-token")
    page.set_session_manager(sessions)
    _with_valid_destination(page, account_id="ACC-001", broker_name="SIM")

    queued_before = list(queue.list_pending())
    assert queued_before, "the page needs a real queued order for this test"

    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    assert page.countdown_active, page.schedule_summary_label.text()
    assert page.config.selected_instrument is None
    # The very same entries, untouched - nothing removed or consumed.
    assert queue.list_pending() == queued_before
    assert page.order_log.rows() == []


def test_applying_a_schedule_does_not_run_the_test_pass(qapp):
    calls = []

    class RecordingRunner:
        def run(self, entries, account=None):
            calls.append(entries)
            return None

    page = make_page(qapp)
    page.set_test_runner_factory(RecordingRunner)

    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    assert calls == []
    assert page._last_test_run is None


def test_applying_a_schedule_does_not_change_diagnostic_visibility(qapp):
    from ui.main_window import ApplicationMode

    page = make_page(qapp)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    assert page.is_diagnostic_visible() is False

    page.apply_mode(ApplicationMode.DIAGNOSTIC)
    assert page.is_diagnostic_visible() is True

    page.apply_mode(ApplicationMode.NORMAL)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)
    assert page.is_diagnostic_visible() is False


def test_schedule_widgets_do_not_disturb_order_fields(qapp):
    page = make_page(qapp)
    page.price_input.setText("1000")
    page.quantity_input.setText("5")

    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    assert page.price_input.text() == "1000"
    assert page.quantity_input.text() == "5"
    assert page.symbol_input.currentText() == ""


def test_a_rejected_input_never_touches_the_network(qapp, monkeypatch):
    import requests

    def _boom(*_args, **_kwargs):
        raise AssertionError("a rejected input must not hit the network")

    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(requests, "post", _boom)

    page = make_page(qapp)
    fill(page, "25:00:00", "13:01:00", "15")
    page._on_apply_schedule()
    _drain_events()

    assert (
        STRINGS.SCHEDULE_REJECTED.split("{", 1)[0].strip()
        in page.schedule_summary_label.text()
    )
    assert page.schedule_timing() is None
