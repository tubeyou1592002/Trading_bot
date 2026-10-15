"""
test_block9_task4_integration.py

Block 9 — Task 4, Stage 3: offline integration & regression.

This module wires the REAL production components together and exercises the
whole authentication path end to end, fully offline:

    AccountStore            (ui/account_store.py)          — real
    CredentialStore         (ui/credential_store.py)       — real, with an
                                                             in-memory stub
                                                             backend
    SessionManager          (ui/session_manager.py)        — real
    AuthenticationService   (ui/authentication_service.py) — real
    AgahAuthenticationAdapter (brokers/agaah/auth_adapter.py) — real
    AgaahBroker.get_captcha()/login() (brokers/agaah/broker.py) — real

Only two things are replaced, exactly as the Task 4 adapter/service tests
already do:

    * the OS credential vault   → an in-memory ``StubBackend``
    * the HTTP transport        → an in-memory ``FakeAgahSession`` installed
                                  on each real ``AgaahBroker.session``

No real network request, no real account, credential, token or order is ever
used. The fake HTTP session serves payloads with exactly the response shapes
that the real ``AgaahBroker.get_captcha()``/``login()`` parse.

Proven here (acceptance criteria, section 4.b):

    1. two Agah accounts get two independent adapters and two independent
       HTTP sessions;
    2. each account's credentials reach only that account's adapter;
    3. a successful login of one account does not log the other in;
    4. each account's token is recorded in its own session and never confused
       with the other account's token;
    5. a failure / cancel of one account leaves the other untouched;
    6. an incomplete / failed broker response never marks a login successful;
    7. no password / access token / refresh token leaks through an error
       message, an exception chain or a public output;
    8. no real network request is sent.

Run:
    py -3 -m pytest -q test_block9_task4_integration.py
"""

import base64
import socket

import pytest

from brokers.agaah import AgaahBroker
from brokers.manager import BrokerManager
from brokers.agaah.auth_adapter import make_agah_adapter_factory
from brokers.agaah.auth_adapter import AgahAuthenticationAdapter
from brokers.authentication import (
    CHALLENGE_CAPTCHA_IMAGE,
    IncompleteLoginError,
    LoginChallenge,
    LoginChallengeError,
    LoginRejectedError,
)
from ui.account_store import AccountStore
from ui.authentication_service import (
    AuthenticationService,
    AuthenticationServiceError,
    UnknownBrokerError,
)
from ui.credential_store import CredentialStore
from ui.session_manager import SessionManager, SessionState


BROKER_AGAH = "آگاه"
BROKER_UNKNOWN = "نامعلوم"

ACC_A = "ACC-integration-A"
ACC_B = "ACC-integration-B"
USER_A = "agah-user-A"
USER_B = "agah-user-B"
PASS_A = "agah-pass-A-SECRET"
PASS_B = "agah-pass-B-SECRET"

CAPTCHA_TEXT = "1234"
CAPTCHA_IMAGE = base64.b64encode(b"fake-png-bytes").decode("ascii")

# Fake, account-specific secrets. They are deliberately distinct per account
# so a cross-account mix-up is detectable.
ACCESS_A = "ACCESS-TOKEN-A-0001"
REFRESH_A = "REFRESH-TOKEN-A-0002"
UID_A = "user-identifier-A"
ACCESS_B = "ACCESS-TOKEN-B-0001"
REFRESH_B = "REFRESH-TOKEN-B-0002"
UID_B = "user-identifier-B"

_TOKENS = {
    ACC_A: {"access": ACCESS_A, "refresh": REFRESH_A, "uid": UID_A},
    ACC_B: {"access": ACCESS_B, "refresh": REFRESH_B, "uid": UID_B},
}

DEFAULT_ACCOUNTS = (
    (ACC_A, USER_A, PASS_A),
    (ACC_B, USER_B, PASS_B),
)


# ---------------------------------------------------------------------------
# In-memory credential backend (mirrors the project's test convention)
# ---------------------------------------------------------------------------

class StubBackend:
    """In-memory keyring-compatible backend; records every call."""

    def __init__(self):
        self.entries = {}
        self.calls = []

    def set_password(self, service, account, password):
        self.calls.append(("set", service, account))
        self.entries[(service, account)] = password

    def get_password(self, service, account):
        self.calls.append(("get", service, account))
        return self.entries.get((service, account))

    def delete_password(self, service, account):
        self.calls.append(("delete", service, account))
        del self.entries[(service, account)]


# ---------------------------------------------------------------------------
# Fake HTTP layer (installed on the REAL AgaahBroker.session)
# ---------------------------------------------------------------------------

class FakeResponse:
    """The slice of requests.Response that AgaahBroker consumes."""

    def __init__(self, payload, status_ok=True):
        self._payload = payload
        self._ok = status_ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("HTTP error from fake session")

    def json(self):
        return self._payload


class FakeAgahSession:
    """
    Fake requests.Session for the Agah API, scoped to ONE account.

    It records every call and serves exactly the captcha / login response
    shapes the real AgaahBroker parses. ``login_outcome`` scripts the
    authenticate endpoint:

        "success"            -> isSuccess with full per-account data
        "bad_captcha"        -> isSuccess=false (rejected login)
        "no_access_token"    -> isSuccess=true, accessToken missing
        "no_user_identifier" -> isSuccess=true, userIdentifier missing
        "no_data"            -> isSuccess=true, data is not a dict
        "http_error"         -> raise_for_status raises
        "explode"            -> authenticate raises an error that ECHOES the
                                password and this account's tokens, to prove
                                redaction
    """

    def __init__(self, account_id, login_outcome="success"):
        self.account_id = account_id
        self.login_outcome = login_outcome
        self.calls = []
        tokens = _TOKENS[account_id]
        self.captcha_id = f"captcha-id-{account_id}"
        self._access = tokens["access"]
        self._refresh = tokens["refresh"]
        self._uid = tokens["uid"]

    # AgaahBroker calls session.get(...) and session.post(...).
    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return FakeResponse({
            "isSuccess": True,
            "data": {
                "captchaId": self.captcha_id,
                "captcha": CAPTCHA_IMAGE,
            },
        })

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        payload = kwargs.get("json", {})

        if self.login_outcome == "http_error":
            return FakeResponse({}, status_ok=False)

        if self.login_outcome == "bad_captcha":
            return FakeResponse({
                "isSuccess": False,
                "message": "کد کپچا یا اعتبارنامه نامعتبر است",
                "errorCode": 12,
            })

        if self.login_outcome == "explode":
            raise RuntimeError(
                "login backend exploded "
                f"password={payload.get('password')} "
                f"access={self._access} "
                f"refresh={self._refresh}"
            )

        data = {
            "accessToken": self._access,
            "refreshToken": self._refresh,
            "userIdentifier": self._uid,
            "userName": payload.get("userName"),
        }
        if self.login_outcome == "no_access_token":
            data.pop("accessToken")
        if self.login_outcome == "no_user_identifier":
            data.pop("userIdentifier")

        if self.login_outcome == "no_data":
            return FakeResponse({"isSuccess": True, "data": None})

        return FakeResponse({"isSuccess": True, "data": data})


class _StaticDeviceInfo:
    """
    Offline replacement for the real ``ExternalDeviceInfoProvider``.

    It returns a fixed device info dict so the real ``AgaahBroker.login()``
    body runs unchanged WITHOUT reading or writing ``client_id.txt``.
    """

    def get(self):
        return {
            "clientId": "offline-test-client",
            "deviceModel": "Chrome",
            "osName": "Linux",
            "osVersion": "0.0.0",
            "appVersion": "offline-test",
            "platform": "web",
        }


# ---------------------------------------------------------------------------
# System builder: real components + real Agah adapter + fake HTTP
# ---------------------------------------------------------------------------

def build_system(accounts_spec=DEFAULT_ACCOUNTS, outcomes=None):
    """
    Build the real authentication stack with an offline HTTP/credential seam.

    Returns a dict with the service and every component so tests can inspect
    the real per-account broker / adapter / HTTP session.
    """
    accounts = AccountStore()
    credential_backend = StubBackend()
    credentials = CredentialStore(backend=credential_backend)
    sessions = SessionManager()
    outcome_map = dict(outcomes or {})

    created = {}
    manager = BrokerManager()

    agah_factory = make_agah_adapter_factory(manager)
    def managed_adapter_factory(account_id):
        adapter = agah_factory(account_id)
        adapter.broker.session = FakeAgahSession(
            account_id, outcome_map.get(account_id, "success")
        )
        adapter.broker.device_info_provider = _StaticDeviceInfo()
        created[account_id] = {
            "adapter": adapter,
            "broker": adapter.broker,
            "session": adapter.broker.session,
        }
        return adapter

    service = AuthenticationService(
        accounts,
        credentials,
        sessions,
        adapter_factories={BROKER_AGAH: managed_adapter_factory},
    )

    for account_id, username, password in accounts_spec:
        accounts.add(account_id, BROKER_AGAH, f"حساب {account_id}")
        credentials.save_credentials(
            account_id, BROKER_AGAH, username, password
        )

    return {
        "service": service,
        "accounts": accounts,
        "credentials": credentials,
        "credential_backend": credential_backend,
        "sessions": sessions,
        "created": created,
        "outcomes": outcome_map,
    }


def login_fully(system, account_id=ACC_A, captcha=CAPTCHA_TEXT):
    """Begin + complete a login; returns (challenge, session_snapshot)."""
    service = system["service"]
    challenge = service.begin_login(account_id)
    session = service.complete_login(account_id, captcha)
    return challenge, session


def _iter_exception_chain(error):
    """Yield every exception reachable via __cause__ / __context__ once."""
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


def _assert_no_secret_anywhere(error, secrets):
    for exc in _iter_exception_chain(error):
        for secret in secrets:
            assert secret not in str(exc), (secret, str(exc))
            assert secret not in repr(exc), (secret, repr(exc))


# ---------------------------------------------------------------------------
# 1. Full-stack success with real components and fake HTTP
# ---------------------------------------------------------------------------

def test_full_stack_login_succeeds_and_records_real_state():
    system = build_system(accounts_spec=[(ACC_A, USER_A, PASS_A)])
    challenge, session = login_fully(system)

    # Public challenge is displayable and carries no broker-specific id.
    assert isinstance(challenge, LoginChallenge)
    assert challenge.kind == CHALLENGE_CAPTCHA_IMAGE
    assert challenge.display_payload == CAPTCHA_IMAGE
    broker_captcha_id = system["created"][ACC_A]["session"].captcha_id
    assert broker_captcha_id not in repr(challenge)
    assert broker_captcha_id not in str(challenge)

    # Real SessionManager recorded the login for exactly this account.
    assert session.account_id == ACC_A
    assert session.broker_name == BROKER_AGAH
    assert session.state is SessionState.LOGGED_IN
    assert system["service"].is_logged_in(ACC_A) is True
    assert system["sessions"].is_logged_in(ACC_A) is True
    assert system["sessions"].get_token(ACC_A) == ACCESS_A

    # The retained adapter is the REAL Agah adapter wrapping a REAL broker.
    adapter = system["service"].get_adapter(ACC_A)
    assert isinstance(adapter, AgahAuthenticationAdapter)
    assert isinstance(adapter.broker, AgaahBroker)
    assert adapter.broker is system["created"][ACC_A]["broker"]
    assert adapter.broker.access_token == ACCESS_A
    assert adapter.broker.refresh_token == REFRESH_A
    assert adapter.broker.user_identifier == UID_A


def test_full_stack_uses_only_existing_agah_endpoints():
    system = build_system(accounts_spec=[(ACC_A, USER_A, PASS_A)])
    login_fully(system)
    urls = [c[1] for c in system["created"][ACC_A]["session"].calls]
    assert any("captcha/getcaptcha" in u for u in urls)
    assert any("users/authenticate" in u for u in urls)


# ---------------------------------------------------------------------------
# 2. Independence of two accounts (acceptance criterion 4.b)
# ---------------------------------------------------------------------------

def test_two_accounts_get_independent_brokers_and_http_sessions():
    system = build_system()
    login_fully(system, ACC_A)
    login_fully(system, ACC_B)

    adapter_a = system["service"].get_adapter(ACC_A)
    adapter_b = system["service"].get_adapter(ACC_B)

    assert adapter_a is not adapter_b
    assert adapter_a.broker is not adapter_b.broker
    assert adapter_a.broker.session is not adapter_b.broker.session
    assert system["created"][ACC_A]["session"] is not system["created"][ACC_B]["session"]


def test_each_accounts_credentials_only_reach_its_own_adapter():
    system = build_system()
    login_fully(system, ACC_A)
    login_fully(system, ACC_B)

    def post_payload(account_id):
        calls = system["created"][account_id]["session"].calls
        return [c[2]["json"] for c in calls if c[0] == "post"][0]

    payload_a = post_payload(ACC_A)
    payload_b = post_payload(ACC_B)

    assert payload_a["userName"] == USER_A
    assert payload_a["password"] == PASS_A
    assert payload_b["userName"] == USER_B
    assert payload_b["password"] == PASS_B

    # No cross-contamination between the two accounts.
    assert payload_a["password"] != PASS_B
    assert payload_b["password"] != PASS_A
    assert PASS_B not in str(system["created"][ACC_A]["session"].calls)
    assert PASS_A not in str(system["created"][ACC_B]["session"].calls)

    # Each adapter used the captchaId from its OWN broker's captcha request.
    assert payload_a["captchaId"] == system["created"][ACC_A]["session"].captcha_id
    assert payload_b["captchaId"] == system["created"][ACC_B]["session"].captcha_id
    assert payload_a["captchaId"] != payload_b["captchaId"]


def test_successful_login_of_one_does_not_log_in_the_other():
    system = build_system()
    login_fully(system, ACC_A)

    assert system["service"].is_logged_in(ACC_A) is True
    assert system["service"].is_logged_in(ACC_B) is False
    assert system["service"].get_adapter(ACC_B) is None

    # Opening a pending attempt for B does not disturb A's established login.
    system["service"].begin_login(ACC_B)
    assert system["service"].is_logged_in(ACC_A) is True
    assert system["service"].is_logged_in(ACC_B) is False
    assert system["sessions"].state(ACC_B) is SessionState.LOGIN_PENDING


def test_each_accounts_token_is_recorded_in_its_own_session():
    system = build_system()
    login_fully(system, ACC_A)
    login_fully(system, ACC_B)

    assert system["sessions"].get_token(ACC_A) == ACCESS_A
    assert system["sessions"].get_token(ACC_B) == ACCESS_B
    assert system["sessions"].get_token(ACC_A) != system["sessions"].get_token(ACC_B)

    assert system["service"].get_adapter(ACC_A).broker.access_token == ACCESS_A
    assert system["service"].get_adapter(ACC_B).broker.access_token == ACCESS_B
    # No swapping between the two accounts.
    assert system["service"].get_adapter(ACC_A).broker.access_token != ACCESS_B
    assert system["service"].get_adapter(ACC_B).broker.access_token != ACCESS_A


def test_failure_of_one_account_leaves_the_other_untouched():
    system = build_system(outcomes={ACC_B: "bad_captcha"})
    login_fully(system, ACC_A)

    system["service"].begin_login(ACC_B)
    with pytest.raises(LoginRejectedError):
        system["service"].complete_login(ACC_B, CAPTCHA_TEXT)

    # A is still fully logged in with its own token.
    assert system["service"].is_logged_in(ACC_A) is True
    assert system["sessions"].get_token(ACC_A) == ACCESS_A
    assert system["service"].get_adapter(ACC_A) is not None

    # B is back to a clean logged-out state.
    assert system["service"].is_logged_in(ACC_B) is False
    assert system["sessions"].state(ACC_B) is SessionState.LOGGED_OUT
    assert system["sessions"].get_token(ACC_B) is None
    assert system["service"].get_adapter(ACC_B) is None


def test_cancel_of_one_account_leaves_the_other_untouched():
    system = build_system()
    login_fully(system, ACC_A)

    system["service"].begin_login(ACC_B)
    system["service"].cancel_login(ACC_B)

    assert system["service"].is_logged_in(ACC_A) is True
    assert system["sessions"].get_token(ACC_A) == ACCESS_A
    assert system["sessions"].state(ACC_B) is SessionState.LOGGED_OUT


# ---------------------------------------------------------------------------
# 3. Incomplete / failed broker responses never authenticate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "outcome, expected_error",
    [
        ("no_access_token", IncompleteLoginError),
        ("no_user_identifier", IncompleteLoginError),
        ("no_data", IncompleteLoginError),
        ("bad_captcha", LoginRejectedError),
        ("http_error", LoginRejectedError),
    ],
)
def test_incomplete_or_failed_response_never_authenticates(outcome, expected_error):
    system = build_system(
        accounts_spec=[(ACC_A, USER_A, PASS_A)],
        outcomes={ACC_A: outcome},
    )
    system["service"].begin_login(ACC_A)

    with pytest.raises(expected_error):
        system["service"].complete_login(ACC_A, CAPTCHA_TEXT)

    assert system["service"].is_logged_in(ACC_A) is False
    assert system["service"].get_adapter(ACC_A) is None
    assert system["sessions"].state(ACC_A) is SessionState.LOGGED_OUT
    assert system["sessions"].get_token(ACC_A) is None
    assert system["created"][ACC_A]["broker"].access_token is None


# ---------------------------------------------------------------------------
# 4. No password / token leakage (acceptance criterion 4.b-7)
# ---------------------------------------------------------------------------

def test_no_secret_leaks_through_error_message_or_chain():
    system = build_system(
        accounts_spec=[(ACC_A, USER_A, PASS_A)],
        outcomes={ACC_A: "explode"},
    )
    system["service"].begin_login(ACC_A)

    # Pre-existing tokens on the real broker: they must be redacted too.
    broker = system["created"][ACC_A]["broker"]
    broker.access_token = ACCESS_A
    broker.refresh_token = REFRESH_A

    with pytest.raises(Exception) as excinfo:
        system["service"].complete_login(ACC_A, CAPTCHA_TEXT)

    error = excinfo.value
    secrets = (PASS_A, ACCESS_A, REFRESH_A)
    for secret in secrets:
        assert secret not in str(error)
        assert secret not in repr(error)
    _assert_no_secret_anywhere(error, secrets)

    # Failed login left no authenticated state behind.
    assert system["service"].is_logged_in(ACC_A) is False
    assert system["service"].get_adapter(ACC_A) is None
    assert system["sessions"].get_token(ACC_A) is None


def test_public_outputs_never_expose_passwords_or_tokens():
    system = build_system(accounts_spec=[(ACC_A, USER_A, PASS_A)])
    _, session = login_fully(system)
    adapter = system["service"].get_adapter(ACC_A)
    authenticated = adapter.get_authenticated_session()

    for secret in (PASS_A, ACCESS_A, REFRESH_A):
        for text in (
            repr(system["service"]),
            repr(adapter),
            repr(session),
            repr(authenticated),
            str(authenticated),
            repr(system["sessions"].get(ACC_A)),
        ):
            assert secret not in text

    # Password is not retained anywhere the produced objects expose.
    assert PASS_A not in repr(system["service"])
    assert PASS_A not in repr(adapter.broker)


# ---------------------------------------------------------------------------
# 5. Fail-closed service wiring
# ---------------------------------------------------------------------------

def test_unknown_broker_fails_closed():
    accounts = AccountStore()
    credentials = CredentialStore(backend=StubBackend())
    sessions = SessionManager()
    accounts.add(ACC_A, BROKER_UNKNOWN, "حساب ناشناس")
    credentials.save_credentials(ACC_A, BROKER_UNKNOWN, USER_A, PASS_A)

    service = AuthenticationService(
        accounts, credentials, sessions,
        adapter_factories={BROKER_AGAH: lambda account_id: AgahAuthenticationAdapter()},
    )

    with pytest.raises(UnknownBrokerError):
        service.begin_login(ACC_A)

    assert service.is_logged_in(ACC_A) is False


def test_relogin_while_logged_in_is_rejected_and_keeps_state():
    system = build_system(accounts_spec=[(ACC_A, USER_A, PASS_A)])
    _, session = login_fully(system)
    adapter_before = system["service"].get_adapter(ACC_A)

    with pytest.raises(AuthenticationServiceError):
        system["service"].begin_login(ACC_A)

    assert system["service"].is_logged_in(ACC_A) is True
    assert system["service"].get_adapter(ACC_A) is adapter_before
    assert system["sessions"].get_token(ACC_A) == ACCESS_A
    assert session.state is SessionState.LOGGED_IN


# ---------------------------------------------------------------------------
# 6. Offline guarantees (acceptance criterion 4.b-8)
# ---------------------------------------------------------------------------

def test_no_real_network_is_used():
    class NoNetwork(socket.socket):
        def __init__(self, *args, **kwargs):
            raise AssertionError("integration must not open a socket")

    original = socket.socket
    socket.socket = NoNetwork
    try:
        system = build_system(outcomes={ACC_B: "bad_captcha"})

        # Full successful login for A.
        login_fully(system, ACC_A)

        # Failed login for B.
        system["service"].begin_login(ACC_B)
        with pytest.raises(LoginRejectedError):
            system["service"].complete_login(ACC_B, CAPTCHA_TEXT)

        # Cancelled attempt for a fresh account.
        system["service"].begin_login(ACC_B)
        system["service"].cancel_login(ACC_B)

        # A second login for B, now scripted to succeed.
        system["outcomes"][ACC_B] = "success"
        login_fully(system, ACC_B)
    finally:
        socket.socket = original

    # Every broker was served by the in-memory fake HTTP session.
    for account_id, parts in system["created"].items():
        assert isinstance(parts["broker"].session, FakeAgahSession), account_id
        assert parts["session"].calls


def test_real_broker_gets_the_fake_http_session_installed():
    system = build_system(accounts_spec=[(ACC_A, USER_A, PASS_A)])
    login_fully(system, ACC_A)
    broker = system["created"][ACC_A]["broker"]
    assert isinstance(broker, AgaahBroker)
    assert isinstance(broker.session, FakeAgahSession)
    # The real login path populated the broker's credentials store fields.
    assert broker.username == USER_A


# ---------------------------------------------------------------------------
# 7. Repeated / simultaneous login attempts rejected with no side effects
# ---------------------------------------------------------------------------

def test_relogin_while_logged_in_rejected_no_factory_call():
    """
    A second begin_login while already LOGGED_IN must be rejected and must
    NOT build a new adapter, read credentials, or make any HTTP call.

    The fake HTTP session's request count is compared before and after the
    rejected attempt, and the established login (adapter identity, session
    state, token) must remain exactly unchanged.
    """
    system = build_system(accounts_spec=[(ACC_A, USER_A, PASS_A)])
    login_fully(system, ACC_A)
    service = system["service"]
    http = system["created"][ACC_A]["session"]

    adapter_before = service.get_adapter(ACC_A)
    broker_before = adapter_before.broker
    token_before = system["sessions"].get_token(ACC_A)
    state_before = system["sessions"].state(ACC_A)
    calls_before = list(http.calls)

    with pytest.raises(AuthenticationServiceError):
        service.begin_login(ACC_A)

    # The rejected attempt issued no additional HTTP request.
    assert len(http.calls) == len(calls_before)
    assert http.calls == calls_before

    # Adapter identity, session state and token are untouched.
    assert service.is_logged_in(ACC_A) is True
    assert state_before is SessionState.LOGGED_IN
    assert system["sessions"].state(ACC_A) is SessionState.LOGGED_IN
    assert service.get_adapter(ACC_A) is adapter_before
    assert service.get_adapter(ACC_A).broker is broker_before
    assert system["created"][ACC_A]["adapter"] is adapter_before
    assert system["sessions"].get_token(ACC_A) == token_before == ACCESS_A


def test_second_login_attempt_while_pending_rejected_no_extra_work():
    """
    Starting a second login for an account with a pending attempt must be
    rejected immediately, with no extra adapter build, credential read,
    or HTTP call.

    The fake HTTP session's request count is compared before and after the
    rejected attempt; the pending adapter, session state and (absent) token
    stay untouched, and the first attempt remains completable.
    """
    system = build_system(accounts_spec=[(ACC_A, USER_A, PASS_A)])
    service = system["service"]
    challenge = service.begin_login(ACC_A)
    assert isinstance(challenge, LoginChallenge)

    http = system["created"][ACC_A]["session"]
    pending_adapter_before = system["created"][ACC_A]["adapter"]
    state_before = system["sessions"].state(ACC_A)
    token_before = system["sessions"].get_token(ACC_A)
    calls_before = list(http.calls)

    with pytest.raises(AuthenticationServiceError):
        service.begin_login(ACC_A)

    # No additional HTTP calls and no replacement adapter from the rejected
    # second attempt.
    assert len(http.calls) == len(calls_before)
    assert http.calls == calls_before
    assert system["created"][ACC_A]["adapter"] is pending_adapter_before

    # Pending state and the absent token are unchanged.
    assert state_before is SessionState.LOGIN_PENDING
    assert system["sessions"].state(ACC_A) is SessionState.LOGIN_PENDING
    assert service.is_logged_in(ACC_A) is False
    assert token_before is None
    assert system["sessions"].get_token(ACC_A) is None

    # First attempt still completable, using the same pending adapter.
    session = service.complete_login(ACC_A, CAPTCHA_TEXT)
    assert session.state is SessionState.LOGGED_IN
    assert service.is_logged_in(ACC_A) is True
    assert service.get_adapter(ACC_A) is pending_adapter_before


def test_failure_after_reservation_resets_session_and_allows_retry():
    """
    A failure that occurs after session reservation (here: credential
    retrieval) must reset the session to LOGGED_OUT and clear the temp
    attempt, and a fresh login attempt must work once the cause is fixed.
    """
    system = build_system(accounts_spec=[(ACC_A, USER_A, PASS_A)])
    service = system["service"]

    # Remove credentials after they were saved in build_system.
    service._credentials._backend.entries.clear()

    with pytest.raises(AuthenticationServiceError):
        service.begin_login(ACC_A)

    assert service.is_logged_in(ACC_A) is False
    assert system["sessions"].state(ACC_A) is SessionState.LOGGED_OUT
    assert system["sessions"].get_token(ACC_A) is None
    assert service.get_adapter(ACC_A) is None

    # Restore credentials, retry succeeds.
    service._credentials.save_credentials(ACC_A, BROKER_AGAH, USER_A, PASS_A)
    login_fully(system, ACC_A)
    assert service.is_logged_in(ACC_A) is True


def test_failure_of_one_account_does_not_touch_other_after_reservation():
    """
    A failure after session reservation (here: captcha failure in complete_login)
    must affect only the failing account: another account's session, token,
    adapter, and HTTP session remain untouched.
    """
    system = build_system(outcomes={ACC_A: "bad_captcha"})
    service = system["service"]

    # Attempt login for ACC_A (will fail on complete_login due to bad_captcha).
    service.begin_login(ACC_A)
    with pytest.raises(LoginRejectedError):
        service.complete_login(ACC_A, CAPTCHA_TEXT)

    # ACC_A is back to clean LOGGED_OUT.
    assert service.is_logged_in(ACC_A) is False
    assert system["sessions"].state(ACC_A) is SessionState.LOGGED_OUT
    assert system["sessions"].get_token(ACC_A) is None
    assert service.get_adapter(ACC_A) is None

    # ACC_B is completely unaffected and can log in successfully.
    login_fully(system, ACC_B)
    assert service.is_logged_in(ACC_B) is True
    assert system["sessions"].state(ACC_B) is SessionState.LOGGED_IN
    assert system["sessions"].get_token(ACC_B) is not None
    assert service.get_adapter(ACC_B) is not None


def test_failure_of_one_account_does_not_touch_other_after_reservation():
    """
    A failure after session reservation must affect only the failing account:
    another account's session, token, adapter, and HTTP session remain
    untouched.
    """
    system = build_system(outcomes={ACC_A: "bad_captcha"})
    service = system["service"]

    # Attempt login for ACC_A — the captcha failure must be caught and
    # ACC_A reset to LOGGED_OUT, while ACC_B remains clean.
    service.begin_login(ACC_A)
    with pytest.raises(LoginRejectedError):
        service.complete_login(ACC_A, CAPTCHA_TEXT)

    # ACC_A is back to clean LOGGED_OUT.
    assert service.is_logged_in(ACC_A) is False
    assert system["sessions"].state(ACC_A) is SessionState.LOGGED_OUT
    assert system["sessions"].get_token(ACC_A) is None
    assert service.get_adapter(ACC_A) is None

    # ACC_B is completely unaffected and can log in successfully.
    login_fully(system, ACC_B)
    assert service.is_logged_in(ACC_B) is True
    assert system["sessions"].state(ACC_B) is SessionState.LOGGED_IN
    assert system["sessions"].get_token(ACC_B) is not None
    assert service.get_adapter(ACC_B) is not None
