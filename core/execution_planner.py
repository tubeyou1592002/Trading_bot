"""
Block 1 — Execution Planner.

The Planner converts a valid logical order instruction into the existing
immutable ``ExecutionPlan`` contract defined in Block 0
(``core.dispatch_contracts.py``).

Dispatch boundary (Block 0/1):

    Trigger
        │
        ▼
    Planner (Block 1)  <-- this module
        │
        ▼
    Dispatch Core (Block 2)
        │
        ▼
    existing M6-A … M6-E  (OrderEngine.prepare / execute)
        │
        ▼
    Broker

The Planner owns ONLY the planning step. It is:

  * broker-independent (references brokers by name only),
  * deterministic,
  * side-effect free (never contacts a broker, never submits an order),
  * scheduling-free (no timers, no polling, no async dispatch).

It does NOT:
  * implement scheduling, timers, polling, async dispatch, execution
    tracking, latency measurement, multi-account execution, multi-broker
    execution, or order splitting (M6-F).
  * call any Broker API or submit any order.
  * enable live trading.
  * modify ``core/dispatch_contracts.py`` or M6-A through M6-E.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.dispatch_contracts import ExecutionPlan


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PlannerValidationError(ValueError):
    """
    Raised when a ``LogicalOrderInstruction`` is invalid or incomplete.

    The Planner is fail-closed: it never silently accepts a malformed
    instruction and it never invents missing fields.
    """


# ---------------------------------------------------------------------------
# Immutable inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedOrder:
    """
    Immutable representation of one planned order, preserving the explicit
    relationship:

        order
          -> account_id
          -> broker_name
          -> sequence
          -> conditions

    ``order`` is the concrete order object (e.g. ``models.order.Order``).
    The Planner does not inspect or validate the order's financial fields;
    that is the Dispatch Core's / M6-A…M6-E responsibility.
    """

    order: Any
    account_id: str
    broker_name: str
    sequence: int
    conditions: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Defensive validation of the immutable record itself.
        if not isinstance(self.account_id, str) or not self.account_id.strip():
            raise PlannerValidationError(
                "PlannedOrder.account_id must be a non-empty string"
            )
        if not isinstance(self.broker_name, str) or not self.broker_name.strip():
            raise PlannerValidationError(
                "PlannedOrder.broker_name must be a non-empty string"
            )
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            raise PlannerValidationError(
                "PlannedOrder.sequence must be an integer"
            )
        if self.sequence < 0:
            raise PlannerValidationError(
                "PlannedOrder.sequence must be >= 0"
            )
        if not isinstance(self.conditions, dict):
            raise PlannerValidationError(
                "PlannedOrder.conditions must be a dict"
            )


@dataclass(frozen=True)
class LogicalOrderInstruction:
    """
    Immutable input to the Execution Planner.

    Contains enough information to describe:

      * plan id
      * orders (as PlannedOrder records)
      * account assignment
      * broker assignment
      * execution sequence
      * execution conditions
    """

    plan_id: str
    orders: List[PlannedOrder] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.plan_id, str) or not self.plan_id.strip():
            raise PlannerValidationError(
                "LogicalOrderInstruction.plan_id must be a non-empty string"
            )
        if not isinstance(self.orders, list):
            raise PlannerValidationError(
                "LogicalOrderInstruction.orders must be a list"
            )
        if not isinstance(self.conditions, dict):
            raise PlannerValidationError(
                "LogicalOrderInstruction.conditions must be a dict"
            )
        # Freeze the mutable defaults so the instruction stays immutable.
        object.__setattr__(self, "orders", tuple(self.orders))
        object.__setattr__(self, "conditions", dict(self.conditions))


# ---------------------------------------------------------------------------
# Execution Planner
# ---------------------------------------------------------------------------


class ExecutionPlanner:
    """
    Convert a ``LogicalOrderInstruction`` into an ``ExecutionPlan``.

    The planner is deterministic and pure: the same instruction always
    produces the same plan, and the planner never contacts a broker or
    submits an order.
    """

    def build_plan(self, instruction: LogicalOrderInstruction) -> ExecutionPlan:
        """
        Validate ``instruction`` and return the existing ``ExecutionPlan``
        contract from Block 0.

        Raises ``PlannerValidationError`` for any invalid or missing
        required field.
        """
        self._validate_instruction(instruction)

        planned_orders: List[PlannedOrder] = list(instruction.orders)

        # Preserve explicit execution order: sort by sequence ascending.
        ordered = sorted(planned_orders, key=lambda po: po.sequence)

        accounts: List[str] = []
        broker_names: List[str] = []
        for po in ordered:
            if po.account_id not in accounts:
                accounts.append(po.account_id)
            if po.broker_name not in broker_names:
                broker_names.append(po.broker_name)

        execution_order: List[int] = [po.sequence for po in ordered]

        # Merge per-order conditions into the plan-level conditions dict.
        # Order conditions are preserved under the "orders" key so the
        # Dispatch Core can inspect them per sequence; plan-level
        # conditions are preserved as-is.
        merged_conditions: Dict[str, Any] = dict(instruction.conditions)
        merged_conditions["orders"] = {
            po.sequence: dict(po.conditions) for po in ordered
        }

        plan = ExecutionPlan(
            orders=[po.order for po in ordered],
            accounts=accounts,
            broker_names=broker_names,
            execution_order=execution_order,
            conditions=merged_conditions,
            plan_id=instruction.plan_id,
            created_at=None,
        )
        return plan

    # -- validation ----------------------------------------------------------

    def _validate_instruction(self, instruction: LogicalOrderInstruction) -> None:
        if not isinstance(instruction, LogicalOrderInstruction):
            raise PlannerValidationError(
                "instruction must be a LogicalOrderInstruction instance"
            )

        if not instruction.orders:
            raise PlannerValidationError(
                "LogicalOrderInstruction.orders must not be empty"
            )

        seen_sequences: set = set()
        for po in instruction.orders:
            if not isinstance(po, PlannedOrder):
                raise PlannerValidationError(
                    "each order must be a PlannedOrder instance"
                )
            if po.sequence in seen_sequences:
                raise PlannerValidationError(
                    f"duplicate execution sequence: {po.sequence}"
                )
            seen_sequences.add(po.sequence)
