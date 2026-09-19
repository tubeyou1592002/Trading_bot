"""
Block 10 — Task 10.2: Safety Gate (final lock before live entry; fail-closed).

Implements the Task 10.1 Live Execution Contract (AI_HANDOFF.md) as the
FINAL LOCK that decides whether entry into Live execution is permitted AT
ALL, based only on the live-permission prerequisites supplied to it.

Narrowed responsibility (Task 10.2 review):

  * The gate is NOT a second OrderEngine and NOT a parallel M6 system.
    M6-A … M6-E keep running ONLY inside the real ``OrderEngine.prepare()``
    path. The gate merely consumes the M6 prerequisite RESULT supplied by
    the caller; it never re-runs, re-implements, or interprets M6 logic.

  * The gate is NOT a parallel binding system. Account -> Broker selection
    and consistency remain exactly the existing Planner / DispatchCore
    logic (``plan.conditions["binding"]`` / ``plan.account_routes``,
    fail-closed in ``DispatchCore._plan_account``). The gate performs no
    binding validation of its own and re-resolves no account and no broker.

  * The gate does NOT run instrument resolution. The real
    InstrumentProvider path stays on the dispatch path only; the gate
    consumes prerequisite results as supplied data instead of repeating
    any dispatch work.

  * There is NO connection to ``DispatchCore``: this module imports
    nothing from the dispatch stack and is wired nowhere. Task 10.3
    (Controlled Live Dispatch) is the only intended future consumer of
    ``SafetyGateDecision.allowed``.

Status vocabulary policy (final Task 10.2 fix):

  * The gate invents NO "allowed for live" vocabulary for external
    prerequisites. It does NOT decide that ``VERIFIED``, ``READY``,
    ``ACTIVE`` or any other value means "permitted for live": which M6 /
    broker-readiness values are valid is SUPPLIED BY THE CALLER (the
    system's official contract wiring) via the constructor. The default
    contract is EMPTY, so with no contract supplied every external
    prerequisite status blocks — fail-closed.

  * The only vocabulary hardcoded here is the Task 10.1 prohibition list
    (``UNKNOWN`` / ``UNVERIFIED`` / ``BLOCKED`` — Task 10.1 §3), the
    official roadmap status ``COMPLETED`` for the Block 9 prerequisite,
    and the ``KNOWN`` encoding of Task 10.1's "live state known and
    unambiguous" rule.

Existing protections stay intact and keep winning independently:

  1. Dispatch-level protection — ``DispatchCore`` builds every envelope
     with ``live=False`` today; the Task 10.3 controlled-live layer is
     the only future writer of ``live=True``.
  2. OrderEngine live guard — ``execute_by_ins_code`` returns
     ``mode="BLOCKED"`` when ``live=True`` is requested from a broker
     whose ``live_trading_enabled`` is ``False``.
  3. Broker-level safety lock — ``broker.place_order(order, live=True)``
     raises ``RuntimeError`` when ``live_trading_enabled`` is ``False``.
  4. M6-A … M6-E — untouched, on the real engine path only.

Fail-closed behavior: any missing prerequisite, any ``UNKNOWN`` /
``UNVERIFIED`` / ``BLOCKED`` / empty status, any value not recognized by
the caller-supplied contract, or ANY exception raised while checking a
prerequisite produces ``mode="BLOCKED"`` — never an allowance. The
default constructed gate allows nothing, so the system default remains
Dry Run / ``live=False``.
"""

from dataclasses import dataclass
from typing import Iterable, Optional


# Task 10.1 §3 prohibition vocabulary — the ONLY statuses the gate itself
# names for external prerequisites; everything else must come from the
# caller-supplied contract.
PREREQ_UNKNOWN = "UNKNOWN"
PREREQ_UNVERIFIED = "UNVERIFIED"
PREREQ_BLOCKED = "BLOCKED"

_UNIVERSAL_DENY = frozenset(
    {PREREQ_UNKNOWN, PREREQ_UNVERIFIED, PREREQ_BLOCKED, ""}
)

# The only Block 9 state that satisfies the Task 10.1 prerequisite §2.1 —
# the official roadmap status vocabulary, not an invented value.
BLOCK9_COMPLETED = "COMPLETED"

# The encoding of Task 10.1's "live state known and unambiguous" rule.
LIVE_STATE_KNOWN = "KNOWN"


@dataclass
class SafetyGateDecision:
    """
    The complete, inspectable outcome of one Safety Gate evaluation.

    ``allowed`` is ``True`` ONLY when every live-entry prerequisite passed.
    ``blocked_by`` names the failed prerequisite; ``reason`` is a
    plain-text explanation safe to log. ``mode`` is ``"ALLOWED"`` or
    ``"BLOCKED"`` (the latter matches the existing fail-closed vocabulary
    of the engine and dispatch core).
    """

    allowed: bool
    mode: str
    blocked_by: Optional[str]
    reason: str


def _normalize_contract(values: Iterable[str]) -> frozenset:
    """Normalize a caller-supplied contract into an uppercase set."""
    return frozenset(
        str(value).strip().upper() for value in values
    )


class SafetyGate:
    """
    Final, independent, fail-closed lock for the decision "may this system
    enter Live execution?".

    Constructed with the environment-level live-permission prerequisites
    (Task 10.1 §2, supplied as plain data — never resolved here):

      * ``live_block9_state``  — Block 9 status; only ``COMPLETED`` passes.
      * ``explicit_live_request`` — an explicit, deliberate live request.
      * ``human_approval``     — explicit human approval for live.
      * ``live_state``         — the live-switch state; only ``KNOWN`` passes.
      * ``m6_status``          — the M6-A … M6-E prerequisite RESULT as data.
      * ``broker_status``      — the live-capable broker readiness RESULT
        as data.

    ``acceptable_m6_statuses`` / ``acceptable_broker_statuses`` are the
    CALLER-SUPPLIED contract: the values the system's official wiring
    recognizes as valid for those prerequisites. The gate invents no
    vocabulary of its own; the empty default blocks every external
    prerequisite status (fail-closed).

    ``evaluate()`` accepts optional per-evaluation overrides for the two
    supplied statuses. The default instance allows nothing, so a freshly
    constructed system is permanently Dry Run until every prerequisite is
    explicitly and validly provided.
    """

    MODE_ALLOWED = "ALLOWED"
    MODE_BLOCKED = "BLOCKED"

    def __init__(
        self,
        live_block9_state: str = PREREQ_UNKNOWN,
        explicit_live_request: bool = False,
        human_approval: bool = False,
        live_state: str = PREREQ_UNKNOWN,
        m6_status: Optional[str] = None,
        broker_status: Optional[str] = None,
        acceptable_m6_statuses: Iterable[str] = (),
        acceptable_broker_statuses: Iterable[str] = (),
    ):
        # All prerequisites default to their deny values so the
        # constructed default is "never live" (fail-closed).
        self.live_block9_state = live_block9_state
        self.explicit_live_request = explicit_live_request
        self.human_approval = human_approval
        self.live_state = live_state
        self.m6_status = m6_status
        self.broker_status = broker_status
        # Caller-supplied contract (empty default => nothing recognized).
        self.acceptable_m6_statuses = _normalize_contract(
            acceptable_m6_statuses
        )
        self.acceptable_broker_statuses = _normalize_contract(
            acceptable_broker_statuses
        )

    # ------------------------------------------------------------------
    # Public evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        m6_status: Optional[str] = None,
        broker_status: Optional[str] = None,
    ) -> SafetyGateDecision:
        """
        Decide whether entry into Live execution is permitted.

        ``m6_status`` / ``broker_status`` optionally override the
        instance-level supplied statuses for this evaluation. Both are
        plain data: the gate resolves nothing and inspects no live
        component.

        Never raises: any exception raised while checking a prerequisite
        is converted into a ``BLOCKED`` decision (fail-closed).
        """
        try:
            checks = (
                ("block9_state", self._check_block9),
                (
                    "m6_gates",
                    lambda: self._check_m6(m6_status),
                ),
                (
                    "broker_status",
                    lambda: self._check_broker_status(broker_status),
                ),
                ("explicit_live_request", self._check_explicit_request),
                ("human_approval", self._check_human_approval),
                ("live_state", self._check_live_state),
            )
            for name, check in checks:
                failure_reason = check()
                if failure_reason is not None:
                    return self._blocked(name, failure_reason)
        except Exception as exc:  # fail-closed: any validation error blocks
            return self._blocked(
                "exception",
                "Fail-closed: prerequisite validation raised "
                f"{type(exc).__name__}: {exc}",
            )

        return SafetyGateDecision(
            allowed=True,
            mode=self.MODE_ALLOWED,
            blocked_by=None,
            reason=(
                "All live-entry prerequisites satisfied; Task 10.3 may "
                "request live at the envelope boundary (the existing "
                "engine guard and broker lock still apply independently)."
            ),
        )

    # ------------------------------------------------------------------
    # Individual prerequisite checks (return None = pass, str = block)
    # ------------------------------------------------------------------

    def _blocked(self, blocked_by: str, reason: str) -> SafetyGateDecision:
        return SafetyGateDecision(
            allowed=False,
            mode=self.MODE_BLOCKED,
            blocked_by=blocked_by,
            reason=reason,
        )

    def _check_status_value(
        self,
        status: object,
        acceptable: frozenset,
        label: str,
    ) -> Optional[str]:
        """One supplied prerequisite status, fail-closed:

          * missing / ``UNKNOWN`` / ``UNVERIFIED`` / ``BLOCKED`` / empty
            -> block (the Task 10.1 prohibition vocabulary);
          * any value NOT recognized by the caller-supplied contract
            -> block (the gate invents no valid vocabulary of its own;
            an empty contract blocks everything);
          * only a value explicitly recognized by the supplied contract
            passes.

        Purely data-driven — no component is resolved or interpreted."""
        if status is None:
            return f"Fail-closed: {label} prerequisite status is missing."
        value = str(status).strip().upper()
        if value in _UNIVERSAL_DENY:
            return (
                f"Fail-closed: {label} prerequisite status is "
                f"{status!r} (UNKNOWN/UNVERIFIED/BLOCKED not allowed)."
            )
        if value not in acceptable:
            return (
                f"Fail-closed: {label} prerequisite status {status!r} is "
                "not recognized as valid by the supplied live contract; "
                "live is forbidden."
            )
        return None

    def _check_block9(self) -> Optional[str]:
        return self._check_status_value(
            self.live_block9_state,
            frozenset({BLOCK9_COMPLETED}),
            "Block 9",
        )

    def _check_m6(self, m6_status: Optional[str]) -> Optional[str]:
        """
        Consume the M6 prerequisite RESULT as supplied data only.

        This is deliberately NOT an M6 implementation: M6-A … M6-E keep
        running exclusively inside the real ``OrderEngine.prepare()``
        path. The gate only refuses to allow live while the reported M6
        result is missing, UNKNOWN/UNVERIFIED/BLOCKED/empty, or not
        recognized by the caller-supplied contract.
        """
        status = m6_status if m6_status is not None else self.m6_status
        return self._check_status_value(
            status,
            self.acceptable_m6_statuses,
            "M6-A … M6-E",
        )

    def _check_broker_status(
        self,
        broker_status: Optional[str],
    ) -> Optional[str]:
        """Consume the live-capable broker readiness RESULT as supplied
        data only — no broker is resolved, read, or interpreted here."""
        status = (
            broker_status
            if broker_status is not None
            else self.broker_status
        )
        return self._check_status_value(
            status,
            self.acceptable_broker_statuses,
            "live-capable broker",
        )

    def _check_explicit_request(self) -> Optional[str]:
        if self.explicit_live_request is not True:
            return (
                "Fail-closed: no explicit live request is present for this "
                "dispatch."
            )
        return None

    def _check_human_approval(self) -> Optional[str]:
        if self.human_approval is not True:
            return (
                "Fail-closed: no explicit human approval for live execution."
            )
        return None

    def _check_live_state(self) -> Optional[str]:
        return self._check_status_value(
            self.live_state,
            frozenset({LIVE_STATE_KNOWN}),
            "live state",
        )
