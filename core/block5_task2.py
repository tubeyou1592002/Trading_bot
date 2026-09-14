"""
Block 5 — Task 2: Result Collection.

A small connector that records the outcome of an existing Dispatch into
the ExecutionTracker (Block 5, Task 1).

Dispatch boundary (Block 5, Task 2 level):

    Dispatch Core (Block 2) / Timed-Burst (Block 3) / Event-Driven (Block 4)
        │
        ▼
    DispatchResult   (existing Block 0 contract)
        │
        ▼
    collect_result   <-- this module (connector only)
        │
        ▼
    ExecutionTracker.update_status   (existing Block 5 Task 1)

Behavior:
  - The execution must already be registered in the tracker.
  - DispatchResult(success=True)  -> ExecutionStatus.REGISTERED
  - DispatchResult(success=False) -> ExecutionStatus.FAILED
  - Unknown / invalid execution_id -> fail-closed with ExecutionTrackerError
    (raised by ExecutionTracker.update_status itself).

Explicitly OUT of scope for this module:
  - Any broker implementation, broker adapter, or broker/exchange API call.
  - Any scheduler, timer, polling loop, or real clock.
  - Any persistence, file I/O, or network access.
  - Any modification to ExecutionTracker, DispatchCore, DispatchResult,
    OrderEngine, Broker, or any M6 component.
  - Fill / Partial Fill tracking (out of scope for Block 5).
"""

from __future__ import annotations

from typing import Optional

from core.dispatch_contracts import DispatchResult
from core.execution_tracker import ExecutionStatus, ExecutionTracker, ExecutionTrackerError


def _map_dispatch_result_to_status(result: DispatchResult) -> ExecutionStatus:
    """Map a DispatchResult to the appropriate ExecutionStatus.

    success=True  -> REGISTERED
    success=False -> FAILED
    """
    if result.success:
        return ExecutionStatus.REGISTERED
    return ExecutionStatus.FAILED


def collect_result(
    tracker: ExecutionTracker,
    execution_id: str,
    result: DispatchResult,
) -> ExecutionStatus:
    """Record the outcome of an existing Dispatch into the tracker.

    Args:
        tracker: The existing ExecutionTracker instance (must already
            contain ``execution_id``).
        execution_id: The id of the execution to update. Must already be
            registered in ``tracker``.
        result: The DispatchResult produced by the Dispatch path.

    Returns:
        The new ExecutionStatus recorded on the execution.

    Raises:
        ExecutionTrackerError: if ``execution_id`` is unknown/invalid
            (fail-closed). Also raised if ``result`` is not a DispatchResult.
    """
    if not isinstance(result, DispatchResult):
        raise ExecutionTrackerError(
            "result must be a DispatchResult"
        )

    status: ExecutionStatus = _map_dispatch_result_to_status(result)
    record = tracker.update_status(execution_id, status)
    return record.status


def collect_result_safe(
    tracker: ExecutionTracker,
    execution_id: str,
    result: DispatchResult,
) -> Optional[ExecutionStatus]:
    """Like :func:`collect_result` but returns ``None`` on failure.

    Useful for callers that want fail-closed behavior without raising.
    """
    try:
        return collect_result(tracker, execution_id, result)
    except ExecutionTrackerError:
        return None