"""Fail-closed UI readiness checks for the existing Block 10 SafetyGate.

The UI does not manufacture M6 or broker-readiness results. The current
production application has no authoritative provider for those two inputs,
and AgaahBroker's own ``live_trading_enabled`` lock defaults to False. Until
those real prerequisites are supplied, a Live start is rejected before the
dispatch path is entered.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class LiveReadiness:
    allowed: bool
    reason: str
    gate: Optional[Any] = None
    ready_for_confirmation: bool = False


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


__all__ = ["LiveReadiness", "check_live_readiness"]
