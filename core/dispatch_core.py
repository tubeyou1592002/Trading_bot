"""
Block 2 — Dispatch Core / Low-Latency Engine.

The Dispatch Core receives an ``ExecutionPlan`` from the Planner (Block 1)
and dispatches the orders through the existing ``OrderEngine`` path, keeping
all M6-A … M6-E preflight gates intact.

Dispatch boundary (Block 0/1/2):

    Trigger
        │
        ▼
    Planner (Block 1)
        │
        ▼
    Dispatch Core (Block 2)   <-- this module
        │
        ▼
    existing M6-A … M6-E  (OrderEngine.prepare / execute)
        │
        ▼
    Broker

Key responsibilities (Block 2 contract):
    - Receive an ``ExecutionPlan`` from Block 1.
    - Preserve the explicit order -> account -> broker binding that the
      Planner already established. It is carried from the planning stage via
      ``plan.conditions["binding"]`` (per sequence). The Dispatch Core NEVER
      re-selects, re-resolves, rebalances, or invents accounts or brokers.
    - Stay compatible with the actual Block 1 output: ``plan.accounts`` is a
      list of account_id strings. When the plan carries only the account_id
      (no resolved ``Account`` object), the exact binding is preserved and
      the order is BLOCKED fail-closed — no Account is ever fabricated and
      ``broker.get_account()`` is never called.
    - Resolve broker names to existing instances only through
      ``BrokerManager`` (no new sessions, no broker lifecycle changes).
    - Resolve instruments only through the existing ``InstrumentProvider``
      path (via ``OrderEngine.execute_by_ins_code``). It never constructs
      broker-specific payloads, headers, or auth tokens.
    - Build and consume the normalized ``BrokerDispatchRequest`` envelope
      (Block 0 contract) as the real conduit of the dispatch path: the
      routing stage builds it, the execution stage consumes it.
    - Keep every order on the existing ``OrderEngine`` execution path so
      M6-A (identity + trading state), M6-B (price/quantity), M6-C
      (BUY capacity), M6-D (SELL capacity), and M6-E (unified capacity)
      all still run unchanged.
    - Stay dry-run by default: ``live`` is always False here; live trading
      remains disabled until Block 10 and explicit human approval.
    - Fail closed: any exception during dispatch produces
      ``DispatchResult(success=False, mode="BLOCKED", ...)``.
    - Record base timestamps (dispatch start/end) for Block 8 latency
      analysis.
    - Provide full traceability via ``trace_id``.

Explicitly NOT implemented here (deferred to their blocks):
    - Scheduler / timer / polling / event bus ............... Blocks 3/4
    - Multi-account execution coordination ................... Block 6
    - Multi-broker routing logic ............................. Block 7
    - Latency analysis ....................................... Block 8
      (base timestamps only are recorded in this block)
    - Order splitting (M6-F) .................................. Deferred
    - Real / live trading .................................... Block 10

The Dispatch Core does NOT touch ``core/dispatch_contracts.py`` and does
NOT modify M6-A … M6-E or any Broker implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from brokers.manager import BrokerManager
from core.dispatch_contracts import (
    BrokerDispatchRequest,
    DispatchResult,
    ExecutionPlan,
)
from core.order_engine import OrderEngine
from models.account import Account


logger = logging.getLogger(__name__)


@dataclass
class DispatchTrace:
    """
    Internal per-dispatch tracing record.

    Holds the base timestamps required by the Block 2 contract
    (dispatch start + end) and the per-order execution results.
    ``end_time`` is set once the dispatch attempt for the plan is over.
    """

    trace_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    results: List[Tuple[int, "OrderExecutionResult"]] = field(default_factory=list)


class DispatchCore:
    """
    The shared execution core of the Dispatch Engine (Block 2).

    API:

        core.dispatch(plan) -> DispatchResult

    ``dispatch`` iterates ``plan.execution_order`` (ascending), reads the
    per-order account_id / broker_name binding preserved by the Planner
    (``plan.conditions["binding"]``), resolves the exact broker instance and
    instrument provider, builds the normalized ``BrokerDispatchRequest``
    envelope, and delegates to the existing ``OrderEngine.execute_by_ins_code``
    path through that envelope. Per-order results are collected and summarized
    into a single ``DispatchResult``.
    """

    def __init__(
        self,
        broker_manager: Optional[BrokerManager] = None,
    ):
        self.broker_manager = broker_manager or BrokerManager()
        self.order_engine = OrderEngine()
        # The Block 2 contract is strict: dry-run only, live trading is
        # always False. This instance flag exists so callers can never
        # accidentally enable live dispatch (Block 10 owns that switch).
        self.live_trading_enabled = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dispatch(self, plan: ExecutionPlan) -> DispatchResult:
        """
        Execute an ``ExecutionPlan`` through the existing OrderEngine path.

        Guards:
        - Fail-closed: any unexpected exception -> success=False, mode=BLOCKED.
        - Dry-run only: ``live`` is always False.
        - No broker payload construction happens in this core.

        Returns a ``DispatchResult`` describing the overall attempt.
        """
        trace_id = str(uuid4())
        start_time = datetime.now()

        # Block 0 contract: an empty plan is a legitimate no-op dispatch.
        if not plan.orders:
            return DispatchResult(
                success=True,
                sent=False,
                mode="NO_ORDERS",
                message="No orders to dispatch",
                order_count=0,
                trace_id=trace_id,
            )

        results: List[Tuple[int, "OrderExecutionResult"]] = []
        try:
            if not plan.execution_order:
                raise ValueError(
                    "plan.execution_order must not be empty"
                )

            # ---- Pre-resolve every broker referenced by the plan --------
            # The Planner already chose the exact brokers (Block 1).
            broker_instances: Dict[str, object] = {}
            for broker_name in plan.broker_names:
                broker_instances[broker_name] = self.broker_manager.get(broker_name)

            # ---- Execute each order exactly once, in plan order --------
            for sequence in plan.execution_order:
                order, account_id, broker_name = self._plan_item(plan, sequence)
                if broker_name not in broker_instances:
                    raise ValueError(
                        f"Unknown broker for sequence {sequence}: {broker_name}"
                    )

                broker = broker_instances[broker_name]

                # The exact Account -> Broker target from planning is kept.
                # Block 1 produces ``plan.accounts`` as account_id strings;
                # the bound Account object (if any) is used as-is. When the
                # plan carries only the account_id, nothing is invented: the
                # order is BLOCKED fail-closed with the binding intact.
                account = self._plan_account(plan, account_id)
                if account is None:
                    result = self._blocked_no_account(
                        order=order,
                        account_id=account_id,
                        broker_name=broker_name,
                        sequence=sequence,
                    )
                    results.append((sequence, result))
                    self._log_order(sequence, result, trace_id)
                    continue

                # Resolve the instrument through the existing
                # InstrumentProvider path (Block 2 sequence step b).
                provider = self.broker_manager.get_instrument_provider(broker_name)
                instrument = self._resolve_instrument(provider, order.nsc_id)

                # Normalized envelope (Block 0 contract). It is the real
                # conduit of the dispatch path: routing builds it, the
                # execution stage (`_execute_single_order`) consumes it.
                dispatch_request = BrokerDispatchRequest(
                    broker_name=broker_name,
                    order=order,
                    account=account,
                    instrument=instrument,
                    live=False,  # dry-run always, until Block 10
                    trace_id=trace_id,
                )

                result = self._execute_single_order(
                    broker=broker,
                    provider=provider,
                    dispatch_request=dispatch_request,
                )
                results.append((sequence, result))

                self._log_order(sequence, result, trace_id)

            trace = DispatchTrace(
                trace_id=trace_id,
                start_time=start_time,
                end_time=datetime.now(),
                results=results,
            )
            return self._build_result(trace)

        except Exception as exc:  # fail-closed by contract
            logger.error(
                "Dispatch failed trace_id=%s error=%s",
                trace_id,
                exc,
                exc_info=True,
            )
            trace = DispatchTrace(
                trace_id=trace_id,
                start_time=start_time,
                end_time=datetime.now(),
                results=results,
            )
            return self._fail_result(trace, message=f"Dispatch failed: {exc}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _plan_item(
        self,
        plan: ExecutionPlan,
        sequence: int,
    ) -> Tuple[object, str, str]:
        """
        Return (order, account_id, broker_name) for one plan sequence.

        The exact Account -> Broker binding is the one the Planner (Block 1)
        established and preserved under ``plan.conditions["binding"]``
        (see ``core/execution_planner.py``). The Dispatch Core never falls
        back to index conventions and never invents a binding.
        """
        idx = self._sequence_index(plan, sequence)
        if idx is None:
            raise ValueError(f"Execution sequence not found in plan: {sequence}")

        order = plan.orders[idx]

        binding = plan.conditions.get("binding", {}).get(sequence, {})
        account_id = binding.get("account_id")
        broker_name = binding.get("broker_name")

        if not account_id:
            raise ValueError(
                f"No account_id bound for sequence {sequence} "
                "(block 1 binding missing)."
            )
        if not broker_name:
            raise ValueError(
                f"No broker_name bound for sequence {sequence} "
                "(block 1 binding missing)."
            )

        return order, account_id, broker_name

    def _sequence_index(
        self,
        plan: ExecutionPlan,
        sequence: int,
    ) -> Optional[int]:
        """Map a sequence number to its index in ``plan.orders``.

        The Planner (Block 1) sorts ``plan.orders`` by sequence ascending,
        so the index of ``sequence`` equals its rank among the sorted
        ``execution_order`` values.
        """
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            return None

        rank = sorted(plan.execution_order)
        try:
            return rank.index(sequence)
        except ValueError:
            return None

    def _plan_account(
        self,
        plan: ExecutionPlan,
        account_id: str,
    ) -> Optional[Account]:
        """
        Locate the exact ``Account`` object that the plan bound to
        ``account_id``.

        The actual Block 1 contract produces ``ExecutionPlan.accounts`` as
        account_id strings (see ``build_plan`` in ``execution_planner.py``).
        Therefore:

        - If the plan carries the resolved ``Account`` object matching the
          bound account_id, it is returned unchanged (no re-selection, no
          re-resolution, no mutation).
        - If the plan carries only the account_id string, ``None`` is
          returned: the binding is preserved as-is and the order is blocked
          fail-closed. The Dispatch Core NEVER invents an ``Account`` object
          and never calls ``broker.get_account()``.
        - If the account_id is not bound in this plan at all, ``ValueError``
          is raised (fail-closed).
        """
        for entry in plan.accounts:
            if (
                isinstance(entry, Account)
                and getattr(entry, "account_id", None) == account_id
            ):
                return entry

        if account_id in plan.accounts:
            return None  # id-only binding; no Account object to execute with

        raise ValueError(
            f"Account not bound in plan for account_id={account_id} "
            "(block 1 binding missing)."
        )

    def _blocked_no_account(
        self,
        order,
        account_id: str,
        broker_name: str,
        sequence: int,
    ) -> "OrderExecutionResult":
        """
        Fail-closed per-order result for an id-only bound account.

        The exact ``account_id`` binding is preserved and reported; no
        ``Account`` object is invented. Resolving Account objects is out of
        Block 2 scope (Block 6 / integration layer); this core only says:
        the account is pre-identified, preserved, and execution cannot
        continue without a resolved Account.
        """
        from core.order_engine import OrderExecutionResult

        return OrderExecutionResult(
            success=False,
            sent=False,
            mode="BLOCKED",
            order=order,
            broker_name=broker_name,
            message=(
                f"No Account object bound for account_id={account_id} "
                f"(sequence {sequence}); binding preserved as account_id "
                "only, no account invented (fail-closed)."
            ),
        )

    def _execute_single_order(
        self,
        broker,
        provider,
        dispatch_request: BrokerDispatchRequest,
    ):
        """
        Delegate one order to the existing OrderEngine path.

        ``BrokerDispatchRequest`` is the real conduit of the Block 2
        dispatch path (Block 0 contract): the routing stage builds the
        envelope and the execution stage consumes it. It is the normalized
        carrier between the Dispatch Core and the Broker boundary; today it
        feeds the existing ``execute_by_ins_code`` path (ins_code ->
        provider resolution -> nsc_id consistency check -> prepare() with all
        M6-A … M6-E gates -> broker.place_order).

        Returns an ``OrderExecutionResult``; never raises.
        """
        try:
            result = self.order_engine.execute_by_ins_code(
                broker=broker,
                provider=provider,
                ins_code=dispatch_request.order.nsc_id,
                order=dispatch_request.order,
                account=dispatch_request.account,
                live=dispatch_request.live,  # always False in Block 2
            )
        except Exception as exc:
            # Fail-closed: any unexpected error -> BLOCKED, never sent.
            from core.order_engine import OrderExecutionResult

            result = OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=dispatch_request.order,
                broker_name=getattr(
                    broker, "name", dispatch_request.broker_name
                ),
                message=f"Dispatch failed: {exc}",
            )
        return result

    def _resolve_instrument(self, provider, ins_code: str):
        """
        Resolve the BrokerInstrument for ``ins_code`` through the existing
        InstrumentProvider abstraction (Block 2 sequence step b).

        Never raises: if the provider cannot confirm the instrument, the
        envelope still carries ``None`` and the OrderEngine path performs
        the authoritative fail-closed lookup afterwards.
        """
        try:
            result = provider.get_instrument(ins_code)
        except Exception:
            return None
        if isinstance(result, tuple) and len(result) == 2:
            return result[1]
        return None

    def _build_result(
        self,
        trace: DispatchTrace,
    ) -> DispatchResult:
        """
        Summarize per-order results into one DispatchResult.

        Fail-closed contract: any per-order failure (preflight BLOCKED,
        execution exception, or id-only account) makes the final verdict
        ``mode="BLOCKED"``. ``ERROR`` / ``FAILED`` are never emitted.
        """
        results = trace.results
        total = len(results)
        successful = sum(1 for _, r in results if r.success)

        if successful == total:
            return DispatchResult(
                success=True,
                sent=False,
                mode="ALL_PROCESSED",
                message=f"All {total} orders processed (dry-run)",
                broker_name=None,  # multi-broker: no single broker applies
                order_count=total,
                trace_id=trace.trace_id,
            )

        # Any failure -> fail-closed BLOCKED (never ERROR / FAILED).
        first_failure = next(
            (
                r.message
                for _, r in results
                if not r.success and r.message
            ),
            None,
        )
        message = f"All {total} orders blocked (fail-closed)"
        if first_failure:
            message = f"{message}: {first_failure}"
        return DispatchResult(
            success=False,
            sent=False,
            mode="BLOCKED",
            message=message,
            broker_name=None,
            order_count=total,
            trace_id=trace.trace_id,
        )

    def _fail_result(
        self,
        trace: DispatchTrace,
        message: str,
    ) -> DispatchResult:
        """Fail-closed DispatchResult for a dispatch-level exception."""
        return DispatchResult(
            success=False,
            sent=False,
            mode="BLOCKED",
            message=message,
            broker_name=None,
            order_count=len(trace.results),
            trace_id=trace.trace_id,
        )

    def _log_order(self, sequence: int, result, trace_id: str) -> None:
        logger.info(
            "Dispatched trace_id=%s sequence=%s mode=%s message=%s",
            trace_id,
            sequence,
            getattr(result, "mode", "UNKNOWN"),
            getattr(result, "message", ""),
        )


# ---------------------------------------------------------------------------
# Backwards-compatibility alias
# ---------------------------------------------------------------------------


class LowLatencyDispatchCore(DispatchCore):
    """
    Alias for backwards compatibility — same implementation as
    ``DispatchCore``. Kept only because the earlier Block 2 skeleton
    exposed this name; new code should import ``DispatchCore``.
    """

    pass