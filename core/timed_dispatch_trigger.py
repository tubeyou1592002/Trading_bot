"""
Block 3 Task 2 - Timed dispatch trigger.

This module defines ``TimedDispatchTrigger``, a concrete ``TimeTrigger``
that fires when ``now`` falls inside the ``[start_time, end_time]`` window
carried by a ``DispatchTiming``.

The trigger is a pure, deterministic function of its inputs. It never
reads the real clock, never sleeps, never spawns a thread or timer, and
knows nothing about brokers, orders, or APIs. It answers only one
question: "is this moment inside the window?"

Dispatch boundary (Block 3, trigger level):

    TimeTrigger (contract)
        |
        v
    TimedDispatchTrigger   <-- this module (pure window test)
        |
        v
    Dispatch Core (Block 2)  --> existing M6-A ... M6-E --> Broker

Explicitly OUT of scope for this module:
  - Any scheduler, timer, polling loop, or real clock.
  - Any broker implementation, broker adapter, or broker API call.
  - Any OrderEngine, preflight gate (M6-A ... M6-E), or order submission.
  - Any modification to ``core/dispatch_contracts.py`` or
    ``core/timing_contracts.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.dispatch_contracts import TimeTrigger
from core.timing_contracts import DispatchTiming


@dataclass(frozen=True, slots=True)
class TimedDispatchTrigger(TimeTrigger):
    """
    Concrete ``TimeTrigger`` backed by a ``DispatchTiming``.

    The trigger fires (returns ``True``) when ``now`` satisfies
    ``start_time <= now <= end_time``. The window is inclusive on both
    ends: the exact start moment and the exact end moment both fire.

    The trigger is immutable (frozen + slots) and deterministic: for a
    given ``now`` it always returns the same boolean, with no side
    effects and no hidden state.

    Attributes:
        timing: The ``DispatchTiming`` carrying the ``start_time`` and
            ``end_time`` of the dispatch window.
    """

    timing: DispatchTiming

    def evaluate(self, now: datetime) -> bool:
        """
        Return ``True`` if ``now`` is inside the dispatch window.

        The window is inclusive: ``start_time <= now <= end_time``.

        Args:
            now: The wall-clock moment to test. Must be a ``datetime``
                instance.

        Returns:
            ``True`` if ``now`` lies within the closed interval
            ``[start_time, end_time]``, otherwise ``False``.

        Raises:
            TypeError: If ``now`` is not a ``datetime`` instance.
        """
        if not isinstance(now, datetime) or isinstance(now, bool):
            raise TypeError(
                f"TimedDispatchTrigger.evaluate expects a datetime for 'now', "
                f"got {type(now).__name__}"
            )

        return self.timing.start_time <= now <= self.timing.end_time
