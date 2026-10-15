"""
test_block9_task5_token_sync.py

Block 9 — Task 5, Stage 2B: offline tests for per-account session/token
synchronization across the broker-independent authentication contract, the
Agah adapter, AuthenticationService and SessionManager.

Everything here is fully offline:

    * the real ``AgaahBroker`` is used, but its HTTP transport
      (``broker.session``) is replaced by an in-memory fake session serving
      exactly the captcha / authenticate / refresh-token response shapes the
      real broker parses;
    * SessionManager, AccountStore, CredentialStore and AuthenticationService
      are the real production classes;
    * no real network request, credential, token or account is ever used.

Contract covered (Stage 2B):

    SessionManager.replace_token
        * successful replacement for a LOGGED_IN account;
        * rejection for unknown / LOGGED_OUT / LOGIN_PENDING / invalid token;
        * public Session identity and state preserved; other accounts intact;
        * no token leakage.

    AuthenticationAdapter.refresh_authenticated_session (contract)
        * non-abstract default fails clearly for adapters without support;
        * Agah override refreshes the broker and returns a new session;
        * identity fields preserved; failures preserve prior state;
        * no request before authentication; no token leakage.

    AuthenticationService.refresh_session
        * successful refresh synchronizes broker + adapter + SessionManager;
        * account isolation (A never touches B);
        * missing adapter / unauthenticated adapter / non-logged-in session
          cause no request and no mutation;
        * failed refresh leaves the prior token and authenticated state;
        * an invalid adapter result is never reported as synchronized;
        * no token leaks through errors, chains, reprs or public snapshots.

Rejected (out of scope here): automatic 401 interception, automatic refresh,
retry, concurrency coordination, invalidation policy, UI wiring.

Run:
    python -m pytest -q test_block9_task5_token_sync.py
"""

import inspect
import socket
import traceback

import pytest

from brokers.agaah import AgaahBroker
from brokers.agaah.auth_adapter import AgahAuthenticationAdapter
from brokers.authentication import (
    AuthenticationAdapter,
    AuthenticatedSession,
    CHALLENGE_CAPTCHA_IMAGE,
    LoginChallenge,
    TokenRefreshError,
)
from ui import authentication_service as authentication_service_module
from ui.account_store import AccountStore
from ui.authentication_service import (
    AuthenticationService,
    AuthenticationServiceError,
)
from ui.credential_store import CredentialStore
from ui.session_manager import (
    Session,
    SessionManager,
    SessionNotFoundError,
    SessionState,
    SessionStateError,
    SessionValidationError,
)


ACC_A = "ACC-sync-A"
ACC_B = "ACC-sync-B"
BROKER_AGAH = "آگاه"
USERNAME = "agah-user"
PASSWORD = "agah-pass-SECRET"
CAPTCHA_ID = "captcha-id-xyz"
CAPTCHA_TEXT = "1234"

OLD_ACCESS = "OLD-ACCESS-TOKEN-SECRET-111"
OLD_REFRESH = "OLD-REFRESH-TOKEN-SECRET-222"
NEW_ACCESS = "NEW-ACCESS-TOKEN-SECRET-333"
NEW_REFRESH = "NEW-REFRESH-TOKEN-SECRET-444"
USER_IDENTIFIER = "user-identifier-789"

REFRESH_SUFFIX = "users/refresh-token"


# ---------------------------------------------------------------------------
# Fake HTTP layer (installed on the REAL AgaahBroker.session)
# ---------------------------------------------------------------------------

class FakeResponse:
    """The slice of requests.Response that AgaahBroker consumes."""

    def __init__(self, payload=None, status_ok=True, json_error=None):
        self._payload = payload
        self._ok = status_ok
        self._json_error = json_error

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("HTTP error from fake session")

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeAgahSession:
    """
    Fake requests.Session for the Agah API, scoped to ONE account.

    It records every call and serves exactly the captcha / authenticate /
    refresh-token shapes the real AgaahBroker parses. ``refresh_outcome``
    scripts the refresh-token endpoint:

        "success"        -> isSuccess with NEW tokens
        "http_error"     -> raise_for_status raises
        "is_success_false" -> isSuccess=false
        "malformed"      -> isSuccess with data not a dict
        "missing_access" -> data has refresh only
        "missing_refresh" -> data has access only
        "explode"        -> raises echoing this account's old tokens
    """

    def __init__(self, refresh_outcome="success"):
        self.calls = []
        self.refresh_outcome = refresh_outcome

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return FakeResponse({
            "isSuccess": True,
            "data": {
                "captchaId": CAPTCHA_ID,
                "captcha": "ZmFrZS1jYXB0Y2hh",
            },
        })

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))

        if REFRESH_SUFFIX in url:
            return self._refresh_response()

        # Authenticate endpoint.
        return FakeResponse({
            "isSuccess": True,
            "data": {
                "accessToken": OLD_ACCESS,
                "refreshToken": OLD_REFRESH,
                "userIdentifier": USER_IDENTIFIER,
                "userName": kwargs.get("json", {}).get("userName"),
            },
        })

    def _refresh_response(self):
        if self.refresh_outcome == "http_error":
            return FakeResponse({}, status_ok=False)
        if self.refresh_outcome == "is_success_false":
            return FakeResponse({
                "isSuccess": False,
                "message": "refresh rejected",
            })
        if self.refresh_outcome == "malformed":
            return FakeResponse({"isSuccess": True, "data": None})
        if self.refresh_outcome == "missing_access":
            return FakeResponse({
                "isSuccess": True,
                "data": {"refreshToken": NEW_REFRESH},
            })
        if self.refresh_outcome == "missing_refresh":
            return FakeResponse({
                "isSuccess": True,
                "data": {"accessToken": NEW_ACCESS},
            })
        if self.refresh_outcome == "explode":
            raise RuntimeError(
                "refresh backend exploded "
                f"access={OLD_ACCESS} refresh={OLD_REFRESH}"
            )
        return FakeResponse({
            "isSuccess": True,
            "data": {
                "accessToken": NEW_ACCESS,
                "refreshToken": NEW_REFRESH,
            },
        })

    def refresh_calls(self):
        return [
            c for c in self.calls
            if c[0] == "post" and REFRESH_SUFFIX in c[1]
        ]


class _StaticDeviceInfo:
    """Offline replacement for the real device-info provider."""

    def get(self):
        return {"clientId": "offline", "platform": "web"}


def make_broker(refresh_outcome="success"):
    broker = AgaahBroker()
    broker.session = FakeAgahSession(refresh_outcome)
    broker.device_info_provider = _StaticDeviceInfo()
    return broker


def make_authenticated_adapter(refresh_outcome="success"):
    broker = make_broker(refresh_outcome)
    adapter = AgahAuthenticationAdapter(broker=broker)
    adapter.begin_login(USERNAME, PASSWORD)
    session = adapter.complete_login(CAPTCHA_TEXT)
    return adapter, broker, session


# ---------------------------------------------------------------------------
# Secret helpers
# ---------------------------------------------------------------------------

def _iter_exception_chain(error):
    seen = set()
    stack = [error]
    while stack:
        exc = stack.pop()
        if exc is None or id(exc) in seen:
            continue
        seen.add(id(exc))
        yield exc
        stack.append(exc.__cause__)
        stack.append(exc.__context__)


def _assert_no_secret(error, secrets):
    """
    Prove a token never escapes a raised error through any reachable view.

    Scanned surfaces: each exception in the reachable ``__context__`` /
    ``__cause__`` chain, its ``str`` and ``repr``, and the formatted
    traceback of the raised error (the same text a logger or crash
    reporter would emit). The formatted traceback is included because a
    secret can survive in a traceback even when the message and the chain
    links were cleaned.
    """
    formatted = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    for secret in secrets:
        for exc in _iter_exception_chain(error):
            assert secret not in str(exc), (secret, str(exc))
            assert secret not in repr(exc), (secret, repr(exc))
        assert secret not in formatted, (secret, formatted)


# ===========================================================================
# 1. SessionManager.replace_token
# ===========================================================================

def logged_in_manager(account_id=ACC_A, token=OLD_ACCESS):
    manager = SessionManager()
    manager.register(account_id, BROKER_AGAH)
    manager.begin_login(account_id)
    manager.mark_logged_in(account_id, token)
    return manager


def test_replace_token_success():
    manager = logged_in_manager()
    result = manager.replace_token(ACC_A, NEW_ACCESS)

    assert isinstance(result, Session)
    assert manager.get_token(ACC_A) == NEW_ACCESS
    assert manager.state(ACC_A) is SessionState.LOGGED_IN


def test_replace_token_preserves_public_session_identity():
    manager = logged_in_manager()
    before = manager.get(ACC_A)

    result = manager.replace_token(ACC_A, NEW_ACCESS)

    assert result is before
    assert manager.get(ACC_A) is before
    assert result.account_id == ACC_A
    assert result.broker_name == BROKER_AGAH
    assert result.state is SessionState.LOGGED_IN


def test_replace_token_snapshot_has_no_token():
    manager = logged_in_manager()
    result = manager.replace_token(ACC_A, NEW_ACCESS)

    assert not hasattr(result, "token")
    assert NEW_ACCESS not in repr(result)
    assert NEW_ACCESS not in str(result)


def test_replace_token_unknown_account_rejected():
    manager = logged_in_manager()
    with pytest.raises(SessionNotFoundError):
        manager.replace_token("no-such-account", NEW_ACCESS)
    assert manager.get_token(ACC_A) == OLD_ACCESS


def test_replace_token_logged_out_rejected():
    manager = SessionManager()
    manager.register(ACC_A, BROKER_AGAH)

    with pytest.raises(SessionStateError):
        manager.replace_token(ACC_A, NEW_ACCESS)

    assert manager.get_token(ACC_A) is None
    assert manager.state(ACC_A) is SessionState.LOGGED_OUT


def test_replace_token_login_pending_rejected():
    manager = SessionManager()
    manager.register(ACC_A, BROKER_AGAH)
    manager.begin_login(ACC_A)

    with pytest.raises(SessionStateError):
        manager.replace_token(ACC_A, NEW_ACCESS)

    assert manager.get_token(ACC_A) is None
    assert manager.state(ACC_A) is SessionState.LOGIN_PENDING


@pytest.mark.parametrize("bad", [None, "", "   ", 123, ["x"], {"a": 1}])
def test_replace_token_invalid_value_rejected(bad):
    manager = logged_in_manager()
    with pytest.raises(SessionValidationError):
        manager.replace_token(ACC_A, bad)
    assert manager.get_token(ACC_A) == OLD_ACCESS


def test_replace_token_is_per_account():
    manager = SessionManager()
    for account_id, token in ((ACC_A, OLD_ACCESS), (ACC_B, OLD_REFRESH)):
        manager.register(account_id, BROKER_AGAH)
        manager.begin_login(account_id)
        manager.mark_logged_in(account_id, token)

    manager.replace_token(ACC_A, NEW_ACCESS)

    assert manager.get_token(ACC_A) == NEW_ACCESS
    assert manager.get_token(ACC_B) == OLD_REFRESH
    assert manager.state(ACC_B) is SessionState.LOGGED_IN


def test_replace_token_errors_do_not_leak_token():
    # Logged-out account: the state error must not echo the supplied token.
    other = SessionManager()
    other.register(ACC_B, BROKER_AGAH)
    with pytest.raises(SessionStateError) as excinfo:
        other.replace_token(ACC_B, NEW_ACCESS)
    assert NEW_ACCESS not in str(excinfo.value)
    assert NEW_ACCESS not in repr(excinfo.value)

    # Invalid value: the validation error must not echo the value.
    manager = logged_in_manager()
    with pytest.raises(SessionValidationError) as excinfo:
        manager.replace_token(ACC_A, {"leak": NEW_ACCESS})
    assert NEW_ACCESS not in str(excinfo.value)


# ===========================================================================
# 2. SessionManager.invalidate_session (independent emergency API)
# ===========================================================================

def test_invalidate_session_logged_in_clears_state_and_token():
    manager = logged_in_manager()
    before = manager.get(ACC_A)

    result = manager.invalidate_session(ACC_A)

    assert isinstance(result, Session)
    assert manager.state(ACC_A) is SessionState.LOGGED_OUT
    assert manager.is_logged_in(ACC_A) is False
    assert manager.get_token(ACC_A) is None
    assert manager._tokens[ACC_A] is None
    assert result.account_id == before.account_id
    assert result.broker_name == before.broker_name


def test_invalidate_session_unknown_account_rejected():
    manager = logged_in_manager()
    with pytest.raises(SessionNotFoundError):
        manager.invalidate_session("no-such-account")
    # The known account is untouched.
    assert manager.get_token(ACC_A) == OLD_ACCESS
    assert manager.state(ACC_A) is SessionState.LOGGED_IN


def test_invalidate_session_from_login_pending():
    manager = SessionManager()
    manager.register(ACC_A, BROKER_AGAH)
    manager.begin_login(ACC_A)

    manager.invalidate_session(ACC_A)

    assert manager.state(ACC_A) is SessionState.LOGGED_OUT
    assert manager.get_token(ACC_A) is None


def test_invalidate_session_is_repeatable_and_predictable():
    manager = logged_in_manager()

    first = manager.invalidate_session(ACC_A)
    # A second call is a no-op that does not raise and stays LOGGED_OUT.
    second = manager.invalidate_session(ACC_A)

    assert first.state is SessionState.LOGGED_OUT
    assert second.state is SessionState.LOGGED_OUT
    assert manager.state(ACC_A) is SessionState.LOGGED_OUT
    assert manager.get_token(ACC_A) is None


def test_invalidate_session_independent_of_logout():
    from unittest import mock

    manager = logged_in_manager()
    with mock.patch.object(
        manager, "logout", side_effect=SessionStateError("logout broken")
    ):
        manager.invalidate_session(ACC_A)

    assert manager.state(ACC_A) is SessionState.LOGGED_OUT
    assert manager.get_token(ACC_A) is None


def test_invalidate_session_is_per_account():
    manager = SessionManager()
    for account_id, token in ((ACC_A, OLD_ACCESS), (ACC_B, OLD_REFRESH)):
        manager.register(account_id, BROKER_AGAH)
        manager.begin_login(account_id)
        manager.mark_logged_in(account_id, token)

    manager.invalidate_session(ACC_A)

    assert manager.state(ACC_A) is SessionState.LOGGED_OUT
    assert manager.get_token(ACC_A) is None
    assert manager.state(ACC_B) is SessionState.LOGGED_IN
    assert manager.get_token(ACC_B) == OLD_REFRESH


def test_invalidate_session_errors_do_not_leak_token():
    manager = logged_in_manager()
    with pytest.raises(SessionNotFoundError) as excinfo:
        manager.invalidate_session("no-such-account")
    assert OLD_ACCESS not in str(excinfo.value)
    assert OLD_ACCESS not in repr(excinfo.value)


def test_invalidate_session_snapshot_has_no_token():
    manager = logged_in_manager()
    result = manager.invalidate_session(ACC_A)

    assert not hasattr(result, "token")
    assert OLD_ACCESS not in repr(result)
    assert OLD_ACCESS not in str(result)


# ===========================================================================
# 3. AuthenticationAdapter contract + Agah adapter
# ===========================================================================

class _NoRefreshAdapter(AuthenticationAdapter):
    """Satisfies the contract but does not support refresh."""

    @property
    def broker_name(self):
        return BROKER_AGAH

    def begin_login(self, username, password):
        return LoginChallenge(
            kind=CHALLENGE_CAPTCHA_IMAGE, display_payload="img", prompt="p"
        )

    def complete_login(self, response):
        return AuthenticatedSession(access_token="AT", user_identifier="UI")

    def cancel_login(self):
        return None

    def is_authenticated(self):
        return True

    def get_authenticated_session(self):
        return None


def test_adapter_without_refresh_support_fails_clearly():
    adapter = _NoRefreshAdapter()  # must remain instantiable
    with pytest.raises(TokenRefreshError) as excinfo:
        adapter.refresh_authenticated_session()
    assert str(excinfo.value).strip()


def test_contract_refresh_is_not_abstract():
    assert "refresh_authenticated_session" in dir(AuthenticationAdapter)
    assert getattr(
        AuthenticationAdapter.refresh_authenticated_session, "__isabstractmethod__",
        False,
    ) is False


def test_default_refresh_error_has_no_chain_inside_except():
    """
    Even when the unsupported-refresh default is invoked while an outer
    ``except`` is active, the raised error must carry no implicit context
    or explicit cause pointing at the handled (secret-bearing) exception.
    """
    adapter = _NoRefreshAdapter()
    secret = "SECRET-CHAIN-PROBE-73"

    with pytest.raises(TokenRefreshError) as excinfo:
        try:
            raise ValueError(f"underlying failure {secret}")
        except ValueError:
            adapter.refresh_authenticated_session()

    error = excinfo.value
    assert isinstance(error, TokenRefreshError)
    assert error.__context__ is None
    assert error.__cause__ is None
    _assert_no_secret(error, (secret, OLD_ACCESS, OLD_REFRESH))
    assert "پشتیبانی" in str(error)


def test_agah_refresh_success_updates_broker_and_returns_new_session():
    adapter, broker, before = make_authenticated_adapter()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH

    refreshed = adapter.refresh_authenticated_session()

    assert isinstance(refreshed, AuthenticatedSession)
    assert refreshed is not before
    assert refreshed.access_token == NEW_ACCESS
    assert refreshed.refresh_token == NEW_REFRESH

    assert broker.access_token == NEW_ACCESS
    assert broker.refresh_token == NEW_REFRESH

    assert adapter.is_authenticated() is True
    assert adapter.get_authenticated_session() is refreshed


def test_agah_refresh_preserves_identity_fields():
    adapter, broker, before = make_authenticated_adapter()

    refreshed = adapter.refresh_authenticated_session()

    assert refreshed.user_identifier == before.user_identifier
    assert refreshed.user_name == before.user_name
    assert refreshed.user_identifier == USER_IDENTIFIER


def test_agah_refresh_uses_only_the_refresh_endpoint_once():
    adapter, broker, _ = make_authenticated_adapter()
    before_calls = len(broker.session.calls)

    adapter.refresh_authenticated_session()

    new_calls = broker.session.calls[before_calls:]
    assert len(new_calls) == 1
    assert REFRESH_SUFFIX in new_calls[0][1]


def test_agah_refresh_http_error_preserves_tokens_and_session():
    adapter, broker, before = make_authenticated_adapter(
        refresh_outcome="http_error"
    )

    with pytest.raises(TokenRefreshError):
        adapter.refresh_authenticated_session()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH
    assert adapter.get_authenticated_session() is before


@pytest.mark.parametrize(
    "outcome",
    ["is_success_false", "malformed", "missing_access", "missing_refresh"],
)
def test_agah_refresh_malformed_preserves_state(outcome):
    adapter, broker, before = make_authenticated_adapter(
        refresh_outcome=outcome
    )

    with pytest.raises(TokenRefreshError):
        adapter.refresh_authenticated_session()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH
    assert adapter.get_authenticated_session() is before


def test_agah_refresh_before_authentication_makes_no_request():
    broker = make_broker()
    adapter = AgahAuthenticationAdapter(broker=broker)

    with pytest.raises(TokenRefreshError):
        adapter.refresh_authenticated_session()

    assert broker.session.calls == []


def test_agah_refresh_failure_does_not_leak_tokens():
    adapter, broker, before = make_authenticated_adapter(
        refresh_outcome="explode"
    )

    with pytest.raises(TokenRefreshError) as excinfo:
        adapter.refresh_authenticated_session()

    _assert_no_secret(
        excinfo.value,
        (OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH),
    )
    # The prior authenticated snapshot and its repr stay secret-free.
    for text in (repr(before), str(adapter.get_authenticated_session())):
        assert OLD_ACCESS not in text
        assert OLD_REFRESH not in text


# ===========================================================================
# 4. AuthenticationService.refresh_session
# ===========================================================================

class StubBackend:
    def __init__(self):
        self.entries = {}

    def set_password(self, service, account, password):
        self.entries[(service, account)] = password

    def get_password(self, service, account):
        return self.entries.get((service, account))

    def delete_password(self, service, account):
        del self.entries[(service, account)]


def build_real_system(accounts_spec=((ACC_A, USERNAME, PASSWORD),)):
    accounts = AccountStore()
    credentials = CredentialStore(backend=StubBackend())
    sessions = SessionManager()

    created = {}
    def adapter_factory(account_id):
        broker = make_broker()
        adapter = AgahAuthenticationAdapter(broker=broker)
        created[account_id] = {
            "adapter": adapter,
            "broker": broker,
            "session": broker.session,
        }
        return adapter

    service = AuthenticationService(
        accounts,
        credentials,
        sessions,
        adapter_factories={BROKER_AGAH: adapter_factory},
    )
    for account_id, username, password in accounts_spec:
        accounts.add(account_id, BROKER_AGAH, f"حساب {account_id}")
        credentials.save_credentials(
            account_id, BROKER_AGAH, username, password
        )

    return {
        "service": service,
        "sessions": sessions,
        "created": created,
    }


def login_fully(system, account_id=ACC_A):
    service = system["service"]
    service.begin_login(account_id)
    return service.complete_login(account_id, CAPTCHA_TEXT)


def test_service_refresh_success_synchronizes_all_views():
    system = build_real_system()
    login_fully(system, ACC_A)

    parts = system["created"][ACC_A]
    sessions = system["sessions"]
    before = sessions.get(ACC_A)

    result = system["service"].refresh_session(ACC_A)

    assert isinstance(result, Session)
    assert result is before
    assert sessions.get_token(ACC_A) == NEW_ACCESS
    assert sessions.state(ACC_A) is SessionState.LOGGED_IN

    assert parts["broker"].access_token == NEW_ACCESS
    assert parts["broker"].refresh_token == NEW_REFRESH

    adapter_session = parts["adapter"].get_authenticated_session()
    assert adapter_session.access_token == NEW_ACCESS
    assert adapter_session.refresh_token == NEW_REFRESH
    assert adapter_session.user_identifier == USER_IDENTIFIER


def test_service_refresh_a_does_not_affect_b():
    system = build_real_system(
        accounts_spec=[(ACC_A, USERNAME, PASSWORD), (ACC_B, USERNAME, PASSWORD)]
    )
    login_fully(system, ACC_A)
    login_fully(system, ACC_B)

    b_parts = system["created"][ACC_B]
    b_calls_before = len(b_parts["session"].calls)

    system["service"].refresh_session(ACC_A)

    assert system["sessions"].get_token(ACC_A) == NEW_ACCESS
    assert system["sessions"].get_token(ACC_B) == OLD_ACCESS

    assert b_parts["broker"].access_token == OLD_ACCESS
    assert b_parts["broker"].refresh_token == OLD_REFRESH
    assert b_parts["adapter"].get_authenticated_session().access_token == (
        OLD_ACCESS
    )
    assert len(b_parts["session"].calls) == b_calls_before


def test_service_refresh_unknown_account_rejected_and_no_request():
    system = build_real_system()
    with pytest.raises(AuthenticationServiceError):
        system["service"].refresh_session("no-such-account")


def test_service_refresh_logged_out_rejected_no_request():
    system = build_real_system()
    service = system["service"]
    # Account exists but has never logged in.
    with pytest.raises(AuthenticationServiceError):
        service.refresh_session(ACC_A)
    assert system["sessions"].get_token(ACC_A) is None
    assert ACC_A not in system["created"]


def test_service_refresh_pending_login_rejected_no_request():
    system = build_real_system()
    service = system["service"]
    service.begin_login(ACC_A)  # LOGIN_PENDING

    parts = system["created"][ACC_A]
    calls_before = list(parts["session"].calls)

    with pytest.raises(AuthenticationServiceError):
        service.refresh_session(ACC_A)

    assert system["sessions"].state(ACC_A) is SessionState.LOGIN_PENDING
    assert parts["session"].calls == calls_before
    assert parts["session"].refresh_calls() == []


def test_service_refresh_missing_adapter_rejected_no_request():
    system = build_real_system()
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]

    # Simulate a logged-in session whose retained adapter has disappeared.
    system["service"]._adapters.pop(ACC_A, None)
    calls_before = list(parts["session"].calls)

    with pytest.raises(AuthenticationServiceError):
        system["service"].refresh_session(ACC_A)

    assert system["sessions"].get_token(ACC_A) == OLD_ACCESS
    assert parts["session"].calls == calls_before


def test_service_refresh_unauthenticated_adapter_rejected_no_request():
    system = build_real_system()
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]

    # Force the adapter into an unauthenticated view.
    parts["adapter"]._authenticated = None
    calls_before = list(parts["session"].calls)

    with pytest.raises(AuthenticationServiceError):
        system["service"].refresh_session(ACC_A)

    assert system["sessions"].get_token(ACC_A) == OLD_ACCESS
    assert parts["broker"].access_token == OLD_ACCESS
    assert parts["session"].calls == calls_before


def test_service_failed_refresh_leaves_token_and_state_unchanged():
    system = build_real_system()
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]

    parts["session"].refresh_outcome = "http_error"
    prior_adapter_session = parts["adapter"].get_authenticated_session()

    with pytest.raises(TokenRefreshError):
        system["service"].refresh_session(ACC_A)

    assert system["sessions"].get_token(ACC_A) == OLD_ACCESS
    assert system["sessions"].state(ACC_A) is SessionState.LOGGED_IN
    assert parts["broker"].access_token == OLD_ACCESS
    assert parts["broker"].refresh_token == OLD_REFRESH
    assert parts["adapter"].get_authenticated_session() is prior_adapter_session


def test_service_sync_failure_after_refresh_logs_out_safely():
    """
    Refresh succeeds at the broker and adapter, then the SessionManager
    token replacement fails. The account must NOT be left authenticated
    with three inconsistent views: it exits the authenticated state through
    the existing logout path and requires re-login. The old token is never
    blindly restored (it may already be invalid server-side after renewal),
    and the raised error leaks no token — not even through a reachable
    exception chain pointing at the injected (token-bearing) sync fault.
    """
    from unittest import mock

    system = build_real_system()
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]

    # The injected sync fault deliberately embeds a token value to prove the
    # final error never reaches it through message, repr, or exception chain.
    sync_fault = f"sync backend rejected token {NEW_ACCESS}"

    with mock.patch.object(
        system["sessions"],
        "replace_token",
        side_effect=SessionValidationError(sync_fault),
    ):
        with pytest.raises(AuthenticationServiceError) as excinfo:
            system["service"].refresh_session(ACC_A)

    error = excinfo.value
    service = system["service"]
    sessions = system["sessions"]

    # Step 1 of the scenario: broker + adapter really refreshed.
    assert parts["broker"].access_token == NEW_ACCESS
    assert parts["broker"].refresh_token == NEW_REFRESH
    assert parts["adapter"].get_authenticated_session().access_token == NEW_ACCESS

    # Step 2: sync failed -> safe, unambiguous, non-authenticated final state.
    assert sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert sessions.get_token(ACC_A) is None
    assert sessions.is_logged_in(ACC_A) is False
    assert service.is_logged_in(ACC_A) is False
    assert service.get_adapter(ACC_A) is None

    # The error reports the resolved-out danger explicitly and requires re-login.
    assert "ورود مجدد" in str(error)

    # The chain is fully clean: no token survives via __context__/__cause__.
    assert error.__context__ is None
    assert error.__cause__ is None
    assert isinstance(error, AuthenticationServiceError)
    assert sync_fault not in str(error)
    assert sync_fault not in repr(error)
    _assert_no_secret(error, (OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH))

    # A fresh login is possible from the safe state.
    service.begin_login(ACC_A)
    assert sessions.state(ACC_A) is SessionState.LOGIN_PENDING


def test_service_sync_and_logout_failure_removes_adapter_and_stays_explicit():
    """
    Both the token replacement and the cleanup logout fail. The adapter
    must be removed regardless of the logout outcome, and the emergency
    independent local session invalidation must leave the account
    ``LOGGED_OUT`` with no token even though the existing cleanup path
    failed. Another logged-in account stays untouched. The failure is
    reported explicitly (no fake "safe" claim), continued authenticated
    refresh is rejected, and neither token value survives message, repr,
    or exception chain.
    """
    from unittest import mock

    system = build_real_system(
        accounts_spec=[(ACC_A, USERNAME, PASSWORD), (ACC_B, USERNAME, PASSWORD)]
    )
    login_fully(system, ACC_A)
    login_fully(system, ACC_B)
    parts = system["created"][ACC_A]
    b_parts = system["created"][ACC_B]

    sync_fault = f"sync rejected {OLD_REFRESH}"
    logout_fault = f"logout path failed {NEW_ACCESS}"

    def replacing_replace_token(account_id, token):
        raise SessionValidationError(sync_fault)

    def failing_logout(account_id):
        raise SessionStateError(logout_fault)

    with mock.patch.object(
        system["sessions"], "replace_token", side_effect=replacing_replace_token
    ), mock.patch.object(
        system["sessions"], "logout", side_effect=failing_logout
    ):
        with pytest.raises(AuthenticationServiceError) as excinfo:
            system["service"].refresh_session(ACC_A)

    error = excinfo.value
    service = system["service"]
    sessions = system["sessions"]

    # The broker + adapter for A really refreshed before sync failed.
    assert parts["broker"].access_token == NEW_ACCESS
    assert parts["adapter"].get_authenticated_session().access_token == NEW_ACCESS

    # Emergency local invalidation resolved the session safely.
    assert sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert sessions.is_logged_in(ACC_A) is False
    assert service.is_logged_in(ACC_A) is False
    assert sessions.get_token(ACC_A) is None
    # The old token is gone from the internal token store as well.
    assert sessions._tokens[ACC_A] is None

    # The refreshed adapter is unreachable regardless of the logout outcome.
    assert service.get_adapter(ACC_A) is None

    # The error reports the invalidation explicitly and requires re-login.
    assert "ورود مجدد" in str(error)

    # The account cannot continue authenticated refresh from this state.
    with pytest.raises(AuthenticationServiceError):
        service.refresh_session(ACC_A)

    # The other account keeps its own state, token and adapter.
    assert sessions.state(ACC_B) is SessionState.LOGGED_IN
    assert sessions.is_logged_in(ACC_B) is True
    assert sessions.get_token(ACC_B) == OLD_ACCESS
    assert service.get_adapter(ACC_B) is not None
    assert b_parts["adapter"].get_authenticated_session().access_token == OLD_ACCESS

    # No token survives message, repr, or the reachable exception chain.
    for token_value in (OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH):
        assert token_value not in str(error)
        assert token_value not in repr(error)
    assert error.__context__ is None
    assert error.__cause__ is None
    _assert_no_secret(error, (OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH))


def test_service_sync_and_logout_failure_adapter_removal_independent_of_logout():
    """
    Focused correction-2 regression: both ``replace_token()`` AND
    ``logout()`` fail at the same time, each injected fault deliberately
    embedding a token value. Adapter removal must happen BEFORE (and
    therefore independently of) any ``logout()`` outcome: even though the
    cleanup ``logout`` raises, the authenticated adapter must not remain
    reachable through ``AuthenticationService.get_adapter()`` and the
    account must not be usable for continued authenticated refresh or
    order submission. The emergency local invalidation resolves the local
    session to ``LOGGED_OUT`` with no token. The failure is explicit
    (re-login required) and no token — old or new — survives the message,
    ``repr``, the reachable exception chain or the formatted traceback.
    """
    from unittest import mock

    system = build_real_system()
    login_fully(system, ACC_A)

    service = system["service"]
    sessions = system["sessions"]
    parts = system["created"][ACC_A]

    # Capture the exact authenticated adapter the service currently exposes.
    retained_adapter = service.get_adapter(ACC_A)
    assert retained_adapter is parts["adapter"]

    sync_fault = f"replace_token rejected token {NEW_ACCESS}"
    logout_fault = f"logout rejected token {OLD_REFRESH}"

    def failing_replace_token(account_id, token):
        raise SessionValidationError(sync_fault)

    def failing_logout(account_id):
        raise SessionStateError(logout_fault)

    with mock.patch.object(
        sessions, "replace_token", side_effect=failing_replace_token
    ), mock.patch.object(sessions, "logout", side_effect=failing_logout):
        with pytest.raises(AuthenticationServiceError) as excinfo:
            service.refresh_session(ACC_A)

    error = excinfo.value

    # The broker + adapter really refreshed before sync failed.
    assert parts["broker"].access_token == NEW_ACCESS
    assert parts["broker"].refresh_token == NEW_REFRESH

    # Adapter removal is independent of the failed logout: the adapter is
    # gone from the service's retained-adapter map and unreachable publicly.
    assert ACC_A not in service._adapters
    assert service.get_adapter(ACC_A) is None
    assert service.get_adapter(ACC_A) is not retained_adapter

    # Emergency local invalidation resolved the local session safely.
    assert sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert sessions.is_logged_in(ACC_A) is False
    assert service.is_logged_in(ACC_A) is False
    assert sessions.get_token(ACC_A) is None
    assert sessions._tokens[ACC_A] is None

    # The failure is explicit and points at re-login (no fake safe claim).
    assert "ورود مجدد" in str(error)

    # Continued authenticated refresh is refused without a retained adapter.
    with pytest.raises(AuthenticationServiceError):
        service.refresh_session(ACC_A)

    # No token survives message, repr, reachable chain or formatted traceback.
    assert error.__context__ is None
    assert error.__cause__ is None
    assert sync_fault not in str(error)
    assert sync_fault not in repr(error)
    assert logout_fault not in str(error)
    _assert_no_secret(error, (OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH))


def test_service_sync_logout_and_invalidate_failure_stays_unresolved_and_explicit():
    """
    Every cleanup path fails at once: ``replace_token``, the existing
    ``logout`` cleanup AND the independent emergency ``invalidate_session``.
    The final error must be an explicit ``AuthenticationServiceError`` that
    says the emergency invalidation did NOT happen and that no safe state is
    confirmed — it must NOT claim success or a resolved/safe session. The
    adapter of A must be unreachable. The REAL leftover session state is
    asserted (not pretended safe): with invalidation fully blocked by the
    mock, A is still authenticated with its old token. No old or new token
    leaks through message, repr, ``__context__``, ``__cause__`` or the
    reachable exception chain, and account B stays untouched.
    """
    from unittest import mock

    system = build_real_system(
        accounts_spec=[(ACC_A, USERNAME, PASSWORD), (ACC_B, USERNAME, PASSWORD)]
    )
    login_fully(system, ACC_A)
    login_fully(system, ACC_B)
    parts = system["created"][ACC_A]
    b_parts = system["created"][ACC_B]

    sync_fault = f"sync rejected {OLD_REFRESH}"
    logout_fault = f"logout path failed {NEW_ACCESS}"
    invalidate_fault = f"invalidate path failed {OLD_ACCESS}"

    def failing_replace_token(account_id, token):
        raise SessionValidationError(sync_fault)

    def failing_logout(account_id):
        raise SessionStateError(logout_fault)

    def failing_invalidate_session(account_id):
        raise SessionNotFoundError(invalidate_fault)

    with mock.patch.object(
        system["sessions"], "replace_token", side_effect=failing_replace_token
    ), mock.patch.object(
        system["sessions"], "logout", side_effect=failing_logout
    ), mock.patch.object(
        system["sessions"],
        "invalidate_session",
        side_effect=failing_invalidate_session,
    ):
        with pytest.raises(AuthenticationServiceError) as excinfo:
            system["service"].refresh_session(ACC_A)

    error = excinfo.value
    service = system["service"]
    sessions = system["sessions"]

    # The final error is the service error type, and it is explicit that the
    # emergency invalidation did NOT happen and no safe state is confirmed.
    assert isinstance(error, AuthenticationServiceError)
    message = str(error)
    assert "ابطال اضطراری" in message
    assert "ممکن نشد" in message
    assert "وضعیت امن ادعا نمی‌شود" in message
    # No false claim: neither the emergency-invalidation success wording nor
    # the ordinary logout-success wording may appear.
    assert "نشست محلی این حساب باطل شد" not in message
    assert "خارج شد" not in message

    # The adapter of A is unreachable through the service.
    assert service.get_adapter(ACC_A) is None

    # The REAL leftover state is asserted, not pretended safe: every mocked
    # cleanup path raised before mutating, so A is still LOGGED_IN with its
    # prior token in the store.
    assert sessions.state(ACC_A) is SessionState.LOGGED_IN
    assert sessions.is_logged_in(ACC_A) is True
    assert sessions.get_token(ACC_A) == OLD_ACCESS
    assert sessions._tokens[ACC_A] == OLD_ACCESS

    # Continued authenticated refresh is still refused (no adapter retained).
    with pytest.raises(AuthenticationServiceError):
        service.refresh_session(ACC_A)

    # Account B keeps its own state, token and adapter untouched.
    assert sessions.state(ACC_B) is SessionState.LOGGED_IN
    assert sessions.is_logged_in(ACC_B) is True
    assert sessions.get_token(ACC_B) == OLD_ACCESS
    assert service.get_adapter(ACC_B) is not None
    assert b_parts["adapter"].get_authenticated_session().access_token == OLD_ACCESS

    # No token survives message, repr, or the reachable exception chain.
    for token_value in (OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH):
        assert token_value not in message
        assert token_value not in repr(error)
    assert error.__context__ is None
    assert error.__cause__ is None
    _assert_no_secret(error, (OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH))


# ---------------------------------------------------------------------------
# Scripted adapters for invalid-result / consistency cases
# ---------------------------------------------------------------------------

class ScriptedRefreshAdapter(AuthenticationAdapter):
    def __init__(self, refresh_result=None, refresh_error=None,
                 authenticated=True):
        self.refresh_result = refresh_result
        self.refresh_error = refresh_error
        self.refresh_calls = 0
        self._authenticated = (
            AuthenticatedSession(
                access_token=OLD_ACCESS,
                user_identifier=USER_IDENTIFIER,
                refresh_token=OLD_REFRESH,
                user_name=USERNAME,
            )
            if authenticated else None
        )

    @property
    def broker_name(self):
        return BROKER_AGAH

    def begin_login(self, username, password):
        return LoginChallenge(
            kind=CHALLENGE_CAPTCHA_IMAGE, display_payload="img", prompt="p"
        )

    def complete_login(self, response):
        return self._authenticated

    def cancel_login(self):
        return None

    def is_authenticated(self):
        return self._authenticated is not None

    def get_authenticated_session(self):
        return self._authenticated

    def refresh_authenticated_session(self):
        self.refresh_calls += 1
        if self.refresh_error is not None:
            raise self.refresh_error
        return self.refresh_result


def build_scripted_system(adapter):
    accounts = AccountStore()
    credentials = CredentialStore(backend=StubBackend())
    sessions = SessionManager()
    service = AuthenticationService(
        accounts, credentials, sessions,
        adapter_factories={BROKER_AGAH: lambda account_id: adapter},
    )
    accounts.add(ACC_A, BROKER_AGAH, "حساب A")
    credentials.save_credentials(ACC_A, BROKER_AGAH, USERNAME, PASSWORD)
    service.begin_login(ACC_A)
    service.complete_login(ACC_A, CAPTCHA_TEXT)
    return {"service": service, "sessions": sessions, "adapter": adapter}


@pytest.mark.parametrize("bad_result", [None, "not-a-session", 42, object()])
def test_service_invalid_adapter_result_not_marked_synced(bad_result):
    adapter = ScriptedRefreshAdapter(refresh_result=bad_result)
    system = build_scripted_system(adapter)

    with pytest.raises(AuthenticationServiceError):
        system["service"].refresh_session(ACC_A)

    assert system["sessions"].get_token(ACC_A) == OLD_ACCESS


def test_service_empty_adapter_token_not_marked_synced():
    empty = AuthenticatedSession(
        access_token="   ", user_identifier=USER_IDENTIFIER
    )
    adapter = ScriptedRefreshAdapter(refresh_result=empty)
    system = build_scripted_system(adapter)

    with pytest.raises(AuthenticationServiceError):
        system["service"].refresh_session(ACC_A)

    assert system["sessions"].get_token(ACC_A) == OLD_ACCESS


def test_service_inconsistent_adapter_view_not_marked_synced():
    # refresh returns a valid new session, but the adapter's own view still
    # reports the old token: the accounts' views would diverge.
    new_session = AuthenticatedSession(
        access_token=NEW_ACCESS,
        user_identifier=USER_IDENTIFIER,
        refresh_token=NEW_REFRESH,
        user_name=USERNAME,
    )
    adapter = ScriptedRefreshAdapter(refresh_result=new_session)
    adapter._authenticated = AuthenticatedSession(
        access_token=OLD_ACCESS,
        user_identifier=USER_IDENTIFIER,
        refresh_token=OLD_REFRESH,
        user_name=USERNAME,
    )
    # refresh_authenticated_session returns new_session without updating the
    # adapter's stored view.
    system = build_scripted_system(adapter)

    with pytest.raises(AuthenticationServiceError):
        system["service"].refresh_session(ACC_A)

    assert system["sessions"].get_token(ACC_A) == OLD_ACCESS


def test_service_no_token_leak_on_failure_and_in_snapshots():
    system = build_real_system()
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]

    parts["session"].refresh_outcome = "explode"

    with pytest.raises(TokenRefreshError) as excinfo:
        system["service"].refresh_session(ACC_A)

    _assert_no_secret(
        excinfo.value,
        (OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH),
    )

    snapshot = system["sessions"].get(ACC_A)
    assert OLD_ACCESS not in repr(snapshot)
    assert OLD_ACCESS not in str(snapshot)
    assert NEW_ACCESS not in repr(snapshot)

    adapter_session = parts["adapter"].get_authenticated_session()
    assert OLD_ACCESS not in repr(adapter_session)
    assert OLD_REFRESH not in repr(adapter_session)


def test_service_module_references_no_agah_specifics():
    source = inspect.getsource(authentication_service_module)
    assert "AgaahBroker" not in source
    assert "refresh-token" not in source
    assert "accessToken" not in source
    assert "refreshToken" not in source


# ===========================================================================
# 5. Offline guarantee
# ===========================================================================

def test_full_sync_makes_no_real_socket():
    class NoNetwork(socket.socket):
        def __init__(self, *args, **kwargs):
            raise AssertionError("token sync must not open a socket")

    original = socket.socket
    socket.socket = NoNetwork
    try:
        system = build_real_system()
        login_fully(system, ACC_A)
        result = system["service"].refresh_session(ACC_A)

        assert isinstance(result, Session)
        assert system["sessions"].get_token(ACC_A) == NEW_ACCESS
    finally:
        socket.socket = original
