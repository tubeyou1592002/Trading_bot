"""
Block 3 Task 3 — Timed dispatch scheduler.

This module defines ``TimedDispatchScheduler``, a small deterministic
scheduler that generates dispatch timestamps for a ``DispatchTiming``
window.

The scheduler:
  - starts at ``start_time``,
  - advances by ``timing.interval``,
  - never emits a timestamp after ``end_time``,
  - includes ``start_time`` and ``end_time`` when they fall exactly on
    the interval.

It is a pure, deterministic function of its inputs. It never reads the
real clock, never sleeps, never spawns a thread or timer, and knows
nothing about brokers, orders, or APIs.

Dispatch boundary (Block 3, scheduler level):

    TimedDispatchTrigger (Task 2)
        │
        ▼
    TimedDispatchScheduler   <-- this module (pure timestamp generation)
        │
        ▼
    Dispatch Core (Block 2)  --> existing M6-A … M6-E --> Broker

Explicitly OUT of scope for this module:
  - Any scheduler loop, timer, polling, or real clock.
  - Any broker implementation, broker adapter, or broker API call.
  - Any OrderEngine, preflight gate (M6-A … M6-E), or order submission.
  - Any modification to ``core/dispatch_contracts.py``,
    ``core/timing_contracts.py``, or ``core/timed_dispatch_trigger.py``.
  - Any new trigger abstraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

from core.timing_contracts import DispatchTiming
from core.timed_dispatch_trigger import TimedDispatchTrigger


@dataclass(frozen=True, slots=True)
class TimedDispatchScheduler:
    """
    Deterministic scheduler that generates dispatch timestamps.

    A ``TimedDispatchScheduler`` is an immutable, pure component. Given
    a ``DispatchTiming``, its ``generate()`` method returns the list of
    wall-clock moments at which a dispatch should fire.

    The scheduler uses the existing ``TimedDispatchTrigger`` to validate
    every candidate timestamp against the ``[start_time, end_time]``
    window. It never reads the real clock and has no side effects.

    Attributes:
        timing: The ``DispatchTiming`` carrying the window and interval.
    """

    timing: DispatchTiming

    def generate(self) -> List[datetime]:
        """
        Generate dispatch timestamps for the window.

        Timestamps start at ``start_time`` and advance by
        ``timing.interval`` until the next step would exceed
        ``end_time``. Both ``start_time`` and ``end_time`` are included
        when they fall exactly on the interval.

        Returns:
            A list of ``datetime`` timestamps in ascending order.
        """
        trigger = TimedDispatchTrigger(timing=self.timing)
        timestamps: List[datetime] = []
        end = self.timing.end_time
        interval = self.timing.interval
        current = self.timing.start_time

        while current <= end:
            if trigger.evaluate(current):
                timestamps.append(current)
            current += interval

        return timestamps
