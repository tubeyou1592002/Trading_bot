"""
Block 4 Task 1 — Trading State Event Trigger.

This module defines ``TradingStateEventTrigger``, a concrete
``EventTrigger`` that evaluates whether a ``TradingState`` allows
passage to the next dispatch stage.

The trigger answers one question:
  "Does this TradingState allow order entry?"

It is a pure, deterministic function of its inputs. It never reads
the real clock, never sleeps, never spawns a thread or timer, and
knows nothing about brokers, orders, or APIs.

Dispatch boundary (Block 4, trigger level):

    EventTrigger (contract)
        │
        ▼
    TradingStateEventTrigger   <-- this module (pure state evaluation)
        │
        ▼
    Dispatch Core (Block 2)  --> existing M6-A … M6-E --> Broker

Explicitly OUT of scope for this module:
  - Any scheduler, timer, polling loop, or real clock.
  - Any broker implementation, broker adapter, or broker API call.
  - Any OrderEngine, preflight gate (M6-A … M6-E), or order submission.
  - Any modification to ``core/dispatch_contracts.py`` or
    ``models/trading_state.py``.
  - Any new state, enum, or model.
  - Any Block 3 dependency (timed dispatch / scheduler).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.dispatch_contracts import EventTrigger
from models.trading_state import TradingState


@dataclass(frozen=True, slots=True)
class TradingStateEventTrigger(EventTrigger):
    """
    Concrete ``EventTrigger`` backed by a ``TradingState``.

    The trigger fires (returns ``True``) when the trading state
    allows order entry: both ``is_order_entry_allowed`` and
    ``is_verified`` must be ``True``.

    Any state that is blocked, unverified, incomplete, or invalid
    results in ``False`` (fail-closed).

    The trigger is immutable (frozen + slots) and deterministic: for
    a given state and ``now`` it always returns the same boolean,
    with no side effects and no hidden state.

    Attributes:
        state: The ``TradingState`` to evaluate.
    """

    state: TradingState

    def evaluate(self, now: datetime) -> bool:
        """
        Return ``True`` if the trading state allows order entry.

        The trigger fires when both ``is_order_entry_allowed`` and
        ``is_verified`` are ``True``. Any other combination returns
        ``False``.

        Args:
            now: The wall-clock moment of evaluation. Must be a
                ``datetime`` instance; non-datetime values result in
                ``False`` (fail-closed).

        Returns:
            ``True`` if the state allows passage to the next stage,
            otherwise ``False``.
        """
        if not isinstance(now, datetime) or isinstance(now, bool):
            return False

        return (
            self.state.is_order_entry_allowed is True
            and self.state.is_verified is True
        )
