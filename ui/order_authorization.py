"""Fail-closed, broker-independent authorization for order operations."""

from dataclasses import dataclass

from ui.session_manager import SessionState


@dataclass(frozen=True)
class AuthorizationResult:
    authorized: bool
    reason: str


def authorize_order(account_store, authentication_service, session_manager,
                    account_id, broker_name):
    """Authorize one account-bound operation without changing any state."""
    try:
        if any(service is None for service in (
            account_store, authentication_service, session_manager
        )):
            return AuthorizationResult(False, "services_unavailable")
        active_id = account_store.active_account_id()
        if active_id is None or active_id != account_id:
            return AuthorizationResult(False, "account_mismatch")
        record = account_store.get(active_id)
        if (record.account_id != account_id or record.broker_name != broker_name):
            return AuthorizationResult(False, "account_mismatch")
        if not authentication_service.is_logged_in(account_id):
            return AuthorizationResult(False, "not_authenticated")
        session = session_manager.get(account_id)
        if (session.account_id != account_id or session.state is not SessionState.LOGGED_IN
                or session.broker_name != record.broker_name):
            return AuthorizationResult(False, "session_invalid")
        local_token = session_manager.get_token(account_id)
        if not isinstance(local_token, str) or not local_token.strip():
            return AuthorizationResult(False, "token_invalid")
        adapter = authentication_service.get_adapter(account_id)
        if adapter is None or adapter.is_authenticated() is not True:
            return AuthorizationResult(False, "adapter_invalid")
        authenticated_session = adapter.get_authenticated_session()
        adapter_token = getattr(authenticated_session, "access_token", None)
        adapter_broker = getattr(adapter, "broker_name", None)
        if (not isinstance(adapter_token, str) or not adapter_token.strip()
                or adapter_token != local_token):
            return AuthorizationResult(False, "adapter_session_invalid")
        if adapter_broker != record.broker_name:
            return AuthorizationResult(False, "broker_mismatch")
        return AuthorizationResult(True, "authorized")
    except Exception:
        # Deliberately omit exception details: they may contain secrets.
        return AuthorizationResult(False, "authorization_error")
