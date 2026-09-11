"""
Block 3 — Timed / Burst Dispatch: timing settings contract.

This module defines a *small, broker-agnostic abstraction* for the
scheduling settings that Block 3 (Timed / Burst Dispatch) will consume.

It is intentionally contract-only at this stage:

  - It carries exactly the three values the Block 3 scope requires:
      * start_time  — when the dispatch window opens
      * end_time    — when the dispatch window closes
      * interval    — the gap between dispatches inside the window
  - It is **independent of Broker and Agah**: no broker import, no
    instrument, no account, no API, no HTTP, no auth.
  - It is **fail-closed**: any invalid or incomplete setting raises
    ``TimingValidationError``. It never silently accepts a malformed
    window and never invents a missing value.
  - It contains **no scheduler, timer, polling, event bus, or real clock
    source**. Deciding *when* to fire is Block 3's job, not this
    contract's. No sample values (e.g. 50ms, 10s) are hard-coded here;
    every value comes from the caller.

Dispatch boundary (Block 3, contract level):

    Trigger
        │
        ▼
    Block 3 scheduling settings  <-- this module (data + validation only)
        │
        ▼
    Dispatch Core (Block 2)   --> existing M6-A … M6-E --> Broker

Explicitly OUT of scope for this contract module:
  - Any scheduler, timer, polling loop, or real clock.
  - Any broker implementation, broker adapter, or broker API call.
  - Any OrderEngine, preflight gate (M6-A … M6-E), or order submission.
  - Any modification to ``core/dispatch_contracts.py`` or M6-A … M6-E.
  - Any hard-coded sample timing values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TimingValidationError(ValueError):
    """
    Raised when a ``DispatchTiming`` window is invalid or incomplete.

    The contract is fail-closed: it never silently accepts a malformed
    window (start after end, zero/negative interval, wrong types) and it
    never invents a missing value.
    """


# ---------------------------------------------------------------------------
# Timing settings contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchTiming:
    """
    Broker-agnostic timing settings for a Timed / Burst dispatch window.

    A ``DispatchTiming`` is a pure, immutable data container carrying the
    three values Block 3 needs:

      * ``start_time`` — the wall-clock moment the dispatch window opens.
      * ``end_time``   — the wall-clock moment the dispatch window closes.
      * ``interval``   — the gap between dispatches inside the window.

    Construction validates the window fail-closed (see
    ``_validate``). The object is frozen: once built it can never be
    mutated into an inconsistent state.

    The contract deliberately does not expose any scheduling primitive.
    It answers only "what are the settings?" and "is this moment inside
    the window?"; it never decides when to wake up or fire.
    """

    start_time: datetime
    end_time: datetime
    interval: timedelta

    def __post_init__(self) -> None:
        self._validate()

    # ------------------------------------------------------------------
    # Validation (fail-closed)
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        # --- start_time must be a real datetime ----------------------
        if not isinstance(self.start_time, datetime) or isinstance(
            self.start_time, bool
        ):
            raise TimingValidationError(
                "DispatchTiming.start_time must be a datetime"
            )

        # --- end_time must be a real datetime ------------------------
        if not isinstance(self.end_time, datetime) or isinstance(
            self.end_time, bool
        ):
            raise TimingValidationError(
                "DispatchTiming.end_time must be a datetime"
            )

        # --- interval must be a real timedelta -----------------------
        if not isinstance(self.interval, timedelta) or isinstance(
            self.interval, bool
        ):
            raise TimingValidationError(
                "DispatchTiming.interval must be a timedelta"
            )

        # --- start must not fall after end ---------------------------
        # A window whose start is later than its end can never contain a
        # valid dispatch moment. Reject it; do not silently invert it.
        if self.start_time > self.end_time:
            raise TimingValidationError(
                "DispatchTiming.start_time must not be after end_time "
                f"(start={self.start_time!r}, end={self.end_time!r})"
            )

        # --- interval must be strictly positive ----------------------
        # Zero or negative gaps cannot space out dispatches. Reject.
        if self.interval <= timedelta(0):
            raise TimingValidationError(
                "DispatchTiming.interval must be strictly positive, "
                f"got {self.interval!r}"
            )


# ---------------------------------------------------------------------------
# End of module
# ---------------------------------------------------------------------------