"""
Block 6 — Task 6.6: Multi-Account Stop/Brake Policy.

Stop/Brake behaviour in a multi-account run must be **explicit, selectable,
and independent of any random order-execution order**. This module defines
that policy as one explicit value:

    StopPolicy.NONE      no brake is ever activated by a per-order result;
                         every account keeps dispatching (default).
    StopPolicy.ACCOUNT   the first successful ``REGISTERED`` result of an
                         account brakes THAT account only. Every other
                         account keeps dispatching.
    StopPolicy.GLOBAL    the first successful ``REGISTERED`` result of ANY
                         account brakes the whole run: no further dispatch is
                         sent, for any account.

Dispatch boundary (Block 6, Task 6.6 level):

    OrderExecutionResult (per order, per account)
        │  account_id is supplied by the caller from the per-order record
        │  (Task 6.5 filled it from the plan binding of that sequence)
        ▼
    StopBrakePolicy.observe_order_result(account_id, result)
        │  only success == REGISTERED ...
        ▼
    StopSignal.observe(...)          (existing Block 5 Task 3 gate)
        │
        ▼
    StopBrakePolicy.should_continue(account_ids) -> ALLOW / STOP
        │
        ▼
    the existing Block 5 send path (``stop_guard`` / ``GuardDecision`` /
    ``mode="STOPPED"`` result), which is where the gate is consulted

Design rules:

  * NO parallel stop system is introduced. Every scope is an ordinary
    EXISTING ``StopSignal`` gate: one gate per braked account (``ACCOUNT``)
    and one gate for the whole run (``GLOBAL``). ``StopSignal`` already has
    exactly the semantics required here — it latches on the FIRST success and
    stays active, and it never activates on a failure — so it is reused
    as-is, without a single change to ``core/block5_task3.py``.
  * ``NONE`` is the fail-open default of this module: the per-order path then
    never touches any gate at all (a result is pure tracking, Task 6.5).
  * Only a successful ``REGISTERED`` result activates a brake. A ``FAILED``
    result never stops anything.
  * A brake only gates *future* dispatches. Orders that were already sent are
    never cancelled, stopped, or modified by this module.
  * ``ACCOUNT`` is per-account: braking account A must not stop account B.
    A single atomic dispatch that mixes a braked account with a non-braked
    one is NOT sent (see :meth:`StopBrakePolicy.should_continue`): a plan is
    one dispatch unit and cannot be sent partially without changing the
    Dispatch Core routing. Not sending is the fail-closed choice — an order of
    a braked account can never be sent.
  * The decision is a pure function of (policy, account identity, result
    status). It never looks at an order index, a position, the symbol, the
    broker, ``plan.accounts[0]``, or the order in which results arrive.
  * Fail-closed: an invalid policy value, a non-``StopSignal`` gate, a
    disabled global gate (it could never brake anything), or a missing /
    malformed / blank account identity raises before any state changes.

Explicitly OUT of scope for this module:
  - Any broker implementation, broker adapter, or broker/exchange API call.
  - Any live trading, scheduler, timer, polling loop, thread, or real clock.
  - Any persistence, file I/O, or network access.
  - Any new dispatch mechanism, routing, or validation logic.
  - Any modification to ``DispatchCore``, ``OrderEngine``, the broker layer,
    the Block 5 Task 3 ``StopSignal``, ``ExecutionTracker``, or routing.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Dict, Optional, Tuple

from core.block5_task3 import StopSignal
from core.dispatch_contracts import DispatchResult
from core.order_engine import OrderExecutionResult


# ---------------------------------------------------------------------------
# Policy value
# ---------------------------------------------------------------------------


class StopPolicy(str, Enum):
    """The explicit, selectable Stop/Brake policy of a multi-account run.

    ``NONE``    — no brake; a per-order result never stops a dispatch.
    ``ACCOUNT`` — a successful registration brakes THAT account only.
    ``GLOBAL``  — the first successful registration brakes the whole run.
    """

    NONE = "NONE"
    ACCOUNT = "ACCOUNT"
    GLOBAL = "GLOBAL"


class StopBrakePolicyError(ValueError):
    """Raised for invalid Stop/Brake policy usage (fail-closed)."""


def _as_gate_result(result: OrderExecutionResult) -> DispatchResult:
    """Express ONE per-order result as the input the EXISTING stop gate takes.

    ``StopSignal.observe`` is the Block 5 Task 3 contract and it consumes a
    ``DispatchResult``. The order outcome is therefore carried over unchanged
    (``success`` / ``sent`` / ``mode`` / ``message`` / ``broker_name``); no
    value is invented, and in particular the ACCOUNT identity is NOT taken
    from here — it is supplied by the caller from the per-order record, which
    Task 6.5 filled from ``plan.conditions["binding"][sequence]["account_id"]``.
    """
    return DispatchResult(
        success=result.success,
        sent=result.sent,
        mode=result.mode,
        message=result.message,
        broker_name=result.broker_name,
    )


# ---------------------------------------------------------------------------
# Policy engine
# ---------------------------------------------------------------------------


class StopBrakePolicy:
    """Explicit multi-account Stop/Brake policy built on ``StopSignal``.

    Attributes:
        policy: The explicit ``StopPolicy`` value in force
            (``NONE`` / ``ACCOUNT`` / ``GLOBAL``).
    """

    def __init__(
        self,
        policy: StopPolicy = StopPolicy.NONE,
        global_signal: Optional[StopSignal] = None,
    ) -> None:
        """Build the policy around the EXISTING Block 5 Task 3 Stop Signal.

        Args:
            policy: The explicit policy value. Must be a member of
                ``StopPolicy`` — a raw string (e.g. ``"ACCOUNT"``) is
                rejected (fail-closed): the policy must be explicit.
            global_signal: Optional existing ``StopSignal`` used as the
                ``GLOBAL`` gate. When omitted, ``StopSignal(enabled=True)``
                is created. A gate that is disabled can never brake anything,
                so it is rejected (fail-closed).

        Raises:
            StopBrakePolicyError: if ``policy`` is not a ``StopPolicy``, or
                ``global_signal`` is not an enabled ``StopSignal``.
        """
        self._require_policy(policy)
        self.policy: StopPolicy = policy

        if global_signal is None:
            global_signal = StopSignal(enabled=True)
        if not isinstance(global_signal, StopSignal):
            raise StopBrakePolicyError("global_signal must be a StopSignal")
        if not global_signal.enabled:
            raise StopBrakePolicyError(
                "global_signal must be enabled: a disabled Stop Signal can "
                "never brake a dispatch (fail-closed)"
            )
        self._global_signal = global_signal

        # One EXISTING StopSignal gate per braked account. A gate is created
        # lazily, on the first successful REGISTERED result of that account,
        # so an account that never registers successfully never gets one.
        self._account_signals: Dict[str, StopSignal] = {}

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def global_signal(self) -> StopSignal:
        """The existing ``StopSignal`` gate used by ``StopPolicy.GLOBAL``."""
        return self._global_signal

    @property
    def is_global_stopped(self) -> bool:
        """Return True once the whole run has been braked (``GLOBAL``)."""
        self._require_policy(self.policy)
        return self._global_signal.is_active

    def validate_account(self, account_id: str) -> str:
        """Return ``account_id`` when the policy can be applied to it.

        Raises:
            StopBrakePolicyError: if the policy value is invalid or
                ``account_id`` is not a non-empty, non-whitespace string
                (fail-closed).
        """
        self._require_policy(self.policy)
        self._require_account_id(account_id)
        return account_id

    def account_signal(self, account_id: str) -> Optional[StopSignal]:
        """Return the gate braked for ``account_id``, or ``None``.

        ``None`` means the account is not braked (it may simply never have
        registered a successful order yet) — this is NOT an error, which is
        exactly what keeps Account B running while Account A is braked.
        """
        self.validate_account(account_id)
        return self._account_signals.get(account_id)

    def is_account_stopped(self, account_id: str) -> bool:
        """Return True if ``account_id`` has been braked (``ACCOUNT``)."""
        signal = self.account_signal(account_id)
        return signal is not None and signal.is_active

    def stopped_accounts(self) -> Tuple[str, ...]:
        """Every braked account, in a deterministic (sorted) order.

        The order is deliberately NOT the execution order and NOT the arrival
        order of the results: the policy state is independent of both.
        """
        self._require_policy(self.policy)
        return tuple(
            sorted(
                account_id
                for account_id, signal in self._account_signals.items()
                if signal.is_active
            )
        )

    # ------------------------------------------------------------------
    # Send-path gate
    # ------------------------------------------------------------------

    def should_continue(self, account_ids: Iterable[str]) -> bool:
        """Decide whether a NEW dispatch may be sent for ``account_ids``.

        The accounts are the ones the new dispatch would send orders for,
        each resolved from its OWN plan binding by the caller. The answer
        depends only on the policy value and on those account identities: no
        index, no symbol, no broker, no arrival order.

        ``NONE``    — always True (no brake is ever applied).
        ``GLOBAL``  — True only while the whole run is not braked.
        ``ACCOUNT`` — True only when NONE of the given accounts is braked.

        For a dispatch that mixes a braked account with a non-braked one the
        answer is False: a plan is ONE atomic dispatch unit and cannot be sent
        partially without changing the Dispatch Core routing. Not sending is
        fail-closed (an order of a braked account is never sent); the
        non-braked account keeps sending through its own dispatches.

        Args:
            account_ids: The account identity of every order of the new
                dispatch (read from the plan binding by the caller).

        Returns:
            True when the dispatch may be sent, False when it must not be.

        Raises:
            StopBrakePolicyError: if the policy value is invalid, an account
                identity is missing / malformed / blank, or ``account_ids``
                is not a collection (fail-closed).
        """
        self._require_policy(self.policy)
        resolved = self._resolve_accounts(account_ids)

        if self.policy is StopPolicy.NONE:
            return True
        if self.policy is StopPolicy.GLOBAL:
            return not self._global_signal.is_active
        return all(
            not self.is_account_stopped(account_id) for account_id in resolved
        )

# ------------------------------------------------------------------
    # Result path
    # ------------------------------------------------------------------

    def observe_order_result(
        self,
        account_id: str,
        result: OrderExecutionResult,
    ) -> bool:
        """Feed ONE per-order result of ONE account to the policy.

        This is the ONLY way a brake can be activated, and only two things
        can activate it:

          * the policy is ``ACCOUNT`` or ``GLOBAL`` (``NONE`` never brakes),
          * the result is a success — i.e. the very outcome the tracker
            records as ``ExecutionStatus.REGISTERED``. A ``FAILED`` result
            never stops anything.

        The account identity must be the one carried by that order (from its
        own plan binding); it is never derived from ``result``, from
        ``accounts[0]``, from a symbol, a broker, an index, or a default.

        Args:
            account_id: The account identity of the order that produced
                ``result`` (supplied by the caller from the order record).
            result: The existing per-order ``OrderExecutionResult``.

        Returns:
            True if THIS call activated a brake, False otherwise (wrong
            policy, failure result, or the brake was already active — the
            gates latch on the first success).

        Raises:
            StopBrakePolicyError: if the policy value or the account identity
                is invalid, or ``result`` is not an ``OrderExecutionResult``
                (fail-closed; nothing is activated).
        """
        self._require_policy(self.policy)
        self._require_account_id(account_id)
        if not isinstance(result, OrderExecutionResult):
            raise StopBrakePolicyError("result must be an OrderExecutionResult")

        # NONE: no brake is ever activated (the result is pure tracking).
        if self.policy is StopPolicy.NONE:
            return False

        # Only a successful (REGISTERED) result may activate a brake.
        if not result.success:
            return False

        if self.policy is StopPolicy.GLOBAL:
            # The existing gate latches on the FIRST success of ANY account.
            return self._global_signal.observe(_as_gate_result(result))

        signal = self._account_signals.get(account_id)
        if signal is None:
            signal = StopSignal(enabled=True)
            self._account_signals[account_id] = signal
        # The existing gate latches on the FIRST success of THIS account only.
        return signal.observe(_as_gate_result(result))

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_policy(policy: StopPolicy) -> None:
        """Fail-closed unless ``policy`` is an explicit ``StopPolicy`` value."""
        if not isinstance(policy, StopPolicy):
            raise StopBrakePolicyError(
                "policy must be one of StopPolicy.NONE / StopPolicy.ACCOUNT / "
                f"StopPolicy.GLOBAL (got {policy!r})"
            )

    @staticmethod
    def _require_account_id(account_id: str) -> None:
        """Fail-closed unless ``account_id`` is a real account identity."""
        if not isinstance(account_id, str) or not account_id.strip():
            raise StopBrakePolicyError("account_id must be a non-empty string")

    @staticmethod
    def _resolve_accounts(account_ids: Iterable[str]) -> Tuple[str, ...]:
        """Fail-closed resolution of the accounts of one dispatch."""
        if (
            isinstance(account_ids, (str, bytes))
            or not isinstance(account_ids, Iterable)
        ):
            raise StopBrakePolicyError(
                "account_ids must be a collection of account ids"
            )
        resolved = tuple(account_ids)
        for account_id in resolved:
            StopBrakePolicy._require_account_id(account_id)
        return resolved