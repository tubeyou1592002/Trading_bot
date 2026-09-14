"""
Block 5 — Task 3: Conditional Stop Signal.

A small, broker-independent Stop Signal that gates *future* dispatches based
on the outcome of *past* dispatches.

Dispatch boundary (Block 5, Task 3 level):

    Dispatch Core (Block 2) / Timed-Burst (Block 3) / Event-Driven (Block 4)
        │
        ▼
    DispatchResult   (existing Block 0 contract)
        │
        ▼
    StopSignal.observe(result)   <-- this module (gate only)
        │
        ▼
    is_active / should_continue   (read by Task 4 / UI later)

Behavior:
  - Default mode (enabled=False): Stop Signal NEVER activates. The dispatch
    flow continues exactly as before. This is the fail-open default for
    normal (non-stop) operation.
  - Conditional mode (enabled=True): the Stop Signal activates on the first
    DispatchResult with success=True (i.e. first successful registration in
    the exchange core). Once active, it stays active.
  - Only NEW dispatches issued after activation are affected. Orders already
    sent before the Stop Signal activated are NOT cancelled or stopped.
  - Per-order results remain independent: a FAILED result never activates
    the signal, and activating the signal does not retroactively change the
    status of any previously recorded execution.

Explicitly OUT of scope for this module:
  - Any scheduler, timer, polling loop, or dispatch mechanism.
  - Any persistence, file I/O, or network access.
  - Any broker implementation, broker adapter, or broker/exchange API call.
  - Any modification to Dispatch Core, Block 3, Block 4, OrderEngine,
    ExecutionTracker, DispatchResult, or the UI.
  - Connecting the Stop Signal to the real Dispatch path (Task 4).
"""

from __future__ import annotations

from core.dispatch_contracts import DispatchResult


class StopSignalError(ValueError):
    """Raised for invalid StopSignal usage (fail-closed)."""


class StopSignal:
    """Conditional stop gate driven by DispatchResult outcomes.

    The Stop Signal is a pure state machine: it observes DispatchResult
    objects and transitions between INACTIVE and ACTIVE. It has no I/O,
    no clock, no broker dependency, and no knowledge of how dispatches are
    actually issued.

    Attributes:
        enabled: Whether the conditional stop rule is active. When False,
            the signal can never activate (default, continuous dispatch).
    """

    def __init__(self, enabled: bool = False) -> None:
        if not isinstance(enabled, bool):
            raise StopSignalError("enabled must be a bool")
        self.enabled: bool = enabled
        self._active: bool = False
        self._activation_count: int = 0

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """Return True once the Stop Signal has been activated."""
        return self._active

    @property
    def activation_count(self) -> int:
        """Number of times the Stop Signal has transitioned to ACTIVE.

        This counts activation *events*, not the number of successful
        results observed. Because the signal latches on the first success
        and stays active, this counter is at most 1 until ``reset()`` is
        called. It is reset to 0 by ``reset()``.
        """
        return self._activation_count

    def should_continue(self) -> bool:
        """Return True while dispatch may proceed (i.e. stop not active).

        Default (enabled=False) always returns True.
        """
        return not self._active

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    def observe(self, result: DispatchResult) -> bool:
        """Feed a DispatchResult to the Stop Signal.

        Args:
            result: The DispatchResult produced by the Dispatch path.

        Returns:
            True if the Stop Signal was *activated by this specific call*
            (first successful result while enabled). False otherwise —
            including when the signal was already active, when the rule is
            disabled, or when the result was a failure.

        Raises:
            StopSignalError: if ``result`` is not a DispatchResult
                (fail-closed).
        """
        if not isinstance(result, DispatchResult):
            raise StopSignalError("result must be a DispatchResult")

        # Disabled rule: never activate, always continue.
        if not self.enabled:
            return False

        # Already active: subsequent successes are no-ops. The signal
        # latches on the FIRST success and stays active.
        if self._active:
            return False

        # Enabled and not yet active: only a success activates it.
        if result.success:
            self._active = True
            self._activation_count += 1
            return True

        # Failure while enabled and not yet active: no activation.
        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Deactivate the Stop Signal (e.g. for a new dispatch batch).

        Does NOT change ``enabled``. After reset the gate can be
        re-activated by a subsequent successful result.
        """
        self._active = False
        self._activation_count = 0