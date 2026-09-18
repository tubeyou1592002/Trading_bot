"""
Block 8 — latency instrumentation.

TWO SEPARATE MEASUREMENT LAYERS, BOTH MONOTONIC (``time.perf_counter_ns``):

    Task 8.2 — internal Dispatch stages (unchanged):

        plan_item             time spent by the existing ``_plan_item(...)``
        plan_account          time spent by the existing ``_plan_account(...)``
        instrument_resolution time spent by the existing ``_resolve_instrument(...)``
        order_engine_path     time spent by the existing ``_execute_single_order(...)``

    Task 8.3 — Broker/API round trips (added by this module):

        Each *existing* broker/provider method call in the order path is
        timed around the call site and recorded per order as a
        ``BrokerApiCallTiming``:

            get_instrument       InstrumentProvider -> Broker instrument read
            get_trading_state    Broker trading-state read
            get_buy_capacity     Broker BUY capacity read
            get_sell_capacity    Broker SELL capacity read
            place_order          Broker order submission call (dry-run today)

ACCURACY STATEMENT (Task 8.3 §5/§6) — READ BEFORE INTERPRETING A REPORT:

    ``broker_api_round_trip`` is the duration of the whole existing broker
    method call. It therefore includes local request preparation, network
    transfer, remote server processing, response transfer, and local response
    handling performed *inside* that method. It is **NOT** pure network
    latency, and this module deliberately does not attempt DNS/TCP/TLS-level
    instrumentation or any other packet-level profiling.

    Application-side time is reported as
    ``OrderLatency.application_side_ns`` = the ``order_engine_path`` stage
    minus the measured broker calls nested inside that stage (never negative).
    The three pure-application stages (``plan_item``, ``plan_account``,
    ``instrument_resolution``) remain available from Task 8.2.

    ``application_before_broker_ns`` / ``application_after_broker_ns`` are the
    two application windows around the existing submission call, computed only
    from boundaries the code already exposes (the ``order_engine_path`` stage
    window and the measured ``place_order`` round trip). No boundary is
    invented; both are ``None`` when no submission call happened.

TWO CLOCKS, NEVER MIXED:

    The stage layer and the broker/API layer each have their own clock, both
    defaulting to ``time.perf_counter_ns()``. In the normal production
    configuration they are the same clock source, so the derived application
    accounting above is computed. A caller may inject a custom stage clock
    (Task 8.2's ``latency_clock``) *without* injecting the same object as the
    broker clock (``broker_clock``); in that case a delta between the two
    layers would be meaningless, so ``application_before_broker_ns``,
    ``application_after_broker_ns`` and ``application_side_ns`` are left
    ``None`` instead of being fabricated. Every broker/API round trip itself
    stays valid either way, because each one is measured entirely on the
    broker clock.

    Consequence for the Task 8.2 stage layer: adding broker/API measurement
    never spends an extra read of the stage clock, so the four stage windows
    and the dispatch window are exactly the ones Task 8.2 defined.

    Task 8.4 — reporting / attribution (read-only, added at the end of this
    module): ``analyze_latency_report()`` converts an existing
    ``DispatchLatencyReport`` into a small factual summary (order counts,
    count/min/median/mean/max distributions, Broker/API totals, per-execution
    attribution). It re-measures nothing, invents nothing, and ranks
    nothing; values that were never measured (e.g. application-side time on
    non-shared clocks) stay ``None``.

Per-order independence (both layers):

    All identity and timing is stored per ``sequence`` inside the collector.
    There is deliberately no shared mutable ``current_account`` /
    ``current_broker`` / ``current_ins_code`` / ``current_sequence`` context.

Opt-in:

    When no collector is supplied the dispatch path performs no timing calls
    at all and ``broker_timing`` is ``None`` at every broker call site, so
    ``DispatchCore.dispatch()`` behavior is unchanged.

Measurement only: this module never optimizes, reorders, caches, retries, or
changes the semantics of any call it observes.
"""

from __future__ import annotations

import statistics
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)

if TYPE_CHECKING:
    from core.order_engine import OrderExecutionResult


# ---------------------------------------------------------------------------
# Internal stage names (Task 8.2 — exactly these four)
# ---------------------------------------------------------------------------

PLAN_ITEM = "plan_item"
PLAN_ACCOUNT = "plan_account"
INSTRUMENT_RESOLUTION = "instrument_resolution"
ORDER_ENGINE_PATH = "order_engine_path"

DISPATCH_STAGES = (
    PLAN_ITEM,
    PLAN_ACCOUNT,
    INSTRUMENT_RESOLUTION,
    ORDER_ENGINE_PATH,
)


# ---------------------------------------------------------------------------
# Broker/API boundary operation names (Task 8.3)
# ---------------------------------------------------------------------------

OP_GET_INSTRUMENT = "get_instrument"
OP_GET_TRADING_STATE = "get_trading_state"
OP_GET_BUY_CAPACITY = "get_buy_capacity"
OP_GET_SELL_CAPACITY = "get_sell_capacity"
OP_PLACE_ORDER = "place_order"

# The single order-submission boundary. Used to split the measured
# ``order_engine_path`` stage into the application windows before/after the
# broker submission call.
SUBMISSION_OPERATION = OP_PLACE_ORDER

# Operations measured inside the dispatch execution path.
DISPATCH_BROKER_OPERATIONS = (
    OP_GET_INSTRUMENT,
    OP_GET_TRADING_STATE,
    OP_GET_BUY_CAPACITY,
    OP_GET_SELL_CAPACITY,
    OP_PLACE_ORDER,
)

# Read-only broker operations that are safe to measure against a REAL broker
# on an already-authenticated connection (Task 8.3 Phase B). The Phase B
# operator tool refuses anything that is not on this list, so it can never be
# pointed at an order/cancel endpoint.
READ_ONLY_OPERATIONS = (
    "get_account",
    OP_GET_INSTRUMENT,
    OP_GET_TRADING_STATE,
    OP_GET_BUY_CAPACITY,
    OP_GET_SELL_CAPACITY,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageTiming:
    """
    Timing for one internal dispatch stage.

    ``start`` / ``end`` / ``duration_ns`` are monotonic
    ``perf_counter_ns()`` ticks (integers), never wall-clock datetimes.
    ``duration_ns`` is derived from ``start`` / ``end`` and can therefore
    never disagree with them.
    """

    stage_name: str
    start: int
    end: int
    duration_ns: int = field(init=False)

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(
                f"stage {self.stage_name!r} end ({self.end}) precedes "
                f"start ({self.start})"
            )
        object.__setattr__(self, "duration_ns", self.end - self.start)


@dataclass(frozen=True)
class BrokerApiCallTiming:
    """
    Round-trip timing for ONE existing Broker/API method call.

    ``operation`` is the name of the existing broker/provider method that was
    invoked. ``ok`` is ``False`` when that call raised (the exception itself
    is always re-raised unchanged).

    See the ACCURACY STATEMENT in this module's docstring: this is a
    broker/API round trip, **not** pure network latency.
    """

    operation: str
    start: int
    end: int
    ok: bool = True
    duration_ns: int = field(init=False)

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(
                f"broker call {self.operation!r} end ({self.end}) precedes "
                f"start ({self.start})"
            )
        object.__setattr__(self, "duration_ns", self.end - self.start)


@dataclass
class OrderLatency:
    """
    Latency record for exactly one order.

    The record carries its own identity — it never borrows identity from
    another order. ``execution_result`` is the same
    ``OrderExecutionResult`` the normal dispatch path produced (a reference,
    not a copy), so the measured path never changes execution semantics.
    """

    sequence: int
    account_id: Optional[str] = None
    broker_name: Optional[str] = None
    ins_code: Optional[str] = None
    stages: List[StageTiming] = field(default_factory=list)
    execution_result: Optional["OrderExecutionResult"] = None

    # Task 8.3 — broker/API boundary measurements for THIS order.
    broker_api_calls: List[BrokerApiCallTiming] = field(default_factory=list)

    # Application windows around the existing submission call (None when the
    # order never reached the submission boundary).
    application_before_broker_ns: Optional[int] = None
    application_after_broker_ns: Optional[int] = None

    # Application-side remainder of the ``order_engine_path`` stage
    # (``None`` when the collector could not derive it on a single clock).
    application_side_ns: Optional[int] = None

    # True when the stage layer and the broker/API layer that filled THIS
    # record were timed on the same clock source (the normal/default
    # configuration). Only then may stage containment be inferred by
    # comparing call timestamps against stage windows; the collector stamps
    # this from its own configuration. Hand-built records default to True
    # (both of their layers are, by construction, on one clock).
    clocks_shared: bool = True

    # -- Task 8.2 stage accessors ------------------------------------------

    def stage(self, stage_name: str) -> Optional[StageTiming]:
        """Return this order's ``StageTiming`` for ``stage_name``, if present."""
        for timing in self.stages:
            if timing.stage_name == stage_name:
                return timing
        return None

    def stage_names(self) -> List[str]:
        """Return this order's recorded stage names, in recording order."""
        return [timing.stage_name for timing in self.stages]

    def duration_ns(self, stage_name: str) -> Optional[int]:
        """Return this order's stage duration in ns, or ``None`` if absent."""
        timing = self.stage(stage_name)
        return None if timing is None else timing.duration_ns

    # -- Task 8.3 broker/API accessors -------------------------------------

    def broker_api_call(
        self, operation: str
    ) -> Optional[BrokerApiCallTiming]:
        """Return the LAST measured call for ``operation``, if any."""
        for timing in reversed(self.broker_api_calls):
            if timing.operation == operation:
                return timing
        return None

    def broker_api_calls_for(
        self, operation: str
    ) -> List[BrokerApiCallTiming]:
        """Return every measured call for ``operation``, in order."""
        return [
            timing
            for timing in self.broker_api_calls
            if timing.operation == operation
        ]

    def broker_api_operations(self) -> List[str]:
        """Return the measured operations in call order."""
        return [timing.operation for timing in self.broker_api_calls]

    @property
    def broker_api_round_trip_ns(self) -> int:
        """
        Total measured Broker/API round trip for this order (all operations).

        This is a broker/API round trip, NOT pure network latency.
        """
        return sum(timing.duration_ns for timing in self.broker_api_calls)

    def broker_api_round_trip_for(self, operation: str) -> int:
        """Total measured round trip for one operation (0 when absent)."""
        return sum(
            timing.duration_ns
            for timing in self.broker_api_calls
            if timing.operation == operation
        )

    def broker_api_totals_by_operation(self) -> Dict[str, int]:
        totals: Dict[str, int] = {}
        for timing in self.broker_api_calls:
            totals[timing.operation] = (
                totals.get(timing.operation, 0) + timing.duration_ns
            )
        return totals

    def broker_api_failures(self) -> List[BrokerApiCallTiming]:
        """Measured calls that raised (fail-closed paths keep their timing)."""
        return [timing for timing in self.broker_api_calls if not timing.ok]

    def broker_api_calls_within(self, stage_name: str) -> List[BrokerApiCallTiming]:
        """
        Task 8.4 accessor: measured calls nested INSIDE the named Task 8.2
        stage window.

        CLOCK SAFETY: stage windows are timed on the stage clock while every
        broker call is timed on the broker clock. Containment by timestamp
        comparison is therefore only computed when this record's two layers
        were timed on the same clock source (``clocks_shared``). Otherwise —
        or when the stage does not exist — the result is an empty list,
        which means "no containment claim possible", NOT "the stage had no
        calls". Callers that must distinguish the two must check
        ``clocks_shared`` / ``stage(...)`` themselves (``stage_failed``
        does).
        """
        if not self.clocks_shared:
            return []
        stage = self.stage(stage_name)
        if stage is None:
            return []
        return [
            call
            for call in self.broker_api_calls
            if call.start >= stage.start and call.end <= stage.end
        ]

    def stage_failed(self, stage_name: str) -> Optional[bool]:
        """
        Task 8.4 accessor: whether any measured call recorded inside the
        named Task 8.2 stage raised (its ``ok`` flag is ``False``).

        Read-only view over the already-recorded data — no behavior change
        and no new measurement.

        Clock-safe, three-valued:

        * ``False`` — the stage exists and (on a shared clock) no nested
          call raised;
        * ``True``  — the stage exists and (on a shared clock) at least
          one nested call raised;
        * ``None``  — no result can be stated: the stage does not exist
          (there is nothing to attribute, and no value is invented), or
          the stage exists but this record's two layers were timed on
          different clock sources (containment cannot be inferred without
          comparing timestamps from different clocks). The raw failures
          stay visible via ``broker_api_failures()`` either way.
        """
        if self.stage(stage_name) is None:
            return None
        if not self.clocks_shared:
            return None
        return any(
            not call.ok
            for call in self.broker_api_calls_within(stage_name)
        )

    # ``application_side_ns`` is a derived field (see
    # ``LatencyCollector.finalize_broker_accounting``): it equals the
    # ``order_engine_path`` stage duration minus the measured broker/API calls
    # nested inside that same stage window, never negative. It is a plain
    # field rather than a property because deriving it requires the single
    # shared clock held by the collector. It is an accounting remainder, not
    # a hard bound: nested wall-clock effects (scheduling, GC) are not
    # separated.


@dataclass
class DispatchLatencyReport:
    """
    Latency report for one dispatch attempt.

    ``dispatch_start`` / ``dispatch_end`` / ``dispatch_duration`` are
    monotonic ``perf_counter_ns()`` ticks. ``orders`` contains one
    independent ``OrderLatency`` per dispatched sequence.
    """

    trace_id: Optional[str]
    dispatch_start: int
    dispatch_end: int
    orders: List[OrderLatency] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.dispatch_end < self.dispatch_start:
            raise ValueError(
                f"dispatch end ({self.dispatch_end}) precedes start "
                f"({self.dispatch_start})"
            )

    @property
    def dispatch_duration(self) -> int:
        return self.dispatch_end - self.dispatch_start

    def order(self, sequence: int) -> Optional[OrderLatency]:
        """Return the latency record for ``sequence``, if present."""
        for record in self.orders:
            if record.sequence == sequence:
                return record
        return None

    def sequences(self) -> List[int]:
        return [record.sequence for record in self.orders]

    def total_stage_duration_ns(self, stage_name: str) -> int:
        """Sum ``stage_name`` duration across all orders (0 when absent)."""
        return sum(
            record.duration_ns(stage_name) or 0 for record in self.orders
        )

    @property
    def broker_api_round_trip_ns(self) -> int:
        """Total measured Broker/API round trip across all orders."""
        return sum(
            record.broker_api_round_trip_ns for record in self.orders
        )

    def broker_api_totals_by_operation(self) -> Dict[str, int]:
        """Total measured Broker/API round trip per operation, across orders."""
        totals: Dict[str, int] = {}
        for record in self.orders:
            for operation, value in record.broker_api_totals_by_operation().items():
                totals[operation] = totals.get(operation, 0) + value
        return totals

    def total_broker_api_calls(self) -> int:
        return sum(len(record.broker_api_calls) for record in self.orders)


# ---------------------------------------------------------------------------
# Broker/API boundary measurement
# ---------------------------------------------------------------------------


def measure_broker_call(
    broker_timing: Optional["BrokerCallRecorder"],
    operation: str,
    func: Callable[[], Any],
) -> Any:
    """
    Invoke ONE existing broker/provider call, optionally measuring it.

    This is the only way Task 8.3 touches the broker boundary:

    - when ``broker_timing`` is ``None`` the call is made exactly as before
      and no clock is read (normal dispatch path — zero cost);
    - otherwise the call is made once, its round trip is recorded (also when
      it raises), and its return value is passed through untouched.

    Exceptions are never swallowed or rewritten, so existing fail-closed
    behavior is preserved exactly.
    """
    if broker_timing is None:
        return func()
    return broker_timing.measure(operation, func)


class BrokerCallRecorder:
    """
    Records Broker/API round trips.

    In the measured dispatch path exactly one recorder is created per
    ``sequence`` and every measured call is written into THAT sequence's own
    ``OrderLatency`` record (``on_call`` sink). There is no shared "current
    order" state.

    A recorder with no sink is also usable standalone — the Task 8.3 Phase B
    operator tool uses it to measure a single real read-only broker call.
    """

    def __init__(
        self,
        clock: Optional[Callable[[], int]] = None,
        sequence: Optional[int] = None,
        on_call: Optional[Callable[[BrokerApiCallTiming], None]] = None,
    ):
        self._clock = clock or time.perf_counter_ns
        self.sequence = sequence
        self._on_call = on_call
        self.calls: List[BrokerApiCallTiming] = []

    @property
    def clock(self) -> Callable[[], int]:
        return self._clock

    def now(self) -> int:
        return self._clock()

    def measure(self, operation: str, func: Callable[[], Any]) -> Any:
        """
        Call ``func`` once, record the round trip, return its value.

        The timing is closed in ``finally``, so a raising call still produces
        a valid (``ok=False``) measurement, and the original exception is
        re-raised unchanged.
        """
        start = self._clock()
        ok = True
        try:
            return func()
        except BaseException:
            ok = False
            raise
        finally:
            self.record(operation, start, self._clock(), ok)

    def record(
        self,
        operation: str,
        start: int,
        end: int,
        ok: bool = True,
    ) -> BrokerApiCallTiming:
        timing = BrokerApiCallTiming(
            operation=operation,
            start=start,
            end=end,
            ok=ok,
        )
        self.calls.append(timing)
        if self._on_call is not None:
            self._on_call(timing)
        return timing

    def calls_for(self, operation: str) -> List[BrokerApiCallTiming]:
        return [call for call in self.calls if call.operation == operation]

    def total_ns(self, operation: Optional[str] = None) -> int:
        return sum(
            call.duration_ns
            for call in self.calls
            if operation is None or call.operation == operation
        )


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class LatencyCollector:
    """
    Opt-in accumulator for one dispatch attempt.

    Storage is keyed by ``sequence``. Each order gets its own
    ``OrderLatency`` record, so a timing record can never reuse mutable
    context belonging to another order.

    ``clock`` is injectable (defaults to ``time.perf_counter_ns``) so tests
    can use a deterministic clock instead of sleeping. It times the Task 8.2
    stage layer and nothing else.

    ``broker_clock`` (defaults to ``time.perf_counter_ns``) times the Task 8.3
    broker/API round trips. Keeping the two clocks separate is what guarantees
    that adding broker/API measurement cannot shift the Task 8.2 stage
    windows. When both default, they are the same clock source and the derived
    application accounting is available; when only the stage clock is
    injected, that accounting is reported as ``None`` rather than computed
    across two different clocks.
    """

    def __init__(
        self,
        clock: Optional[Callable[[], int]] = None,
        broker_clock: Optional[Callable[[], int]] = None,
    ):
        self._clock = clock or time.perf_counter_ns
        self._broker_clock = broker_clock or time.perf_counter_ns
        # True in the normal configuration, where both layers are timed on the
        # same clock source. Only then may a delta between the two layers be
        # computed (see ``finalize_broker_accounting``).
        self._clocks_shared = self._clock is self._broker_clock
        self._orders: "OrderedDict[int, OrderLatency]" = OrderedDict()

    @property
    def clock(self) -> Callable[[], int]:
        return self._clock

    @property
    def broker_clock(self) -> Callable[[], int]:
        return self._broker_clock

    @property
    def clocks_shared(self) -> bool:
        return self._clocks_shared

    def now(self) -> int:
        """Return the current monotonic tick."""
        return self._clock()

    def _order(self, sequence: int) -> OrderLatency:
        record = self._orders.get(sequence)
        if record is None:
            record = OrderLatency(
                sequence=sequence,
                # Stamp THIS collector's clock configuration onto the
                # record, so Task 8.4 reporting can tell whether stage
                # containment is even inferable for it.
                clocks_shared=self._clocks_shared,
            )
            self._orders[sequence] = record
        return record

    def record_identity(
        self,
        sequence: int,
        account_id: Optional[str] = None,
        broker_name: Optional[str] = None,
        ins_code: Optional[str] = None,
    ) -> OrderLatency:
        """Attach identity to the record owned by ``sequence``."""
        record = self._order(sequence)
        record.account_id = account_id
        record.broker_name = broker_name
        record.ins_code = ins_code
        return record

    def record_stage(
        self,
        sequence: int,
        stage_name: str,
        start: int,
        end: int,
    ) -> StageTiming:
        """Append a stage timing to the record owned by ``sequence``."""
        timing = StageTiming(stage_name=stage_name, start=start, end=end)
        self._order(sequence).stages.append(timing)
        return timing

    def record_execution_result(
        self,
        sequence: int,
        result: "OrderExecutionResult",
    ) -> OrderLatency:
        """Attach the existing execution result to ``sequence``'s record."""
        record = self._order(sequence)
        record.execution_result = result
        return record

    def broker_recorder(self, sequence: int) -> BrokerCallRecorder:
        """
        Return the broker/API recorder owned by ``sequence``.

        Every measured call is written into that sequence's own
        ``OrderLatency.broker_api_calls`` — never into another order's record.

        The recorder is deliberately bound to the *broker* clock, not the
        stage clock, so that adding broker/API measurement never consumes an
        extra read of the Task 8.2 stage clock and the four stage windows stay
        exactly as Task 8.2 defined them.
        """
        record = self._order(sequence)
        return BrokerCallRecorder(
            clock=self._broker_clock,
            sequence=sequence,
            on_call=record.broker_api_calls.append,
        )

    def finalize_broker_accounting(
        self,
        sequence: int,
    ) -> Optional[OrderLatency]:
        """
        Derive ``sequence``'s application-side accounting from the recorded
        measurements.

        Computed only from boundaries the code already exposes — the measured
        ``order_engine_path`` stage window and the measured ``place_order``
        round trip — so no boundary is invented:

            application_before_broker_ns = submission.start - stage.start
            application_after_broker_ns  = stage.end - submission.end
            application_side_ns          = stage.duration
                                           - broker calls nested in the stage

        The application windows stay ``None`` when the order never reached the
        submission boundary (e.g. a fail-closed preflight block).

        Cross-clock guard: these three values are deltas between the stage
        clock and the broker clock. When the two are not the same clock source
        they are left ``None`` instead of being fabricated. Every broker/API
        round trip remains available in that case, since each one is measured
        entirely on the broker clock.
        """
        record = self._order(sequence)
        if not self._clocks_shared:
            return record

        stage = record.stage(ORDER_ENGINE_PATH)
        if stage is None:
            return record

        nested = sum(
            timing.duration_ns
            for timing in record.broker_api_calls
            if timing.start >= stage.start and timing.end <= stage.end
        )
        record.application_side_ns = max(0, stage.duration_ns - nested)

        submission = record.broker_api_call(SUBMISSION_OPERATION)
        if submission is not None:
            record.application_before_broker_ns = submission.start - stage.start
            record.application_after_broker_ns = stage.end - submission.end

        return record

    def orders(self) -> List[OrderLatency]:
        return list(self._orders.values())

    def build_report(
        self,
        trace_id: Optional[str],
        dispatch_start: int,
        dispatch_end: int,
    ) -> DispatchLatencyReport:
        return DispatchLatencyReport(
            trace_id=trace_id,
            dispatch_start=dispatch_start,
            dispatch_end=dispatch_end,
            orders=list(self._orders.values()),
        )


# ---------------------------------------------------------------------------
# Task 8.4 — reporting / attribution (read-only over the Task 8.2/8.3 data)
# ---------------------------------------------------------------------------


def _ns_stats(durations: Tuple[int, ...]) -> "LatencyDistribution":
    """
    Compute count/min/median/mean/max for ``durations`` (ns).

    Zero-arg guard returns ``count=0`` and all ``None`` values — an empty set
    has no latency, and no value is invented for it.
    """
    if not durations:
        return LatencyDistribution()
    return LatencyDistribution(
        count=len(durations),
        min_ns=min(durations),
        median_ns=int(statistics.median(durations)),
        mean_ns=int(statistics.mean(durations)),
        max_ns=max(durations),
    )


@dataclass(frozen=True)
class LatencyDistribution:
    """
    A factual latency distribution: count / min / median / mean / max.

    All values are integers in nanoseconds measured by Task 8.2/8.3; ``None``
    means "no data" (e.g. ``count=0``), never an estimate. Empty-set values
    are left ``None`` rather than being fabricated (e.g. as 0).
    """

    count: int = 0
    min_ns: Optional[int] = None
    median_ns: Optional[int] = None
    mean_ns: Optional[int] = None
    max_ns: Optional[int] = None


@dataclass(frozen=True)
class BrokerApiFailureInfo:
    """
    One recorded Broker/API call failure, exactly as Task 8.3 kept it.

    The timing of a failed call is preserved (never dropped from the
    report); ``duration_ns`` is the real measured window of the failing
    call. No exception text is re-synthesized here.
    """

    sequence: int
    operation: str
    duration_ns: int


@dataclass(frozen=True)
class OrderLatencyAttribution:
    """
    Factual attribution for exactly one execution (one ``sequence``).

    ``broker_api_time_ns`` is ENGINE-SCOPED: it counts only the measured
    round trips of calls nested inside the attribution window (the record's
    ``order_engine_path`` stage), and only when containment is inferable
    (shared clock). ``application_side_ns`` is the measured Task 8.2/8.3
    derived value carried by the record (``None`` when the clocks are not
    shared — never a guess).

    ``broker_api_time_sequence_wide_ns`` is the sequence-wide sum: ALL
    measured round trips of this record, including calls outside the
    attribution window (e.g. the pre-engine instrument resolution). It is
    kept under its own explicit name so the engine-scoped decomposition is
    never silently mixed with it. The same sequence-wide coverage applies
    to ``broker_api_failure_count`` and to every aggregate.

    ``total_execution_latency_ns`` is available only when the record itself
    states the whole execution window (its ``order_engine_path`` stage). When
    that stage was never recorded (e.g. the dispatch failed before the
    engine stage) the total is ``None`` — the split is not invented from
    other windows.

    ``order_success`` is the existing Task 8.2 ``OrderExecutionResult.success``
    flag (``None`` when the order never produced a result). A raising
    Broker/API call is not folded into it: the existing engine already turns
    broker exceptions into fail-closed results, and the raw call failures
    stay separately visible in ``broker_api_failure_count`` and
    ``engine_stage_failed``. There is deliberately no broker ranking here:
    the record keeps its own ``broker_name`` so the report stays factual
    per execution.

    Attribution boundary: ``total_execution_latency_ns``,
    ``broker_api_time_ns`` and ``application_side_ns`` decompose the SAME
    execution window — the record's measured ``order_engine_path`` stage:

        total_execution_latency_ns = order_engine_path stage duration
        broker_api_time_ns         = round trips of calls nested in that
                                     window (0 when containment is not
                                     inferable across clocks)
        application_side_ns        = the collector's own remainder of that
                                     window (None when clocks are not shared)

    Broker/API calls OUTSIDE that window (e.g. the pre-engine instrument
    resolution in ``DispatchCore._resolve_instrument``) stay recorded and
    keep counting in ``broker_api_time_sequence_wide_ns``, in
    ``broker_api_failure_count`` and in every aggregate; they are never
    silently folded into this window's decomposition.
    """

    sequence: int
    broker_name: Optional[str]
    total_execution_latency_ns: Optional[int]
    # Engine-scoped: only calls nested in the attribution window.
    broker_api_time_ns: int
    application_side_ns: Optional[int]
    order_success: Optional[bool]
    engine_stage_failed: Optional[bool]
    # Sequence-wide: EVERY measured round trip of this record, inside the
    # window or not (kept under its own explicit name).
    broker_api_time_sequence_wide_ns: int
    broker_api_failure_count: int
    broker_api_calls_within_engine: int


@dataclass(frozen=True)
class LatencyAnalysis:
    """
    Task 8.4 factual summary over one ``DispatchLatencyReport``.

    Built by ``analyze_latency_report()``; every number is derived from the
    measurements the report already carries. Nothing here re-measures,
    extrapolates, or ranks brokers.
    """

    trace_id: Optional[str]
    total_orders: int
    successful_orders: int
    failed_orders: int

    # Total measured dispatch window (``dispatch_start``/``dispatch_end``).
    dispatch_duration_ns: int

    # Per-execution latency distribution (each order's measured
    # ``order_engine_path`` window — the same value the attribution reports
    # as ``total_execution_latency_ns``).
    execution_latency_ns: "LatencyDistribution"

    # Task 8.2 stage detail (includes ``order_engine_path``).
    stage_durations_ns: Dict[str, "LatencyDistribution"]

    # Task 8.3: Broker/API round trips — the sum across orders, the
    # per-order distribution, the per-operation detail, and the failures the
    # report actually recorded.
    broker_api_total_ns: int
    broker_api_time_ns: "LatencyDistribution"
    broker_api_by_operation_ns: Dict[str, "LatencyDistribution"]
    broker_api_failure_count: int
    broker_api_failures: Tuple["BrokerApiFailureInfo", ...]

    # Task 8.4 attribution (one entry per execution record, in report order).
    attributions: Tuple["OrderLatencyAttribution", ...]

    # Application-side attribution is only defined on a shared clock; the
    # report never fabricates it. ``None`` when no order carried a value.
    application_side_time_ns: "LatencyDistribution"


def analyze_latency_report(report: DispatchLatencyReport) -> LatencyAnalysis:
    """
    Convert a Task 8.3 ``DispatchLatencyReport`` into a factual summary.

    Read-only: this function takes the report's own measurements (Task 8.2
    stage windows, Task 8.3 broker/API round trips, the derived application
    accounting the collector already produced) and aggregates them. It does
    not touch the dispatch path, re-measure anything, or rank brokers.

    Attribution rules (Task 8.4):

    * The attribution boundary is the record's own measured
      ``order_engine_path`` stage window; ``total_execution_latency_ns`` is
      that window's duration (``None`` when it was not recorded).
    * Broker/API time inside that decomposition = only the round trips of
      calls actually nested in that window, when containment is inferable
      (shared clock). Cross-clock records leave the engine-scoped
      ``broker_api_time_ns`` at 0 — no containment claim is fabricated —
      while ``broker_api_time_sequence_wide_ns`` keeps the full sum.
    * Sequence-wide broker/API time (``broker_api_time_sequence_wide_ns``,
      ``broker_api_failure_count``) and every aggregate still covers ALL
      measured calls of the record, including calls outside the engine
      window (e.g. the pre-engine instrument resolution); nothing is lost.
    * Application-side time = the value the record itself carries
      (``None`` when the two clocks are not shared — never a guess).
    * Nothing is negative: stage/round-trip windows are validated monotonic
      at creation, and the derived application remainder is clamped at 0 by
      the collector. No value here can turn negative.
    """
    orders = list(report.orders)

    successful = sum(
        1
        for record in orders
        if record.execution_result is not None
        and record.execution_result.success is True
    )
    failed = len(orders) - successful

    stage_distributions: Dict[str, "LatencyDistribution"] = {}
    for stage_name in DISPATCH_STAGES:
        durations = tuple(
            record.duration_ns(stage_name)
            for record in orders
            if record.duration_ns(stage_name) is not None
        )
        stage_distributions[stage_name] = _ns_stats(durations)  # type: ignore[arg-type]

    broker_totals = tuple(
        record.broker_api_round_trip_ns for record in orders
    )
    application_sides = tuple(
        record.application_side_ns
        for record in orders
        if record.application_side_ns is not None
    )

    by_operation: Dict[str, List[int]] = {}
    for record in orders:
        for operation, value in record.broker_api_totals_by_operation().items():
            by_operation.setdefault(operation, []).append(value)

    failures = tuple(
        BrokerApiFailureInfo(
            sequence=record.sequence,
            operation=call.operation,
            duration_ns=call.duration_ns,
        )
        for record in orders
        for call in record.broker_api_calls
        if not call.ok
    )

    attributions = tuple(
        OrderLatencyAttribution(
            sequence=record.sequence,
            broker_name=record.broker_name,
            total_execution_latency_ns=record.duration_ns(ORDER_ENGINE_PATH),
            application_side_ns=record.application_side_ns,
            # Task 8.2 ``success`` flag. A raising Broker/API call is NOT
            # counted as an order failure here: the existing engine turns
            # many broker exceptions into fail-closed BLOCKED results with
            # ``success=False`` — that distinction stays visible (and is
            # reported factually) via ``stage_failed`` / failure info
            # instead of being double-counted.
            order_success=(
                record.execution_result.success
                if record.execution_result is not None
                else None
            ),
            engine_stage_failed=record.stage_failed(ORDER_ENGINE_PATH),
            broker_api_failure_count=len(record.broker_api_failures()),
            # Explicit boundary: ``broker_api_time_ns`` is engine-scoped —
            # only calls nested in the engine window belong to this
            # window's decomposition. When containment is not inferable
            # (different clocks) no within-window value is fabricated
            # (it stays 0); the full sequence-wide sum is kept explicitly
            # in ``broker_api_time_sequence_wide_ns``.
            broker_api_time_ns=sum(
                call.duration_ns
                for call in record.broker_api_calls_within(ORDER_ENGINE_PATH)
            ),
            broker_api_time_sequence_wide_ns=record.broker_api_round_trip_ns,
            broker_api_calls_within_engine=len(
                record.broker_api_calls_within(ORDER_ENGINE_PATH)
            ),
        )
        for record in orders
    )

    return LatencyAnalysis(
        trace_id=report.trace_id,
        total_orders=len(orders),
        successful_orders=successful,
        failed_orders=failed,
        dispatch_duration_ns=report.dispatch_duration,
        execution_latency_ns=stage_distributions[ORDER_ENGINE_PATH],
        stage_durations_ns=stage_distributions,
        broker_api_total_ns=sum(broker_totals),
        broker_api_time_ns=_ns_stats(broker_totals),
        broker_api_by_operation_ns={
            operation: _ns_stats(tuple(values))
            for operation, values in by_operation.items()
        },
        broker_api_failure_count=len(failures),
        broker_api_failures=failures,
        attributions=attributions,
        application_side_time_ns=_ns_stats(application_sides),
    )
