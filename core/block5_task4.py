"""
Block 5 — Task 4: Real Dispatch Integration (Tracking + Stop Signal).

This module connects the Block 5 components that already exist:

  - ``ExecutionTracker``        (Task 1 — ``core/execution_tracker.py``)
  - ``collect_result(...)``     (Task 2 — ``core/block5_task2.py``)
  - ``StopSignal``              (Task 3 — ``core/block5_task3.py``)

...to the **real, existing** dispatch path, without modifying it:

  - Block 2 ``DispatchCore.dispatch(plan)`` (``core/dispatch_core.py``)
  - Block 4 ``connect_plan_to_dispatch(...)`` (``core/block4_task3.py``)
  - Block 3 Timed / Burst dispatch (``core/timed_dispatch_*``) — the
    Timed/Burst path issues its dispatches through the same existing
    ``DispatchCore.dispatch(plan)`` entry point.

The integration adds NO new dispatch mechanism. It is a thin, opt-in
boundary object that is duck-type compatible with the Dispatch Core
(``dispatch(plan)``), so the existing Block 4 connector can pass a plan
through it unchanged.

Dispatch boundary (Block 5, Task 4 level):

    SEND PATH                                    RESULT PATH
    ---------                                    -----------

    Block 3 (Timed / Burst)                      DispatchResult (late,
    Block 4 (Event-Driven)                       possibly out of order)
        │  connect_plan_to_dispatch(...)              │
        ▼                                             ▼
    DispatchIntegration.dispatch(plan)           DispatchIntegration.record_result(
        │                                             │   execution_id, result)
        │  guard: is the Stop Signal active?          │
        ├ STOP  → no send (mode="STOPPED")            │   collect_result(...) (Task 2)
         ALLOW                                       ▼
             register the new execution (PENDING)  ExecutionTracker       (Task 1)
             │                                        │
             ▼                                        ▼
    DispatchCore.dispatch(plan)  (Block 2,       StopSignal.observe(...) (Task 3)
        │                         unchanged)
        ▼
    existing M6-A … M6-E  (OrderEngine.prepare / execute)
        │
        ▼
    Broker

Absolute rule (Block 5 goal): **sending never waits for the result of a
previous order.** The send path (``dispatch``) contains no result logic at
all: it only (a) consults the Stop Signal, (b) registers a new execution as
PENDING, and (c) delegates to ``DispatchCore.dispatch(plan)``. Results are
fed in independently through ``record_result`` and may arrive in any order,
for any execution, at any time.

Behavior:

  - Stop Signal inactive (the default: ``StopSignal(enabled=False)``):
    the guard returns ALLOW and the dispatch is delegated exactly as it
    would be without the integration.
  - Stop Signal active: the guard returns STOP. ``DispatchCore.dispatch``
    is NOT called, no new order is sent, no previously sent order is
    cancelled or modified, and no execution is registered. The returned
    ``DispatchResult`` carries ``mode=STOPPED_MODE`` ("STOPPED").
  - Every dispatch that IS issued gets its own execution record
    (``PENDING``) before the order is sent, so the result path can always
    record it independently (one execution per dispatch call).
  - The result path is strictly ordered as mandated:
    ``DispatchResult -> collect_result -> ExecutionTracker ->
    StopSignal.observe``. The Stop Signal semantics themselves are
    untouched: they live entirely in ``core/block5_task3.py``.
  - Fail-closed: an invalid plan, an invalid execution_id, or a duplicate
    execution_id raises before anything is dispatched. A synthetic
    ``STOPPED`` result is rejected by the result path: a bypassed dispatch
    has no execution, so it can never be attributed to one.

Block 6 Task 6.5 — Account-Aware Tracking (additive extension of the
Result Path):

The Block 5 Result Path above records ONE result per dispatch execution.
Block 6 Task 6.5 adds the account-aware layer required for multi-account
execution: **every order of a dispatch keeps its own execution record and
its own status**, so that ``REGISTERED`` for the order of one account can
never be confused with the status of another order — not for the same
account, not for the same broker, not for the same symbol.

    DispatchIntegration.dispatch(plan)
        │  guard: is the Stop Signal active?
        ├── resolve the Account binding of EVERY sequence  (fail-closed)
        │      plan.conditions["binding"][sequence]["account_id"]
        ├── register the dispatch execution                (PENDING)
        ├── register ONE order record per sequence          (PENDING)
        └── DispatchCore.dispatch(plan)   (Block 2, unchanged)

    DispatchIntegration.record_order_result(execution_id, sequence, result)
        │  result is the existing per-order ``OrderExecutionResult``
        ▼  produced by the DispatchCore path for THAT sequence
    ExecutionTracker.update_order_status(execution_id, sequence, status)

Rules of the account-aware layer (Task 6.5):

  * NO parallel execution id is created here. An order record reuses the
    EXISTING dispatch ``execution_id`` and is keyed by it together with the
    order's own plan ``sequence``; the ``account_id`` is carried along as
    the higher-level identity of that order.
  * ``account_id`` is read ONLY from the binding of that same sequence
    (``plan.conditions["binding"][sequence]["account_id"]``). There is no
    fallback whatsoever: no ``plan.accounts[0]``, no symbol / ``nsc_id``, no
    broker, no order index or position, no previously seen account.
  * One result touches exactly one record. Recording the result of one order
    never changes the status of any other order.
  * Fail-closed: a missing / malformed / blank account binding, an
    unregistered execution, an unknown sequence, or a result of the wrong
    type raises before anything is recorded.
  * The per-order path never touches the Stop Signal: Stop / Brake policy is
    Block 6 Task 6.6 and stays entirely out of this module.
  * The Block 5 dispatch-level path (``register`` / ``record_result`` /
    ``StopSignal``) is unchanged; the account-aware layer is strictly
    additive.

Explicitly OUT of scope for this module:
  - Any scheduler, timer, polling loop, real clock, thread, or sleep.
  - Any broker implementation, broker adapter, or broker/exchange API call.
  - Any persistence, file I/O, or network access.
  - Any new dispatch path or new routing/validation logic.
  - Any modification to ``DispatchCore``, ``OrderEngine``, M6-A … M6-E,
    Block 1/3/4, ``collect_result``, ``StopSignal``, ``DispatchResult``,
    ``ExecutionPlan``, or the broker layer. ``ExecutionTracker`` is only
    EXTENDED by the additive Block 6 Task 6.5 account-aware layer described
    above; its Block 5 API and behavior stay unchanged.
  - Cancelling / stopping orders that were already sent (out of Block 5).
  - Fill / partial fill tracking (out of Block 5).
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional
from uuid import uuid4

from core.block5_task2 import collect_result
from core.block5_task3 import StopSignal
from core.dispatch_contracts import DispatchResult, ExecutionPlan
from core.execution_tracker import ExecutionStatus, ExecutionTracker
from core.order_engine import OrderExecutionResult


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


STOPPED_MODE = "STOPPED"
"""``DispatchResult.mode`` used when the guard bypassed a dispatch.

The string is deliberately distinct from the Dispatch Core's own modes
(``ALL_PROCESSED`` / ``NO_ORDERS`` / ``BLOCKED``) because a bypassed
dispatch is not a dispatch attempt at all: no order was sent.
"""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DispatchIntegrationError(ValueError):
    """Raised for invalid Block 5 Task 4 integration usage (fail-closed)."""


# ---------------------------------------------------------------------------
# Send-path guard
# ---------------------------------------------------------------------------


class GuardDecision(str, Enum):
    """Explicit outcome of the send-path guard.

    ``ALLOW`` — a new dispatch may be issued.
    ``STOP``  — the Stop Signal is active; no new dispatch may be issued.
    """

    ALLOW = "ALLOW"
    STOP = "STOP"


def stop_guard(stop_signal: StopSignal) -> GuardDecision:
    """Decide whether a NEW dispatch may be issued.

    This is the ONLY condition the send path evaluates before a new
    dispatch: whether the Stop Signal is active. No previous order
    result is ever awaited here.

    Args:
        stop_signal: The existing Block 5 Task 3 ``StopSignal``.

    Returns:
        ``GuardDecision.STOP`` when the Stop Signal is active, otherwise
        ``GuardDecision.ALLOW``.

    Raises:
        DispatchIntegrationError: if ``stop_signal`` is not a ``StopSignal``
            (fail-closed).
    """
    if not isinstance(stop_signal, StopSignal):
        raise DispatchIntegrationError("stop_signal must be a StopSignal")

    return GuardDecision.STOP if stop_signal.is_active else GuardDecision.ALLOW


# ---------------------------------------------------------------------------
# Account binding (Block 6 Task 6.5)
# ---------------------------------------------------------------------------


def bound_account_id(plan: ExecutionPlan, sequence: int) -> str:
    """Account identity bound to ``sequence`` — from the plan binding ONLY.

    The single permitted source is exactly::

        plan.conditions["binding"][sequence]["account_id"]

    No fallback of any kind exists: not ``plan.accounts[0]``, not the symbol
    / ``nsc_id`` of the order, not the broker, not the position or index of
    the order, and not a previously seen account. An order whose account
    cannot be proven from its OWN binding is therefore never tracked
    (fail-closed).

    Args:
        plan: The ``ExecutionPlan`` carrying the planning-stage binding.
        sequence: The order's execution sequence in that plan.

    Returns:
        The bound ``account_id`` (a non-empty, non-whitespace string).

    Raises:
        DispatchIntegrationError: if the plan, the ``binding`` mapping, the
            entry of this sequence, or its ``account_id`` is missing,
            malformed, or blank (fail-closed).
    """
    if not isinstance(plan, ExecutionPlan):
        raise DispatchIntegrationError("plan must be an ExecutionPlan")
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        raise DispatchIntegrationError("sequence must be an integer")

    conditions = plan.conditions
    if not isinstance(conditions, dict):
        raise DispatchIntegrationError(
            "plan.conditions must be a mapping "
            f"(sequence {sequence}); cannot resolve the Account binding."
        )

    binding = conditions.get("binding")
    if not isinstance(binding, dict):
        raise DispatchIntegrationError(
            "plan.conditions['binding'] is missing or malformed "
            f"(sequence {sequence}); cannot resolve the Account binding."
        )

    entry = binding.get(sequence)
    if not isinstance(entry, dict):
        raise DispatchIntegrationError(
            f"no binding for sequence {sequence} in "
            "plan.conditions['binding'] (fail-closed)."
        )

    account_id = entry.get("account_id")
    if not isinstance(account_id, str) or not account_id.strip():
        raise DispatchIntegrationError(
            f"account_id is missing or invalid for sequence {sequence} "
            "in the plan binding (fail-closed)."
        )

    return account_id


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class DispatchIntegration:
    """Opt-in boundary that connects Tracking + Stop Signal to dispatch.

    The object exposes ``dispatch(plan)``, so it is duck-type compatible
    with the existing Block 2 ``DispatchCore`` and can be handed to the
    existing Block 4 connector unchanged:

        integration = DispatchIntegration(
            dispatch_core=existing_dispatch_core,
            tracker=tracker,
            stop_signal=StopSignal(enabled=True),
        )

        # SEND PATH — existing Block 4 connection point, unchanged:
        outcome = connect_plan_to_dispatch(plan, integration)

        # RESULT PATH — independent, may arrive later / out of order:
        integration.record_result(integration.last_execution_id, result)

    Without this integration, existing callers keep behaving exactly as
    before: they keep passing their own ``DispatchCore`` to
    ``connect_plan_to_dispatch`` or calling ``DispatchCore.dispatch``
    directly.

    Attributes:
        dispatch_core: The existing Dispatch Core whose ``dispatch(plan)``
            entry point is used unchanged.
        tracker: The ExecutionTracker (Task 1) used for execution records.
        stop_signal: The StopSignal (Task 3) used as the send-path gate.
    """

    def __init__(
        self,
        dispatch_core,
        tracker: Optional[ExecutionTracker] = None,
        stop_signal: Optional[StopSignal] = None,
    ) -> None:
        """Build the integration around an existing Dispatch Core.

        Args:
            dispatch_core: An existing object exposing ``dispatch(plan)``
                (normally the Block 2 ``DispatchCore``). It is never
                created here: the caller owns the Dispatch Core instance.
            tracker: Existing ``ExecutionTracker``. When omitted, a fresh
                empty tracker is created (still the Task 1 component).
            stop_signal: Existing ``StopSignal``. When omitted, the Task 3
                default ``StopSignal(enabled=False)`` is used, i.e. the
                gate never activates (continuous dispatch — the fail-open
                default of Block 5 Task 3).

        Raises:
            DispatchIntegrationError: if ``dispatch_core`` does not expose
                a callable ``dispatch``, or ``tracker`` / ``stop_signal``
                have the wrong type (fail-closed).
        """
        if not callable(getattr(dispatch_core, "dispatch", None)):
            raise DispatchIntegrationError(
                "dispatch_core must expose a callable dispatch(plan)"
            )
        if tracker is not None and not isinstance(tracker, ExecutionTracker):
            raise DispatchIntegrationError(
                "tracker must be an ExecutionTracker"
            )
        if stop_signal is not None and not isinstance(stop_signal, StopSignal):
            raise DispatchIntegrationError("stop_signal must be a StopSignal")

        self.dispatch_core = dispatch_core
        self.tracker = tracker if tracker is not None else ExecutionTracker()
        self.stop_signal = (
            stop_signal if stop_signal is not None else StopSignal()
        )

        self._last_execution_id: Optional[str] = None

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def is_stopped(self) -> bool:
        """Return True while the Stop Signal is active.

        While stopped, every NEW dispatch is bypassed; nothing else
        changes (already sent orders are untouched).
        """
        return self.stop_signal.is_active

    @property
    def last_execution_id(self) -> Optional[str]:
        """Return the execution_id of the last dispatch that was issued.

        ``None`` until the first dispatch passes the guard. A dispatch
        that was bypassed by the Stop Signal does NOT update this value
        (no execution exists for it).
        """
        return self._last_execution_id

    # ------------------------------------------------------------------
    # SEND PATH
    # ------------------------------------------------------------------

    def dispatch(
        self,
        plan: ExecutionPlan,
        execution_id: Optional[str] = None,
    ) -> DispatchResult:
        """Send path: guard the new dispatch, then delegate it unchanged.

        Steps:

          1. Guard — consult ONLY the Stop Signal (``stop_guard``).
             * STOP -> return a ``mode=STOPPED_MODE`` result and never
               touch the Dispatch Core, the tracker, or any prior order.
             * ALLOW -> continue.
          2. Resolve the Account binding of EVERY sequence of the plan
             (Block 6 Task 6.5) — before anything is registered or sent.
             * invalid / missing / blank binding -> raise, nothing is
               registered and nothing is dispatched (fail-closed).
          3. Register the NEW execution in the tracker as ``PENDING``
             (no waiting for any previous order result).
          4. Register ONE account-aware order record (``PENDING``) per
             sequence, keyed by that same execution id + the order's own
             sequence, so each order of each account is tracked separately.
          5. Delegate to the existing ``DispatchCore.dispatch(plan)`` and
             return its ``DispatchResult`` unchanged.

        The returned ``DispatchResult`` is NOT processed here: the result
        path (``record_result``) is independent and may be called later,
        in any order.

        Args:
            plan: The ``ExecutionPlan`` to dispatch (Block 0 contract),
                normally produced by Block 1 / Block 4 Task 2.
            execution_id: Optional execution id for this dispatch. When
                omitted (the Block 4 connector path, which passes only the
                plan), a unique id is generated by the integration and is
                exposed through ``last_execution_id``.

        Returns:
            The ``DispatchResult`` of the dispatch, or a fail-closed
            ``mode=STOPPED_MODE`` result when the guard stopped it.

        Raises:
            DispatchIntegrationError: if ``plan`` is not an
                ``ExecutionPlan``, ``execution_id`` is provided but is not a
                non-empty string, or the Account binding of any sequence is
                missing / malformed (fail-closed).
            ExecutionTrackerError: if ``execution_id`` is already
                registered (fail-closed, raised before anything is sent).
        """
        if not isinstance(plan, ExecutionPlan):
            raise DispatchIntegrationError("plan must be an ExecutionPlan")

        # ---- 1) GUARD (send path): only the Stop Signal is consulted ----
        if stop_guard(self.stop_signal) is GuardDecision.STOP:
            return self._stopped_result()

        # ---- 2) Resolve the Account binding of EVERY order (fail-closed) --
        # Read exclusively from plan.conditions["binding"][sequence]
        # ["account_id"]; no account is ever guessed. Resolving first means
        # an untrackable plan is never dispatched and never leaves a record.
        account_bindings = self._plan_account_bindings(plan)

        # ---- 3) Register the NEW execution (PENDING) --------------------
        # Non-blocking tracking only: nothing is awaited here.
        self._last_execution_id = self._register_execution(execution_id)

        # ---- 4) Register ONE order record per sequence (account-aware) ---
        self._register_plan_orders(self._last_execution_id, account_bindings)

        # ---- 5) Delegate to the existing Block 2 entry point ------------
        # DispatchCore.dispatch is used unchanged; its DispatchResult is
        # returned as-is and is not consumed by the send path.
        return self.dispatch_core.dispatch(plan)

    # ------------------------------------------------------------------
    # RESULT PATH
    # ------------------------------------------------------------------

    def record_result(
        self,
        execution_id: str,
        result: DispatchResult,
    ) -> ExecutionStatus:
        """Result path: record one dispatch result, independently.

        Pipeline (unchanged Block 5 order):

            DispatchResult -> collect_result(...)  (Task 2)
                -> ExecutionTracker               (Task 1)
                -> StopSignal.observe(...)         (Task 3)

        May be called at any time, for any execution that was issued, in
        any order — results are per-execution and fully independent. A
        failure never stops the send path by itself; only the Stop Signal
        can gate future dispatches.

        Args:
            execution_id: The id of the execution to update. Must be an
                execution that was issued (registered) by this integration.
            result: The ``DispatchResult`` produced by the dispatch path.

        Returns:
            The new ``ExecutionStatus`` recorded on the execution
            (``REGISTERED`` for a successful result, ``FAILED`` otherwise).

        Raises:
            DispatchIntegrationError: if ``result`` carries
                ``mode=STOPPED_MODE``. Such a result is synthetic: the
                dispatch was bypassed, so it has no execution and must
                never be attributed to an execution id (in particular not
                to a previously issued one) — fail-closed.
            ExecutionTrackerError: if ``execution_id`` is unknown/invalid
                or ``result`` is not a ``DispatchResult`` (fail-closed; the
                tracker and the Stop Signal are then left unchanged).
        """
        # A STOPPED result is synthetic: it means no dispatch was issued, so
        # it has no execution of its own. It must never be attached to an
        # execution id — otherwise a bypassed dispatch could overwrite the
        # status of a real (previously issued) execution.
        if isinstance(result, DispatchResult) and result.mode == STOPPED_MODE:
            raise DispatchIntegrationError(
                "a STOPPED result has no execution and cannot be recorded: "
                "the result path only accepts dispatches that were issued"
            )

        status: ExecutionStatus = collect_result(
            self.tracker, execution_id, result
        )
        self.stop_signal.observe(result)
        return status

    # ------------------------------------------------------------------
    # ACCOUNT-AWARE ORDER RESULT PATH (Block 6 Task 6.5)
    # ------------------------------------------------------------------

    def record_order_result(
        self,
        execution_id: str,
        sequence: int,
        result: OrderExecutionResult,
    ) -> ExecutionStatus:
        """Record ONE order result of ONE issued execution, independently.

        Pipeline::

            OrderExecutionResult (DispatchCore path, per sequence)
                -> the order record of (execution_id, sequence)
                -> ExecutionTracker.update_order_status

        The result belongs to the order identified by ``sequence`` and may
        arrive at any time, before or after the results of the other orders
        of the same dispatch. It is applied to that SINGLE record only: the
        status of every other order stays exactly as it was — including
        orders of the same account, the same broker, or the same symbol, and
        including orders of other dispatch executions.

        The account identity is NOT taken from ``result``: it was fixed when
        the order was registered, from the plan binding of that sequence.

        The Stop Signal is deliberately neither consulted nor updated here:
        the per-order path is pure tracking (Stop / Brake policy is Block 6
        Task 6.6) and a per-order result never gates future dispatches.

        Args:
            execution_id: The id of an execution issued by this integration
                (the dispatch that contained this order).
            sequence: The order's own execution sequence in that plan.
            result: The existing ``OrderExecutionResult`` produced by the
                DispatchCore path for that same sequence.

        Returns:
            The new ``ExecutionStatus`` of that order (``REGISTERED`` for a
            successful result, ``FAILED`` otherwise).

        Raises:
            DispatchIntegrationError: if ``result`` is not an
                ``OrderExecutionResult`` (fail-closed; nothing recorded).
            ExecutionTrackerError: if ``execution_id`` is unknown, the order
                of that sequence is not tracked, or ``execution_id`` /
                ``sequence`` is invalid (fail-closed; nothing recorded).
        """
        if not isinstance(result, OrderExecutionResult):
            raise DispatchIntegrationError(
                "result must be an OrderExecutionResult (the per-order "
                "result produced by the DispatchCore path)"
            )

        status: ExecutionStatus = (
            ExecutionStatus.REGISTERED
            if result.success
            else ExecutionStatus.FAILED
        )

        # Only the record of THIS order/account is touched.
        return self.tracker.update_order_status(
            execution_id, sequence, status
        ).status

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _register_execution(self, execution_id: Optional[str]) -> str:
        """Register the execution for a dispatch that is about to be issued.

        Returns the execution_id actually registered. When the caller does
        not supply one, a unique generated id is used. Registration is
        fail-closed and happens strictly BEFORE the order is dispatched:
        an invalid or duplicate id therefore prevents the dispatch instead
        of sending an untrackable order.
        """
        if execution_id is None:
            new_id = f"exec-{uuid4()}"
        else:
            if not isinstance(execution_id, str) or not execution_id.strip():
                raise DispatchIntegrationError(
                    "execution_id must be a non-empty string when provided"
                )
            new_id = execution_id

        # ExecutionTracker.register raises ExecutionTrackerError on a blank
        # or duplicate id; nothing has been dispatched at this point.
        self.tracker.register(new_id)
        return new_id

    def _plan_account_bindings(self, plan: ExecutionPlan) -> Dict[int, str]:
        """Resolve the Account identity of EVERY order of the plan.

        Each ``account_id`` is read exclusively from that sequence's binding
        (see :func:`bound_account_id`). The first invalid binding aborts the
        whole dispatch — before any execution or order record is created —
        so a plan whose orders cannot be proven to belong to their accounts
        is never dispatched untracked (fail-closed).

        Returns:
            ``{sequence: account_id}`` for every sequence of the plan, in
            ``plan.execution_order`` order.
        """
        execution_order = plan.execution_order
        if not execution_order:
            # DispatchCore treats a missing / empty execution order as a
            # dispatch-level failure; nothing to bind here.
            return {}
        if not isinstance(execution_order, (list, tuple)):
            raise DispatchIntegrationError(
                "plan.execution_order must be a list of sequences"
            )

        return {
            sequence: bound_account_id(plan, sequence)
            for sequence in execution_order
        }

    def _register_plan_orders(
        self,
        execution_id: str,
        account_bindings: Dict[int, str],
    ) -> None:
        """Register ONE PENDING order record per sequence (account-aware).

        The record reuses the EXISTING dispatch ``execution_id`` together
        with the order's own sequence as its key — no parallel identifier is
        created — and carries the bound ``account_id`` as the higher-level
        identity of that order. Registration is fail-closed via the tracker.
        """
        for sequence, account_id in account_bindings.items():
            self.tracker.register_order(execution_id, sequence, account_id)

    def _stopped_result(self) -> DispatchResult:
        """Fail-closed result for a dispatch bypassed by the Stop Signal.

        No order was sent (``sent=False``) and the Dispatch Core was never
        invoked, so there is no trace_id and no order count.
        """
        return DispatchResult(
            success=False,
            sent=False,
            mode=STOPPED_MODE,
            message=(
                "Dispatch skipped: Stop Signal is active. No new order was "
                "sent and no previously sent order was cancelled or modified."
            ),
            broker_name=None,
            order_count=0,
            trace_id=None,
        )