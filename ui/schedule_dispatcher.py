"""
ui/schedule_dispatcher.py — UI-7 Task 3: periodic, concurrent dispatch.

Once a schedule is applied, the frozen orders are handed to the EXISTING
send path again and again, every ``dispatch_interval_ms`` milliseconds,
until the window closes. At every turn the send to each destination
broker STARTS concurrently: one broker's slow answer must never delay the
start of another broker's send.

    UI-7 Task 2 (locked time base) + Block 3 window [start, end]
        |
        v
    PeriodicScheduleDispatcher            <-- this module
        |  generates the ms-cadence due times on the MONOTONIC clock
        |  groups the FROZEN orders by destination broker
        |  starts one send per broker group, all at once
        v
    runner_factory() -> one INDEPENDENT runner per group and per turn
        |
        v
    TestRunner.run(...)                   (EXISTING UI-5 send path)
        -> build_execution_plan_from_selected_entries
        -> DispatchIntegration.dispatch() / DispatchCore.dispatch_with_latency()
        -> SafetyGate -> BrokerDispatchRequest -> OrderEngine   (EXISTING)

This module never builds a plan, never resolves a broker, never calls a
broker API, and never constructs an envelope. It only decides WHEN a turn
starts, WHO it is sent to, and HOW MANY turns may run at once. All
validation, the SafetyGate and the live-permission bridge stay exactly
where they already are, inside the existing send path.

The send path is the EXISTING one, and it is Dry Run
---------------------------------------------------
The only send path this page owns is ``ui.test_runner.TestRunner``, which
routes through ``DispatchIntegration`` / ``DispatchCore``. That Core builds
every envelope with ``live=False`` unless a ``SafetyGate`` is explicitly
attached, and the UI never attaches one, so EVERY send from this page is
Dry Run by construction. This module does not and cannot turn it into a
live send: it has no ``live`` switch at all. Anything else would require
wiring a ``SafetyGate`` into the UI, which is a Block 10 decision that is
out of this task's scope. See the module-level note in the page.

Execution interval is the REAL spacing, in MILLISECONDS
--------------------------------------------------------
``parse_execution_interval_ms`` accepts a whole positive number of
milliseconds (for example ``50``), and that value IS the distance between
consecutive due times — not a lateness tolerance, not a margin. With
``50`` the due times are 50 ms apart on the monotonic clock. The unit is
explicit in the parser, the label and the placeholder, and the value is
used with ``timedelta(milliseconds=...)`` — it is NEVER read as seconds.
Zero, a negative number, a decimal and any malformed text are rejected
fail-closed and are never clamped or repaired.

Due times are generated here, not copied from Block 3
------------------------------------------------------
Block 3 still owns the WINDOW: its valid ``DispatchTiming`` start and end
bound the run, and its scheduler/trigger contracts are used unchanged.
But Block 3's own moments are whole SECONDS, so they cannot be the list
of dispatch repetitions. This module therefore generates the repetition
due times itself, at the requested ms spacing, projected onto the
MONOTONIC clock from UI-7 Task 2's locked base — so a system-clock step
can neither move nor skip a turn, and a slow broker answer can never shift
the later due times. No Block 3 component is copied, re-implemented or
re-designed.

Honest timing, kept separate from Block 8
-----------------------------------------
Each turn records the moment it was DUE and the moment its sends were
actually HANDED to the send path, so the in-programme start delay is
measurable on its own:

    TurnRecord.due_mono -> TurnRecord.started_mono -> start_delay_ms

The hand-off boundary is exact and narrow: for EACH broker group the
monotonic clock is read IMMEDIATELY BEFORE ``runner.run(...)`` is called.
That instant is the boundary "the programme gives the send over to the
EXISTING send path". It is deliberately NOT:

  * the ``ThreadPoolExecutor.submit`` moment — submitting only prepares a
    thread, it has not handed anything to the send path yet;
  * the moment the group started being scheduled for;
  * the moment the broker ANSWERED. Waiting for a broker response is the
    broker's latency, not this programme's start delay, so it can never
    inflate the recorded start.

Because the groups of one turn start CONCURRENTLY, each group keeps its
own time on its own ``BrokerTurnResult.started_mono``;
``TurnRecord.started_mono`` is explicitly the FIRST REAL group hand-off of
that turn (the earliest of them), never a submit time and never a thread
preparation time.

These are Task 3's own scheduling measurements. They are never added into,
merged with, or substituted for the Block 8 ``DispatchLatencyReport``
(dispatch total, the four internal stages, or the broker/API round trips).
Broker and network latency stay a separate concern that the fan-out only
*starts*, never measures.

Turn identity is NOT a trace id
-------------------------------
``TurnRecord.turn_id`` is this module's own scheduling label. The dispatch
TRACE id is read ONLY from the real Core result
(``DispatchResult.trace_id``) and is reported per broker in
``BrokerTurnResult.trace_id``. A turn id is never presented as, or
substituted for, a Core trace id.

No catch-up or burst; outstanding work is measured
-------------------------------------------------
  * A window start that is ALREADY PAST does not create a backlog. The
    first turn is anchored at the first EXECUTION OPPORTUNITY (the
    monotonic now at freeze time) instead of the missed window start, so
    the very first send begins at once and no due time is walked, counted
    or recorded on the way. A window start that is still in the FUTURE
    keeps its exact scheduled instant, never shifted.
  * Missed due times are SKIPPED and recorded as ``SKIPPED_MISSED``: they
    are never replayed and never fired back to back.
  * A pending broker response NEVER blocks a later cadence turn. There is
    no response-based rejection: every due turn is started. Outstanding
    turns and the peak are tracked, with a warning when the backlog grows
    past the observation threshold; slow responses can still accumulate.
  * ``stop()`` prevents any NEW turn from starting. Runs already handed to
    the send path are never force-cancelled; their outcome is collected
    through the normal result path.

Thread-safety of the send path
------------------------------
A single shared ``TestRunner`` / ``DispatchIntegration`` instance is NOT
thread-safe: it carries per-run mutable state (``last_result``,
``last_execution_id``, ``last_order_results``, ``last_report``) that
concurrent turns would overwrite and cross-contaminate. Every group of
every turn therefore gets its OWN runner instance from ``runner_factory``,
so no two concurrent sends ever share runner state. The factory — not
this module — decides what that instance wraps.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ui import strings as STRINGS


# ---------------------------------------------------------------------------
# Contract constants (named, documented, never silently changed)
# ---------------------------------------------------------------------------


#: Maximum number of turns allowed to be in flight at the same time.
#: Two is enough to overlap a slow broker with a fast one while still
#: bounding how many requests the application can have outstanding.
OUTSTANDING_TURN_WARNING_THRESHOLD = 2

_LOGGER = logging.getLogger(__name__)


#: The execution interval is a whole number of MILLISECONDS. One format,
#: one meaning, and never a second: "50" here is 50 ms, never 50 seconds.
EXECUTION_INTERVAL_PATTERN = re.compile(r"^[0-9]+$")

EXECUTION_INTERVAL_LABEL = STRINGS.LABEL_DISPATCH_INTERVAL_MS
EXECUTION_INTERVAL_PLACEHOLDER = STRINGS.PLACEHOLDER_DISPATCH_INTERVAL


class DispatchIntervalError(ValueError):
    """Raised when the execution interval in ms is invalid (fail-closed)."""


class DispatchTargetSetError(ValueError):
    """
    Raised when the send set cannot be dispatched to at all.

    The WHOLE set is rejected rather than trimmed: a schedule never sends
    a silent partial set, and it never resolves, infers or fabricates a
    destination that the user did not register. The message is the reason
    shown to the user, so it names the offending order, account or broker.
    """


def parse_execution_interval_ms(value: object) -> float:
    """
    Parse the execution interval as a positive whole number of ms.

    ``50`` means 50 milliseconds — the real spacing between consecutive
    dispatch due times. It is never interpreted as seconds.

    Raises:
        DispatchIntervalError: the value is missing, malformed, not a whole
            number, or not strictly positive (zero and negatives are
            rejected rather than clamped, because a zero gap would make the
            dispatcher degenerate into an unbounded burst).
    """
    if value is None:
        raise DispatchIntervalError(f"{EXECUTION_INTERVAL_LABEL} is required")
    if not isinstance(value, str):
        raise DispatchIntervalError(
            f"{EXECUTION_INTERVAL_LABEL} must be text"
        )
    text = value.strip()
    if not text:
        raise DispatchIntervalError(f"{EXECUTION_INTERVAL_LABEL} is required")
    # A decimal ("1.5"), a sign ("-5", "+5") and any unit suffix ("50ms")
    # are malformed — the field is whole milliseconds and nothing else.
    if not EXECUTION_INTERVAL_PATTERN.match(text):
        raise DispatchIntervalError(
            f"{EXECUTION_INTERVAL_LABEL} must be a whole number of "
            f"milliseconds (e.g. 50), got {value!r}"
        )
    milliseconds = int(text)
    if milliseconds <= 0:
        raise DispatchIntervalError(
            f"{EXECUTION_INTERVAL_LABEL} must be greater than zero "
            f"milliseconds, got {milliseconds}"
        )
    return float(milliseconds)


def execution_interval_timedelta(value: object) -> timedelta:
    """The parsed ms interval as a ``timedelta`` (never as seconds)."""
    return timedelta(milliseconds=parse_execution_interval_ms(value))


# ---------------------------------------------------------------------------
# Frozen dispatch set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchTarget:
    """
    ONE frozen destination: the exact queue entry plus where it must go.

    Frozen at Apply time and never re-resolved, so every turn sends the
    very same order to the very same broker. The ``Account`` object is the
    one the UI already resolved; it is passed to the existing send path
    verbatim and is never rebuilt, inferred or fabricated here.
    """

    entry: object
    account_id: str
    broker_name: str
    account: object


@dataclass(frozen=True)
class BrokerGroup:
    """All frozen targets for one destination broker (and its account)."""

    account_id: str
    broker_name: str
    account: object
    targets: Tuple[DispatchTarget, ...]


def group_targets_by_broker(
    targets: Sequence[DispatchTarget],
) -> List[BrokerGroup]:
    """
    Group the frozen targets by their destination broker.

    Grouping is by the frozen ``(account_id, broker_name)`` binding only —
    never inferred from a symbol, an instrument or a position. Broker order
    is the first-seen order, so the grouping is deterministic and testable.
    """
    groups: Dict[Tuple[str, str], List[DispatchTarget]] = {}
    for target in targets:
        key = (target.account_id, target.broker_name)
        groups.setdefault(key, []).append(target)
    return [
        BrokerGroup(
            account_id=account_id,
            broker_name=broker_name,
            account=targets_for_group[0].account,
            targets=tuple(targets_for_group),
        )
        for (account_id, broker_name), targets_for_group in groups.items()
    ]


# ---------------------------------------------------------------------------
# Turn records (Task 3's own scheduling measurement)
# ---------------------------------------------------------------------------


class TurnStatus(Enum):
    """Outcome of ONE dispatch turn."""

    DISPATCHED = "DISPATCHED"
    #: The due time was already past when the turn was considered; it is
    #: recorded and dropped. Never replayed, never burst.
    SKIPPED_MISSED = "SKIPPED_MISSED"
    #: Stop was requested before this turn could start.
    SKIPPED_STOPPED = "SKIPPED_STOPPED"


#: The statuses that mean "nothing was sent for this turn".
SKIPPED_STATUSES = (
    TurnStatus.SKIPPED_MISSED,
    TurnStatus.SKIPPED_STOPPED,
)


@dataclass(frozen=True)
class BrokerTurnResult:
    """The existing send path's own outcome for ONE broker of ONE turn."""

    broker_name: str
    account_id: str
    #: The EXISTING execution id of that send path run (never invented).
    execution_id: Optional[str]
    #: The EXISTING Core dispatch trace id, read ONLY from the real
    #: ``DispatchResult.trace_id``. Never a turn id.
    trace_id: Optional[str]
    success: bool
    message: str
    #: THIS group's own hand-off moment: the monotonic reading taken
    #: IMMEDIATELY BEFORE ``runner.run(...)`` was called for it. Groups of
    #: one turn start concurrently, so each one keeps its OWN start time;
    #: they are never collapsed into a single shared one.
    #: ``None`` only when this group never reached the send path at all.
    started_mono: Optional[float] = None


@dataclass(frozen=True)
class TurnRecord:
    """
    One dispatch turn, with its own independent scheduling identity.

    ``turn_id`` is this module's scheduling label — NOT a trace id. The
    real Core trace id lives on each ``BrokerTurnResult.trace_id``.
    """

    turn_id: str
    #: 0-based position of this turn in the ms cadence.
    turn_index: int
    #: Monotonic instant this turn was DUE.
    due_mono: float
    #: The wall-clock moment this due time corresponds to, derived from the
    #: locked base (display only; never used to decide when to send).
    due_moment: Optional[datetime]
    #: Monotonic instant of the FIRST REAL hand-off of this turn — the
    #: earliest of this turn's per-group ``BrokerTurnResult.started_mono``,
    #: each of which is read immediately before its own ``runner.run(...)``.
    #: It is deliberately NOT the ``submit`` moment and NOT the moment the
    #: turn finished. Every group's own time stays on its own result.
    started_mono: Optional[float]
    status: TurnStatus
    results: Tuple[BrokerTurnResult, ...] = ()
    error: Optional[str] = None

    @property
    def dispatched(self) -> bool:
        return self.status is TurnStatus.DISPATCHED

    @property
    def skipped(self) -> bool:
        return self.status in SKIPPED_STATUSES

    @property
    def start_delay_ms(self) -> Optional[float]:
        """
        In-programme start delay: due time -> actual send start.

        This is Task 3's own scheduling measurement and is deliberately
        NOT part of, and never added into, any Block 8 report.
        """
        if self.started_mono is None:
            return None
        return (self.started_mono - self.due_mono) * 1000.0

    @property
    def trace_ids(self) -> Tuple[str, ...]:
        """The real Core trace ids of this turn, one per broker sent."""
        return tuple(
            r.trace_id for r in self.results if r.trace_id is not None
        )

    @property
    def brokers(self) -> Tuple[str, ...]:
        return tuple(result.broker_name for result in self.results)


# ---------------------------------------------------------------------------
# The dispatcher
# ---------------------------------------------------------------------------


class PeriodicScheduleDispatcher:
    """
    Repeats the frozen send set on an ms cadence, fanning out per broker.

    ``runner_factory`` is called once per broker group per turn and must
    return a NEW, independent runner instance. That is what keeps the
    existing send path thread-safe: the runner carries per-run mutable
    state, so two concurrent sends must never share one. In production the
    factory builds a ``ui.test_runner.TestRunner`` over the existing Core
    chain; the dispatcher never touches the Core itself.
    """

    def __init__(
        self,
        runner_factory: Callable[[], object],
        mono_clock: Optional[Callable[[], float]] = None,
        on_turn: Optional[Callable[[TurnRecord], None]] = None,
    ) -> None:
        if not callable(runner_factory):
            raise TypeError("runner_factory must be callable")
        if mono_clock is not None and not callable(mono_clock):
            raise TypeError("mono_clock must be callable or None")
        self._runner_factory = runner_factory
        # The monotonic clock is never optional: a wall clock would let a
        # system-clock step move or skip a due time. Tests may inject one.
        self._mono: Callable[[], float] = (
            time.monotonic if mono_clock is None else mono_clock
        )
        self._on_turn = on_turn

        self._groups: Tuple[BrokerGroup, ...] = ()
        self._interval_ms: Optional[float] = None
        self._locked_base: Optional[datetime] = None
        self._locked_mono: Optional[float] = None
        #: (start, end) wall moments from the EXISTING Block 3 window.
        self._window: Optional[Tuple[datetime, datetime]] = None
        #: Monotonic instant of the first due time.
        self._first_due_mono: Optional[float] = None
        #: Did Apply happen AFTER the window start, so the first turn was
        #: anchored at the first execution opportunity instead of the
        #: already-past window start? Diagnostic only - the ladder itself
        #: carries the real answer.
        self._started_late = False

        self._turns: List[TurnRecord] = []
        self._in_flight = 0
        self._peak_in_flight = 0
        self._backlog_warning_active = False
        self._stopped = False
        self._next_turn_index = 0
        self._lock = threading.RLock()

    # -- configuration ----------------------------------------------------

    def freeze(
        self,
        targets: Sequence[DispatchTarget],
        interval_ms: float,
        locked_base: datetime,
        locked_mono: float,
        window: Optional[Tuple[datetime, datetime]] = None,
    ) -> None:
        """
        Fix the send set, its destinations and the cadence for this run.

        Called once at Apply. Everything the turns will send is decided
        here, so no later turn can pick up a different order or a different
        destination.

        ``window`` is the EXISTING Block 3 window (its start/end datetimes);
        it bounds the run and is never re-generated here.
        """
        if self._interval_ms is not None:
            raise ValueError("dispatcher is already frozen")
        if not isinstance(interval_ms, (int, float)) or interval_ms <= 0:
            raise ValueError("interval_ms must be a positive number")
        self._groups = tuple(group_targets_by_broker(targets))
        self._interval_ms = float(interval_ms)
        self._locked_base = locked_base
        self._locked_mono = float(locked_mono)
        self._window = window
        # The first due time is the window start projected onto the
        # monotonic clock; every later one is exactly one interval after
        # it. The Block 3 SECOND-resolution moments are not used as the
        # repetition list.
        if window is not None:
            planned_first_mono = self.project_mono(window[0])
        else:
            planned_first_mono = self._locked_mono
        # If the WINDOW START is ALREADY PAST, anchoring the ladder on it
        # would make every due time between it and now a MISSED one, which
        # is exactly the walk-through-the-past / backlog behaviour this
        # module must not have. Instead the first turn is anchored at the
        # FIRST EXECUTION OPPORTUNITY - the monotonic now - so it is due
        # immediately, the missed due times are never walked or recorded,
        # and every later turn continues at the user's fixed interval from
        # that anchor on the monotonic clock. The window end is unchanged
        # and still the ceiling.
        #
        # A window start that is still in the FUTURE is NEVER shifted: it
        # stays at exactly its scheduled instant.
        #
        # Without a window there is no planned start that could be past, so
        # the anchor stays exactly on the locked time base and nothing is
        # re-anchored here.
        self._started_late = False
        if window is not None:
            now_mono = self._mono()
            if planned_first_mono < now_mono:
                self._started_late = True
                self._first_due_mono = now_mono
            else:
                self._first_due_mono = planned_first_mono
        else:
            self._first_due_mono = planned_first_mono

    def project_mono(self, moment: datetime) -> float:
        """
        Project a wall moment onto the monotonic clock.

        The reference is UI-7 Task 2's LOCKED time base, so a system-clock
        step can neither move nor skip a due time.
        """
        if self._locked_base is None or self._locked_mono is None:
            raise ValueError("dispatcher is not frozen")
        offset = (moment - self._locked_base).total_seconds()
        return self._locked_mono + offset

    def project_wall(self, mono: float) -> datetime:
        """The wall moment a monotonic instant corresponds to (display)."""
        if self._locked_base is None or self._locked_mono is None:
            raise ValueError("dispatcher is not frozen")
        return self._locked_base + timedelta(seconds=mono - self._locked_mono)

    @property
    def interval_ms(self) -> Optional[float]:
        return self._interval_ms

    @property
    def frozen_groups(self) -> Tuple[BrokerGroup, ...]:
        return self._groups

    @property
    def turns(self) -> Tuple[TurnRecord, ...]:
        return tuple(self._turns)

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight

    @property
    def peak_in_flight(self) -> int:
        """Highest number of unanswered dispatch turns observed this run."""
        with self._lock:
            return self._peak_in_flight

    @property
    def stopped(self) -> bool:
        return self._stopped

    def mono_now(self) -> float:
        """The dispatcher's monotonic clock (exposed for the worker loop)."""
        return self._mono()

    def index_in_window(self, index: int) -> bool:
        """
        Is the ``index``-th due time inside the EXISTING Block 3 window?

        Used by the worker to stop cleanly at the window end.
        """
        if self._window is None:
            return True
        start_mono = self.project_mono(self._window[0])
        end_mono = self.project_mono(self._window[1])
        due = self.due_mono_for_turn(index)
        return start_mono <= due <= end_mono

    # -- the ms cadence ---------------------------------------------------

    def due_mono_for_turn(self, index: int) -> float:
        """
        The monotonic due time of the ``index``-th turn.

        Exactly ``interval_ms`` after the previous one — this is the REAL
        spacing, not a tolerance.
        """
        if self._interval_ms is None or self._first_due_mono is None:
            raise ValueError("dispatcher is not frozen")
        return self._first_due_mono + (index * self._interval_ms) / 1000.0

    def due_mono_at_or_after(self, now_mono: float) -> Optional[float]:
        """
        The next due time at or after ``now_mono``, or ``None`` when the
        window has already closed.

        The cadence is walked from the fixed first due time, so a late or
        early caller never shifts the schedule: the returned instant is
        always an exact multiple of the interval from that anchor.
        """
        if self._interval_ms is None or self._first_due_mono is None:
            raise ValueError("dispatcher is not frozen")
        if self._window is not None:
            end_mono = self.project_mono(self._window[1])
            if now_mono > end_mono:
                return None
        if now_mono <= self._first_due_mono:
            return self._first_due_mono
        elapsed = now_mono - self._first_due_mono
        steps = int(elapsed // (self._interval_ms / 1000.0))
        return self.due_mono_for_turn(steps)

    # -- the loop ---------------------------------------------------------

    def service_due_turn(
        self,
        now_mono: float,
        turn_index: int,
    ) -> Optional[TurnRecord]:
        """
        Service ONE due time of the cadence (given its index).

        Returns ``None`` when that due time has not arrived yet, so the
        caller can wait. A turn NEVER fires early. Each index is serviced
        at most once by contract: the caller owns the cursor and only
        advances it past a turn this method actually serviced.
        """
        if self._interval_ms is None:
            raise ValueError("dispatcher is not frozen")

        due_mono = self.due_mono_for_turn(turn_index)

        # Not due yet: nothing is sent and nothing is recorded.
        if now_mono < due_mono:
            return None

        if self._window is not None:
            start_mono = self.project_mono(self._window[0])
            end_mono = self.project_mono(self._window[1])
            # Outside the Block 3 window: nothing is sent, ever.
            if due_mono < start_mono or due_mono > end_mono:
                return None

        moment = self.project_wall(due_mono)

        if self._stopped:
            return self._record(
                turn_index, due_mono, moment, TurnStatus.SKIPPED_STOPPED
            )

        # A due time already past by more than one whole interval is
        # MISSED: skipped, never caught up and never burst.
        #
        # The one exception is the anchored FIRST turn of a late start: its
        # due time IS "the first execution opportunity" by construction, so
        # being a few ms past it is the intended behaviour and not a missed
        # due time. Skipping it would defeat the immediate start.
        tolerance = self._interval_ms / 1000.0
        anchored_first_turn = self._started_late and turn_index == 0
        if not anchored_first_turn and now_mono > due_mono + tolerance:
            return self._record(
                turn_index, due_mono, moment, TurnStatus.SKIPPED_MISSED
            )

        with self._lock:
            # Outstanding responses are measured, never used to reject a
            # due turn. The selected cadence takes priority; a slow broker
            # cannot suppress the next scheduled send.
            index = self._next_turn_index
            self._next_turn_index += 1
            self._in_flight += 1
            self._peak_in_flight = max(self._peak_in_flight, self._in_flight)
            if (
                self._in_flight > OUTSTANDING_TURN_WARNING_THRESHOLD
                and not self._backlog_warning_active
            ):
                _LOGGER.warning(
                    "UI-7 dispatch backlog is %d unanswered turns; "
                    "scheduled sends continue without response-based drops",
                    self._in_flight,
                )
                self._backlog_warning_active = True
            turn_id = f"ui7-turn-{index}"
            # One barrier PER TURN, created here and passed down as an
            # argument. It must never live on ``self``: with two turns in
            # flight, a shared field would be overwritten by the second
            # turn and the first turn's brokers would wait on — or trip —
            # the wrong barrier.
            barrier = (
                threading.Barrier(len(self._groups))
                if len(self._groups) > 1
                else None
            )

        # NOTE: no start time is taken here. The hand-off boundary is
        # INSIDE ``_send_to_group``, immediately before ``runner.run``;
        # recording it before ``submit`` would measure thread preparation,
        # which is not the moment the send path was given the work.
        worker = ThreadPoolExecutor(max_workers=max(1, len(self._groups)))
        try:
            futures = [
                worker.submit(self._send_to_group, group, barrier)
                for group in self._groups
            ]
            results: List[BrokerTurnResult] = []
            error: Optional[str] = None
            try:
                for future in futures:
                    results.append(future.result())
            except Exception as exc:  # fail-closed, never crash the caller
                error = f"{type(exc).__name__}: {exc}"
        finally:
            worker.shutdown(wait=True)
            self._release_slot()

        # The turn's own start time is the FIRST REAL hand-off of its
        # groups (each group carries its own on its result). It is never
        # the submit time and never the moment the responses came back.
        handed_off = [
            r.started_mono for r in results if r.started_mono is not None
        ]
        return self._record(
            turn_index,
            due_mono,
            moment,
            TurnStatus.DISPATCHED,
            started_mono=min(handed_off) if handed_off else None,
            results=tuple(results),
            error=error,
            sequence_id=index,
            turn_id=turn_id,
        )

    def _send_to_group(
        self,
        group: BrokerGroup,
        barrier: Optional[threading.Barrier] = None,
    ) -> BrokerTurnResult:
        """
        Hand ONE broker group to its OWN independent send-path runner.

        This method's OWN ``barrier`` argument is crossed FIRST, before the
        send is issued, so every group of the turn has entered this method
        before any of them starts waiting on a broker. A failing group is
        caught here and returned as that group's own failed result — it can
        never abort the other groups or serialize them behind itself.
        """
        if barrier is not None:
            try:
                barrier.wait(timeout=30)
            except threading.BrokenBarrierError:  # pragma: no cover
                pass
        # ``None`` until the hand-off actually happens; stays ``None`` if
        # this group fails before reaching the send path at all.
        started_mono: Optional[float] = None
        try:
            # A NEW runner per group per turn: the existing runner carries
            # per-run mutable state, so sharing one across concurrent
            # groups/turns would cross-contaminate their results.
            runner = self._runner_factory()
            entries = [target.entry for target in group.targets]
            # THE hand-off boundary. Read the monotonic clock immediately
            # before the send is given to the EXISTING send path, so this
            # is the real moment of hand-off and not the submit time, the
            # thread preparation, or the end of the broker's answer.
            started_mono = self._mono()
            _plan, execution_id, result = runner.run(
                entries, account=group.account
            )
            # The trace id is read ONLY from the real Core result.
            trace = getattr(result, "trace_id", None)
            success = bool(getattr(result, "success", False))
            message = str(getattr(result, "message", "") or "")
            return BrokerTurnResult(
                broker_name=group.broker_name,
                account_id=group.account_id,
                execution_id=execution_id,
                trace_id=trace,
                success=success,
                message=message,
                started_mono=started_mono,
            )
        except Exception as exc:  # fail-closed for THIS broker only
            return BrokerTurnResult(
                broker_name=group.broker_name,
                account_id=group.account_id,
                execution_id=None,
                trace_id=None,
                success=False,
                message=f"{type(exc).__name__}: {exc}",
                started_mono=started_mono,
            )

    def _release_slot(self) -> None:
        with self._lock:
            self._in_flight -= 1
            if self._in_flight <= OUTSTANDING_TURN_WARNING_THRESHOLD:
                self._backlog_warning_active = False

    def _record(
        self,
        turn_index: int,
        due_mono: float,
        moment: datetime,
        status: TurnStatus,
        started_mono: Optional[float] = None,
        results: Sequence[BrokerTurnResult] = (),
        error: Optional[str] = None,
        sequence_id: Optional[int] = None,
        turn_id: Optional[str] = None,
    ) -> TurnRecord:
        with self._lock:
            if sequence_id is None:
                sequence_id = self._next_turn_index
                self._next_turn_index += 1
            record = TurnRecord(
                turn_id=turn_id or f"ui7-turn-{sequence_id}",
                turn_index=turn_index,
                due_mono=due_mono,
                due_moment=moment,
                started_mono=started_mono,
                status=status,
                results=tuple(results),
                error=error,
            )
            self._turns.append(record)
        if self._on_turn is not None:
            self._on_turn(record)
        return record

    # -- stop -------------------------------------------------------------

    def stop(self) -> None:
        """
        Stop starting NEW turns.

        Runs already handed to the send path are never force-cancelled:
        whatever they return is still collected into their own turn record
        through the normal result path.
        """
        self._stopped = True


__all__ = [
    "OUTSTANDING_TURN_WARNING_THRESHOLD",
    "EXECUTION_INTERVAL_PATTERN",
    "EXECUTION_INTERVAL_LABEL",
    "EXECUTION_INTERVAL_PLACEHOLDER",
    "DispatchIntervalError",
    "DispatchTargetSetError",
    "parse_execution_interval_ms",
    "execution_interval_timedelta",
    "DispatchTarget",
    "BrokerGroup",
    "group_targets_by_broker",
    "TurnStatus",
    "SKIPPED_STATUSES",
    "BrokerTurnResult",
    "TurnRecord",
    "PeriodicScheduleDispatcher",
]
