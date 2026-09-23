"""
Block UI-4 — Task 1: Order -> LogicalOrderInstruction Adapter.

A small adapter that converts a batch of existing ``Order`` objects into a
``LogicalOrderInstruction`` (the immutable Block 1 input contract).

The adapter intentionally does NOT:
  * validate order fields (``PlannedOrder.order`` is ``Any``; the Planner --
    Block 1 -- and Dispatch Core own order-field validation),
  * clone or mutate the ``Order`` objects,
  * guess ``account_id`` / ``broker_name`` from the order or the symbol,
  * perform login or broker access,
  * dispatch anything,
  * touch execution tracking,
  * introduce any new class or status,
  * invent validation rules.

Validation is delegated entirely to the existing repository contracts
(``PlannedOrder.__post_init__`` / ``LogicalOrderInstruction.__post_init__``
in ``core.execution_planner``): an invalid ``account_id``, ``broker_name``,
or ``plan_id`` raises ``PlannerValidationError`` exactly as those models
already define. Nothing here guesses at new rules.

``conditions`` are left at the real contract defaults (empty dicts) because
the repository defines no other per-order / instruction condition schema;
introducing keys here would be a guess.
"""

from __future__ import annotations

from typing import Any, List

from core.dispatch_contracts import ExecutionPlan
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)


def build_logical_instruction(
    queued_orders: List[Any],
    account_id: str,
    broker_name: str,
    plan_id: str,
) -> LogicalOrderInstruction:
    """
    Convert ``queued_orders`` into one ``LogicalOrderInstruction``.

    Each order is wrapped in a ``PlannedOrder`` with:
      * ``order``      = the exact same Order object (no clone / mutation),
      * ``account_id`` = the passed ``account_id`` (never guessed),
      * ``broker_name``= the passed ``broker_name`` (never guessed),
      * ``sequence``   = the index of the order in ``queued_orders`` (0, 1, 2, ...),
      * ``conditions`` = the real contract default (``{}``).

    The returned ``LogicalOrderInstruction`` carries ``plan_id`` and the
    planned orders. Invalid ``account_id`` / ``broker_name`` / ``plan_id``
    propagate the existing ``PlannerValidationError`` from the contracts.
    """
    planned_orders: List[PlannedOrder] = [
        PlannedOrder(
            order=order,
            account_id=account_id,
            broker_name=broker_name,
            sequence=sequence,
        )
        for sequence, order in enumerate(queued_orders)
    ]

    return LogicalOrderInstruction(
        plan_id=plan_id,
        orders=planned_orders,
    )


def build_instruction_from_queue(
    queue: Any,
    account_id: str,
    broker_name: str,
    plan_id: str,
) -> LogicalOrderInstruction:
    """
    Convert the pending entries of an ``OrderQueue`` into one
    ``LogicalOrderInstruction``.

    Path enforced by this bridge:

        OrderQueue.list_pending()
            -> QueueEntry.order            (exact objects, never cloned)
            -> build_logical_instruction() (existing adapter)
            -> LogicalOrderInstruction

    ``account_id``, ``broker_name`` and ``plan_id`` are taken explicitly
    from the caller; they are never inferred, overridden, or replaced by any
    per-entry bound value. No grouping / splitting of entries by account or
    broker is performed: the queue contents become ONE instruction, exactly
    as the underlying adapter contract requires (one account + one broker per
    batch).

    No dispatch, login, broker, network, UI, or persistence work happens.
    """
    pending = queue.list_pending()
    orders = [entry.order for entry in pending]

    return build_logical_instruction(
        queued_orders=orders,
        account_id=account_id,
        broker_name=broker_name,
        plan_id=plan_id,
    )


def build_execution_plan_from_queue(
    queue: Any,
    account_id: str,
    broker_name: str,
    plan_id: str,
) -> ExecutionPlan:
    """
    Build a real ``ExecutionPlan`` from the pending entries of an
    ``OrderQueue``, using only the existing repository contracts.

    Real path enforced by this function:

        OrderQueue.list_pending()
            -> build_instruction_from_queue()  (Task 3 bridge)
            -> LogicalOrderInstruction         (Block 1 input contract)
            -> ExecutionPlanner.build_plan()   (Block 1 planner)
            -> ExecutionPlan                   (Block 0 contract)

    ``account_id`` and ``broker_name`` are the explicit caller-supplied
    values; they are never inferred from entries, orders, symbols, or the
    broker, and nothing here groups/splits entries by account or broker
    (one batch -> one instruction -> one plan).

    Note on the real planner contract: ``ExecutionPlanner.build_plan``
    stores ``ExecutionPlan.accounts`` as account_id *strings* (even though
    the ``ExecutionPlan.accounts`` annotation refers to Account objects).
    That pre-existing Repository behavior is preserved and is out of scope
    here.

    Note on an empty queue: the real planner rejects an instruction with no
    orders (``PlannerValidationError: LogicalOrderInstruction.orders must
    not be empty``); this function does not invent behavior around it, so
    the planner's existing error propagates as-is.

    No dispatch, login, broker, network, UI, or persistence work happens.
    """
    instruction = build_instruction_from_queue(
        queue,
        account_id=account_id,
        broker_name=broker_name,
        plan_id=plan_id,
    )

    planner = ExecutionPlanner()
    return planner.build_plan(instruction)