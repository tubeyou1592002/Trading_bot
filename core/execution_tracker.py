"""
Block 5 Task 1 — Execution Tracker Core.

A minimal, broker-independent record keeper for per-order execution
tracking. It supports ONLY:

  - registering a new execution (starts in PENDING),
  - updating the status of an existing execution,
  - reading the current status of an execution.

Dispatch boundary (Block 5, Task 1 level):

    Dispatch Core (Block 2) / Timed-Burst (Block 3) / Event-Driven (Block 4)
        │
        ▼
    ExecutionTracker   <-- this module (record + status only)
        │
        ▼
    Result Collection (Block 5, Task 2 — future)

Explicitly OUT of scope for this module:
  - Any broker implementation, broker adapter, or broker/exchange API call.
  - Any fill data, average fill price, execution ID, or full order lifecycle.
  - Any modification to Dispatch Core, OrderEngine, M6-A … M6-E,
    Block 3, Block 4, Strategy, or UI.
  - Any scheduler, timer, polling loop, or dispatch mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional


class ExecutionStatus(str, Enum):
    """Execution lifecycle states tracked by Block 5 Task 1.

    Only registration-focused states are modeled. Fill tracking
    (FILLED / PARTIAL_FILLED) is intentionally absent: fill is
    out of scope for Block 5 per the approved AI_HANDOFF contract.
    """

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    REGISTERED = "REGISTERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExecutionTrackerError(ValueError):
    """Raised for invalid tracker usage (fail-closed)."""


@dataclass
class ExecutionRecord:
    """Immutable identity + mutable status of one tracked execution."""

    execution_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class ExecutionTracker:
    """In-memory registry of execution records.

    Pure record keeper: no I/O, no clock reads, no broker calls.
    """

    _records: Dict[str, ExecutionRecord] = field(default_factory=dict)

    def register(self, execution_id: str) -> ExecutionRecord:
        """Register a new execution in PENDING status.

        Raises ExecutionTrackerError for blank/duplicate ids.
        """
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ExecutionTrackerError(
                "execution_id must be a non-empty string"
            )
        if execution_id in self._records:
            raise ExecutionTrackerError(
                f"duplicate execution_id: {execution_id}"
            )
        record = ExecutionRecord(execution_id=execution_id)
        self._records[execution_id] = record
        return record

    def update_status(
        self, execution_id: str, status: ExecutionStatus
    ) -> ExecutionRecord:
        """Update the status of an existing execution.

        Raises ExecutionTrackerError for unknown ids or invalid states.
        """
        record = self._records.get(execution_id)
        if record is None:
            raise ExecutionTrackerError(
                f"unknown execution_id: {execution_id}"
            )
        if not isinstance(status, ExecutionStatus):
            raise ExecutionTrackerError(
                "status must be an ExecutionStatus"
            )
        record.status = status
        return record

    def get_status(self, execution_id: str) -> ExecutionStatus:
        """Return the current status of an existing execution.

        Raises ExecutionTrackerError for unknown ids.
        """
        record = self._records.get(execution_id)
        if record is None:
            raise ExecutionTrackerError(
                f"unknown execution_id: {execution_id}"
            )
        return record.status
