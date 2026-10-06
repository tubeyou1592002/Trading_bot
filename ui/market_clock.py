"""
ui/market_clock.py — UI-7 Task 1 clock foundation.

Establishes a *trustworthy time source* for the schedule UI without ever
changing the operating-system clock and without implementing NTP:

    User presses "Apply Schedule"
        |
        v
    MarketClockService  <-- this module (source selection + honest offset)
        |
        v
    Schedule window (DispatchTiming)  --> existing Block 3 validation

Two sources exist and the service reports which one is in use:

  * SYSTEM  — the local system clock. Assumed NTP-disciplined by the
              operating system; this module neither checks NTP nor runs
              it and never writes the system clock.
  * MARKET  — the TSETMC market-time endpoint, preferred when valid.

Market source contract (verified by the user, unofficial / no SLA):

    GET https://cdn.tsetmc.com/api/StaticData/GetTime
    -> 200, Content-Type: text/plain
    -> body: "MM/DD/YYYY HH:MM:SS", Gregorian, **second precision**
    -> the body time is **Tehran time** (Asia/Tehran, UTC+03:30)
    -> the HTTP `Date` header is **UTC** and is NOT the body timezone

Because the body has one-second resolution the market time is only known
to within a whole second, so this module never claims millisecond
accuracy and never claims a zero offset: every market reading carries an
explicit ``uncertainty`` which the UI shows as a "+/- Ns" band.

Fail-closed response policy
---------------------------
This endpoint is unofficial, undocumented, and served through a CDN, so a
response is only accepted as "current market time" when it proves it is
current. A response missing the evidence is REFUSED, not trusted:

  * ``Content-Type``, ``Date`` and ``Age`` are all REQUIRED. A response
    without them cannot be shown to be fresh, so it is refused rather
    than treated as a valid market time.
  * ``Content-Type`` must be ``text/plain`` with only allowed parameters
    (``charset`` of ``utf-8`` / ascii). A missing header is a refusal, not
    a pass.
  * ``Age`` must be numeric, non-negative and within
    ``MARKET_TIME_MAX_CDN_AGE_SECONDS``.
  * ``Cache-Control`` (``max-age`` / ``s-maxage`` / ``no-store`` /
    ``no-cache`` / ``must-revalidate``) and ``Expires`` are applied as a
    cache policy; a response that its own policy marks as expired is
    refused.
  * Freshness is judged THREE ways, never by body-vs-Date alone: the body
    against the ``Date`` header, the body against the local receive time,
    and the ``Age`` / cache-policy evidence.

Non-rewinding clock
-------------------
The application clock is anchored to the computer's **monotonic** clock,
so an operating-system time adjustment (NTP step, manual change) cannot
drag the schedule clock around, and the operating system is never written
to. On top of that the returned time is clamped so it can never decrease:
when the applied offset falls (a negative correction, or losing the site
clock), the schedule clock *holds* instead of rewinding, and resumes at
the correct rate once monotonic time has caught up. Holding is the honest
cost of "never go backwards": a discrete negative correction necessarily
stalls the clock for its own magnitude.

The offset itself only ever moves by ``MAX_CORRECTION_STEP_SECONDS`` per
observation, toward its target, in both directions.

Explicitly OUT of scope (UI-7 Task 1):
  * any countdown, timer, or schedule lifecycle (UI-7 Task 2)
  * connecting due times to the order-send path (UI-7 Task 3)
  * NTP client, SNTP/NTP protocol, or any system-clock write
  * touching Core, the execution path, SafetyGate, or Block 3
  * manufacturing a clock reading when none was obtained
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Callable, Mapping, Optional
from zoneinfo import ZoneInfo

from PySide6.QtCore import QThread, Signal


# ---------------------------------------------------------------------------
# UI-7 Task 2 — schedule sync freshness constants
# ---------------------------------------------------------------------------
# These constants belong in market_clock.py because they govern when a
# MarketClockService reading is fresh enough to be used for a schedule
# Apply. They are named, documented, and never silently changed.
# ---------------------------------------------------------------------------

#: Maximum age of a successful market clock sync before it is considered
#: stale for schedule Apply. A sync older than this cannot be used as the
#: basis for a new schedule; the user must re-sync.
SCHEDULE_SYNC_MAX_AGE_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Contract constants (named, documented, never changed silently)
# ---------------------------------------------------------------------------

TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")
UTC = timezone.utc

TSETMC_TIME_URL = "https://cdn.tsetmc.com/api/StaticData/GetTime"

#: Exact documented body format. Gregorian, US field order, second precision.
MARKET_TIME_FORMAT = "%m/%d/%Y %H:%M:%S"

#: Strict shape check. Anything else (extra spaces, ISO order, a trailing
#: newline, a bare date) is a malformed answer, not a time to guess at.
MARKET_TIME_PATTERN = re.compile(
    r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}$"
)

#: Request deadline. A slow exchange CDN must never freeze the UI.
MARKET_TIME_TIMEOUT_SECONDS = 5.0

#: The body resolves time only to whole seconds.
MARKET_TIME_QUANTUM_SECONDS = 1.0

#: The endpoint does not document whether it TRUNCATES or ROUNDS to the
#: second, so neither is assumed. Truncation leaves the true instant in
#: ``[body, body + 1s)``; rounding leaves it in ``[body - 0.5s, body + 0.5s)``.
#: The union of both possibilities spans 1.5s, which is why the floor is
#: 0.75s per side and not the 0.5s a naive "half a quantum" would give.
MARKET_TIME_QUANTUM_AMBIGUITY_SECONDS = 0.75

#: A cached CDN object older than this is refused outright via ``Age``.
MARKET_TIME_MAX_CDN_AGE_SECONDS = 15.0

#: The body must not be older than this relative to the server's own
#: ``Date`` header.
MARKET_TIME_MAX_BODY_AGE_SECONDS = 30.0

#: The body must not be older than this relative to when WE received it.
#: This is a separate check from the ``Date`` one: a response whose
#: ``Date`` is self-consistent can still have been sitting in a cache.
MARKET_TIME_MAX_RECEIVE_SKEW_SECONDS = 30.0

#: Guard against a wrong host, a hijacked response, or a wildly wrong
#: system clock. A reading this far out is not a usable offset.
MARKET_TIME_MAX_ABS_OFFSET_SECONDS = 300.0

#: Headers without which a response cannot be proven fresh. All three are
#: mandatory; see the fail-closed policy in the module docstring.
MARKET_TIME_REQUIRED_HEADERS = ("content-type", "date", "age")

#: ``Content-Type`` values and parameters that are acceptable.
MARKET_TIME_ALLOWED_MEDIA_TYPES = ("text/plain",)
MARKET_TIME_ALLOWED_CHARSETS = ("utf-8", "us-ascii", "ascii")

#: The largest change the applied offset may make per observation. Any
#: correction is therefore bounded and gradual, never a jump.
MAX_CORRECTION_STEP_SECONDS = 0.25

#: Shown wherever a market reading is displayed, so the second-resolution
#: limit is never presented as millisecond precision.
MARKET_PRECISION_NOTE = "second-resolution source"

CLOCK_NOTICE_SYSTEM = "System clock (assumed NTP-synced by the OS)"
CLOCK_NOTICE_MARKET = "TSETMC market time"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MarketClockError(RuntimeError):
    """Base class for every market-clock refusal."""


class MarketClockTimeout(MarketClockError):
    """The endpoint did not answer within the deadline."""


class MarketClockInvalidResponse(MarketClockError):
    """Status, headers, or body format did not match the contract."""


class MarketClockStale(MarketClockError):
    """A syntactically valid answer that is too old to be used as 'now'."""


# ---------------------------------------------------------------------------
# Transport (injectable so tests never touch the network)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransportResult:
    """The minimal HTTP facts the clock contract needs."""

    status_code: int
    text: str
    headers: Mapping[str, str]


def default_transport(
    url: str = TSETMC_TIME_URL,
    timeout: float = MARKET_TIME_TIMEOUT_SECONDS,
) -> TransportResult:
    """
    Perform the real HTTP GET via ``requests``.

    ``requests`` is imported here — never at module level — so that
    importing any ``ui`` module stays offline (the UI-1 offline contract).
    """
    import requests

    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    return TransportResult(
        status_code=response.status_code,
        text=response.text,
        headers={str(k): str(v) for k, v in response.headers.items()},
    )


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return value
    return None


# ---------------------------------------------------------------------------
# Body / header parsing and validation
# ---------------------------------------------------------------------------


def parse_market_time(body: str) -> datetime:
    """
    Parse the documented body into an aware Tehran datetime.

    The value is interpreted as ``Asia/Tehran`` **because the body says
    so** — never from the HTTP ``Date`` header, which is UTC.

    Raises:
        MarketClockInvalidResponse: the body does not match the contract.
    """
    if not isinstance(body, str):
        raise MarketClockInvalidResponse("market time body must be text")

    text = body.strip()
    if not text:
        raise MarketClockInvalidResponse("market time body is empty")

    if not MARKET_TIME_PATTERN.match(text):
        raise MarketClockInvalidResponse(
            "market time body does not match the documented "
            f"MM/DD/YYYY HH:MM:SS format: {text!r}"
        )

    try:
        parsed = datetime.strptime(text, MARKET_TIME_FORMAT)
    except ValueError as exc:
        raise MarketClockInvalidResponse(
            f"market time body is not a real calendar date: {text!r}"
        ) from exc

    if parsed.strftime(MARKET_TIME_FORMAT) != text:
        raise MarketClockInvalidResponse(
            f"market time body is not a zero-padded canonical time: {text!r}"
        )

    return parsed.replace(tzinfo=TEHRAN_TIMEZONE)


def parse_http_date_utc(headers: Mapping[str, str]) -> Optional[datetime]:
    """
    Parse the HTTP ``Date`` header into an aware UTC datetime.

    Used ONLY as a staleness reference. It is never returned as the market
    time — that value is UTC while the market clock is Tehran.
    """
    raw = _header(headers, "Date")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_age_seconds(headers: Mapping[str, str]) -> Optional[float]:
    raw = _header(headers, "Age")
    if raw is None:
        return None
    try:
        age = float(str(raw).strip())
    except (TypeError, ValueError):
        raise MarketClockInvalidResponse(
            f"CDN Age header is not numeric: {raw!r}"
        )
    if age < 0:
        raise MarketClockInvalidResponse(
            f"CDN Age header is negative: {raw!r}"
        )
    return age


def _validate_content_type(headers: Mapping[str, str]) -> None:
    """
    Require ``text/plain`` with only allowed parameters.

    A MISSING ``Content-Type`` is a refusal, not a pass: without it there
    is no evidence the body is the plain-text market time at all.
    """
    raw = _header(headers, "Content-Type")
    if raw is None:
        raise MarketClockInvalidResponse(
            "market time response has no Content-Type header; "
            "a response that cannot prove its own type is refused"
        )

    parts = [piece.strip() for piece in str(raw).split(";")]
    media_type = parts[0].lower()
    if media_type not in MARKET_TIME_ALLOWED_MEDIA_TYPES:
        raise MarketClockInvalidResponse(
            f"market time must be one of "
            f"{MARKET_TIME_ALLOWED_MEDIA_TYPES}, got {media_type!r}"
        )

    for parameter in parts[1:]:
        if not parameter:
            continue
        if "=" not in parameter:
            raise MarketClockInvalidResponse(
                f"malformed Content-Type parameter: {parameter!r}"
            )
        name, value = parameter.split("=", 1)
        name = name.strip().lower()
        value = value.strip().strip('"').lower()
        if name != "charset":
            raise MarketClockInvalidResponse(
                f"Content-Type parameter {name!r} is not allowed on this "
                f"endpoint; only 'charset' is, e.g. 'text/plain; "
                f"charset=utf-8'"
            )
        if value not in MARKET_TIME_ALLOWED_CHARSETS:
            raise MarketClockInvalidResponse(
                f"Content-Type charset {value!r} is not allowed; expected one "
                f"of {MARKET_TIME_ALLOWED_CHARSETS}"
            )


# ---------------------------------------------------------------------------
# Cache policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CachePolicy:
    """What the response's own caching metadata says about its freshness."""

    directives: Mapping[str, Optional[str]]
    max_age_seconds: Optional[float]
    requires_revalidation: bool
    expires_at: Optional[datetime]


def _parse_cache_control(raw: str) -> Mapping[str, Optional[str]]:
    directives = {}
    for piece in str(raw).split(","):
        piece = piece.strip()
        if not piece:
            continue
        if "=" in piece:
            name, value = piece.split("=", 1)
            directives[name.strip().lower()] = value.strip().strip('"')
        else:
            directives[piece.lower()] = None
    return directives


def evaluate_cache_policy(headers: Mapping[str, str]) -> CachePolicy:
    """
    Read ``Cache-Control`` / ``Expires`` into an explicit policy.

    ``no-store`` / ``no-cache`` / ``must-revalidate`` mean the answer must
    not be reused as-is, which is exactly what this module does (it always
    asks again), so they raise no staleness of their own. A ``max-age`` /
    ``s-maxage`` bound, or an ``Expires`` in the past, is a real staleness
    signal and is applied in :func:`validate_response`.
    """
    raw_cc = _header(headers, "Cache-Control")
    directives = _parse_cache_control(raw_cc) if raw_cc else {}

    max_age = None
    for key in ("s-maxage", "max-age"):
        if key in directives and directives[key] is not None:
            try:
                candidate = float(directives[key])
            except (TypeError, ValueError):
                raise MarketClockInvalidResponse(
                    f"Cache-Control {key} is not numeric: {directives[key]!r}"
                )
            if candidate < 0:
                raise MarketClockInvalidResponse(
                    f"Cache-Control {key} is negative: {candidate}"
                )
            max_age = candidate if max_age is None else min(max_age, candidate)

    requires_revalidation = any(
        key in directives
        for key in ("no-store", "no-cache", "must-revalidate", "proxy-revalidate")
    )

    expires_at = None
    raw_expires = _header(headers, "Expires")
    if raw_expires:
        try:
            parsed = parsedate_to_datetime(raw_expires)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            expires_at = parsed.astimezone(UTC)

    return CachePolicy(
        directives=directives,
        max_age_seconds=max_age,
        requires_revalidation=requires_revalidation,
        expires_at=expires_at,
    )


def validate_response(
    result: TransportResult,
    received_at_utc: datetime,
) -> datetime:
    """
    Validate one HTTP response and return its Tehran market time.

    Raises:
        MarketClockInvalidResponse: contract violation (including any
            missing header needed to prove freshness).
        MarketClockStale: a valid but cached / too-old answer.
    """
    headers = result.headers or {}

    if not isinstance(result.status_code, int) or result.status_code != 200:
        raise MarketClockInvalidResponse(
            f"market time endpoint returned status "
            f"{getattr(result, 'status_code', None)!r}, expected 200"
        )

    missing = [
        name
        for name in MARKET_TIME_REQUIRED_HEADERS
        if _header(headers, name) is None
    ]
    if missing:
        raise MarketClockInvalidResponse(
            "market time response is missing required header(s) "
            f"{missing}; without them the response cannot be proven fresh "
            f"(required: {list(MARKET_TIME_REQUIRED_HEADERS)})"
        )

    _validate_content_type(headers)

    cdn_age = _parse_age_seconds(headers)
    if cdn_age > MARKET_TIME_MAX_CDN_AGE_SECONDS:
        raise MarketClockStale(
            f"market time came from CDN cache (Age={cdn_age:.0f}s, "
            f"limit {MARKET_TIME_MAX_CDN_AGE_SECONDS:.0f}s)"
        )

    policy = evaluate_cache_policy(headers)
    date_header = parse_http_date_utc(headers)
    if date_header is None:
        raise MarketClockInvalidResponse(
            "market time Date header is unparseable; freshness cannot be "
            "established"
        )

    if policy.max_age_seconds is not None and cdn_age >= policy.max_age_seconds:
        raise MarketClockStale(
            f"market time exceeded its own Cache-Control lifetime "
            f"(Age={cdn_age:.0f}s, max-age={policy.max_age_seconds:.0f}s)"
        )

    if policy.expires_at is not None and policy.expires_at <= received_at_utc:
        raise MarketClockStale(
            f"market time response is already expired at receive time "
            f"(Expires={policy.expires_at.isoformat()}, "
            f"received={received_at_utc.isoformat()})"
        )

    market_time = parse_market_time(result.text)
    market_utc = market_time.astimezone(UTC)

    body_vs_date = (date_header - market_utc).total_seconds()
    if body_vs_date > MARKET_TIME_MAX_BODY_AGE_SECONDS:
        raise MarketClockStale(
            f"market time body is {body_vs_date:.0f}s older than its own "
            f"Date header (limit {MARKET_TIME_MAX_BODY_AGE_SECONDS:.0f}s)"
        )
    if body_vs_date < -MARKET_TIME_MAX_BODY_AGE_SECONDS:
        raise MarketClockStale(
            f"market time body is {-body_vs_date:.0f}s ahead of its own "
            f"Date header (limit {MARKET_TIME_MAX_BODY_AGE_SECONDS:.0f}s)"
        )

    body_vs_receive = (received_at_utc - market_utc).total_seconds()
    if body_vs_receive > MARKET_TIME_MAX_RECEIVE_SKEW_SECONDS:
        raise MarketClockStale(
            f"market time body is {body_vs_receive:.0f}s older than when we "
            f"received it (limit {MARKET_TIME_MAX_RECEIVE_SKEW_SECONDS:.0f}s)"
        )
    if body_vs_receive < -MARKET_TIME_MAX_RECEIVE_SKEW_SECONDS:
        raise MarketClockStale(
            f"market time body is {-body_vs_receive:.0f}s ahead of when we "
            f"received it (limit {MARKET_TIME_MAX_RECEIVE_SKEW_SECONDS:.0f}s)"
        )

    system_offset = (market_utc - received_at_utc).total_seconds()
    if abs(system_offset) > MARKET_TIME_MAX_ABS_OFFSET_SECONDS:
        raise MarketClockStale(
            f"market time disagrees with the system clock by "
            f"{system_offset:.0f}s (limit "
            f"{MARKET_TIME_MAX_ABS_OFFSET_SECONDS:.0f}s)"
        )

    return market_time


# ---------------------------------------------------------------------------
# Market reading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketClockSample:
    """
    One accepted market-time reading with its honest uncertainty band.

    ``offset`` is ``market_time - system_time_at_round_trip_midpoint``. It
    is an *estimate*: the body is second-resolution with undocumented
    rounding, and the round trip is not zero. ``uncertainty`` is the
    explicit band around it and is never zero.
    """

    market_time: datetime
    offset: timedelta
    uncertainty: timedelta
    round_trip: timedelta
    body_age: timedelta
    cdn_age: Optional[float]
    fetched_at_utc: datetime

    @property
    def offset_seconds(self) -> float:
        return self.offset.total_seconds()

    @property
    def uncertainty_seconds(self) -> float:
        return self.uncertainty.total_seconds()

    @property
    def is_sub_second_claim(self) -> bool:
        """Always ``False``: this source can never justify ms precision."""
        return False

    @property
    def offset_text(self) -> str:
        """The offset shown WITH its band, never as a bare exact number."""
        return (
            f"{self.offset_seconds:+.2f}s "
            f"+/-{self.uncertainty_seconds:.2f}s"
        )


def build_sample(
    result: TransportResult,
    requested_at_utc: datetime,
    received_at_utc: datetime,
) -> MarketClockSample:
    """
    Turn one validated response into a ``MarketClockSample``.

    The offset is estimated at the round-trip midpoint so the assumed
    one-way latency is split evenly instead of being charged entirely to
    one side. The uncertainty band is deliberately conservative and is the
    SUM of two independent sources of ambiguity:

      1. ``MARKET_TIME_QUANTUM_AMBIGUITY_SECONDS`` (0.75s) — the body's
         second resolution combined with the undocumented choice between
         truncation and rounding.
      2. half the round trip — the unknown split of transit time between
         request and response.

    Because source (1) is a fixed floor, the band can never collapse to
    zero and can never be narrower than 0.75s.
    """
    market_time = validate_response(result, received_at_utc)

    round_trip = received_at_utc - requested_at_utc
    if round_trip < timedelta(0):
        round_trip = timedelta(0)
    midpoint = requested_at_utc + round_trip / 2

    offset = market_time.astimezone(UTC) - midpoint

    uncertainty_seconds = (
        MARKET_TIME_QUANTUM_AMBIGUITY_SECONDS
        + round_trip.total_seconds() / 2.0
    )

    date_header = parse_http_date_utc(result.headers or {})
    reference = date_header if date_header is not None else received_at_utc
    body_age = reference - market_time.astimezone(UTC)

    return MarketClockSample(
        market_time=market_time,
        offset=offset,
        uncertainty=timedelta(seconds=uncertainty_seconds),
        round_trip=round_trip,
        body_age=body_age,
        cdn_age=_parse_age_seconds(result.headers or {}),
        fetched_at_utc=received_at_utc,
    )


def fetch_market_clock(
    transport: Optional[Callable[..., TransportResult]] = None,
    now_utc: Optional[Callable[[], datetime]] = None,
    timeout: float = MARKET_TIME_TIMEOUT_SECONDS,
) -> MarketClockSample:
    """
    Fetch, validate, and return one market-time reading.

    ``transport`` and ``now_utc`` are injected so tests control the clock
    and the HTTP answer exactly; the defaults are the real network call
    and the real system clock.

    Raises:
        MarketClockTimeout: the request exceeded ``timeout``.
        MarketClockInvalidResponse / MarketClockStale: contract violation.
    """
    getter = transport if transport is not None else default_transport
    clock = now_utc if now_utc is not None else (lambda: datetime.now(UTC))

    requested_at = clock()
    try:
        result = getter(TSETMC_TIME_URL, timeout)
    except TimeoutError as exc:
        raise MarketClockTimeout(
            f"market time request exceeded {timeout:.0f}s"
        ) from exc
    except MarketClockError:
        raise
    except Exception as exc:  # noqa: BLE001 — network failure is a fallback
        raise MarketClockTimeout(
            f"market time request failed: {exc}"
        ) from exc

    received_at = clock()
    return build_sample(result, requested_at, received_at)


# ---------------------------------------------------------------------------
# Source selection with bounded, gradual, non-rewinding correction
# ---------------------------------------------------------------------------


class ClockSource(Enum):
    """Which time source the application currently trusts."""

    SYSTEM = "SYSTEM"
    MARKET = "MARKET"


@dataclass(frozen=True)
class ClockStatus:
    """What the UI needs to tell the user about the clock, honestly."""

    source: ClockSource
    applied_offset: timedelta
    uncertainty: Optional[timedelta]
    market_time: Optional[datetime]
    notice: str
    precision_note: str

    # UI-7 Task 2 — sync tracking for manual sync display
    last_successful_sync: Optional[datetime] = None
    last_sync_attempt: Optional[datetime] = None
    last_sync_ok: bool = False

    # UI-7 Task 2 — age of the last SUCCESSFUL sync, measured on the
    # MONOTONIC clock (never on the wall clock, which a system-clock step
    # could move and thereby make a stale reading look fresh). ``None``
    # when no successful sync has ever completed.
    sync_age_seconds: Optional[float] = None

    @property
    def offset_seconds(self) -> float:
        return self.applied_offset.total_seconds()

    @property
    def uncertainty_seconds(self) -> Optional[float]:
        if self.uncertainty is None:
            return None
        return self.uncertainty.total_seconds()


class MarketClockService:
    """
    Chooses the clock source and applies a bounded, gradual correction.

    The application's notion of "now" is built as::

        wall_anchor + (monotonic_now - monotonic_anchor) + applied_offset

    so it advances on the computer's monotonic clock and an operating
    system time adjustment cannot move it. On top of that the returned
    value is clamped to never decrease: if a negative correction or a
    fallback would move the offset down, the clock HOLDS at its previous
    value rather than rewinding, and continues at the correct rate once
    monotonic time has caught up.

    The applied offset itself walks toward its target by at most
    ``MAX_CORRECTION_STEP_SECONDS`` per observation, in both directions.
    """

    def __init__(
        self,
        transport: Optional[Callable[..., TransportResult]] = None,
        now_utc: Optional[Callable[[], datetime]] = None,
        mono_clock: Optional[Callable[[], float]] = None,
        max_step_seconds: float = MAX_CORRECTION_STEP_SECONDS,
    ) -> None:
        self._transport = transport
        self._now_utc = now_utc if now_utc is not None else (
            lambda: datetime.now(UTC)
        )
        self._mono = mono_clock if mono_clock is not None else time.monotonic
        self._max_step = timedelta(seconds=abs(max_step_seconds))
        self._source = ClockSource.SYSTEM
        self._applied_offset = timedelta(0)
        self._uncertainty: Optional[timedelta] = None
        self._market_time: Optional[datetime] = None
        self._notice = CLOCK_NOTICE_SYSTEM
        self._last_error: Optional[str] = None
        self._wall_anchor = self._now_utc()
        self._mono_anchor = self._mono()
        self._last_now: Optional[datetime] = None

        # UI-7 Task 2 — sync tracking for schedule freshness
        self._last_successful_sync: Optional[datetime] = None
        self._last_sync_attempt: Optional[datetime] = None
        self._last_sync_ok: bool = False
        # Monotonic readings taken at those same moments. Freshness for a
        # schedule Apply is ALWAYS judged on these, never on the wall
        # clock: an NTP step must neither renew a stale reading nor expire
        # a fresh one.
        self._last_successful_sync_mono: Optional[float] = None
        self._last_sync_attempt_mono: Optional[float] = None

    # -- state ------------------------------------------------------------

    @property
    def transport(self) -> Optional[Callable[..., TransportResult]]:
        """
        The HTTP transport this service uses.

        Exposed so a caller that fetches on a background thread uses the
        *same* transport as the service, and can never silently diverge
        into a different (possibly real-network) transport.
        """
        return self._transport

    @property
    def now_utc(self) -> Callable[[], datetime]:
        """The system-clock callable this service measures against."""
        return self._now_utc

    @property
    def mono_clock(self) -> Callable[[], float]:
        """The monotonic callable the application clock advances on."""
        return self._mono

    @property
    def source(self) -> ClockSource:
        return self._source

    @property
    def applied_offset(self) -> timedelta:
        return self._applied_offset

    @property
    def market_time(self) -> Optional[datetime]:
        return self._market_time

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def now(self) -> datetime:
        """
        Current application time (aware, UTC-based), never decreasing.

        Advancing is anchored to the monotonic clock, so a system-clock
        step cannot drag the schedule clock. The final clamp guarantees
        monotonicity even when the applied offset decreases.
        """
        elapsed = self._mono() - self._mono_anchor
        if elapsed < 0:
            elapsed = 0.0
        candidate = (
            self._wall_anchor
            + timedelta(seconds=elapsed)
            + self._applied_offset
        )
        if self._last_now is not None and candidate < self._last_now:
            return self._last_now
        self._last_now = candidate
        return candidate

    def now_tehran(self) -> datetime:
        """Current application time, expressed in Tehran."""
        return self.now().astimezone(TEHRAN_TIMEZONE)

    def status(self) -> ClockStatus:
        """A snapshot the UI can render without recomputing anything."""
        return ClockStatus(
            source=self._source,
            applied_offset=self._applied_offset,
            uncertainty=self._uncertainty,
            market_time=self._market_time,
            notice=self._notice,
            precision_note=(
                MARKET_PRECISION_NOTE
                if self._source is ClockSource.MARKET
                else "system clock"
            ),
            last_successful_sync=self._last_successful_sync,
            last_sync_attempt=self._last_sync_attempt,
            last_sync_ok=self._last_sync_ok,
            sync_age_seconds=self._sync_age_seconds(),
        )

    # UI-7 Task 2 — sync freshness tracking
    # ------------------------------------
    @property
    def last_successful_sync(self) -> Optional[datetime]:
        """UTC time of the last successful market clock sync, or None."""
        return self._last_successful_sync

    @property
    def last_sync_attempt(self) -> Optional[datetime]:
        """UTC time of the last sync attempt (success or failure), or None."""
        return self._last_sync_attempt

    @property
    def last_sync_ok(self) -> bool:
        """True if the last sync attempt succeeded."""
        return self._last_sync_ok

    def _sync_age_seconds(self) -> Optional[float]:
        """Age of the last successful sync on the MONOTONIC clock."""
        if self._last_successful_sync_mono is None:
            return None
        age = self._mono() - self._last_successful_sync_mono
        if age < 0.0:
            # A monotonic clock never goes backwards; clamp anyway so a
            # swapped monotonic source can never report a negative age.
            age = 0.0
        return age

    def sync_age_seconds(self) -> Optional[float]:
        """
        Age of the last successful sync in seconds, or ``None`` if the
        service has never completed one.

        Measured with the monotonic clock, so adjusting the system clock
        cannot make an old reading look fresh or a fresh one look old.
        """
        return self._sync_age_seconds()

    def is_sync_fresh(
        self, max_age_seconds: float = SCHEDULE_SYNC_MAX_AGE_SECONDS
    ) -> bool:
        """
        Is the last successful sync fresh enough for a schedule Apply?

        ``False`` when no sync has ever completed successfully, or when
        the monotonic age exceeds ``max_age_seconds``. The wall clock is
        deliberately not consulted.
        """
        age = self._sync_age_seconds()
        if age is None:
            return False
        return age <= max_age_seconds

    # -- observations -----------------------------------------------------

    def _step_toward(self, target: timedelta) -> timedelta:
        """Move the applied offset toward ``target`` by at most one step."""
        remaining = target - self._applied_offset
        if abs(remaining) <= self._max_step:
            return target
        if remaining > timedelta(0):
            return self._applied_offset + self._max_step
        return self._applied_offset - self._max_step

    def observe(self, sample: MarketClockSample) -> ClockStatus:
        """
        Accept a validated market reading and switch to the market source.

        The correction is applied gradually: this call moves the applied
        offset by at most one step, never by the whole measured amount.
        """
        if not isinstance(sample, MarketClockSample):
            raise MarketClockInvalidResponse(
                f"observe() requires a MarketClockSample, got "
                f"{type(sample).__name__}"
            )

        self._source = ClockSource.MARKET
        self._market_time = sample.market_time
        self._uncertainty = sample.uncertainty
        self._last_error = None
        self._applied_offset = self._step_toward(sample.offset)
        self._notice = (
            f"{CLOCK_NOTICE_MARKET} "
            f"(offset {self._applied_offset.total_seconds():+.2f}s, "
            f"uncertainty +/-{sample.uncertainty_seconds:.2f}s, "
            f"{MARKET_PRECISION_NOTE})"
        )
        # UI-7 Task 2 — record successful sync time (wall + monotonic)
        self._last_successful_sync = self._now_utc()
        self._last_successful_sync_mono = self._mono()
        self._last_sync_attempt = self._last_successful_sync
        self._last_sync_attempt_mono = self._last_successful_sync_mono
        self._last_sync_ok = True
        return self.status()

    def note_unavailable(self, reason: str) -> ClockStatus:
        """
        State explicitly that no usable market clock reading is available.

        Falls back to the system clock with a soft notice, exactly like
        :meth:`mark_market_unavailable`, but records NO sync attempt: it is
        for the UI to say "there is nothing fresh to schedule against"
        without pretending a request had been made.
        """
        self._source = ClockSource.SYSTEM
        self._uncertainty = None
        self._last_error = str(reason)
        self._applied_offset = self._step_toward(timedelta(0))
        self._notice = (
            f"{CLOCK_NOTICE_SYSTEM} - market time unavailable "
            f"({reason}); using system clock"
        )
        return self.status()

    def mark_market_unavailable(self, reason: str) -> ClockStatus:
        """
        Fall back to the system clock after a refusal, with a soft notice.

        The applied offset walks back toward zero by at most one step, so
        the transition is gradual; because the returned time is clamped,
        the application clock holds rather than rewinding.
        """
        self.note_unavailable(reason)
        # UI-7 Task 2 — record failed sync attempt (wall + monotonic)
        self._last_sync_attempt = self._now_utc()
        self._last_sync_attempt_mono = self._mono()
        self._last_sync_ok = False
        return self.status()

    def apply_sample_or_fallback(
        self,
        sample: Optional[MarketClockSample],
        error: Optional[BaseException] = None,
    ) -> ClockStatus:
        """Route a successful reading or a refusal to the right branch."""
        if sample is not None and error is None:
            return self.observe(sample)
        reason = str(error) if error is not None else "no reading"
        return self.mark_market_unavailable(reason)

    def refresh(self) -> ClockStatus:
        """
        Perform one real fetch and route the outcome.

        Never raises: any transport, format, or freshness problem becomes
        a system-clock fallback with a user-visible reason.
        """
        try:
            sample = fetch_market_clock(
                transport=self._transport,
                now_utc=self._now_utc,
            )
        except MarketClockError as exc:
            return self.mark_market_unavailable(str(exc))
        except Exception as exc:  # noqa: BLE001 — never crash the UI
            return self.mark_market_unavailable(
                f"unexpected market clock failure: {exc}"
            )
        return self.observe(sample)


# ---------------------------------------------------------------------------
# Background fetch (never block the GUI thread on the network)
# ---------------------------------------------------------------------------


class MarketClockWorker(QThread):
    """
    Runs one market-clock fetch off the GUI thread and reports it.

    ``now_utc`` is passed in rather than read here so the request
    timestamps come from the *same* clock the owning service uses. A
    worker that used its own clock could disagree with the service about
    how old a body is.
    """

    clock_succeeded = Signal(object)
    clock_failed = Signal(str)

    def __init__(
        self,
        transport: Optional[Callable[..., TransportResult]] = None,
        now_utc: Optional[Callable[[], datetime]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._transport = transport
        self._now_utc = now_utc

    def run(self) -> None:
        try:
            sample = fetch_market_clock(
                transport=self._transport,
                now_utc=self._now_utc,
            )
        except MarketClockError as exc:
            self.clock_failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — failure must not crash UI
            self.clock_failed.emit(str(exc))
            return
        self.clock_succeeded.emit(sample)


# ---------------------------------------------------------------------------
# Formatting helpers (UI-7 Task 1 summary text)
# ---------------------------------------------------------------------------


def format_offset(value: timedelta) -> str:
    return f"{value.total_seconds():+.2f}s"


def format_uncertainty(value: Optional[timedelta]) -> str:
    if value is None:
        return "unknown (system clock only)"
    return f"+/-{value.total_seconds():.2f}s"


def describe_clock(status: ClockStatus) -> str:
    """
    One honest, non-technical line describing the active clock source.

    The sync age shown here comes from ``status.sync_age_seconds``, which
    the service measured on the monotonic clock — this function never reads
    the wall clock itself, so a system-clock step cannot rewrite history.
    """
    parts = [
        f"Source: {status.source.value}",
        status.notice,
        f"Applied offset: {format_offset(status.applied_offset)}",
        f"Uncertainty: {format_uncertainty(status.uncertainty)}",
        f"Precision: {status.precision_note}",
    ]
    # UI-7 Task 2 — add sync info if available
    if status.last_successful_sync is not None:
        age = status.sync_age_seconds
        parts.append(
            f"Last sync: {age:.0f}s ago" if age is not None
            else "Last sync: recorded"
        )
    elif status.last_sync_attempt is not None:
        parts.append("Last sync: failed")
    else:
        parts.append("Last sync: none yet")
    return " | ".join(parts)


__all__ = [
    "TEHRAN_TIMEZONE",
    "UTC",
    "SCHEDULE_SYNC_MAX_AGE_SECONDS",
    "TSETMC_TIME_URL",
    "MARKET_TIME_FORMAT",
    "MARKET_TIME_PATTERN",
    "MARKET_TIME_TIMEOUT_SECONDS",
    "MARKET_TIME_QUANTUM_SECONDS",
    "MARKET_TIME_QUANTUM_AMBIGUITY_SECONDS",
    "MARKET_TIME_MAX_CDN_AGE_SECONDS",
    "MARKET_TIME_MAX_BODY_AGE_SECONDS",
    "MARKET_TIME_MAX_RECEIVE_SKEW_SECONDS",
    "MARKET_TIME_MAX_ABS_OFFSET_SECONDS",
    "MARKET_TIME_REQUIRED_HEADERS",
    "MARKET_TIME_ALLOWED_MEDIA_TYPES",
    "MARKET_TIME_ALLOWED_CHARSETS",
    "MAX_CORRECTION_STEP_SECONDS",
    "MARKET_PRECISION_NOTE",
    "CLOCK_NOTICE_SYSTEM",
    "CLOCK_NOTICE_MARKET",
    "MarketClockError",
    "MarketClockTimeout",
    "MarketClockInvalidResponse",
    "MarketClockStale",
    "TransportResult",
    "default_transport",
    "parse_market_time",
    "parse_http_date_utc",
    "validate_response",
    "CachePolicy",
    "evaluate_cache_policy",
    "MarketClockSample",
    "build_sample",
    "fetch_market_clock",
    "ClockSource",
    "ClockStatus",
    "MarketClockService",
    "MarketClockWorker",
    "format_offset",
    "format_uncertainty",
    "describe_clock",
]