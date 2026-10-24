"""Immutable, batch-scoped Live authorization for one scheduled run.

Task 11.3 separates two things that must never be conflated:

  * the *actual* evidence gathered for a frozen queue/prepared batch
    (account records, local sessions, resolved broker capabilities, and the
    real M6-A … M6-E results captured by ``OrderEngine.prepare_order``), and
  * the *permission* to release exactly those prepared payloads during
    exactly one schedule window.

``LiveBatchAuthorization`` is that permission. It is valid only for the
exact ``LiveBatchSnapshot`` it was issued for. Nothing here performs a
network read, resolves an instrument, refreshes a token, toggles a broker
lock, or invents a readiness status. The only M6/broker status values this
module names are derived from complete, successful evidence already present
in the snapshot.

The module is deliberately independent of the UI: it imports no UI or
broker implementation. Callers in ``ui.live_order_gate`` capture the
snapshot from the existing services and then either issue an authorization
or validate a previously issued one against the *current* snapshot.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Tuple


# Status values derived ONLY from actual successful prepared-order evidence.
# They are not generic "READY"/"ACTIVE" aliases and are never supplied when
# any required prepared order or destination is unverified.
M6_EVIDENCE_PASSED = "PREPARED_M6_PASSED"
BROKER_LIVE_SUBMIT_AVAILABLE = "PREPARED_LIVE_SUBMIT_AVAILABLE"

MODE_ALLOWED = "ALLOWED"
MODE_BLOCKED = "BLOCKED"


class LiveAuthorizationError(ValueError):
    """Raised when an authorization cannot be issued from the evidence."""


def fingerprint(value: Any) -> str:
    """Stable JSON fingerprint used to compare immutable evidence."""
    return json.dumps(
        value, sort_keys=True, default=str, separators=(",", ":")
    )


def payload_fingerprint(payload_json: Any) -> str:
    """Fingerprint an already-built payload without rebuilding it."""
    if isinstance(payload_json, str):
        return fingerprint(payload_json)
    return fingerprint(payload_json)


def m6_fingerprint(prepared: Any) -> str:
    """Fingerprint M6 evidence while excluding elapsed TTL deadlines.

    Source timestamps, evidence names/outcomes, preparation times and the
    scheduled-validity decision are bound. The expiry instant is checked at
    authorization issuance; crossing it later does not cause a network
    refresh or invalidate the already-authorized execution.
    """
    freshness = tuple(getattr(prepared, "freshness", ()) or ())
    evidence = tuple(
        tuple(item[:5]) + (None,)
        if isinstance(item, tuple) and len(item) == 6
        else item
        for item in (getattr(prepared, "m6_results", ()) or ())
    )
    return fingerprint(
        {
            "m6_results": evidence,
            "m6_completed_at": getattr(prepared, "m6_completed_at", None),
            "freshness": freshness,
            "prepared_at": getattr(prepared, "prepared_at", None),
            "checks_succeeded": getattr(prepared, "checks_succeeded", False),
            "scheduled_valid": getattr(prepared, "scheduled_valid", False),
            "execution_id": getattr(prepared, "execution_id", None),
        }
    )


def prepared_fingerprint(prepared: Any) -> str:
    """Fingerprint every binding that makes one prepared order immutable."""
    order = getattr(prepared, "order", None)
    order_payload = order.to_payload() if callable(
        getattr(order, "to_payload", None)
    ) else None
    return fingerprint(
        {
            "order": order_payload,
            "payload_json": getattr(prepared, "payload_json", None),
            "account_id": getattr(prepared, "account_id", None),
            "broker_name": getattr(prepared, "broker_name", None),
            "prepared_at": getattr(prepared, "prepared_at", None),
            "expires_at": getattr(prepared, "expires_at", None),
            "m6_fingerprint": m6_fingerprint(prepared),
            "order_fingerprint": getattr(prepared, "order_fingerprint", None),
            "account_fingerprint": getattr(
                prepared, "account_fingerprint", None
            ),
            "broker_identity": getattr(prepared, "broker_identity", None),
            "evidence_order_fingerprint": getattr(
                prepared, "evidence_order_fingerprint", None
            ),
            "evidence_account_id": getattr(
                prepared, "evidence_account_id", None
            ),
            "evidence_broker_name": getattr(
                prepared, "evidence_broker_name", None
            ),
            "checks_succeeded": getattr(prepared, "checks_succeeded", False),
            "scheduled_valid": getattr(prepared, "scheduled_valid", False),
        }
    )


@dataclass(frozen=True)
class DestinationSnapshot:
    """Exact account, local session and broker capability for one target."""

    account_id: str
    broker_name: str
    account_identity: int
    account_fingerprint: str
    broker_identity: int
    broker_live_enabled: bool
    broker_prepared_submit: bool
    session_broker_name: str
    session_state: str
    session_revision: Any
    session_token_fingerprint: str


@dataclass(frozen=True)
class OrderAuthorizationSnapshot:
    """Exact frozen queue entry plus its prepared payload and M6 evidence."""

    entry_identity: int
    order_identity: int
    order_fingerprint: str
    payload_fingerprint: str
    payload_json: str
    account_id: str
    broker_name: str
    broker_identity: int
    prepared_identity: int
    prepared_fingerprint: str
    m6_fingerprint: str
    m6_completed_at: datetime
    prepared_at: datetime
    m6_passed: bool
    scheduled_valid: bool
    execution_id: str


@dataclass(frozen=True)
class ScheduleSnapshot:
    """The only schedule window/repetition scope this permission covers."""

    start: datetime
    end: datetime
    interval_ms: float
    planned_turns: int
    order_count: int
    max_submissions: int

    def __post_init__(self):
        if not isinstance(self.start, datetime) or not isinstance(
            self.end, datetime
        ):
            raise LiveAuthorizationError(
                "schedule start/end must be datetimes"
            )
        if self.end < self.start:
            raise LiveAuthorizationError(
                "schedule end must not precede its start"
            )
        if not isinstance(self.interval_ms, (int, float)) or isinstance(
            self.interval_ms, bool
        ) or self.interval_ms <= 0:
            raise LiveAuthorizationError(
                "schedule interval must be a positive number of milliseconds"
            )
        if not isinstance(self.planned_turns, int) or self.planned_turns <= 0:
            raise LiveAuthorizationError(
                "planned turns must be a positive integer"
            )
        if not isinstance(self.order_count, int) or self.order_count <= 0:
            raise LiveAuthorizationError(
                "order count must be a positive integer"
            )
        if (
            not isinstance(self.max_submissions, int)
            or self.max_submissions <= 0
            or self.max_submissions
            != self.planned_turns * self.order_count
        ):
            raise LiveAuthorizationError(
                "maximum submissions must equal planned turns x order count"
            )


@dataclass(frozen=True)
class LiveBatchSnapshot:
    """Everything one Live permission is bound to at issuance time."""

    orders: Tuple[OrderAuthorizationSnapshot, ...]
    destinations: Tuple[DestinationSnapshot, ...]
    schedule: ScheduleSnapshot
    execution_id: str
    queue_revision: Any
    queue_fingerprint: str
    m6_status: str
    broker_status: str

    def __post_init__(self):
        if not self.orders:
            raise LiveAuthorizationError(
                "a Live authorization requires at least one prepared order"
            )
        if not self.destinations:
            raise LiveAuthorizationError(
                "a Live authorization requires at least one destination"
            )
        if not isinstance(self.queue_fingerprint, str) or not (
            self.queue_fingerprint
        ):
            raise LiveAuthorizationError("queue fingerprint is required")
        if len(self.orders) != self.schedule.order_count:
            raise LiveAuthorizationError(
                "prepared order count does not match the schedule scope"
            )
        if not isinstance(self.execution_id, str) or not self.execution_id:
            raise LiveAuthorizationError("scheduled execution identity is required")


@dataclass(frozen=True)
class LiveBatchAuthorization:
    """Immutable permission scoped to exactly one live batch snapshot."""

    authorization_id: str
    snapshot: LiveBatchSnapshot
    issued_at: datetime
    expires_at: datetime
    explicit_live_request: bool
    human_approval: bool
    gate_mode: str
    gate_reason: str
    usage_ledger: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class AuthorizationCheck:
    """Fail-closed result of comparing a permission with current evidence."""

    allowed: bool
    reason: str = ""
    current_snapshot: Optional[LiveBatchSnapshot] = None


class LiveAuthorizationLedger:
    """Thread-safe one-run counter for the authorization's exact send cap.

    The immutable authorization records the approved maximum. This separate
    runtime ledger consumes one slot before each broker hand-off, including
    attempts whose response later becomes ambiguous, so the same permission
    cannot be replayed beyond its approved exposure.
    """

    def __init__(self, authorization: LiveBatchAuthorization):
        if not isinstance(authorization, LiveBatchAuthorization):
            raise LiveAuthorizationError("a valid authorization is required")
        self._authorization_id = authorization.authorization_id
        self._maximum = authorization.snapshot.schedule.max_submissions
        self._per_order_maximum = authorization.snapshot.schedule.planned_turns
        self._approved_orders = {
            item.order_identity for item in authorization.snapshot.orders
        }
        self._total = 0
        self._per_order = {}
        self._lock = threading.Lock()

    @property
    def used(self):
        with self._lock:
            return self._total

    def claim(self, authorization: LiveBatchAuthorization, order: Any):
        """Atomically consume one approved attempt, or deny it."""
        if (
            not isinstance(authorization, LiveBatchAuthorization)
            or authorization.authorization_id != self._authorization_id
            or id(order) not in self._approved_orders
        ):
            return AuthorizationCheck(False, "submission is outside this ledger")
        identity = id(order)
        with self._lock:
            count = self._per_order.get(identity, 0)
            if self._total >= self._maximum:
                return AuthorizationCheck(False, "maximum submissions exhausted")
            if count >= self._per_order_maximum:
                return AuthorizationCheck(
                    False, "this order's planned repetitions are exhausted"
                )
            self._per_order[identity] = count + 1
            self._total += 1
        return AuthorizationCheck(True, "")


def _authorization_fingerprint(snapshot: LiveBatchSnapshot) -> str:
    """Fingerprint all approved scope fields to detect dataclass replacement."""
    return fingerprint(
        {
            "queue_revision": snapshot.queue_revision,
            "queue": snapshot.queue_fingerprint,
            "orders": snapshot.orders,
            "destinations": snapshot.destinations,
            "schedule": snapshot.schedule,
            "execution_id": snapshot.execution_id,
            "m6_status": snapshot.m6_status,
            "broker_status": snapshot.broker_status,
        }
    )


def build_snapshot(
    *,
    orders: Tuple[OrderAuthorizationSnapshot, ...],
    destinations: Tuple[DestinationSnapshot, ...],
    schedule: ScheduleSnapshot,
    execution_id: str,
    queue_revision: Any,
    queue_fingerprint: str,
) -> LiveBatchSnapshot:
    """Build a snapshot whose readiness statuses are evidence-derived only."""
    if not orders:
        raise LiveAuthorizationError("no prepared orders were supplied")
    if not destinations:
        raise LiveAuthorizationError("no destinations were supplied")

    for order in orders:
        if not isinstance(order, OrderAuthorizationSnapshot):
            raise LiveAuthorizationError("invalid prepared order snapshot")
        if order.m6_passed is not True or order.scheduled_valid is not True:
            raise LiveAuthorizationError(
                "one or more prepared orders lack complete M6 evidence"
            )
        if not isinstance(order.execution_id, str) or not order.execution_id:
            raise LiveAuthorizationError(
                "a prepared order lacks its scheduled execution identity"
            )
        if not order.order_fingerprint or not order.payload_fingerprint:
            raise LiveAuthorizationError(
                "one or more prepared orders lack payload identity"
            )

    destination_pairs = {
        (destination.account_id, destination.broker_name)
        for destination in destinations
    }
    if any(
        (order.account_id, order.broker_name) not in destination_pairs
        for order in orders
    ):
        raise LiveAuthorizationError(
            "an order has no matching destination snapshot"
        )
    execution_ids = {order.execution_id for order in orders}
    if len(execution_ids) != 1:
        raise LiveAuthorizationError(
            "prepared M6 evidence belongs to different scheduled executions"
        )
    if execution_ids != {execution_id}:
        raise LiveAuthorizationError(
            "M6 evidence does not belong to this scheduled execution"
        )
    if any(
        not isinstance(item.m6_completed_at, datetime)
        or not isinstance(item.prepared_at, datetime)
        for item in orders
    ):
        raise LiveAuthorizationError(
            "M6 evidence is missing its completion timestamp"
        )
    if any(
        destination.broker_live_enabled is not True
        or destination.broker_prepared_submit is not True
        or destination.session_state != "LOGGED_IN"
        or not destination.session_token_fingerprint
        for destination in destinations
    ):
        raise LiveAuthorizationError(
            "one or more destinations lack a real logged-in session or "
            "prepared-submit capable broker"
        )

    return LiveBatchSnapshot(
        orders=tuple(orders),
        destinations=tuple(destinations),
        schedule=schedule,
        execution_id=execution_id,
        queue_revision=queue_revision,
        queue_fingerprint=queue_fingerprint,
        m6_status=M6_EVIDENCE_PASSED,
        broker_status=BROKER_LIVE_SUBMIT_AVAILABLE,
    )


def issue_authorization(
    snapshot: LiveBatchSnapshot,
    *,
    explicit_live_request: bool,
    human_approval: bool,
    gate_mode: str,
    gate_reason: str,
    issued_at: datetime,
) -> LiveBatchAuthorization:
    """Issue one permission for exactly ``snapshot`` or fail closed."""
    if not isinstance(snapshot, LiveBatchSnapshot):
        raise LiveAuthorizationError("invalid live batch snapshot")
    if snapshot.m6_status != M6_EVIDENCE_PASSED:
        raise LiveAuthorizationError("M6 evidence is not complete")
    if snapshot.broker_status != BROKER_LIVE_SUBMIT_AVAILABLE:
        raise LiveAuthorizationError("broker capability is not verified")
    if any(
        item.m6_passed is not True or item.scheduled_valid is not True
        for item in snapshot.orders
    ):
        raise LiveAuthorizationError("one or more prepared orders are invalid")
    if any(
        item.broker_live_enabled is not True
        or item.broker_prepared_submit is not True
        or item.session_state != "LOGGED_IN"
        or not item.session_token_fingerprint
        for item in snapshot.destinations
    ):
        raise LiveAuthorizationError("one or more destinations are invalid")
    if explicit_live_request is not True:
        raise LiveAuthorizationError("explicit Live request is missing")
    if human_approval is not True:
        raise LiveAuthorizationError("explicit human approval is missing")
    if gate_mode != MODE_ALLOWED:
        raise LiveAuthorizationError("SafetyGate did not allow Live")
    if not isinstance(issued_at, datetime):
        raise LiveAuthorizationError("issuance time is required")
    if issued_at > snapshot.schedule.end:
        raise LiveAuthorizationError("the schedule window has already ended")

    authorization_id = _authorization_fingerprint(snapshot)
    authorization = LiveBatchAuthorization(
        authorization_id=authorization_id,
        snapshot=snapshot,
        issued_at=issued_at,
        expires_at=snapshot.schedule.end,
        explicit_live_request=True,
        human_approval=True,
        gate_mode=gate_mode,
        gate_reason=str(gate_reason),
    )
    object.__setattr__(
        authorization, "usage_ledger", LiveAuthorizationLedger(authorization)
    )
    return authorization


def validate_authorization(
    authorization: Any,
    *,
    current_snapshot: Any,
    now: datetime,
) -> AuthorizationCheck:
    """Compare a permission with the *current* evidence, fail closed."""
    if not isinstance(authorization, LiveBatchAuthorization):
        return AuthorizationCheck(False, "Live authorization is missing")
    if not isinstance(current_snapshot, LiveBatchSnapshot):
        return AuthorizationCheck(False, "current batch snapshot is unavailable")
    if not isinstance(now, datetime):
        return AuthorizationCheck(False, "current time is unavailable")
    if authorization.expires_at != authorization.snapshot.schedule.end:
        return AuthorizationCheck(False, "authorization expiry was altered")
    if authorization.authorization_id != _authorization_fingerprint(
        authorization.snapshot
    ):
        return AuthorizationCheck(False, "authorization snapshot was altered")
    if now > authorization.expires_at:
        return AuthorizationCheck(False, "the schedule window has ended")
    if now < authorization.snapshot.schedule.start:
        return AuthorizationCheck(False, "the schedule window has not started")
    if authorization.snapshot != current_snapshot:
        return AuthorizationCheck(
            False, "the current batch no longer matches the approved snapshot"
        )
    if current_snapshot.execution_id != authorization.snapshot.execution_id:
        return AuthorizationCheck(
            False, "M6 evidence belongs to another scheduled execution"
        )
    if authorization.explicit_live_request is not True:
        return AuthorizationCheck(False, "explicit Live request is missing")
    if authorization.human_approval is not True:
        return AuthorizationCheck(False, "explicit human approval is missing")
    if authorization.gate_mode != MODE_ALLOWED:
        return AuthorizationCheck(False, "SafetyGate did not allow this batch")
    if current_snapshot.m6_status != M6_EVIDENCE_PASSED:
        return AuthorizationCheck(False, "M6 evidence is incomplete")
    if current_snapshot.broker_status != BROKER_LIVE_SUBMIT_AVAILABLE:
        return AuthorizationCheck(False, "broker capability is unverified")
    return AuthorizationCheck(True, "", current_snapshot)


def _find_order(
    snapshot: LiveBatchSnapshot,
    *,
    order: Any,
    prepared: Any,
    account_id: str,
    broker_name: str,
    broker: Any,
) -> Optional[OrderAuthorizationSnapshot]:
    order_identity = id(order)
    prepared_identity = id(prepared)
    broker_identity = id(broker)
    for candidate in snapshot.orders:
        if (
            candidate.order_identity == order_identity
            and candidate.prepared_identity == prepared_identity
            and candidate.account_id == account_id
            and candidate.broker_name == broker_name
            and candidate.broker_identity == broker_identity
        ):
            return candidate
    return None


def validate_prepared_submission(
    authorization: Any,
    *,
    prepared: Any,
    broker: Any,
    account: Any,
    order: Any,
    account_id: str,
    broker_name: str,
    now: datetime,
    current_snapshot: Any = None,
    usage_ledger: Any = None,
) -> AuthorizationCheck:
    """Defence-in-depth check before handing one prepared payload to submit.

    This never performs a network read or re-runs M6. It proves that the
    prepared order still is the exact one bound by the approved snapshot and
    that the schedule window has not ended.
    """
    if not isinstance(authorization, LiveBatchAuthorization):
        return AuthorizationCheck(False, "Live authorization is missing")
    if (
        authorization.explicit_live_request is not True
        or authorization.human_approval is not True
        or authorization.gate_mode != MODE_ALLOWED
        or authorization.expires_at != authorization.snapshot.schedule.end
        or authorization.authorization_id
        != _authorization_fingerprint(authorization.snapshot)
        or authorization.snapshot.m6_status != M6_EVIDENCE_PASSED
        or authorization.snapshot.broker_status
        != BROKER_LIVE_SUBMIT_AVAILABLE
    ):
        return AuthorizationCheck(False, "Live authorization evidence is invalid")
    current_check = validate_authorization(
        authorization,
        current_snapshot=current_snapshot,
        now=now,
    )
    if not current_check.allowed:
        return current_check
    snapshot = authorization.snapshot
    if not isinstance(now, datetime):
        return AuthorizationCheck(False, "current time is unavailable")
    if now < snapshot.schedule.start:
        return AuthorizationCheck(False, "the schedule window has not started")
    if now > authorization.expires_at:
        return AuthorizationCheck(False, "the schedule window has ended")
    if now < authorization.snapshot.schedule.start:
        return AuthorizationCheck(False, "the schedule window has not started")

    candidate = _find_order(
        snapshot,
        order=order,
        prepared=prepared,
        account_id=account_id,
        broker_name=broker_name,
        broker=broker,
    )
    if candidate is None:
        return AuthorizationCheck(
            False, "the prepared order is not part of this authorization"
        )
    if current_check.current_snapshot is None:
        return AuthorizationCheck(False, "current batch snapshot is unavailable")
    current_candidate = next(
        (
            item for item in current_check.current_snapshot.orders
            if item.entry_identity == candidate.entry_identity
            and item.order_identity == candidate.order_identity
        ),
        None,
    )
    if current_candidate != candidate:
        return AuthorizationCheck(
            False, "the queue entry no longer matches the approved snapshot"
        )

    order_payload = (
        order.to_payload()
        if callable(getattr(order, "to_payload", None))
        else None
    )
    if fingerprint(order_payload) != candidate.order_fingerprint:
        return AuthorizationCheck(False, "the order changed after approval")
    if payload_fingerprint(
        getattr(prepared, "payload_json", None)
    ) != candidate.payload_fingerprint:
        return AuthorizationCheck(False, "the prepared payload changed")
    try:
        if fingerprint(prepared.payload) != fingerprint(order_payload):
            return AuthorizationCheck(
                False, "the prepared payload no longer matches the order"
            )
    except Exception:
        return AuthorizationCheck(False, "the prepared payload is invalid")
    if prepared_fingerprint(prepared) != candidate.prepared_fingerprint:
        return AuthorizationCheck(False, "the prepared order changed")
    if m6_fingerprint(prepared) != candidate.m6_fingerprint:
        return AuthorizationCheck(False, "the M6 evidence changed")
    evidence = tuple(getattr(prepared, "m6_results", ()) or ())
    freshness = tuple(getattr(prepared, "freshness", ()) or ())
    if (
        getattr(prepared, "checks_succeeded", False) is not True
        or getattr(prepared, "scheduled_valid", False) is not True
        or not evidence
        or not freshness
        or any(
            not isinstance(item, tuple) or len(item) != 6
            or item[1] is not True
            or not isinstance(item[2], int) or item[2] < 0
            or not isinstance(item[3], str) or not item[3]
            or not isinstance(item[4], datetime)
            for item in evidence
        )
    ):
        return AuthorizationCheck(False, "the prepared M6 evidence is invalid")
    if getattr(prepared, "execution_id", None) != candidate.execution_id:
        return AuthorizationCheck(
            False, "prepared M6 evidence belongs to another execution"
        )
    if getattr(prepared, "account_id", None) != account_id:
        return AuthorizationCheck(False, "the account changed")
    if getattr(prepared, "broker_name", None) != broker_name:
        return AuthorizationCheck(False, "the broker changed")
    if getattr(prepared, "broker_identity", None) != id(broker):
        return AuthorizationCheck(False, "the broker instance changed")
    account_fingerprint = fingerprint(vars(account))
    destination = next(
        (
            item
            for item in snapshot.destinations
            if item.account_id == account_id
            and item.broker_name == broker_name
        ),
        None,
    )
    if destination is None:
        return AuthorizationCheck(False, "the destination is not approved")
    if account_fingerprint != destination.account_fingerprint:
        return AuthorizationCheck(False, "the account changed after approval")
    if id(account) != destination.account_identity:
        return AuthorizationCheck(False, "the account instance changed after approval")
    if destination.session_state != "LOGGED_IN":
        return AuthorizationCheck(False, "the destination session is not valid")
    if getattr(broker, "live_trading_enabled", False) is not True:
        return AuthorizationCheck(False, "the broker Live lock is still off")
    if not callable(getattr(broker, "submit_prepared_order", None)):
        return AuthorizationCheck(
            False, "the broker cannot submit an already-prepared payload"
        )
    if (
        not isinstance(usage_ledger, LiveAuthorizationLedger)
        or usage_ledger is not authorization.usage_ledger
    ):
        return AuthorizationCheck(False, "the authorization use ledger is missing")
    claim = usage_ledger.claim(authorization, order)
    if not claim.allowed:
        return claim
    return AuthorizationCheck(True, "", current_check.current_snapshot)


def authorization_diagnostics(authorization: Any) -> dict:
    """Safe, credential-free summary for tests/logs (no token is included)."""
    if not isinstance(authorization, LiveBatchAuthorization):
        return {"allowed": False}
    return {
        "authorization_id": authorization.authorization_id,
        "orders": len(authorization.snapshot.orders),
        "destinations": len(authorization.snapshot.destinations),
        "start": authorization.snapshot.schedule.start,
        "end": authorization.snapshot.schedule.end,
        "max_submissions": authorization.snapshot.schedule.max_submissions,
        "m6_status": authorization.snapshot.m6_status,
        "broker_status": authorization.snapshot.broker_status,
    }


__all__ = [
    "AuthorizationCheck",
    "BROKER_LIVE_SUBMIT_AVAILABLE",
    "DestinationSnapshot",
    "LiveAuthorizationError",
    "LiveBatchAuthorization",
    "LiveBatchSnapshot",
    "LiveAuthorizationLedger",
    "M6_EVIDENCE_PASSED",
    "MODE_ALLOWED",
    "MODE_BLOCKED",
    "OrderAuthorizationSnapshot",
    "ScheduleSnapshot",
    "authorization_diagnostics",
    "build_snapshot",
    "fingerprint",
    "issue_authorization",
    "m6_fingerprint",
    "payload_fingerprint",
    "prepared_fingerprint",
    "validate_authorization",
    "validate_prepared_submission",
]
