"""
ui/schedule_settings.py — UI-7 Task 1 schedule inputs and validation.

Turns the three user inputs (Start Time, End Time, Interval) into the
**existing** Block 3 contract objects. This module deliberately owns no
window logic of its own:

    Start / End / Interval  (user input)
        |
        v
    ScheduleValidationError (fail-closed)      <-- this module: parsing only
        |
        v
    core.timing_contracts.DispatchTiming      (EXISTING contract, reused)
        |
        v
    core.timed_dispatch_scheduler
        TimedDispatchScheduler                 (EXISTING generator, reused)

Every schedule moment shown to the user is produced by the real
``TimedDispatchScheduler``. There is no second, parallel schedule
generator anywhere in the UI, and no second validation rule set: a window
this module cannot build is a window the user must fix, never one the UI
silently repairs.

Fail-closed rules (UI-7 Task 1 acceptance criterion 1):
  * an empty field is rejected — it is never defaulted
  * a malformed time or interval is rejected — it is never coerced
  * a start at or after the end is rejected — the window is never inverted
  * a non-positive interval is rejected — it is never clamped to a minimum

Timezone: Start and End are Tehran wall-clock times on the current Tehran
day, because the market clock and the market session are Tehran-based.
The values are built as ``Asia/Tehran`` aware datetimes and only then
handed to the existing contract, which validates them again itself.

Out of scope (UI-7 Task 1): the countdown and schedule lifecycle (Task 2),
wiring due times to the order-send path (Task 3), any Core change, and
overnight / multi-day windows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Sequence

from ui import strings as STRINGS
from ui.market_clock import TEHRAN_TIMEZONE


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------

#: Start / End are Tehran wall-clock times of day: "HH:MM" or "HH:MM:SS".
TIME_INPUT_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")

#: Interval is a whole number of seconds. One format, one meaning.
INTERVAL_INPUT_PATTERN = re.compile(r"^[0-9]+$")

SCHEDULE_GROUP_TITLE = STRINGS.GROUP_SCHEDULE
TIME_INPUT_PLACEHOLDER = STRINGS.PLACEHOLDER_TIME_INPUT
INTERVAL_INPUT_PLACEHOLDER = STRINGS.PLACEHOLDER_INTERVAL_INPUT

START_INPUT_LABEL = STRINGS.LABEL_START_TIME
END_INPUT_LABEL = STRINGS.LABEL_END_TIME
INTERVAL_INPUT_LABEL = STRINGS.LABEL_INTERVAL_SECONDS

TIMEZONE_NOTE = STRINGS.NOTE_TIMEZONE

SCHEDULE_UNAVAILABLE = STRINGS.COUNTDOWN_UNAVAILABLE

# UI-7 Task 2 — schedule lifecycle and freshness constants
# --------------------------------------------------------
#: Maximum age of a successful clock sync before it is considered stale
#: for schedule Apply. Named, documented, never silently changed.
SCHEDULE_SYNC_MAX_AGE_SECONDS = 30.0

#: User-facing labels for the schedule state machine. The order below is
#: the lifecycle: configuring -> waiting -> counting (or starting once) ->
#: stopped / expired, after which the page returns to configuring.
SCHEDULE_STATE_CONFIG = STRINGS.STATE_CONFIGURING
SCHEDULE_STATE_WAITING = STRINGS.STATE_WAITING
SCHEDULE_STATE_COUNTING = STRINGS.STATE_COUNTING
SCHEDULE_STATE_START_NOW = STRINGS.STATE_START_NOW
SCHEDULE_STATE_STOPPED = STRINGS.STATE_STOPPED
SCHEDULE_STATE_EXPIRED = STRINGS.STATE_EXPIRED

#: Button labels. The SAME button is Apply before a schedule is accepted
#: and Stop afterwards (UI-7 Task 2); it is the only enabled button of the
#: schedule/order set while a schedule is active.
APPLY_BUTTON_LABEL = STRINGS.BUTTON_APPLY_SCHEDULE
STOP_BUTTON_LABEL = STRINGS.BUTTON_STOP_SCHEDULE

#: Button labels of the independent manual sync action.
SYNC_BUTTON_LABEL = "همگام‌سازی ساعت"
SYNC_BUTTON_LABEL_BUSY = "در حال همگام‌سازی…"
SYNC_BUTTON_LABEL_FAILED = "ناموفق - دوباره تلاش کنید"

#: Countdown texts (UI-7 Task 2).
COUNTDOWN_LABEL_UNAVAILABLE = SCHEDULE_UNAVAILABLE
COUNTDOWN_LABEL_NO_UPCOMING = STRINGS.COUNTDOWN_NO_UPCOMING
COUNTDOWN_LABEL_STOPPED = STRINGS.COUNTDOWN_STOPPED

#: Sync line states (UI-7 Task 2). Each one is shown explicitly; a stale
#: or missing reading is never dressed up as a fresh market clock.
SYNC_STATE_IN_PROGRESS = STRINGS.SYNC_IN_PROGRESS
SYNC_STATE_NEVER = STRINGS.SYNC_NEVER
SYNC_STATE_FAILED = STRINGS.SYNC_FAILED


class ScheduleValidationError(ValueError):
    """Raised when the schedule inputs are incomplete or invalid."""


# ---------------------------------------------------------------------------
# Parsed (still un-built) inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedScheduleInputs:
    """Three validated raw fields, before any window is constructed."""

    start_text: str
    end_text: str
    interval_text: str
    start_time_of_day: timedelta
    end_time_of_day: timedelta
    interval: timedelta


def _require_text(value: object, label: str) -> str:
    if value is None:
        raise ScheduleValidationError(f"{label} is required")
    if not isinstance(value, str):
        raise ScheduleValidationError(f"{label} must be text")
    text = value.strip()
    if not text:
        raise ScheduleValidationError(f"{label} is required")
    return text


def _parse_time_of_day(value: object, label: str) -> timedelta:
    """
    Parse a Tehran wall-clock time of day into an offset from midnight.

    A rejected value is never repaired: "25:00", "9:5", "10:00:00 PM" and
    "2026-10-02 10:00:00" are all errors, not near-misses to fix up.
    """
    text = _require_text(value, label)
    match = TIME_INPUT_PATTERN.match(text)
    if match is None:
        raise ScheduleValidationError(
            f"{label} must be Tehran time as HH:MM or HH:MM:SS, "
            f"got {text!r}"
        )
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3) or 0)
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _parse_interval(value: object) -> timedelta:
    """
    Parse the run interval in whole seconds.

    Zero is rejected rather than clamped, because a zero gap would make
    the schedule degenerate into a burst.
    """
    text = _require_text(value, INTERVAL_INPUT_LABEL)
    if not INTERVAL_INPUT_PATTERN.match(text):
        raise ScheduleValidationError(
            f"{INTERVAL_INPUT_LABEL} must be a whole number of seconds, "
            f"got {text!r}"
        )
    seconds = int(text)
    if seconds <= 0:
        raise ScheduleValidationError(
            f"{INTERVAL_INPUT_LABEL} must be greater than zero, got {seconds}"
        )
    return timedelta(seconds=seconds)


def parse_schedule_inputs(
    start_text: object,
    end_text: object,
    interval_text: object,
) -> ParsedScheduleInputs:
    """
    Validate the three raw inputs without building or correcting anything.

    Returns:
        The three cleaned field texts plus their parsed equivalents.

    Raises:
        ScheduleValidationError: any field is missing or malformed.
    """
    start_clean = _require_text(start_text, START_INPUT_LABEL)
    end_clean = _require_text(end_text, END_INPUT_LABEL)
    interval_clean = _require_text(interval_text, INTERVAL_INPUT_LABEL)

    start_offset = _parse_time_of_day(start_clean, START_INPUT_LABEL)
    end_offset = _parse_time_of_day(end_clean, END_INPUT_LABEL)
    interval = _parse_interval(interval_clean)

    if start_offset > end_offset:
        raise ScheduleValidationError(
            f"{START_INPUT_LABEL} must not be after {END_INPUT_LABEL} on "
            f"the same Tehran day ({start_clean} > {end_clean})"
        )

    return ParsedScheduleInputs(
        start_text=start_clean,
        end_text=end_clean,
        interval_text=interval_clean,
        start_time_of_day=start_offset,
        end_time_of_day=end_offset,
        interval=interval,
    )


# ---------------------------------------------------------------------------
# Existing Block 3 contract reuse
# ---------------------------------------------------------------------------


def _core_timing():
    """Import the existing timing contract lazily (offline construction)."""
    from core.timing_contracts import DispatchTiming, TimingValidationError

    return DispatchTiming, TimingValidationError


def build_dispatch_timing(
    parsed: ParsedScheduleInputs,
    tehran_date: datetime,
) -> object:
    """
    Build a REAL ``DispatchTiming`` from validated inputs.

    ``DispatchTiming`` performs its own fail-closed validation; any error
    it raises is surfaced unchanged rather than being worked around.

    Raises:
        ScheduleValidationError: the contract rejected the window.
    """
    if not isinstance(parsed, ParsedScheduleInputs):
        raise ScheduleValidationError(
            f"build_dispatch_timing requires ParsedScheduleInputs, got "
            f"{type(parsed).__name__}"
        )
    if not isinstance(tehran_date, datetime):
        raise ScheduleValidationError(
            "tehran_date must be a datetime"
        )

    DispatchTiming, TimingValidationError = _core_timing()

    midnight = tehran_date.astimezone(TEHRAN_TIMEZONE).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = midnight + parsed.start_time_of_day
    end = midnight + parsed.end_time_of_day

    try:
        return DispatchTiming(
            start_time=start,
            end_time=end,
            interval=parsed.interval,
        )
    except TimingValidationError as exc:
        raise ScheduleValidationError(str(exc)) from exc


def generate_schedule_times(timing: object) -> List[datetime]:
    """
    Generate the run moments with the REAL ``TimedDispatchScheduler``.

    No timestamp is ever produced by this module itself.
    """
    from core.timed_dispatch_scheduler import TimedDispatchScheduler

    return list(TimedDispatchScheduler(timing=timing).generate())


# ---------------------------------------------------------------------------
# Window assessment against the selected clock
# ---------------------------------------------------------------------------


class ScheduleState(Enum):
    """Where the schedule window stands relative to the selected clock."""

    PENDING = "PENDING"
    START_NOW = "START_NOW"
    EXPIRED = "EXPIRED"


STATE_LABEL = {
    ScheduleState.PENDING: STRINGS.STATE_WAITING,
    ScheduleState.START_NOW: STRINGS.STATE_START_NOW,
    ScheduleState.EXPIRED: STRINGS.STATE_EXPIRED,
}


@dataclass(frozen=True)
class ScheduleAssessment:
    """
    The outcome of checking a built window against the current time.

    ``fire_now`` is a single boolean, not a count: a window whose start
    has passed contributes exactly one immediate start, never one run per
    missed interval.

    ``upcoming`` holds only moments strictly in the future. Missed moments
    are counted and discarded rather than replayed, which is what keeps a
    clock-source change or a late start from turning into a burst.
    """

    state: ScheduleState
    fire_now: bool
    upcoming: Sequence[datetime]
    missed: Sequence[datetime]
    now: datetime

    @property
    def missed_count(self) -> int:
        return len(self.missed)

    @property
    def upcoming_count(self) -> int:
        return len(self.upcoming)

    @property
    def state_label(self) -> str:
        return STATE_LABEL[self.state]

    @property
    def is_expired(self) -> bool:
        return self.state is ScheduleState.EXPIRED


def assess_schedule_window(
    timing: object,
    now: datetime,
    times: Optional[Sequence[datetime]] = None,
) -> ScheduleAssessment:
    """
    Classify the window against ``now`` and split past from future moments.

    Raises:
        ScheduleValidationError: ``now`` is not a datetime.
    """
    if not isinstance(now, datetime):
        raise ScheduleValidationError(
            f"now must be a datetime, got {type(now).__name__}"
        )

    moments = list(times) if times is not None else generate_schedule_times(timing)

    start_time = getattr(timing, "start_time", None)
    end_time = getattr(timing, "end_time", None)
    if not isinstance(start_time, datetime) or not isinstance(end_time, datetime):
        raise ScheduleValidationError(
            "timing must expose real start_time and end_time datetimes"
        )

    if now > end_time:
        return ScheduleAssessment(
            state=ScheduleState.EXPIRED,
            fire_now=False,
            upcoming=(),
            missed=tuple(m for m in moments if m <= now),
            now=now,
        )

    if now < start_time:
        return ScheduleAssessment(
            state=ScheduleState.PENDING,
            fire_now=False,
            upcoming=tuple(moments),
            missed=(),
            now=now,
        )

    future = tuple(m for m in moments if m > now)
    already = tuple(m for m in moments if m <= now)
    return ScheduleAssessment(
        state=ScheduleState.START_NOW,
        fire_now=True,
        upcoming=future,
        missed=already,
        now=now,
    )


# ---------------------------------------------------------------------------
# Summary presentation (shown before anything starts)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduleSummary:
    """The user-facing summary shown before a schedule is accepted."""

    start_text: str
    end_text: str
    interval_text: str
    timezone_note: str
    total_times: int
    state: ScheduleState
    state_label: str
    fire_now: bool
    missed_count: int
    upcoming_count: int
    next_times: Sequence[datetime]
    clock_description: str

    @property
    def is_expired(self) -> bool:
        return self.state is ScheduleState.EXPIRED


def _format_moment(moment: datetime) -> str:
    local = moment.astimezone(TEHRAN_TIMEZONE)
    return local.strftime("%H:%M:%S")


def build_schedule_summary(
    parsed: ParsedScheduleInputs,
    timing: object,
    assessment: ScheduleAssessment,
    clock_description: str,
    moments: Optional[Sequence[datetime]] = None,
    preview_limit: int = 5,
) -> ScheduleSummary:
    """Render the accepted schedule for confirmation before it starts."""
    all_moments = (
        list(moments) if moments is not None else generate_schedule_times(timing)
    )
    preview = tuple(assessment.upcoming[:preview_limit])
    return ScheduleSummary(
        start_text=parsed.start_text,
        end_text=parsed.end_text,
        interval_text=parsed.interval_text,
        timezone_note=TIMEZONE_NOTE,
        total_times=len(all_moments),
        state=assessment.state,
        state_label=assessment.state_label,
        fire_now=assessment.fire_now,
        missed_count=assessment.missed_count,
        upcoming_count=assessment.upcoming_count,
        next_times=preview,
        clock_description=clock_description,
    )


def describe_summary(summary: ScheduleSummary) -> str:
    """A clear multi-line summary of the accepted schedule and clock.

    Every visible word comes from ``STRINGS``; only the clock/moment values
    (times, and the ``Asia/Tehran`` identifier) stay Latin because they are
    technical, while the counts go through ``format_persian_digits``.
    """
    lines = [
        STRINGS.SUMMARY_WINDOW.format(
            start=summary.start_text,
            end=summary.end_text,
            timezone=summary.timezone_note,
        ),
        STRINGS.SUMMARY_INTERVAL.format(
            interval=STRINGS.format_persian_digits(summary.interval_text)
        ),
        STRINGS.SUMMARY_RUN_MOMENTS.format(
            count=STRINGS.format_persian_digits(summary.total_times)
        ),
        STRINGS.SUMMARY_STATE.format(state=summary.state_label),
    ]
    if summary.missed_count:
        lines.append(
            STRINGS.SUMMARY_SKIPPED.format(
                count=STRINGS.format_persian_digits(summary.missed_count)
            )
        )
    if summary.next_times:
        rendered = ", ".join(_format_moment(m) for m in summary.next_times)
        shown = summary.upcoming_count > len(summary.next_times)
        lines.append(
            STRINGS.SUMMARY_NEXT_MOMENTS.format(
                count=STRINGS.format_persian_digits(summary.upcoming_count),
                times=rendered,
            )
            + (" …" if shown else "")
        )
    else:
        lines.append(STRINGS.SUMMARY_NEXT_MOMENTS_NONE)
    if summary.fire_now:
        lines.append(STRINGS.SUMMARY_IMMEDIATE_START)
    lines.append(STRINGS.SUMMARY_CLOCK.format(clock=summary.clock_description))
    return "\n".join(lines)