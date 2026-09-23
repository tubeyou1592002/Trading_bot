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

from typing import Any, List, Tuple

from core.block5_task4 import DispatchIntegration
from core.dispatch_contracts import DispatchResult, ExecutionPlan
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from core.order_queue import QueueEntry


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


def build_execution_plan_from_selected_entries(
    entries: List[QueueEntry],
    account_id: str,
    broker_name: str,
    plan_id: str,
) -> ExecutionPlan:
    """
    Build a real ``ExecutionPlan`` from a chosen subset of ``QueueEntry``\\ s.

    Real path enforced by this function:

        selected QueueEntry
            -> QueueEntry.order            (exact objects, never cloned)
            -> build_logical_instruction() (existing adapter)
            -> LogicalOrderInstruction
            -> ExecutionPlanner.build_plan()
            -> ExecutionPlan

    Fail-closed binding check: every ``entry`` must carry the exact
    ``account_id`` / ``broker_name`` passed by the caller. If ANY entry has
    a different account or broker, ``ValueError`` is raised before anything
    is built (no plan is produced, nothing is guessed, nothing is grouped or
    split).

    The plan contains ONLY the orders of the selected entries, in the same
    order, bound to the explicit caller-supplied ``account_id`` /
    ``broker_name``. The queue is never touched (no mutation) and the order
    objects are never cloned.

    Note on an empty selection: the real planner rejects an instruction with
    no orders (``PlannerValidationError: LogicalOrderInstruction.orders must
    not be empty``); this function does not invent behavior around it, so the
    planner's existing fail-closed error propagates as-is.

    No dispatch, login, broker, network, UI, or persistence work happens.
    """
    for entry in entries:
        if entry.account_id != account_id or entry.broker_name != broker_name:
            raise ValueError(
                "selected entry is incompatible with the requested binding "
                f"(entry account_id={entry.account_id!r} broker_name="
                f"{entry.broker_name!r} vs requested account_id="
                f"{account_id!r} broker_name={broker_name!r}): "
                "cannot build a single-batch plan from mixed accounts/brokers"
            )

    orders = [entry.order for entry in entries]

    instruction = build_logical_instruction(
        queued_orders=orders,
        account_id=account_id,
        broker_name=broker_name,
        plan_id=plan_id,
    )

    planner = ExecutionPlanner()
    return planner.build_plan(instruction)


def dispatch_selected_entries(
    entries: List[QueueEntry],
    dispatch_integration: DispatchIntegration,
    account_id: str,
    broker_name: str,
    plan_id: str,
) -> Tuple[ExecutionPlan, str, DispatchResult]:
    """
    Build ONE ``ExecutionPlan`` from selected ``QueueEntry``\\ s and dispatch
    it through the existing ``DispatchIntegration``.

    Real path enforced by this bridge:

        selected QueueEntry
            -> build_execution_plan_from_selected_entries()  (Task 7 adapter)
            -> ExecutionPlan                                  (Block 0 contract)
            -> DispatchIntegration.dispatch(plan)             (Block 5 connector)
            -> DispatchResult

    The dispatch is issued with NO caller-supplied ``execution_id`` so the
    integration itself owns the execution identity. Immediately after the
    dispatch, ``dispatch_integration.last_execution_id`` is read and the
    exactly three values are returned, unchanged:

        (plan, execution_id, result)

    ``plan_id`` is NEVER used as an execution id, and no execution id is
    generated here. Any lasting ``execution_id`` -> entries relationship is
    the caller's responsibility; nothing is recorded or persisted by this
    bridge.

    Fail-closed: if the dispatch did not issue an execution (a guard /
    Stop Signal bypassed it, so ``dispatch_integration.last_execution_id``
    is ``None``), ``ValueError`` is raised and no id is fabricated.

    No queue mutation, no tracker writes, and no broker / network / UI work
    is performed here beyond the dispatch itself.
    """
    plan = build_execution_plan_from_selected_entries(
        entries,
        account_id=account_id,
        broker_name=broker_name,
        plan_id=plan_id,
    )

    result = dispatch_integration.dispatch(plan)

    execution_id = dispatch_integration.last_execution_id
    if execution_id is None:
        raise ValueError(
            "dispatch did not issue an execution "
            "(dispatch_integration.last_execution_id is None); "
            "plan.plan_id is never used as an execution id"
        )

    return plan, execution_id, result
