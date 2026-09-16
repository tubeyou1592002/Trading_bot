"""
Block 5 Task 1 — Execution Tracker Core.

A minimal, broker-independent record keeper for per-order execution
tracking. It supports ONLY:

  - registering a new execution (starts in PENDING),
  - updating the status of an existing execution,
  - reading the current status of an execution.

Block 6 Task 6.5 — Account-Aware Tracking (extension):

The same tracker also keeps ONE independent record per **order** inside a
tracked dispatch execution, so that the status of a given order of a given
account can never be confused with the status of another order:

  - ``register_order(execution_id, sequence, account_id)``,
  - ``update_order_status(execution_id, sequence, status)``,
  - ``get_order_status(execution_id, sequence)``,
  - ``get_order_record(execution_id, sequence)``,
  - ``order_records(execution_id)`` (read-only view).

Design rules for the account-aware layer (Task 6.5):

  * NO parallel / new identifier is invented. An order record is keyed by
    the **existing** dispatch ``execution_id`` plus the order's own
    ``sequence``; the ``account_id`` is the higher-level identity carried
    along with it.
  * A per-order record can only be created under an already registered
    dispatch execution (fail-closed): a result can never be attributed to
    an execution that was not issued.
  * Every order/account pair has its own record. Updating one record never
    reads or writes any other record — not for the same account, the same
    broker, or the same symbol.
  * ``account_id`` must be a non-empty, non-whitespace string. It is always
    supplied by the caller from the plan binding; the tracker never derives
    or fabricates an account identity, and never falls back to a default.
  * Re-registering the same (execution_id, sequence) is rejected; in
    particular, re-binding an already tracked order to a *different*
    account is fail-closed (cross-account contamination is impossible).

The dispatch-level API (Block 5 Task 1) is unchanged, both in behavior and
in the ``_records`` mapping it uses.

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
from typing import Dict, Optional, Tuple


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
    """Immutable identity + mutable status of one tracked execution.

    ``sequence`` / ``account_id`` (Block 6 Task 6.5) are set only for the
    account-aware per-order records. A dispatch-level record (Block 5
    Task 1) leaves both ``None``: its identity stays the ``execution_id``
    only, exactly as before.
    """

    execution_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Account-aware per-order identity (Block 6 Task 6.5). ``None`` for the
    # dispatch-level records created by ``register()``.
    sequence: Optional[int] = None
    account_id: Optional[str] = None


@dataclass
class ExecutionTracker:
    """In-memory registry of execution records.

    Pure record keeper: no I/O, no clock reads, no broker calls.
    """

    _records: Dict[str, ExecutionRecord] = field(default_factory=dict)

    # Account-aware per-order records (Block 6 Task 6.5), keyed by the
    # EXISTING dispatch execution_id plus the order's own plan sequence.
    # Kept separate from ``_records`` so the Block 5 dispatch-level API and
    # its mapping are byte-for-byte unchanged.
    _order_records: Dict[Tuple[str, int], ExecutionRecord] = field(
        default_factory=dict
    )

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

    # ------------------------------------------------------------------
    # Account-aware per-order tracking (Block 6 Task 6.5)
    # ------------------------------------------------------------------
    #
    # One independent record per order inside one tracked dispatch
    # execution, keyed by the EXISTING (execution_id, sequence) pair. No new
    # identifier is generated here: the execution_id is the one Block 5
    # already registered for the dispatch, and the sequence is the order's
    # own execution sequence from the plan.

    def register_order(
        self,
        execution_id: str,
        sequence: int,
        account_id: str,
    ) -> ExecutionRecord:
        """Register ONE order of a tracked execution in PENDING status.

        The order keeps its own record for its own account, so two orders of
        two different accounts — or two orders of the SAME account, the same
        broker, or the same symbol — never share a status.

        Args:
            execution_id: The EXISTING dispatch execution id (already
                registered through :meth:`register`).
            sequence: The order's own execution sequence in the plan.
            account_id: The account identity bound to that sequence. It is
                always supplied by the caller (from the plan binding) and is
                never derived, defaulted, or fabricated here.

        Returns:
            The new ``ExecutionRecord`` (``PENDING``) for that order/account.

        Raises:
            ExecutionTrackerError: if ``execution_id`` is not a registered
                execution, ``sequence`` is not a non-negative integer,
                ``account_id`` is not a non-empty/non-whitespace string, the
                same order is registered twice, or the same order is
                re-registered for a different account (fail-closed).
        """
        self._require_registered_execution(execution_id)
        self._require_sequence(sequence)
        self._require_account_id(account_id)

        key = (execution_id, sequence)
        existing = self._order_records.get(key)
        if existing is not None:
            if existing.account_id != account_id:
                raise ExecutionTrackerError(
                    "order execution already tracked for another account: "
                    f"execution_id={execution_id} sequence={sequence} "
                    f"account_id={existing.account_id} "
                    f"(refusing to re-bind it to {account_id})"
                )
            raise ExecutionTrackerError(
                "duplicate order execution: "
                f"execution_id={execution_id} sequence={sequence}"
            )

        record = ExecutionRecord(
            execution_id=execution_id,
            sequence=sequence,
            account_id=account_id,
        )
        self._order_records[key] = record
        return record

    def update_order_status(
        self,
        execution_id: str,
        sequence: int,
        status: ExecutionStatus,
    ) -> ExecutionRecord:
        """Update the status of ONE order of a tracked execution.

        Only the record of ``(execution_id, sequence)`` is touched; every
        other order record — including orders of the same account, the same
        broker, or the same symbol — stays exactly as it was.

        Raises:
            ExecutionTrackerError: if the order is not tracked or ``status``
                is not an ``ExecutionStatus`` (fail-closed).
        """
        record = self.get_order_record(execution_id, sequence)
        if not isinstance(status, ExecutionStatus):
            raise ExecutionTrackerError(
                "status must be an ExecutionStatus"
            )
        record.status = status
        return record

    def get_order_record(
        self,
        execution_id: str,
        sequence: int,
    ) -> ExecutionRecord:
        """Return the record of ONE order of a tracked execution.

        Raises:
            ExecutionTrackerError: if the order is not tracked (fail-closed).
        """
        self._require_sequence(sequence)
        self._require_execution_id(execution_id)
        record = self._order_records.get((execution_id, sequence))
        if record is None:
            raise ExecutionTrackerError(
                "unknown order execution: "
                f"execution_id={execution_id} sequence={sequence}"
            )
        return record

    def get_order_status(
        self,
        execution_id: str,
        sequence: int,
    ) -> ExecutionStatus:
        """Return the current status of ONE order of a tracked execution.

        Raises:
            ExecutionTrackerError: if the order is not tracked.
        """
        return self.get_order_record(execution_id, sequence).status

    def order_records(self, execution_id: str) -> Dict[int, ExecutionRecord]:
        """Return ``{sequence: record}`` for one tracked execution.

        The mapping is a copy, so reading it never mutates the tracker.
        """
        return {
            sequence: record
            for (exec_id, sequence), record in self._order_records.items()
            if exec_id == execution_id
        }

    # -- validation helpers ----------------------------------------------

    def _require_registered_execution(self, execution_id: str) -> None:
        """Fail-closed unless ``execution_id`` is a registered execution."""
        self._require_execution_id(execution_id)
        if execution_id not in self._records:
            raise ExecutionTrackerError(
                f"unknown execution_id: {execution_id} "
                "(an order can only be tracked under a registered execution)"
            )

    @staticmethod
    def _require_execution_id(execution_id: str) -> None:
        """Fail-closed unless ``execution_id`` can be used as a key."""
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ExecutionTrackerError(
                "execution_id must be a non-empty string"
            )

    @staticmethod
    def _require_sequence(sequence: int) -> None:
        """Fail-closed unless ``sequence`` is a non-negative integer."""
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise ExecutionTrackerError("sequence must be an integer")
        if sequence < 0:
            raise ExecutionTrackerError("sequence must be >= 0")

    @staticmethod
    def _require_account_id(account_id: str) -> None:
        """Fail-closed unless ``account_id`` is a real account identity."""
        if not isinstance(account_id, str) or not account_id.strip():
            raise ExecutionTrackerError(
                "account_id must be a non-empty string"
            )
