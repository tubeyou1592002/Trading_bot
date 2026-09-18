"""
Block 8 — Task 8.2: internal Dispatch latency instrumentation.

This module is **measurement only**. It observes the four existing internal
``DispatchCore`` stages; it does not optimize, reorder, cache, or otherwise
change dispatch behavior.

Measured stages (exactly these, and nothing else):

    plan_item            time spent by the existing ``_plan_item(...)``
    plan_account         time spent by the existing ``_plan_account(...)``
    instrument_resolution time spent by the existing ``_resolve_instrument(...)``
    order_engine_path    time spent by the existing ``_execute_single_order(...)``

``order_engine_path`` covers everything downstream of
``_execute_single_order()``, **including** any broker call currently hidden
behind the ``OrderEngine``. It is therefore NOT pure application time.
Broker / API / network latency separation is explicitly deferred to Task 8.3
and is NOT attempted here.

Timing clock:

    Elapsed durations use ``time.perf_counter_ns()`` (monotonic,
    high-resolution). The existing wall-clock ``DispatchTrace.start_time`` /
    ``end_time`` (``datetime.now()``) timestamps are left untouched and are
    never mixed with this clock.

Per-order independence:

    Every order's identity (``account_id`` / ``broker_name`` / ``ins_code``)
    and stage timings are stored per ``sequence`` inside the collector. There
    is deliberately no shared mutable ``current_account`` /
    ``current_broker`` / ``current_ins_code`` context that one order could
    inherit from another.

Opt-in:

    When no collector is supplied the dispatch path performs no timing calls
    at all; ``DispatchCore.dispatch()`` behavior is unchanged.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
    from core.order_engine import OrderExecutionResult


# ---------------------------------------------------------------------------
# Stage names (Task 8.2 — exactly these four)
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
    can use a deterministic clock instead of sleeping.
    """

    def __init__(self, clock: Optional[Callable[[], int]] = None):
        self._clock = clock or time.perf_counter_ns
        self._orders: "OrderedDict[int, OrderLatency]" = OrderedDict()

    @property
    def clock(self) -> Callable[[], int]:
        return self._clock

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
