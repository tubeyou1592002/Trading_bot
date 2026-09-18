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
            record = OrderLatency(sequence=sequence)
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
