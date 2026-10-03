"""
test_ui7_task1_schedule_clock.py — UI-7 Task 1 schedule + clock foundation.

Fully offline. Every clock reading and every HTTP answer is injected by the
test, so nothing here touches the network, a real broker, or the real
system clock. The suite is organised by the eight UI-7 Task 1 acceptance
criteria.

Task 1 scope under test
-----------------------
  * Start Time / End Time / Interval inputs + Apply Schedule action
  * validation and moment generation delegated to the EXISTING Block 3
    ``DispatchTiming`` and ``TimedDispatchScheduler`` (no parallel logic)
  * Tehran (``Asia/Tehran``) interpretation of the window
  * the TSETMC market-time endpoint as the preferred clock, with status /
    format / timeout / freshness validation and an honest uncertainty band
  * fallback to the NTP-assumed system clock with a soft notice, and
    recovery back to the market clock
  * a bounded, gradual correction that cannot cause an early, duplicated,
    or catch-up run

Explicitly NOT tested here (other UI-7 tasks): the countdown and schedule
lifecycle (Task 2), and connecting due times to the order-send path
(Task 3). No test asserts that anything is dispatched.
"""

import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from ui.market_clock import (
    MarketClockInvalidResponse,
    MarketClockStale,
    build_sample,
)

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
UTC = timezone.utc

# A fixed "now" used everywhere: 2026-10-02 09:29:00Z == 12:59:00 Tehran.
FIXED_NOW = datetime(2026, 10, 2, 9, 29, 0, tzinfo=UTC)
TEHRAN = timezone(timedelta(hours=3, minutes=30))
FIXED_TEHRAN = FIXED_NOW.astimezone(TEHRAN)

# The documented market body, same instant as FIXED_NOW, as Tehran text.
GOOD_BODY = "10/02/2026 12:59:00"
GOOD_DATE_HEADER = "Thu, 02 Oct 2026 09:29:00 GMT"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def make_page(qapp, now=FIXED_NOW, transport=None):
    """
    A real page whose clock service uses a controlled clock and transport.

    The factory honours the transport it is handed. The default is an
    offline stub serving a valid fresh reading, so no test can reach the
    real network by accident; the system and monotonic clocks are frozen
    so that "no test time elapsed" comparisons are exact.
    """
    from ui.account_store import AccountStore
    from ui.market_clock import MarketClockService
    from ui.order_configuration_page import OrderConfigurationPage

    page = OrderConfigurationPage(AccountStore())
    page.set_clock_service_factory(
        lambda t: MarketClockService(
            transport=t,
            now_utc=(lambda: now),
            mono_clock=(lambda: 0.0),
        )
    )
    page.set_clock_transport(
        offline_transport() if transport is None else transport
    )
    return page


def stepped_service(wall, mono):
    """
    A service whose system and monotonic clocks the test drives directly.

    ``wall[0]`` is the system clock reading, ``mono[0]`` the monotonic
    one. This is what makes an NTP step reproducible: the wall clock can
    jump while the monotonic clock shows that no real time has passed.
    """
    from ui.market_clock import MarketClockService

    return MarketClockService(
        transport=forbidden_transport,
        now_utc=(lambda: wall[0]),
        mono_clock=(lambda: mono[0]),
    )


def sample_at(offset_seconds, market_hour=12, market_minute=59, market_second=0):
    """A hand-built ``MarketClockSample`` with a chosen offset."""
    from ui.market_clock import MarketClockSample

    return MarketClockSample(
        market_time=datetime(
            2026, 10, 2, market_hour, market_minute, market_second, tzinfo=TEHRAN
        ),
        offset=timedelta(seconds=offset_seconds),
        uncertainty=timedelta(seconds=0.75),
        round_trip=timedelta(seconds=0.0),
        body_age=timedelta(seconds=0),
        cdn_age=0,
        fetched_at_utc=FIXED_NOW,
    )


def fill(page, start, end, interval):
    page.schedule_start_input.setText(start)
    page.schedule_end_input.setText(end)
    page.schedule_interval_input.setText(interval)


def apply_schedule(page):
    """
    Press Apply and let any pending clock work settle.

    UI-7 Task 2: Apply does NOT fetch the clock itself — it consumes the
    last completed sync (or waits for one already in flight). This helper
    therefore only presses Apply, waits if a worker happens to be running,
    and drains the event loop.
    """
    page._on_apply_schedule()
    thread = page._clock_thread
    if thread is not None:
        assert thread.wait(10_000), "the clock refresh did not finish"
    _drain_events()


def sync_clock(page):
    """
    Press the independent sync button and wait for its COMPLETED result.

    This is the action that produces the reading Apply later consumes.
    """
    page._on_sync_clock()
    thread = page._clock_thread
    if thread is not None:
        assert thread.wait(10_000), "the clock sync did not finish"
    _drain_events()


def make_result(status=200, text=GOOD_BODY, headers=None):
    from ui.market_clock import TransportResult

    return TransportResult(
        status_code=status,
        text=text,
        headers=headers if headers is not None else {},
    )


def fixed_transport(result=None, raises=None):
    """A transport stub that never touches the network."""
    calls = []

    def _transport(url, timeout):
        calls.append((url, timeout))
        if raises is not None:
            raise raises
        return result if result is not None else make_result()

    _transport.calls = calls
    return _transport


def market_headers(extra=None):
    """A response that satisfies the full fail-closed freshness contract."""
    headers = {
        "Content-Type": "text/plain",
        "Date": GOOD_DATE_HEADER,
        "Age": "0",
    }
    if extra:
        headers.update(extra)
    return headers


def offline_transport(result=None):
    """Default stub: a valid, fresh market answer, served locally."""
    return fixed_transport(
        result=result if result is not None else make_result(headers=market_headers())
    )


def forbidden_transport(url, timeout):
    raise AssertionError(
        "a real network fetch was attempted; tests must stay offline"
    )


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
    assert "rejected" in summary.lower(), summary
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
    assert "rejected" in page.schedule_summary_label.text().lower()


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


def test_run_moment_come_from_the_real_scheduler_not_a_parallel_one(qapp):
    from core.timed_dispatch_scheduler import TimedDispatchScheduler

    page = make_page(qapp)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    timing = page.schedule_timing()
    expected = TimedDispatchScheduler(timing=timing).generate()
    assert list(page.schedule_times()) == list(expected)
    assert len(page.schedule_times()) == 5


def test_summary_is_clear_and_shows_window_interval_and_clock(qapp):
    page = make_page(qapp)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    summary = page.schedule_summary_label.text()
    assert "13:00:00" in summary
    assert "13:01:00" in summary
    assert "15" in summary
    assert "Asia/Tehran" in summary
    assert "Run moments in window: 5" in summary
    assert "Clock:" in summary


def test_window_too_large_is_not_truncated_silently(qapp):
    page = make_page(qapp)
    fill(page, "13:00:00", "14:00:00", "1")
    apply_schedule(page)

    assert page.schedule_timing() is not None
    assert len(page.schedule_times()) == 3601


# ============================================================
# 3. Tehran timezone applied; HTTP Date (UTC) is not the market time
# ============================================================

def test_window_times_are_tehran_aware(qapp):
    page = make_page(qapp)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    timing = page.schedule_timing()
    assert timing.start_time.utcoffset() == timedelta(hours=3, minutes=30)
    assert timing.start_time.astimezone(TEHRAN).strftime("%H:%M:%S") == "13:00:00"


def test_market_body_is_parsed_as_tehran_not_utc():
    from ui.market_clock import parse_market_time

    parsed = parse_market_time(GOOD_BODY)
    assert parsed.utcoffset() == timedelta(hours=3, minutes=30)
    assert parsed.hour == 12
    assert parsed.minute == 59
    # Same instant as the UTC Date header of the same response.
    assert parsed.astimezone(UTC) == FIXED_NOW


def test_http_date_header_is_never_returned_as_the_market_time():
    from ui.market_clock import build_sample

    result = make_result(
        text=GOOD_BODY,
        headers=market_headers(),
    )
    sample = build_sample(result, FIXED_NOW, FIXED_NOW)

    assert sample.market_time.hour == 12, "body time must win, not the Date header"
    assert sample.market_time.tzinfo is not None
    assert sample.market_time.utcoffset() == timedelta(hours=3, minutes=30)


def test_wrong_utc_interpretation_would_be_detected():
    """Reading the body as UTC instead of Tehran is a 3.5h error."""
    body = GOOD_BODY
    as_tehran = datetime.strptime(body, "%m/%d/%Y %H:%M:%S").replace(tzinfo=TEHRAN)
    as_utc = datetime.strptime(body, "%m/%d/%Y %H:%M:%S").replace(tzinfo=UTC)

    assert as_tehran.astimezone(UTC) == FIXED_NOW
    error = abs(as_utc.astimezone(UTC) - FIXED_NOW)
    assert error == timedelta(hours=3, minutes=30)


def test_schedule_is_assessed_against_tehran_now_not_utc_now(qapp):
    """FIXED_NOW is 09:29Z == 12:59 Tehran, so 13:00 is still ahead."""
    page = make_page(qapp)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    state = page.schedule_state()
    assert state.state.value == "PENDING"
    assert state.fire_now is False


# ============================================================
# 4. Timeout / invalid / stale -> system fallback + notice; recovery
# ============================================================

@pytest.mark.parametrize(
    "label,result,raises",
    [
        ("timeout", None, TimeoutError("timed out")),
        ("connection error", None, OSError("network unreachable")),
        ("bad status", make_result(status=503, text=GOOD_BODY), None),
        ("not found", make_result(status=404, text=""), None),
        ("json content type",
         make_result(text="{}", headers={"Content-Type": "application/json"}),
         None),
        ("iso body", make_result(text="2026-10-02T12:59:00Z"), None),
        ("empty body", make_result(text="   "), None),
        ("garbage body", make_result(text="hello"), None),
        ("wrong date part", make_result(text="13/45/2026 12:59:00"), None),
        ("cdn age header",
         make_result(text=GOOD_BODY, headers=market_headers({"Age": "600"})),
         None),
        ("cdn age non numeric",
         make_result(text=GOOD_BODY, headers=market_headers({"Age": "soon"})),
         None),
        ("stale body",
         make_result(text="10/02/2026 11:00:00", headers=market_headers()),
         None),
        ("far future body",
         make_result(text="10/02/2026 15:00:00", headers=market_headers()),
         None),
    ],
)
def test_every_refusal_falls_back_to_system_with_a_notice(label, result, raises):
    from ui.market_clock import MarketClockService

    service = MarketClockService(
        transport=fixed_transport(result=result, raises=raises),
        now_utc=(lambda: FIXED_NOW),
    )
    status = service.refresh()

    assert status.source.value == "SYSTEM", label
    assert status.uncertainty is None, label
    assert "unavailable" in status.notice, label
    assert service.last_error, label


def test_fallback_notice_names_the_reason():
    from ui.market_clock import MarketClockService

    service = MarketClockService(
        transport=fixed_transport(result=make_result(status=503, text="")),
        now_utc=(lambda: FIXED_NOW),
    )
    status = service.refresh()
    assert "503" in status.notice


def test_valid_fresh_response_switches_to_market_clock():
    from ui.market_clock import ClockSource, MarketClockService

    service = MarketClockService(
        transport=fixed_transport(
            result=make_result(headers=market_headers())
        ),
        now_utc=(lambda: FIXED_NOW),
    )
    status = service.refresh()

    assert status.source is ClockSource.MARKET
    assert status.market_time.hour == 12
    assert "TSETMC" in status.notice


def test_clock_recovers_to_market_then_falls_back_again(qapp):
    page = make_page(qapp, transport=None)

    good = fixed_transport(result=make_result(headers=market_headers()))
    bad = fixed_transport(result=make_result(status=503, text=""))

    page.set_clock_transport(bad)
    page.clock_service().refresh()
    assert page.clock_status().source.value == "SYSTEM"

    page.set_clock_transport(good)
    page.clock_service().refresh()
    assert page.clock_status().source.value == "MARKET"

    page.set_clock_transport(bad)
    page.clock_service().refresh()
    assert page.clock_status().source.value == "SYSTEM"
    assert "unavailable" in page.clock_status().notice


def test_unknown_cache_control_is_not_treated_as_freshness_evidence():
    """A cache directive alone never proves freshness; the body age decides."""
    from ui.market_clock import MarketClockService

    service = MarketClockService(
        transport=fixed_transport(
            result=make_result(
                text="10/02/2026 11:00:00",
                headers=market_headers({"Cache-Control": "public, max-age=600"}),
            )
        ),
        now_utc=(lambda: FIXED_NOW),
    )
    status = service.refresh()
    assert status.source.value == "SYSTEM"


# ============================================================
# 5. Clock-source change cannot duplicate or burst the schedule
# ============================================================

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
    assert "not replayed" in page.schedule_summary_label.text()
    assert "Immediate start: once, now" in page.schedule_summary_label.text()


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
    assert "expired" in page.schedule_summary_label.text().lower()


def test_missed_moments_are_never_replayed_in_order(qapp):
    later = FIXED_NOW + timedelta(seconds=100)
    page = make_page(qapp, now=later)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    upcoming = list(page.schedule_state().upcoming)
    assert upcoming == sorted(upcoming)
    assert len(set(upcoming)) == len(upcoming)
    assert upcoming[0].astimezone(TEHRAN).strftime("%H:%M:%S") == "13:00:45"


def test_switching_clock_source_does_not_change_the_moment_list(qapp):
    good = fixed_transport(result=make_result(headers=market_headers()))
    page = make_page(qapp, transport=good)

    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)
    before_times = list(page.schedule_times())
    before_fire = page.schedule_state().fire_now

    page.clock_service().refresh()
    apply_schedule(page)

    assert list(page.schedule_times()) == before_times
    assert page.schedule_state().fire_now == before_fire


def test_correction_is_bounded_and_gradual_never_a_jump():
    from ui.market_clock import MAX_CORRECTION_STEP_SECONDS, MarketClockService
    from ui.market_clock import MarketClockSample

    sample = MarketClockSample(
        market_time=datetime(2026, 10, 2, 12, 59, 4, tzinfo=TEHRAN),
        offset=timedelta(seconds=4.0),
        uncertainty=timedelta(seconds=0.7),
        round_trip=timedelta(seconds=0.1),
        body_age=timedelta(seconds=0),
        cdn_age=None,
        fetched_at_utc=FIXED_NOW,
    )
    service = MarketClockService(now_utc=(lambda: FIXED_NOW))

    step = MAX_CORRECTION_STEP_SECONDS
    previous = 0.0
    for index in range(1, 40):
        status = service.observe(sample)
        current = status.offset_seconds
        assert abs(current - previous) <= step + 1e-9, (
            f"step {index} moved {current - previous}s, limit {step}s"
        )
        assert current <= 4.0 + 1e-9, "applied offset overshot the target"
        previous = current

    assert previous == pytest.approx(4.0, abs=1e-6)


def test_fallback_walks_the_offset_back_gradually_not_by_a_jump():
    from ui.market_clock import MAX_CORRECTION_STEP_SECONDS, MarketClockService
    from ui.market_clock import MarketClockSample

    sample = MarketClockSample(
        market_time=datetime(2026, 10, 2, 12, 59, 2, tzinfo=TEHRAN),
        offset=timedelta(seconds=2.0),
        uncertainty=timedelta(seconds=0.6),
        round_trip=timedelta(seconds=0.1),
        body_age=timedelta(seconds=0),
        cdn_age=None,
        fetched_at_utc=FIXED_NOW,
    )
    service = MarketClockService(now_utc=(lambda: FIXED_NOW))
    for _ in range(20):
        service.observe(sample)
    assert service.applied_offset.total_seconds() == pytest.approx(2.0, abs=1e-6)

    step = MAX_CORRECTION_STEP_SECONDS
    previous = service.applied_offset.total_seconds()
    for index in range(1, 20):
        status = service.mark_market_unavailable("simulated outage")
        current = status.offset_seconds
        assert abs(current - previous) <= step + 1e-9, f"step {index}"
        assert current >= -1e-9, "offset must never overshoot past zero"
        previous = current

    assert service.applied_offset.total_seconds() == pytest.approx(0.0, abs=1e-9)


def test_applied_offset_never_rewinds_now():
    from ui.market_clock import (
        MAX_CORRECTION_STEP_SECONDS,
        MarketClockSample,
        MarketClockService,
    )

    ticks = [0.0]
    base = FIXED_NOW

    def _now():
        return base + timedelta(seconds=ticks[0])

    sample = MarketClockSample(
        market_time=datetime(2026, 10, 2, 13, 0, 1, tzinfo=TEHRAN),
        offset=timedelta(seconds=1.0),
        uncertainty=timedelta(seconds=0.6),
        round_trip=timedelta(seconds=0.1),
        body_age=timedelta(seconds=0),
        cdn_age=None,
        fetched_at_utc=FIXED_NOW,
    )

    service = MarketClockService(now_utc=_now)
    service.observe(sample)
    service.mark_market_unavailable("outage")

    step = MAX_CORRECTION_STEP_SECONDS
    previous = service.now()
    for index in range(20):
        ticks[0] = index * 0.5
        current = service.now()
        delta = (current - previous).total_seconds()
        assert delta >= 0, f"clock rewound by {-delta}s at step {index}"
        assert delta <= 0.5 + step + 1e-9, f"clock jumped {delta}s at step {index}"
        previous = current


# ============================================================
# 6. No system-clock write; no millisecond claim
# ============================================================

def test_no_module_writes_the_system_clock():
    """Neither new module may touch the OS clock or speak NTP."""
    banned = (
        r"\bsettimeofday\b",
        r"\bclock_settime\b",
        r"\bw32tm\b",
        r"\bSetSystemTime\b",
        r"\bntplib\b",
        r"\bsntp\b",
        r"\bimport\s+ctypes\b",
    )
    for name in ("ui/market_clock.py", "ui/schedule_settings.py"):
        with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as handle:
            body = handle.read()
        for pattern in banned:
            assert re.search(pattern, body) is None, f"{name} contains {pattern}"


def test_uncertainty_is_never_zero_and_never_sub_second():
    from ui.market_clock import fetch_market_clock

    sample = fetch_market_clock(
        transport=fixed_transport(result=make_result(headers=market_headers())),
        now_utc=(lambda: FIXED_NOW),
    )
    assert sample.uncertainty_seconds > 0
    assert sample.uncertainty_seconds >= 0.5
    assert sample.is_sub_second_claim is False


def test_uncertainty_grows_with_round_trip_time():
    from ui.market_clock import fetch_market_clock

    fast = fetch_market_clock(
        transport=fixed_transport(result=make_result(headers=market_headers())),
        now_utc=(lambda: FIXED_NOW),
    )
    assert fast.round_trip == timedelta(0)

    ticks = iter(
        [
            FIXED_NOW,
            FIXED_NOW + timedelta(seconds=2),
            FIXED_NOW + timedelta(seconds=2),
        ]
    )

    def _clock():
        return next(ticks)

    slow = fetch_market_clock(
        transport=fixed_transport(result=make_result(headers=market_headers())),
        now_utc=_clock,
    )

    assert slow.round_trip == timedelta(seconds=2)
    assert slow.uncertainty_seconds > fast.uncertainty_seconds


def test_precision_note_disclaims_milliseconds():
    from ui.market_clock import (
        MARKET_PRECISION_NOTE,
        MarketClockService,
        describe_clock,
    )

    assert "second" in MARKET_PRECISION_NOTE
    assert "millisecond" not in MARKET_PRECISION_NOTE

    service = MarketClockService(
        transport=fixed_transport(result=make_result(headers=market_headers())),
        now_utc=(lambda: FIXED_NOW),
    )
    text = describe_clock(service.refresh())
    assert MARKET_PRECISION_NOTE in text
    assert "+/-" in text


def test_system_clock_status_states_unknown_uncertainty():
    from ui.market_clock import MarketClockService, describe_clock

    service = MarketClockService(now_utc=(lambda: FIXED_NOW))
    status = service.status()

    assert status.source.value == "SYSTEM"
    assert status.uncertainty is None
    text = describe_clock(status)
    assert "unknown (system clock only)" in text
    assert "NTP" in text
    assert "zero" not in text.lower()


# ============================================================
# 7. Offline tests only
# ============================================================

def test_refresh_clock_uses_the_injected_transport(qapp):
    transport = fixed_transport(result=make_result(headers=market_headers()))
    page = make_page(qapp, transport=transport)
    page._on_refresh_clock()

    thread = page._clock_thread
    assert thread is not None
    assert thread.wait(10_000), "the clock worker did not finish"
    _drain_events()

    assert transport.calls, "the injected transport was never called"
    url, timeout = transport.calls[0]
    assert url == "https://cdn.tsetmc.com/api/StaticData/GetTime"
    assert timeout == 5.0
    assert page.clock_status().source.value == "MARKET"
    assert "TSETMC" in page.clock_status_label.text()


def _drain_events():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for _ in range(50):
        app.processEvents()


def test_refresh_clock_failure_is_reported_without_raising(qapp):
    transport = fixed_transport(raises=TimeoutError("timed out"))
    page = make_page(qapp, transport=transport)
    apply_schedule(page)
    page._on_refresh_clock()

    thread = page._clock_thread
    assert thread is not None
    assert thread.wait(10_000), "the clock worker did not finish"
    _drain_events()

    assert page.clock_status().source.value == "SYSTEM"
    assert "unavailable" in page.clock_status_label.text()


def test_no_schedule_or_clock_path_touches_the_real_network(qapp, monkeypatch):
    """Any accidental real fetch fails loudly instead of hitting the wire."""
    import ui.market_clock as market_clock

    def _boom(*_args, **_kwargs):
        raise AssertionError("a real network fetch was attempted")

    monkeypatch.setattr(market_clock, "default_transport", _boom)

    good = fixed_transport(result=make_result(headers=market_headers()))
    page = make_page(qapp, transport=good)

    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)
    assert page.schedule_timing() is not None

    page._on_refresh_clock()
    thread = page._clock_thread
    assert thread is not None
    assert thread.wait(10_000)
    _drain_events()
    assert page.clock_status().source.value == "MARKET"


def test_page_module_import_pulls_no_network_or_trading_module():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys;"
            "import ui.order_configuration_page, ui.schedule_settings, ui.market_clock;"
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
            "from ui.main_window import MainWindow",
            "app = ui_app.create_app([])",
            "window = MainWindow()",
            "page = window.order_configuration_page",
            "banned = ('brokers', 'market', 'core', 'main')",
            "leaked = sorted(m for m in sys.modules if m.split('.')[0] in banned)",
            "assert not leaked, f'UI imported trading modules: {leaked}'",
            "assert page.apply_schedule_button.text() == 'Apply Schedule'",
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
# 8. UI-5 and UI-6 behaviour unchanged
# ============================================================

def test_applying_a_schedule_sends_nothing_and_touches_no_order(qapp):
    from core.order_queue import OrderQueue

    from ui.account_store import AccountStore
    from ui.market_clock import MarketClockService
    from ui.order_configuration_page import OrderConfigurationPage

    queue = OrderQueue()
    store = AccountStore()
    store.add("ACC-001", "SIM")
    store.set_active("ACC-001")

    service = MarketClockService(now_utc=(lambda: FIXED_NOW))
    page = OrderConfigurationPage(store, order_queue=queue)
    page.set_clock_service_factory(lambda _t: service)

    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    assert page.config.selected_instrument is None
    assert queue.list_pending() == []
    assert page.queue_list.count() == 0
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


def test_clock_status_is_outside_the_diagnostic_section(qapp):
    """UI-6 keeps diagnostics mode-gated; the clock line is not one."""
    page = make_page(qapp)
    page.clock_service().refresh()
    page._refresh_clock_display()

    assert page.is_diagnostic_visible() is False
    assert "Source:" in page.clock_status_label.text()


def test_schedule_widgets_do_not_disturb_order_fields(qapp):
    page = make_page(qapp)
    page.price_input.setText("1000")
    page.quantity_input.setText("5")

    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    assert page.price_input.text() == "1000"
    assert page.quantity_input.text() == "5"
    assert page.symbol_input.currentText() == ""

# ============================================================
# 9. FIX 1 — a system-clock step must never rewind market time
# ============================================================

def test_positive_offset_survives_a_backward_system_clock_step(qapp):
    """
    Before the fix, now() = system + offset, so a 5s backward NTP step
    dragged market time 5s backwards with it.
    """
    wall = [FIXED_NOW]
    mono = [1000.0]
    service = stepped_service(wall, mono)
    service.observe(sample_at(+100))

    before = service.now_tehran()
    wall[0] = FIXED_NOW - timedelta(seconds=5)   # NTP steps time backwards
    mono[0] = 1000.0                            # ...but no real time passed

    assert service.now_tehran() == before


def test_negative_offset_survives_a_forward_system_clock_step(qapp):
    wall = [FIXED_NOW]
    mono = [1000.0]
    service = stepped_service(wall, mono)
    service.observe(sample_at(-100))

    before = service.now_tehran()
    wall[0] = FIXED_NOW + timedelta(seconds=5)   # NTP jumps time forwards
    mono[0] = 1000.0

    assert service.now_tehran() == before


def test_market_time_still_advances_with_the_monotonic_clock(qapp):
    """Freezing the rewinding bug must not freeze the clock entirely."""
    mono = [1000.0]
    service = stepped_service([FIXED_NOW], mono)

    before = service.now_tehran()
    mono[0] = 1030.0                            # 30 real seconds passed

    assert (service.now_tehran() - before) == timedelta(seconds=30)


def test_market_time_never_rewinds_across_a_noisy_system_clock(qapp):
    """A wildly jittering system clock must still never rewind the app."""
    wall = [FIXED_NOW]
    mono = [0.0]
    service = stepped_service(wall, mono)
    service.observe(sample_at(+250))

    noise = [-3600, 3600, 0, -12, 45, -3, 900, -900, 0, 5]
    previous = service.now_tehran()
    for index, jitter in enumerate(noise):
        mono[0] = float(index)              # real time creeps forward
        wall[0] = FIXED_NOW + timedelta(seconds=jitter)
        current = service.now_tehran()
        assert current >= previous, f"rewound at jitter {jitter}s"
        previous = current


def test_a_failed_refresh_does_not_move_market_time_backwards(qapp):
    mono = [0.0]
    service = stepped_service([FIXED_NOW], mono)
    service.observe(sample_at(+250))
    before = service.now_tehran()

    service.mark_market_unavailable("network is down")
    mono[0] = 10.0

    assert service.now_tehran() >= before
    assert service.status().source.value == "SYSTEM"


def test_fallback_to_system_clock_does_not_rewind_immediately(qapp):
    """
    Switching from MARKET to SYSTEM must not move time backwards, even
    with no clock advancement between the two observations.
    """
    mono = [0.0]
    service = stepped_service([FIXED_NOW], mono)

    # Establish market time with a positive offset
    service.observe(sample_at(+150))
    market_now = service.now_tehran()

    # Immediately fall back to system clock - no time passes
    service.mark_market_unavailable("network down")
    system_now = service.now_tehran()

    assert system_now >= market_now, "fallback must not rewind time"
    assert service.status().source.value == "SYSTEM"


def test_fallback_from_negative_offset_does_not_rewind(qapp):
    """
    Same test with a negative market offset (market behind system).
    """
    mono = [0.0]
    service = stepped_service([FIXED_NOW], mono)

    service.observe(sample_at(-80))
    market_now = service.now_tehran()

    service.mark_market_unavailable("network down")
    system_now = service.now_tehran()

    assert system_now >= market_now, "fallback must not rewind time"
    assert service.status().source.value == "SYSTEM"


def test_recovery_to_market_does_not_rewind(qapp):
    """
    Recovering from SYSTEM back to MARKET must not rewind either.

    The applied offset walks back toward the new sample gradually, so
    the clock should hold or advance, never jump backwards.
    """
    mono = [0.0]
    service = stepped_service([FIXED_NOW], mono)

    # Start with market
    service.observe(sample_at(+200))
    market1 = service.now_tehran()

    # Fall back to system
    service.mark_market_unavailable("temp outage")
    system_now = service.now_tehran()

    # Recover with a fresh market reading (smaller offset)
    service.observe(sample_at(+50))
    market2 = service.now_tehran()

    assert system_now >= market1
    assert market2 >= system_now, "recovery must not rewind"
    assert service.status().source.value == "MARKET"


# ============================================================
# 10. Apply consumes the last completed sync — it never fetches
# ============================================================

def test_apply_without_a_prior_sync_starts_no_request(qapp):
    """
    UI-7 Task 2: Apply itself never opens a network connection.

    It consumes whatever the last completed sync produced. With no sync
    at all the page falls back to the system clock and SAYS so.
    """
    transport = offline_transport()
    page = make_page(qapp, transport=transport)

    assert transport.calls == []
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    assert transport.calls == [], "Apply must not fetch the clock itself"
    assert page.schedule_timing() is not None

    status = page.clock_status()
    assert status.source.value == "SYSTEM"
    assert "no market clock sync has completed yet" in status.notice
    assert "unavailable" in status.notice.lower()


def test_apply_consumes_the_completed_sync_and_adds_no_request(qapp):
    """
    After a successful manual sync, Apply uses that very result and the
    request count does not grow.
    """
    transport = offline_transport()
    page = make_page(qapp, transport=transport)

    sync_clock(page)
    assert len(transport.calls) == 1
    assert page.clock_status().source.value == "MARKET"

    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    assert len(transport.calls) == 1, "Apply added a second request"
    status = page.clock_status()
    assert status.source.value == "MARKET"
    assert status.market_time is not None
    assert status.uncertainty is not None
    assert page.schedule_timing() is not None


def test_the_summary_states_the_uncertainty_for_a_market_clock(qapp):
    transport = offline_transport()
    page = make_page(qapp, transport=transport)

    sync_clock(page)
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    summary = page.schedule_summary_label.text()
    assert "+/-" in summary, f"summary hides the band: {summary!r}"
    assert len(transport.calls) == 1


def test_apply_refuses_a_response_that_is_too_old_to_trust(qapp):
    """
    A body an hour older than the moment we received it is refused by the
    sync itself, so Apply never gets to schedule against it.
    """
    transport = offline_transport(
        make_result(headers=market_headers(), text="10/02/2026 11:59:00")
    )
    page = make_page(qapp, transport=transport)
    sync_clock(page)
    assert page.clock_status().source.value == "SYSTEM"

    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    status = page.clock_status()
    assert status.source.value == "SYSTEM"
    assert page.schedule_timing() is not None
    assert "unavailable" in status.notice.lower()
    assert len(transport.calls) == 1, "Apply must not ask again"


def test_apply_waits_for_a_sync_that_is_already_in_flight(qapp):
    """
    Apply pressed while a sync runs waits for THAT result instead of
    starting a second request, and never evaluates early.
    """
    seen = []

    def _slow(url, timeout):
        seen.append(page.schedule_timing())
        import time as _time

        _time.sleep(0.05)
        return make_result(headers=market_headers())

    page = make_page(qapp, transport=_slow)
    fill(page, "13:00:00", "13:01:00", "15")

    page._on_sync_clock()          # the sync is now in flight
    page._on_apply_schedule()      # Apply must wait for its result

    assert page._clock_thread is not None
    assert page.schedule_timing() is None, "Apply evaluated too early"

    assert page._clock_thread.wait(10_000)
    _drain_events()

    assert seen, "the transport was never used"
    assert all(value is None for value in seen), (
        "the schedule was assessed before the clock response arrived"
    )
    assert page.schedule_timing() is not None
    assert page.clock_status().source.value == "MARKET"


def test_apply_does_not_block_the_gui_thread(qapp):
    import time as _time

    def _slow(url, timeout):
        _time.sleep(1.0)
        return make_result(headers=market_headers())

    page = make_page(qapp, transport=_slow)
    fill(page, "13:00:00", "13:01:00", "15")

    page._on_sync_clock()

    started = _time.monotonic()
    page._on_apply_schedule()
    elapsed = _time.monotonic() - started

    assert elapsed < 0.5, f"Apply blocked the GUI thread for {elapsed:.2f}s"
    thread = page._clock_thread
    assert thread is not None
    assert thread.wait(10_000)
    _drain_events()
    assert page.schedule_timing() is not None


def test_apply_falls_back_to_the_system_clock_when_the_sync_fails(qapp):
    page = make_page(
        qapp,
        transport=fixed_transport(raises=TimeoutError("no route to host")),
    )
    sync_clock(page)
    assert page.clock_status().source.value == "SYSTEM"

    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    status = page.clock_status()
    assert status.source.value == "SYSTEM"
    assert page.schedule_timing() is not None
    summary = page.schedule_summary_label.text()
    assert summary
    assert "system clock" in summary.lower()
    assert "unavailable" in status.notice.lower()


def test_a_rejected_input_never_starts_a_clock_refresh(qapp):
    transport = offline_transport()
    page = make_page(qapp, transport=transport)

    fill(page, "25:00:00", "13:01:00", "15")
    page._on_apply_schedule()
    _drain_events()

    assert transport.calls == [], "an invalid input must not hit the network"
    assert "rejected" in page.schedule_summary_label.text().lower()
    assert page.schedule_timing() is None


# ============================================================
# 11. FIX 3 — the response itself is validated, not just the body
# ============================================================

def test_missing_content_type_is_rejected():
    with pytest.raises(MarketClockInvalidResponse):
        build_sample(
            make_result(headers={"Date": GOOD_DATE_HEADER, "Age": "0"}),
            FIXED_NOW,
            FIXED_NOW,
        )


def test_wrong_content_type_is_rejected():
    with pytest.raises(MarketClockInvalidResponse):
        build_sample(
            make_result(headers=market_headers({"Content-Type": "text/html"})),
            FIXED_NOW,
            FIXED_NOW,
        )


def test_content_type_parameters_are_accepted():
    sample = build_sample(
        make_result(
            headers=market_headers({"Content-Type": "text/plain; charset=UTF-8"})
        ),
        FIXED_NOW,
        FIXED_NOW,
    )
    assert sample.market_time is not None


def test_missing_date_header_is_rejected():
    headers = market_headers()
    headers.pop("Date")
    with pytest.raises(MarketClockInvalidResponse):
        build_sample(make_result(headers=headers), FIXED_NOW, FIXED_NOW)


def test_missing_age_header_is_rejected():
    headers = market_headers()
    headers.pop("Age")
    with pytest.raises(MarketClockInvalidResponse):
        build_sample(make_result(headers=headers), FIXED_NOW, FIXED_NOW)


def test_a_stale_date_header_is_rejected():
    with pytest.raises(MarketClockStale):
        build_sample(
            make_result(
                headers=market_headers(
                    {"Date": "Thu, 02 Oct 2026 09:00:00 GMT"}
                )
            ),
            FIXED_NOW,
            FIXED_NOW,
        )


def test_a_date_from_the_future_is_rejected():
    with pytest.raises(MarketClockStale):
        build_sample(
            make_result(
                headers=market_headers({"Date": "Thu, 02 Oct 2026 11:00:00 GMT"})
            ),
            FIXED_NOW,
            FIXED_NOW,
        )


def test_no_store_does_not_make_a_freshly_fetched_answer_stale():
    """
    ``no-store`` is a storage directive, not a staleness signal.

    We have just fetched this body, so rejecting it would be wrong; the
    directive is recorded instead, and this module always refetches.
    """
    sample = build_sample(
        make_result(headers=market_headers({"Cache-Control": "no-store"})),
        FIXED_NOW,
        FIXED_NOW,
    )
    assert sample.market_time is not None


def test_no_store_is_still_recorded_as_requiring_revalidation():
    from ui.market_clock import evaluate_cache_policy

    policy = evaluate_cache_policy(
        market_headers({"Cache-Control": "no-store, max-age=5"})
    )
    assert policy.requires_revalidation is True


def test_a_body_older_than_max_age_is_rejected():
    """A real staleness bound is honoured: Age 5s against a max-age of 1s."""
    with pytest.raises(MarketClockStale):
        build_sample(
            make_result(
                headers=market_headers(
                    {"Cache-Control": "max-age=1", "Age": "5"}
                )
            ),
            FIXED_NOW,
            FIXED_NOW,
        )


def test_an_expired_expires_header_is_rejected():
    with pytest.raises(MarketClockStale):
        build_sample(
            make_result(
                headers=market_headers(
                    {"Expires": "Thu, 02 Oct 2026 09:00:00 GMT"}
                )
            ),
            FIXED_NOW,
            FIXED_NOW,
        )


def test_expires_after_date_but_before_receive_is_rejected():
    """
    Expires is after the Date header but before the moment we received it.

    The response was still "valid" per its Date, but by the time it reached
    us it had already expired. The effective age at receive time (Date + Age)
    exceeds the Expires deadline, so it must be rejected.
    """
    # Date is 09:29:00, Age=0, so effective generation time = 09:29:00
    # Expires at 09:29:10 (10s after Date), but we receive at 09:29:00 (FIXED_NOW)
    # Wait - FIXED_NOW is 09:29:00, so Expires at 09:29:10 is in the future.
    # To test this we need Expires between Date and receive time.
    # Let's set Date earlier, Age=5, and Expires between Date+Age and receive.
    with pytest.raises(MarketClockStale):
        build_sample(
            make_result(
                headers=market_headers(
                    {
                        "Date": "Thu, 02 Oct 2026 09:28:50 GMT",  # 10s before FIXED_NOW
                        "Age": "5",                                # 5s in CDN
                        "Expires": "Thu, 02 Oct 2026 09:28:58 GMT", # 8s after Date, 2s before receive
                    }
                )
            ),
            FIXED_NOW,
            FIXED_NOW,
        )


def test_expires_after_receive_is_accepted():
    """
    Expires is after the receive time - the response is still fresh when we get it.
    """
    sample = build_sample(
        make_result(
            headers=market_headers(
                {
                    "Date": "Thu, 02 Oct 2026 09:28:50 GMT",
                    "Age": "5",
                    "Expires": "Thu, 02 Oct 2026 09:29:10 GMT",  # 10s after FIXED_NOW
                }
            )
        ),
        FIXED_NOW,
        FIXED_NOW,
    )
    assert sample.market_time is not None


def test_a_cdn_cached_body_is_accepted_when_age_explains_it():
    """
    A body served 5s ago from a CDN is fine as long as Age says so.

    This must not be rejected: the body alone looks 5s stale, and the
    honest answer is "5 seconds old", not "invalid".
    """
    sample = build_sample(
        make_result(
            headers=market_headers(
                {
                    "Date": "Thu, 02 Oct 2026 09:28:55 GMT",
                    "Age": "5",
                }
            )
        ),
        FIXED_NOW,
        FIXED_NOW,
    )
    assert sample.cdn_age == 5
    assert sample.body_age <= timedelta(seconds=1)


def test_a_body_far_from_its_own_date_header_is_rejected():
    """The body must agree with the server's own Date, not just with us."""
    with pytest.raises(MarketClockStale):
        build_sample(
            make_result(
                text="10/02/2026 09:20:00",
                headers=market_headers({"Date": GOOD_DATE_HEADER, "Age": "0"}),
            ),
            FIXED_NOW,
            FIXED_NOW,
        )


def test_a_non_ok_status_is_rejected():
    with pytest.raises(MarketClockInvalidResponse):
        build_sample(
            make_result(
                status=503,
                headers=market_headers({"Retry-After": "120"}),
            ),
            FIXED_NOW,
            FIXED_NOW,
        )


# ============================================================
# 12. FIX 4 — the offset is never presented as exact
# ============================================================

def test_the_uncertainty_band_never_collapses_to_zero():
    """Second-resolution body + unknown transit: >= 0.75s always."""
    sample = build_sample(
        make_result(headers=market_headers()),
        FIXED_NOW,
        FIXED_NOW,
    )
    assert sample.uncertainty_seconds >= 0.75
    assert sample.is_sub_second_claim is False


def test_the_uncertainty_band_widens_with_the_round_trip():
    tight = build_sample(
        make_result(headers=market_headers()),
        FIXED_NOW,
        FIXED_NOW,
    )
    slow = build_sample(
        make_result(headers=market_headers()),
        FIXED_NOW,
        FIXED_NOW + timedelta(seconds=2),
    )
    assert slow.uncertainty_seconds > tight.uncertainty_seconds


def test_the_offset_is_reported_with_its_band_not_as_a_bare_number():
    sample = build_sample(
        make_result(headers=market_headers()),
        FIXED_NOW,
        FIXED_NOW,
    )
    text = sample.offset_text
    assert "+/-" in text, f"offset shown without a band: {text!r}"
    assert sample.uncertainty_seconds > 0


def test_the_system_clock_says_its_uncertainty_is_unknown():
    page = make_page(
        qapp,
        transport=fixed_transport(raises=TimeoutError("offline")),
    )
    fill(page, "13:00:00", "13:01:00", "15")
    apply_schedule(page)

    assert page.clock_status().source.value == "SYSTEM"
    summary = page.schedule_summary_label.text().lower()
    assert "system clock" in summary
    assert "unknown" in summary, f"system clock hides its uncertainty: {summary}"
