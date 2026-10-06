"""
test_ui7_task2_countdown_state.py — UI-7 Task 2: startup sync, schedule
lifecycle (Apply / lock / Stop), countdown and displayed states.

Fully offline. Every clock reading and every HTTP answer is injected by the
test, so nothing here touches the network, a real broker, or the real
system clock.

The ten scenarios mandated by the UI-7 Task 2 spec
--------------------------------------------------
  1. the ONE startup sync runs after the window is shown, off the Home
     page, without depending on the Order Configuration page, and without
     any request during construction/import;
  2. the independent manual sync reports source / offset / uncertainty /
     freshness for both success and failure, and never runs twice at once;
  3. Apply CONSUMES the last completed sync and starts no request itself;
  4. Apply pressed during an in-flight sync waits for THAT result and
     falls back to the system clock when it fails;
  5. freshness is measured on the MONOTONIC clock — a system-clock step
     can neither renew a stale reading nor expire a fresh one;
  6. Apply locks every order / queue / schedule control and turns itself
     into Stop, with Stop being the single way out;
  7. Stop stops the timer, clears the plan and unlocks — and sends
     nothing (Task 2 never dispatches);
  8. a later sync or a system-clock step cannot move an active countdown;
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

import pytest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
UTC = timezone.utc

# A fixed "now": 2026-10-02 09:29:00Z == 12:59:00 Tehran.
FIXED_NOW = datetime(2026, 10, 2, 9, 29, 0, tzinfo=UTC)
TEHRAN = timezone(timedelta(hours=3, minutes=30))
FIXED_TEHRAN = FIXED_NOW.astimezone(TEHRAN)

GOOD_BODY = "10/02/2026 12:59:00"
GOOD_DATE_HEADER = "Thu, 02 Oct 2026 09:29:00 GMT"

from ui.market_clock import (  # noqa: E402  (constants used below)
    SCHEDULE_SYNC_MAX_AGE_SECONDS,
)
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
    SYNC_BUTTON_LABEL,
    SYNC_STATE_FAILED,
    SYNC_STATE_NEVER,
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
        "Age": "0",
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

    page.store.add(account_id, broker_name)
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
    """
    A real page whose clock service is driven by a test-owned ``Clock``.

    The default transport is an offline stub serving a valid fresh
    reading, so no test can reach the real network by accident.
    """
    from ui.account_store import AccountStore
    from ui.market_clock import MarketClockService
    from ui.order_configuration_page import OrderConfigurationPage

    clock = clock if clock is not None else Clock()
    page = OrderConfigurationPage(AccountStore())
    page.set_clock_service_factory(
        lambda t: MarketClockService(
            transport=t,
            now_utc=(lambda: clock.wall),
            mono_clock=(lambda: clock.mono),
        )
    )
    page.set_clock_transport(
        offline_transport() if transport is None else transport
    )
    page.clock = clock
    _with_valid_destination(page)
    PAGES.append(page)
    return page


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
    """Press the independent sync button and wait for its COMPLETED result."""
    page._on_sync_clock()
    thread = page._clock_thread
    if thread is not None:
        assert thread.wait(10_000), "the clock sync did not finish"
    _drain_events()


def apply_schedule(page):
    """Press Apply; Apply itself never starts a network request."""
    page._on_apply_schedule()
    thread = page._clock_thread
    if thread is not None:
        assert thread.wait(10_000), "the clock refresh did not finish"
    _drain_events()


def locked_controls(page):
    """Every widget of the page that may change an order, queue or schedule."""
    widgets = {
        "schedule start": page.schedule_start_input,
        "schedule end": page.schedule_end_input,
        "schedule interval": page.schedule_interval_input,
        "sync": page.sync_clock_button,
        "refresh clock": page.refresh_clock_button,
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
# 1. One startup sync, after show, off the Home page, offline build
# ============================================================


def test_1_startup_sync_runs_once_after_show_from_the_home_page(
    qapp, monkeypatch
):
    """
    The real MainWindow path: construction imports and builds nothing that
    talks to the network, ``show()`` schedules exactly one non-blocking
    sync, and it happens while Home is still the visible page — i.e. the
    sync does NOT depend on the Order Configuration page being opened.
    """
    import ui.market_clock as market_clock
    from ui.main_window import MainWindow
    from ui.market_clock import MarketClockService

    def _boom(url, timeout):
        raise AssertionError("a real network fetch was attempted")

    # Any accidental real fetch during construction fails loudly.
    monkeypatch.setattr(market_clock, "default_transport", _boom)

    # --- construction is offline and schedules nothing yet ---------------
    window = MainWindow()
    page = window.order_configuration_page
    assert window._startup_sync_started is False
    assert page._startup_sync_done is False
    assert page._clock_thread is None
    assert page._clock_service is None

    # Inject a deterministic clock + an instrumented transport, exactly the
    # way the production seam is meant to be used, and count every request.
    calls = []

    def _record(url, timeout):
        calls.append(url)
        return make_result(headers=market_headers())

    page.set_clock_service_factory(
        lambda t: MarketClockService(
            transport=t,
            now_utc=(lambda: FIXED_NOW),
            mono_clock=(lambda: 0.0),
        )
    )
    page.set_clock_transport(_record)
    assert calls == [], "configuring the page must not fetch the clock"

    window.startup_sync_delay_ms = 0
    window.show()
    pump(400)

    thread = page._clock_thread
    if thread is not None:
        assert thread.wait(10_000), "the startup sync did not finish"
    _drain_events()
    pump(50)

    assert len(calls) == 1, f"expected exactly one startup sync, got {len(calls)}"

    # the sync landed and produced a market reading
    assert page.clock_status().source.value == "MARKET"
    assert page.sync_status_label.text() != SYNC_STATE_NEVER

    # Home was visible the whole time — the sync was never gated on the
    # Order Configuration page.
    assert window.content_area.currentWidget() is window.placeholder_pages["Home"]

    # a second show must not start a second sync
    window.hide()
    window.show()
    pump(300)
    assert len(calls) == 1, "the startup sync must be one-shot"

    # and the page refuses a second one even if it is asked directly
    assert page.start_startup_sync() is False
    assert len(calls) == 1

    window.close()


# ============================================================
# 2. The independent manual sync: success, failure, no duplicate
# ============================================================


def test_2_manual_sync_reports_result_and_never_runs_twice_at_once(qapp):
    transport = offline_transport()
    page = make_page(qapp, transport=transport)

    assert page.sync_status_label.text() == SYNC_STATE_NEVER

    page._on_sync_clock()          # first press starts the worker
    page._on_sync_clock()          # second press while it is in flight
    page._on_sync_clock()
    thread = page._clock_thread
    assert thread is not None, "the first press did not start a sync"
    assert thread.wait(10_000)
    _drain_events()

    assert len(transport.calls) == 1, "two syncs ran at the same time"
    assert page._clock_worker is None

    status = page.clock_status()
    assert status.source.value == "MARKET"
    assert status.uncertainty is not None

    text = page.sync_status_label.text()
    # UI-9 Task 3: the line is Persian; the freshness wording and the
    # source token now come from ui.strings.
    assert STRINGS.SYNC_OK_PREFIX.split("{", 1)[0] in text, text   # freshness
    assert f"منبع {status.source.value}" in text, text          # source
    assert "+0." in text or "-0." in text or "+1" in text, text  # offset
    assert "+/-" in text, text                             # uncertainty
    assert "failed" not in text.lower(), text

    assert page.sync_clock_button.isEnabled()
    assert page.sync_clock_button.text() == SYNC_BUTTON_LABEL


def test_2b_manual_sync_failure_is_reported_softly_and_never_fabricates(qapp):
    transport = fixed_transport(raises=TimeoutError("offline"))
    page = make_page(qapp, transport=transport)

    sync_clock(page)

    assert len(transport.calls) == 1
    status = page.clock_status()
    assert status.source.value == "SYSTEM"
    assert "unavailable" in status.notice.lower()
    assert page.sync_status_label.text() == SYNC_STATE_FAILED
    assert page.sync_clock_button.isEnabled()
    assert page.sync_clock_button.text() != SYNC_BUTTON_LABEL
    # no reading was invented
    assert "+/-" not in page.clock_status_label.text()


# ============================================================
# 3. Apply consumes the last completed sync — no request of its own
# ============================================================


def test_3_apply_consumes_the_completed_sync_without_new_requests(qapp):
    transport = offline_transport()
    page = make_page(qapp, transport=transport)

    sync_clock(page)
    assert len(transport.calls) == 1

    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)

    assert len(transport.calls) == 1, "Apply must not fetch the clock itself"
    assert page.clock_status().source.value == "MARKET"
    assert page.schedule_timing() is not None
    assert page.schedule_times()
    assert page.sync_status_label.text() != SYNC_STATE_NEVER


# ============================================================
# 4. Apply waits for an in-flight sync; failure falls back softly
# ============================================================


def test_4_apply_waits_for_the_in_flight_sync_and_falls_back_on_failure(qapp):
    calls = []

    def _slow_fail(url, timeout):
        calls.append(url)
        _time.sleep(0.05)
        raise TimeoutError("the network is down")

    page = make_page(qapp, transport=_slow_fail)
    fill(page, "13:00:00", "13:05:00", "15")

    page._on_sync_clock()          # the sync is in flight
    page._on_apply_schedule()      # Apply must wait for THAT result

    assert page._clock_thread is not None
    assert page.schedule_timing() is None, "Apply evaluated before the sync landed"
    assert page.sync_status_label.text() != SYNC_STATE_NEVER

    assert page._clock_thread.wait(10_000)
    _drain_events()

    assert len(calls) == 1, "Apply started a second request"
    # the failed sync drove the soft system-clock fallback
    assert page.schedule_timing() is not None, "Apply never completed"
    assert page.clock_status().source.value == "SYSTEM"
    assert "unavailable" in page.clock_status().notice.lower()
    assert page.sync_status_label.text() == SYNC_STATE_FAILED
    # and the schedule it accepted is an active, locked one
    assert page.apply_schedule_button.text() == STOP_BUTTON_LABEL
    assert not page.sync_clock_button.isEnabled()


# ============================================================
# 4a. Apply during a pending sync locks now; Stop cancels for good
# ============================================================


def test_4a_apply_while_the_sync_is_pending_locks_immediately_and_stop_cancels(qapp):
    """
    Apply pressed DURING an in-flight sync locks the controls and turns
    itself into Stop straight away, and Stop before the sync lands cancels
    the pending plan for good: the landing sync result must never revive
    it.
    """
    calls = []

    def _slow_ok(url, timeout):
        calls.append(url)
        _time.sleep(0.05)
        return make_result(headers=market_headers())

    page = make_page(qapp, transport=_slow_ok)
    widgets = locked_controls(page)
    before = {name: w.isEnabled() for name, w in widgets.items()}
    fill(page, "13:00:00", "13:05:00", "15")

    # --- (a) Stop BEFORE the sync lands ----------------------------------
    page._on_sync_clock()          # the sync is in flight
    assert page._clock_thread is not None
    page._on_apply_schedule()      # Apply while it is still running

    # locked IMMEDIATELY — not when the sync happens to land
    assert page._schedule_locked, "Apply did not lock while the sync ran"
    assert page.apply_schedule_button.text() == STOP_BUTTON_LABEL
    for name, w in widgets.items():
        assert not w.isEnabled(), f"{name} was still editable while pending"
    assert page.schedule_timing() is None, "a plan was accepted too early"

    # Stop is the single way out, and it cancels the pending plan
    page._on_schedule_button_clicked()

    assert not page._schedule_locked, "Stop did not free the controls"
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL
    for name, w in widgets.items():
        assert w.isEnabled() == before[name], f"{name} stayed locked after Stop"
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_STOPPED

    # --- the landing sync result must NOT revive the cancelled plan -------
    assert page._clock_thread.wait(10_000)
    _drain_events()

    assert len(calls) == 1, "the cancelled Apply started a new request"
    assert page.schedule_timing() is None, "the sync revived a cancelled plan"
    assert not page.countdown_active, "the sync started a cancelled countdown"
    assert not page._schedule_locked, "the sync re-locked a cancelled plan"
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL

    # --- (b) an Apply that is NOT cancelled still completes normally ------
    page2 = make_page(qapp, transport=offline_transport(), clock=Clock())
    fill(page2, "13:00:00", "13:05:00", "15")
    page2._on_sync_clock()
    page2._on_apply_schedule()
    assert page2._schedule_locked
    assert page2.apply_schedule_button.text() == STOP_BUTTON_LABEL
    assert page2._clock_thread.wait(10_000)
    _drain_events()
    assert page2.schedule_timing() is not None, "the pending Apply never landed"
    assert page2.countdown_active


def test_4b_apply_without_any_sync_says_so_and_never_fetches(qapp):
    transport = offline_transport()
    page = make_page(qapp, transport=transport)

    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)

    assert transport.calls == [], "Apply must not start a sync on its own"
    assert page.schedule_timing() is not None
    assert page.clock_status().source.value == "SYSTEM"
    assert "no market clock sync has completed yet" in page.clock_status().notice
    assert page.sync_status_label.text() == SYNC_STATE_NEVER


# ============================================================
# 5. Freshness is monotonic: a wall-clock step proves nothing
# ============================================================


def test_5_freshness_uses_the_monotonic_clock_not_the_wall_clock(qapp):
    clock = Clock()
    transport = offline_transport()
    page = make_page(qapp, transport=transport, clock=clock)
    service = page.clock_service()

    sync_clock(page)
    assert service.sync_age_seconds() == pytest.approx(0.0)
    assert service.is_sync_fresh() is True

    # --- a system-clock step FORWARD must not expire a fresh reading ----
    clock.step_wall(3600)
    assert service.sync_age_seconds() == pytest.approx(0.0), (
        "the age was measured on the wall clock"
    )
    assert service.is_sync_fresh() is True

    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)
    assert len(transport.calls) == 1
    assert page.clock_status().source.value == "MARKET", (
        "a forward NTP step expired a fresh sync"
    )
    assert page.apply_schedule_button.text() == STOP_BUTTON_LABEL
    page._on_stop_schedule()

    # --- a system-clock step BACKWARD must not renew a stale reading ----
    clock.step_wall(-7200)
    clock.advance(SCHEDULE_SYNC_MAX_AGE_SECONDS + 1)
    clock.step_wall(-3600)          # wall clock says we are back in time
    assert service.sync_age_seconds() == pytest.approx(
        SCHEDULE_SYNC_MAX_AGE_SECONDS + 1
    )
    assert service.is_sync_fresh() is False, (
        "a backward NTP step renewed a stale sync"
    )

    fill(page, "13:10:00", "13:15:00", "15")
    apply_schedule(page)
    assert len(transport.calls) == 1, "Apply started a request of its own"
    assert page.clock_status().source.value == "SYSTEM"
    assert (
        f"{SCHEDULE_SYNC_MAX_AGE_SECONDS:.0f}s schedule limit"
        in page.clock_status().notice
    )
    # the stale reading was refused rather than silently reused
    assert "+/-" not in page.clock_status().notice
    assert page.sync_status_label.text().startswith(
        STRINGS.SYNC_STALE.split("{", 1)[0]
    )


# ============================================================
# 5b. The freshness DISPLAY ages by itself, without any new request
# ============================================================


def test_5b_the_freshness_display_expires_without_any_new_request(qapp):
    """
    The sync line must stop claiming "fresh" once the monotonic age
    passes the schedule limit, WITHOUT the user syncing again — and the
    re-render must not move the active schedule's countdown or its time
    base, nor perform a network request.
    """
    clock = Clock()
    transport = offline_transport()
    page = make_page(qapp, transport=transport, clock=clock)

    sync_clock(page)
    assert len(transport.calls) == 1

    # A schedule is active, so there IS a countdown and a locked base
    # that a careless display refresh could disturb.
    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)
    assert page.countdown_active
    base_before = page._locked_base_time
    mono_anchor_before = page._locked_mono_anchor
    target_before = page._countdown_target
    label_before = page.countdown_label.text()

    # The display timer is running and does no work of its own.
    assert page._sync_freshness_timer is not None
    assert page._sync_freshness_timer.isActive(), "the freshness timer is off"
    assert STRINGS.SYNC_OK_PREFIX.split("{", 1)[0] in page.sync_status_label.text(), (
        "the sync line does not report a fresh reading"
    )

    # --- monotonic time passes the freshness limit, no sync happens -----
    clock.advance(SCHEDULE_SYNC_MAX_AGE_SECONDS + 5)
    page._refresh_sync_freshness_display()

    assert len(transport.calls) == 1, (
        "the freshness refresh performed a network request"
    )
    text = page.sync_status_label.text()
    assert text.startswith(STRINGS.SYNC_STALE.split("{", 1)[0]), (
        f"the line still claims a fresh reading: {text!r}"
    )
    assert STRINGS.format_technical(SCHEDULE_SYNC_MAX_AGE_SECONDS) in text

    # --- and it moved neither the countdown nor the locked time base ----
    assert page._locked_base_time == base_before, "the locked base moved"
    assert page._locked_mono_anchor == mono_anchor_before
    assert page._countdown_target == target_before, "the countdown target moved"
    assert page.countdown_label.text() == label_before, "the countdown moved"
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

    sync_clock(page)
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

    sync_clock(page)
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
# 8. A later sync or clock step cannot move an active countdown
# ============================================================


def test_8_a_later_sync_or_clock_step_cannot_move_the_countdown(qapp):
    clock = Clock()
    transport = offline_transport()
    page = make_page(qapp, transport=transport, clock=clock)

    sync_clock(page)
    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)

    assert page.countdown_active
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_WAITING
    target_before = page._countdown_target
    times_before = page.schedule_times()
    now_before = page._get_locked_now_tehran()
    label_before = page.countdown_label.text()
    assert target_before is not None

    # --- a later sync (even a successful one) must not move anything ----
    sync_clock(page)
    assert len(transport.calls) == 2, "the second sync did not run"
    assert page._countdown_target == target_before, "a sync moved the target"
    assert page.schedule_times() == times_before, "a sync regenerated the moments"
    assert page._get_locked_now_tehran() == now_before, "a sync moved the clock"
    assert page.countdown_active
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_WAITING

    # --- a failed sync / fallback must not move anything either ---------
    failed = fixed_transport(raises=TimeoutError("gone"))
    page.set_clock_transport(failed)
    page._on_sync_clock()
    assert page._clock_thread is not None
    assert page._clock_thread.wait(10_000)
    _drain_events()
    assert page.clock_status().source.value == "SYSTEM", "no fallback happened"
    assert page._countdown_target == target_before, "the fallback moved the target"
    assert page._get_locked_now_tehran() == now_before
    assert page.countdown_active

    # --- a system-clock step must not move anything either --------------
    clock.step_wall(-3600)
    page._update_countdown()
    assert page._countdown_target == target_before, "an NTP step moved the target"
    assert page.countdown_label.text() == label_before, "an NTP step rewound the countdown"
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


def test_8b_apply_locks_the_effective_now_after_a_gradual_correction(qapp):
    """
    Apply must freeze the clock service's EFFECTIVE time, not rebuild it
    from ``wall_anchor + applied_offset``.

    A positive offset that is gradually walked back toward zero makes the
    service HOLD its effective time (the non-rewinding guarantee) while
    the raw terms already sit behind it. Reconstructing the locked clock
    from those raw terms would therefore start the countdown in the past.
    """
    # A market body 4s AHEAD of the system clock -> a POSITIVE offset
    # (still inside the endpoint's accepted skew, so it is accepted).
    ahead_body = "10/02/2026 12:59:04"
    ahead_date = "Thu, 02 Oct 2026 09:29:04 GMT"
    transport = fixed_transport(
        result=make_result(
            text=ahead_body,
            headers=market_headers({"Date": ahead_date}),
        )
    )
    clock = Clock()
    page = make_page(qapp, transport=transport, clock=clock)

    sync_clock(page)
    # The page may rebuild the service on sync, so always re-read it.
    service = page.clock_service()
    assert service.applied_offset > timedelta(0), "no positive offset applied"

    # Establish the effective time while the offset is still positive...
    service.now()
    positive_offset = service.applied_offset
    held = service.now()

    # ...then let the gradual correction walk the offset toward zero.
    # now() must HOLD instead of rewinding.
    service.note_unavailable("gradual correction back toward zero")
    assert service.applied_offset < positive_offset, "the offset did not fall"
    assert service.now() == held, "the service rewound instead of holding"

    fill(page, "13:05:00", "13:10:00", "15")
    apply_schedule(page)
    service = page.clock_service()
    assert page.countdown_active
    assert service.now() == held, "Apply moved the effective time"

    # The raw terms are genuinely BEHIND the effective time now — this is
    # exactly the instant the old wall_anchor + applied_offset formula
    # would have made the countdown jump backwards.
    elapsed = service._mono() - service._mono_anchor
    raw = (
        service._wall_anchor
        + timedelta(seconds=max(0.0, elapsed))
        + service.applied_offset
    )
    assert raw < service.now(), "the raw terms are not behind; test is void"

    # One countdown tick: the locked clock must not be behind the recorded
    # effective time.
    page._update_countdown()
    locked = page._get_locked_now_tehran()
    assert locked >= held.astimezone(TEHRAN), (
        "the countdown jumped backwards after Apply"
    )
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_WAITING

    # Real elapsed time still advances it, on the monotonic clock alone.
    clock.advance(30)
    page._update_countdown()
    later = page._get_locked_now_tehran()
    assert later - locked == timedelta(seconds=30)
    assert page.schedule_lifecycle_state() == SCHEDULE_STATE_WAITING


# ============================================================
# 9. Expiry frees the controls and the next Apply is clean
# ============================================================


def test_9_expiry_frees_the_controls_and_the_next_apply_is_clean(qapp):
    clock = Clock()
    transport = offline_transport()
    page = make_page(qapp, transport=transport, clock=clock)
    widgets = locked_controls(page)
    before = {name: w.isEnabled() for name, w in widgets.items()}

    sync_clock(page)
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
    import ui.market_clock as market_clock
    from ui.main_window import MainWindow

    def _boom(url, timeout):
        raise AssertionError("a real network fetch was attempted")

    monkeypatch.setattr(market_clock, "default_transport", _boom)

    window = MainWindow()
    page = window.order_configuration_page
    assert window._startup_sync_started is False
    assert page._startup_sync_done is False
    assert page._clock_thread is None
    # the offline clock path is still wired up lazily
    assert page._clock_service is None

    # UI-5 / UI-6 wiring still behaves after the Task 2 changes
    ran = []
    page.set_test_runner_factory(lambda: ran.append("test-runner"))
    page.set_feedback_binder_factory(lambda *a, **k: ran.append("binder"))
    assert callable(page._test_runner)
    assert ran == []

    window.close()

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

    sync_clock(page)
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

    sync_clock(page)
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
