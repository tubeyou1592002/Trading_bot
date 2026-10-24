"""Fail-closed UI readiness checks for the existing Block 10 SafetyGate.

The UI does not manufacture M6 or broker-readiness results. A single-order
Live start uses ``check_live_readiness`` and remains fully fail-closed. Task
11.3 adds ``check_live_batch_readiness``: it captures the *actual* prepared
batch, destination accounts, local sessions, broker instances/capabilities
and schedule scope, derives the M6/broker statuses only from that evidence,
and returns an immutable authorization bound to that exact snapshot.
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Any, Optional

from core.live_order_authorization import (
    BROKER_LIVE_SUBMIT_AVAILABLE,
    M6_EVIDENCE_PASSED,
    MODE_ALLOWED,
    AuthorizationCheck,
    DestinationSnapshot,
    LiveAuthorizationError,
    OrderAuthorizationSnapshot,
    ScheduleSnapshot,
    build_snapshot,
    fingerprint,
    issue_authorization,
    m6_fingerprint,
    payload_fingerprint,
    prepared_fingerprint,
    validate_authorization,
)


@dataclass(frozen=True)
class LiveReadiness:
    allowed: bool
    reason: str
    gate: Optional[Any] = None
    ready_for_confirmation: bool = False
    authorization: Optional[Any] = None


def check_live_readiness(
    *,
    account_store,
    authentication_service,
    session_manager,
    broker_manager,
    account_id: str,
    broker_name: str,
    explicit_live_request: bool,
    human_approval: bool,
    prerequisite_provider=None,
) -> LiveReadiness:
    """Check only verifiable prerequisites, then evaluate SafetyGate.

    ``prerequisite_provider`` is deliberately explicit. It must return a
    mapping containing the real ``m6_status``, ``broker_status`` and the
    accepted status contracts. No guessed READY/ACTIVE values are supplied
    by this function.
    """
    from core.safety_gate import SafetyGate
    from ui.order_authorization import authorize_order

    authorization = authorize_order(
        account_store,
        authentication_service,
        session_manager,
        account_id,
        broker_name,
    )
    if not authorization.authorized:
        return LiveReadiness(False, "حساب فعال و ورود معتبر تأیید نشد.")

    try:
        broker = broker_manager.get_for_account(account_id, broker_name)
    except Exception:
        return LiveReadiness(False, "کارگزار حساب فعال قابل‌دسترسی نیست.")

    # This lock is an independent final broker safeguard. The UI must never
    # flip it; report its state separately from readiness/feedback.
    if getattr(broker, "live_trading_enabled", False) is not True:
        return LiveReadiness(
            False,
            "قفل ایمنی داخلی AgaahBroker خاموش است؛ Live از مسیر UI قابل‌فعال‌سازی نیست.",
        )

    if prerequisite_provider is None:
        return LiveReadiness(
            False,
            "منبع معتبر وضعیت M6-A…M6-E پیش از ارسال و منبع رسمی آمادگی Live کارگزار متصل نیستند؛ M6 فعلی فقط در OrderEngine.prepare اجرا می‌شود و برای SafetyGate نتیجهٔ پیشینی فراهم نمی‌کند.",
        )

    try:
        prerequisites = prerequisite_provider(
            account_id=account_id,
            broker_name=broker_name,
            broker=broker,
        )
        if not isinstance(prerequisites, dict):
            raise TypeError("prerequisite provider must return a mapping")
        gate = SafetyGate(
            live_block9_state="COMPLETED",
            explicit_live_request=explicit_live_request,
            human_approval=human_approval,
            live_state="KNOWN",
            m6_status=prerequisites.get("m6_status"),
            broker_status=prerequisites.get("broker_status"),
            acceptable_m6_statuses=prerequisites.get(
                "acceptable_m6_statuses", ()
            ),
            acceptable_broker_statuses=prerequisites.get(
                "acceptable_broker_statuses", ()
            ),
        )
        decision = gate.evaluate()
    except Exception:
        return LiveReadiness(
            False,
            "پیش‌نیازهای واقعی Live قابل‌تأیید نیستند.",
        )

    if decision.allowed is not True:
        if decision.blocked_by == "human_approval" and not human_approval:
            # All earlier SafetyGate prerequisites passed. This is only a
            # preflight result authorizing the UI to ask the user; it is not
            # a permission to dispatch. A second evaluation after explicit
            # confirmation must return an allowed gate.
            return LiveReadiness(
                False,
                "تأیید صریح کاربر لازم است.",
                ready_for_confirmation=True,
            )
        return LiveReadiness(False, decision.reason, gate)
    return LiveReadiness(True, "آمادگی Live تأیید شد.", gate)


def _prepared_orders(prepared_batch):
    if prepared_batch is None:
        return ()
    orders = getattr(prepared_batch, "orders", None)
    if orders is not None:
        return tuple(orders)
    return tuple(prepared_batch)


def _schedule_window(timing):
    start = getattr(timing, "start_time", None)
    end = getattr(timing, "end_time", None)
    if start is None and isinstance(timing, (tuple, list)) and len(timing) == 2:
        start, end = timing
    return start, end


def _token_fingerprint(token):
    return hashlib.sha256(
        token.encode("utf-8", "surrogatepass")
    ).hexdigest()


def _capture_batch_snapshot(
    *,
    account_store,
    authentication_service,
    session_manager,
    broker_manager,
    targets,
    prepared_batch,
    timing,
    interval_ms,
    planned_turns,
    execution_id,
    now,
    engine=None,
    queue_revision=None,
    check_source_expiry=True,
):
    """Capture the actual batch evidence. No network call is made."""
    from ui.order_authorization import authorize_destination
    from ui.schedule_settings import count_planned_turns

    if engine is None or not callable(
        getattr(engine, "validate_prepared_order", None)
    ):
        raise LiveAuthorizationError(
            "the actual OrderEngine prepared-evidence validator is required"
        )
    if not isinstance(execution_id, str) or not execution_id.strip():
        raise LiveAuthorizationError("scheduled execution identity is required")
    targets = tuple(targets or ())
    if not targets:
        raise LiveAuthorizationError("the frozen order queue is empty")

    start, end = _schedule_window(timing)
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise LiveAuthorizationError("the schedule window is unavailable")
    if end < start:
        raise LiveAuthorizationError("the schedule window is inverted")
    if not isinstance(interval_ms, (int, float)) or isinstance(
        interval_ms, bool
    ) or interval_ms <= 0:
        raise LiveAuthorizationError("the dispatch interval is invalid")
    expected_turns = count_planned_turns(start, end, interval_ms)
    if planned_turns is None:
        planned_turns = expected_turns
    elif planned_turns != expected_turns:
        raise LiveAuthorizationError(
            "planned turns do not match the schedule window"
        )

    prepared_orders = _prepared_orders(prepared_batch)
    if hasattr(prepared_batch, "valid") and prepared_batch.valid is not True:
        raise LiveAuthorizationError("the prepared batch is not valid")
    if (
        hasattr(prepared_batch, "checks_succeeded")
        and prepared_batch.checks_succeeded is not True
    ):
        raise LiveAuthorizationError(
            "the prepared batch checks did not succeed"
        )
    by_order = {}
    for prepared in prepared_orders:
        order = getattr(prepared, "order", None)
        if order is None:
            raise LiveAuthorizationError("a prepared order has no order")
        if id(order) in by_order:
            raise LiveAuthorizationError(
                "the same order was prepared more than once"
            )
        by_order[id(order)] = prepared
    if len(prepared_orders) != len(targets):
        raise LiveAuthorizationError(
            "prepared order count does not match the frozen queue"
        )
    execution_ids = {
        getattr(prepared, "execution_id", None)
        for prepared in prepared_orders
    }
    if len(execution_ids) != 1 or None in execution_ids:
        raise LiveAuthorizationError(
            "prepared M6 evidence belongs to different executions"
        )
    if execution_ids != {execution_id}:
        raise LiveAuthorizationError(
            "prepared M6 evidence belongs to another scheduled execution"
        )
    batch_execution_id = getattr(prepared_batch, "execution_id", None)
    if batch_execution_id != execution_id:
        raise LiveAuthorizationError(
            "prepared batch and M6 evidence execution identities differ"
        )

    destinations = {}
    orders = []
    for target in targets:
        entry = getattr(target, "entry", None)
        order = getattr(entry, "order", None)
        account_id = getattr(target, "account_id", None)
        broker_name = getattr(target, "broker_name", None)
        account = getattr(target, "account", None)
        if (
            entry is None or order is None
            or not isinstance(account_id, str) or not account_id
            or not isinstance(broker_name, str) or not broker_name
            or account is None
        ):
            raise LiveAuthorizationError(
                "a frozen queue entry lacks its order/account/broker binding"
            )
        if getattr(entry, "account_id", None) != account_id:
            raise LiveAuthorizationError(
                "a queue entry's account binding changed"
            )
        if getattr(entry, "broker_name", None) != broker_name:
            raise LiveAuthorizationError(
                "a queue entry's broker binding changed"
            )

        prepared = by_order.get(id(order))
        if prepared is None:
            raise LiveAuthorizationError(
                "a frozen order has no matching prepared order"
            )
        if getattr(prepared, "account_id", None) != account_id:
            raise LiveAuthorizationError(
                "a prepared order belongs to another account"
            )
        if getattr(prepared, "broker_name", None) != broker_name:
            raise LiveAuthorizationError(
                "a prepared order belongs to another broker"
            )

        key = (account_id, broker_name)
        destination = destinations.get(key)
        if destination is None:
            auth = authorize_destination(
                account_store, authentication_service, session_manager,
                account_id, broker_name,
            )
            if auth.authorized is not True:
                raise LiveAuthorizationError(
                    f"destination {account_id!r} has no valid account/session"
                )
            record = account_store.get(account_id)
            if record.broker_name != broker_name:
                raise LiveAuthorizationError(
                    "the account record's broker does not match the order"
                )
            try:
                session = session_manager.get(account_id)
                token = session_manager.get_token(account_id)
                revision = session_manager.revision(account_id)
            except Exception as exc:
                raise LiveAuthorizationError(
                    "the destination local session is unavailable"
                ) from exc
            if (
                not isinstance(token, str) or not token.strip()
                or session.account_id != account_id
                or session.broker_name != broker_name
            ):
                raise LiveAuthorizationError(
                    "the destination local session is invalid"
                )
            state = getattr(session.state, "value", str(session.state))
            if state != "logged_in":
                raise LiveAuthorizationError(
                    "the destination local session is not logged in"
                )
            try:
                broker = broker_manager.get_for_account(
                    account_id, broker_name
                )
            except Exception as exc:
                raise LiveAuthorizationError(
                    "the destination broker is unavailable"
                ) from exc
            broker_name_attr = getattr(broker, "name", None)
            if (
                not isinstance(broker_name_attr, str)
                or not broker_name_attr.strip()
                or broker_name_attr != broker_name
            ):
                raise LiveAuthorizationError(
                    "the resolved broker identity does not match the order"
                )
            if getattr(broker, "live_trading_enabled", False) is not True:
                raise LiveAuthorizationError(
                    "the broker Live lock is not enabled"
                )
            if not callable(getattr(broker, "submit_prepared_order", None)):
                raise LiveAuthorizationError(
                    "the broker cannot submit an already-prepared payload"
                )
            destination = DestinationSnapshot(
                account_id=account_id,
                broker_name=broker_name,
                account_identity=id(record.account),
                account_fingerprint=fingerprint(vars(record.account)),
                broker_identity=id(broker),
                broker_live_enabled=True,
                broker_prepared_submit=True,
                session_broker_name=session.broker_name,
                session_state="LOGGED_IN",
                session_revision=revision,
                session_token_fingerprint=_token_fingerprint(token),
            )
            destinations[key] = destination

        record = account_store.get(account_id)
        if id(account) != destination.account_identity:
            raise LiveAuthorizationError(
                "the frozen destination Account object changed"
            )
        if (
            getattr(record, "account_id", None) != account_id
            or getattr(record, "broker_name", None) != broker_name
            or record.account is not account
            or fingerprint(vars(record.account))
            != destination.account_fingerprint
        ):
            raise LiveAuthorizationError(
                "the current account record does not match the destination snapshot"
            )
        if id(broker) != getattr(prepared, "broker_identity", None):
            raise LiveAuthorizationError(
                "the prepared order used another broker instance"
            )

        valid, message = engine.validate_prepared_order(
            prepared, broker, account, account_id, broker_name, now=now,
            check_expiry=check_source_expiry,
        )
        if not valid:
            raise LiveAuthorizationError(message)

        order_payload = order.to_payload()
        order_fingerprint = fingerprint(order_payload)
        prepared_payload_json = getattr(prepared, "payload_json", None)
        if not isinstance(prepared_payload_json, str) or not prepared_payload_json:
            raise LiveAuthorizationError("the prepared payload is unavailable")
        orders.append(
            OrderAuthorizationSnapshot(
                entry_identity=id(entry),
                order_identity=id(order),
                order_fingerprint=order_fingerprint,
                payload_fingerprint=payload_fingerprint(prepared_payload_json),
                payload_json=prepared_payload_json,
                account_id=account_id,
                broker_name=broker_name,
                broker_identity=id(broker),
                prepared_identity=id(prepared),
                prepared_fingerprint=prepared_fingerprint(prepared),
                m6_fingerprint=m6_fingerprint(prepared),
                m6_completed_at=prepared.m6_completed_at,
                prepared_at=prepared.prepared_at,
                m6_passed=True,
                scheduled_valid=True,
                execution_id=prepared.execution_id,
            )
        )

    queue_fingerprint = fingerprint(
        tuple(
            (
                order.entry_identity,
                order.order_identity,
                order.order_fingerprint,
                order.account_id,
                order.broker_name,
                order.payload_fingerprint,
                order.prepared_fingerprint,
                order.m6_fingerprint,
            )
            for order in orders
        )
    )
    schedule = ScheduleSnapshot(
        start=start,
        end=end,
        interval_ms=float(interval_ms),
        planned_turns=int(planned_turns),
        order_count=len(orders),
        max_submissions=int(planned_turns) * len(orders),
    )
    snapshot = build_snapshot(
        orders=tuple(orders),
        destinations=tuple(destinations.values()),
        schedule=schedule,
        execution_id=execution_id,
        queue_revision=queue_revision,
        queue_fingerprint=queue_fingerprint,
    )
    return snapshot


def check_live_batch_readiness(
    *,
    account_store,
    authentication_service,
    session_manager,
    broker_manager,
    targets,
    prepared_batch,
    timing,
    interval_ms,
    explicit_live_request,
    human_approval,
    planned_turns=None,
    execution_id=None,
    queue_revision=None,
    engine=None,
    now=None,
) -> LiveReadiness:
    """Derive batch readiness from real evidence, then issue one permit.

    A destination's account/session is validated independently: the UI active
    account is not required and is never substituted for a queued order's own
    account. Missing/changed evidence, an ended window, an invalid session or
    an incapable broker blocks issuance (fail-closed).
    """
    from core.safety_gate import SafetyGate

    now = now or datetime.now().astimezone()
    try:
        snapshot = _capture_batch_snapshot(
            account_store=account_store,
            authentication_service=authentication_service,
            session_manager=session_manager,
            broker_manager=broker_manager,
            targets=targets,
            prepared_batch=prepared_batch,
            timing=timing,
            interval_ms=interval_ms,
            planned_turns=planned_turns,
            execution_id=execution_id,
            now=now,
            engine=engine,
            queue_revision=queue_revision,
            check_source_expiry=True,
        )
    except Exception as exc:
        return LiveReadiness(
            False,
            f"آمادگی Live از شواهد واقعی قابل‌تأیید نیست: {exc}",
        )

    gate = SafetyGate(
        live_block9_state="COMPLETED",
        explicit_live_request=explicit_live_request,
        human_approval=human_approval,
        live_state="KNOWN",
        m6_status=snapshot.m6_status,
        broker_status=snapshot.broker_status,
        acceptable_m6_statuses=(M6_EVIDENCE_PASSED,),
        acceptable_broker_statuses=(BROKER_LIVE_SUBMIT_AVAILABLE,),
    )
    decision = gate.evaluate()
    if decision.allowed is not True:
        if decision.blocked_by == "human_approval" and not human_approval:
            return LiveReadiness(
                False,
                "تأیید صریح کاربر لازم است.",
                gate=gate,
                ready_for_confirmation=True,
            )
        return LiveReadiness(False, decision.reason, gate)

    try:
        authorization = issue_authorization(
            snapshot,
            explicit_live_request=explicit_live_request,
            human_approval=human_approval,
            gate_mode=MODE_ALLOWED,
            gate_reason=decision.reason,
            issued_at=now,
        )
    except Exception as exc:
        return LiveReadiness(
            False,
            f"مجوز Live صادر نشد: {exc}",
            gate,
        )

    return LiveReadiness(
        True,
        "آمادگی و مجوز Live برای همین snapshot تأیید شد.",
        gate=gate,
        authorization=authorization,
    )


def validate_live_batch_authorization(
    *,
    authorization,
    account_store,
    authentication_service,
    session_manager,
    broker_manager,
    targets,
    prepared_batch,
    timing,
    interval_ms,
    planned_turns=None,
    execution_id=None,
    queue_revision=None,
    engine=None,
    now=None,
    pre_arm=False,
) -> AuthorizationCheck:
    """Re-capture current evidence and compare it with the approved snapshot.

    This is a local check only: no network request, token refresh, M6 re-run
    or instrument lookup is performed. Any change, expiry or unverifiable
    input denies the authorization.
    """
    now = now or datetime.now().astimezone()
    try:
        current = _capture_batch_snapshot(
            account_store=account_store,
            authentication_service=authentication_service,
            session_manager=session_manager,
            broker_manager=broker_manager,
            targets=targets,
            prepared_batch=prepared_batch,
            timing=timing,
            interval_ms=interval_ms,
            planned_turns=planned_turns,
            execution_id=execution_id,
            now=now,
            engine=engine,
            queue_revision=queue_revision,
            # M6 evidence was verified at arming and remains valid for this
            # execution only. Do not expire/re-fetch it mid-run; the whole
            # authorization ends at the schedule window boundary.
            check_source_expiry=False,
        )
    except Exception as exc:
        return AuthorizationCheck(
            False, f"the current batch cannot be verified: {exc}"
        )
    if pre_arm:
        # Local-only pre-arm validation: confirm the immutable permit matches
        # the freshly captured snapshot without consuming its future start.
        # The submit path continues to call validate_authorization normally.
        from core.live_order_authorization import _authorization_fingerprint

        if (authorization is None
                or authorization.authorization_id != _authorization_fingerprint(
                    authorization.snapshot
                )
                or authorization.snapshot != current
                or authorization.explicit_live_request is not True
                or authorization.human_approval is not True):
            return AuthorizationCheck(False, "pre-arm snapshot mismatch")
        if now > authorization.expires_at:
            return AuthorizationCheck(False, "the schedule window has ended")
        return AuthorizationCheck(True, "", current)
    return validate_authorization(authorization, current_snapshot=current, now=now)


__all__ = [
    "LiveReadiness",
    "check_live_batch_readiness",
    "check_live_readiness",
    "validate_live_batch_authorization",
]
