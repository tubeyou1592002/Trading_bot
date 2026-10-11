"""
test_block9_task4_agah_auth_adapter.py

Block 9 — Task 4, Stage 2: tests for the Agah authentication adapter
(brokers/agaah/auth_adapter.py), fully offline.

The adapter wraps the REAL AgaahBroker methods (get_captcha / login) but the
HTTP layer is replaced by an injected fake session, so:

    * no network request is ever sent,
    * no real credentials are used,
    * the real Agaah API response shapes are exercised exactly as the
      production code parses them.

Contract coverage:

    1. Successful Agah login → AuthenticatedSession with a valid access
       token and userIdentifier.
    2. Failed captcha / rejected login → LoginRejectedError.
    3. Apparently-successful but incomplete API response →
       IncompleteLoginError (never authenticated).
    4. captchaId stays inside the adapter and never crosses the boundary.
    5. Two adapters on the same broker are fully independent: broker
       instance, HTTP session, login state and token.
    6. Cleanup of a failed attempt state and cancel_login.
    7. No password or token leakage in outputs, errors or exception chains.

Run:
    pytest -q test_block9_task4_agah_auth_adapter.py
"""

import base64
import socket

import pytest

from brokers import authentication as auth_module
from brokers.authentication import (
    AuthenticatedSession,
    AuthenticationUnavailableError,
    CHALLENGE_CAPTCHA_IMAGE,
    IncompleteLoginError,
    LoginChallenge,
    LoginChallengeError,
    LoginNotInProgressError,
    LoginRejectedError,
)
from brokers.agaah import AgaahBroker
from brokers.agaah.auth_adapter import AgahAuthenticationAdapter


USERNAME = "agah-user"
PASSWORD = "agah-pass-SECRET"
CAPTCHA_ID = "captcha-id-xyz"
CAPTCHA_TEXT = "1234"
CAPTCHA_IMAGE = base64.b64encode(b"fake-png-bytes").decode("ascii")
ACCESS_TOKEN = "ACCESS-TOKEN-SECRET-123"
REFRESH_TOKEN = "REFRESH-TOKEN-SECRET-456"
USER_IDENTIFIER = "user-identifier-789"


# ---------------------------------------------------------------------------
# Fake HTTP layer (replaces requests.Session on the real broker instance)
# ---------------------------------------------------------------------------

class FakeResponse:
    """Mimics the slice of requests.Response that AgaahBroker consumes."""

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
    Fake requests.Session for the Agah API. It records calls and serves
    scripted payloads for the captcha and login endpoints.

    login_outcome controls what the authenticate endpoint returns:
        "success"          -> isSuccess with full data
        "bad_captcha"      -> isSuccess=false (rejected login)
        "no_access_token"  -> isSuccess=true but missing accessToken
        "no_user_identifier" -> isSuccess=true but missing userIdentifier
        "no_data"          -> isSuccess=true but data is not a dict
        "http_error"       -> raise_for_status raises
    """

    def __init__(self, login_outcome="success"):
        self.calls = []
        self.login_outcome = login_outcome

    # AgaahBroker calls session.get(...) and session.post(...).
    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return FakeResponse({
            "isSuccess": True,
            "data": {
                "captchaId": CAPTCHA_ID,
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

        data = {
            "accessToken": ACCESS_TOKEN,
            "refreshToken": REFRESH_TOKEN,
            "userIdentifier": USER_IDENTIFIER,
            "userName": USERNAME,
        }
        if self.login_outcome == "no_access_token":
            data.pop("accessToken")
        if self.login_outcome == "no_user_identifier":
            data.pop("userIdentifier")

        if self.login_outcome == "no_data":
            return FakeResponse({"isSuccess": True, "data": None})

        return FakeResponse({"isSuccess": True, "data": data})


def make_adapter(login_outcome="success"):
    """Build a real AgaahBroker with a fake HTTP session installed."""
    broker = AgaahBroker()
    broker.session = FakeAgahSession(login_outcome)
    return AgahAuthenticationAdapter(broker=broker), broker


def make_real_broker_with_fake_session(login_outcome="success"):
    """The adapter must work with a broker that was NOT pre-injected too."""
    broker = AgaahBroker()
    broker.session = FakeAgahSession(login_outcome)
    return broker


# ---------------------------------------------------------------------------
# 1. Successful login
# ---------------------------------------------------------------------------

def test_begin_login_returns_displayable_captcha_challenge():
    adapter, broker = make_adapter()
    challenge = adapter.begin_login(USERNAME, PASSWORD)

    assert isinstance(challenge, LoginChallenge)
    assert challenge.kind == CHALLENGE_CAPTCHA_IMAGE
    assert challenge.display_payload == CAPTCHA_IMAGE
    assert "captchaId" not in repr(challenge)
    assert "captchaId" not in str(challenge)


def test_begin_login_calls_the_real_captcha_endpoint():
    adapter, broker = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)

    captcha_calls = [c for c in broker.session.calls if c[0] == "get"]
    assert len(captcha_calls) == 1
    assert "captcha/getcaptcha" in captcha_calls[0][1]


def test_begin_login_does_not_authenticate_yet():
    adapter, _ = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    assert adapter.is_authenticated() is False
    assert adapter.get_authenticated_session() is None


def test_complete_login_succeeds_with_real_api_response():
    adapter, broker = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    session = adapter.complete_login(CAPTCHA_TEXT)

    assert isinstance(session, AuthenticatedSession)
    assert session.access_token == ACCESS_TOKEN
    assert session.user_identifier == USER_IDENTIFIER
    assert session.refresh_token == REFRESH_TOKEN
    assert session.user_name == USERNAME


def test_complete_login_sends_captcha_response_and_id():
    adapter, broker = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    adapter.complete_login(CAPTCHA_TEXT)

    login_calls = [c for c in broker.session.calls if c[0] == "post"]
    assert len(login_calls) == 1
    payload = login_calls[0][2]["json"]
    assert payload["userName"] == USERNAME
    assert payload["captcha"] == CAPTCHA_TEXT
    assert payload["captchaId"] == CAPTCHA_ID
    assert "authenticate" in login_calls[0][1]


def test_login_marks_adapter_authenticated():
    adapter, broker = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    adapter.complete_login(CAPTCHA_TEXT)

    assert adapter.is_authenticated() is True
    assert adapter.get_authenticated_session() is not None
    assert broker.access_token == ACCESS_TOKEN
    assert broker.user_identifier == USER_IDENTIFIER


def test_broker_name_matches_agah():
    adapter, _ = make_adapter()
    assert adapter.broker_name == "آگاه"


def test_default_construction_creates_own_broker():
    # No broker injected: the adapter still owns a real AgaahBroker instance.
    adapter = AgahAuthenticationAdapter()
    assert isinstance(adapter.broker, AgaahBroker)
    assert adapter.broker_name == "آگاه"


# ---------------------------------------------------------------------------
# 2. Failed captcha / rejected login
# ---------------------------------------------------------------------------

def test_rejected_login_raises_login_rejected():
    adapter, _ = make_adapter(login_outcome="bad_captcha")
    adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(LoginRejectedError):
        adapter.complete_login("wrong-captcha")


def test_rejected_login_does_not_authenticate():
    adapter, broker = make_adapter(login_outcome="bad_captcha")
    adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(LoginRejectedError):
        adapter.complete_login("wrong-captcha")

    assert adapter.is_authenticated() is False
    assert broker.access_token is None
    assert broker.user_identifier is None


def test_rejected_login_message_does_not_leak_password():
    adapter, _ = make_adapter(login_outcome="bad_captcha")
    adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(LoginRejectedError) as excinfo:
        adapter.complete_login("wrong-captcha")

    text = str(excinfo.value)
    assert PASSWORD not in text
    assert PASSWORD not in repr(excinfo.value)


def test_empty_captcha_response_is_rejected():
    adapter, _ = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(LoginRejectedError):
        adapter.complete_login("   ")


# ---------------------------------------------------------------------------
# 3. Apparently-successful but incomplete API responses
# ---------------------------------------------------------------------------

def test_missing_access_token_is_incomplete_login():
    adapter, _ = make_adapter(login_outcome="no_access_token")
    adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(IncompleteLoginError):
        adapter.complete_login(CAPTCHA_TEXT)


def test_missing_user_identifier_is_incomplete_login():
    adapter, _ = make_adapter(login_outcome="no_user_identifier")
    adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(IncompleteLoginError):
        adapter.complete_login(CAPTCHA_TEXT)


def test_missing_data_is_incomplete_login():
    adapter, _ = make_adapter(login_outcome="no_data")
    adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(IncompleteLoginError):
        adapter.complete_login(CAPTCHA_TEXT)


def test_incomplete_login_never_authenticates():
    for outcome in ("no_access_token", "no_user_identifier", "no_data"):
        adapter, broker = make_adapter(login_outcome=outcome)
        adapter.begin_login(USERNAME, PASSWORD)

        with pytest.raises(IncompleteLoginError):
            adapter.complete_login(CAPTCHA_TEXT)

        assert adapter.is_authenticated() is False
        assert broker.access_token is None


def test_http_error_does_not_authenticate():
    adapter, _ = make_adapter(login_outcome="http_error")
    adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(Exception):
        adapter.complete_login(CAPTCHA_TEXT)

    assert adapter.is_authenticated() is False


# ---------------------------------------------------------------------------
# 4. captchaId stays inside the adapter
# ---------------------------------------------------------------------------

def test_challenge_does_not_expose_captcha_id():
    adapter, _ = make_adapter()
    challenge = adapter.begin_login(USERNAME, PASSWORD)

    public = (repr(challenge), str(challenge), vars(challenge))
    for text in public:
        assert CAPTCHA_ID not in str(text)


def test_adapter_public_api_does_not_expose_captcha_id():
    adapter, _ = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)

    # No public attribute on the adapter leaks the broker-specific id.
    public_attrs = {
        name: getattr(adapter, name)
        for name in dir(adapter)
        if not name.startswith("_")
    }
    for name, value in public_attrs.items():
        assert CAPTCHA_ID not in str(value), name


# ---------------------------------------------------------------------------
# 5. Two adapters on the same broker are fully independent
# ---------------------------------------------------------------------------

def test_two_adapters_have_independent_broker_instances():
    adapter_a, broker_a = make_adapter()
    adapter_b, broker_b = make_adapter()

    assert adapter_a is not adapter_b
    assert broker_a is not broker_b
    assert broker_a.session is not broker_b.session


def test_two_adapters_logins_are_independent():
    adapter_a, broker_a = make_adapter()
    adapter_b, broker_b = make_adapter()

    adapter_a.begin_login(USERNAME, PASSWORD)
    adapter_a.complete_login(CAPTCHA_TEXT)

    # B is untouched.
    assert adapter_b.is_authenticated() is False
    assert broker_b.access_token is None
    assert broker_b.user_identifier is None

    # B logs in independently with its own token.
    adapter_b.begin_login("other-user", "other-pass")
    adapter_b.complete_login(CAPTCHA_TEXT)

    assert adapter_b.is_authenticated() is True
    assert broker_b.access_token == ACCESS_TOKEN
    assert broker_a.access_token == ACCESS_TOKEN
    assert broker_a.session is not broker_b.session


def test_two_adapters_keep_independent_login_state():
    adapter_a, broker_a = make_adapter()
    adapter_b, broker_b = make_adapter()

    adapter_a.begin_login(USERNAME, PASSWORD)
    adapter_b.begin_login(USERNAME, PASSWORD)

    # A fails, B succeeds afterwards — A's failure must not affect B.
    broker_a.session.login_outcome = "bad_captcha"
    with pytest.raises(LoginRejectedError):
        adapter_a.complete_login(CAPTCHA_TEXT)

    adapter_b.complete_login(CAPTCHA_TEXT)

    assert adapter_a.is_authenticated() is False
    assert adapter_b.is_authenticated() is True


def test_independent_sessions_send_their_own_captcha_ids():
    adapter_a, broker_a = make_adapter()
    adapter_b, broker_b = make_adapter()

    adapter_a.begin_login(USERNAME, PASSWORD)
    adapter_b.begin_login(USERNAME, PASSWORD)

    adapter_a.complete_login(CAPTCHA_TEXT)
    adapter_b.complete_login(CAPTCHA_TEXT)

    a_payload = [c for c in broker_a.session.calls if c[0] == "post"][0][2]["json"]
    b_payload = [c for c in broker_b.session.calls if c[0] == "post"][0][2]["json"]

    assert a_payload["captchaId"] == CAPTCHA_ID
    assert b_payload["captchaId"] == CAPTCHA_ID
    # Two separate HTTP sessions, two separate request trails.
    assert len(broker_a.session.calls) == 2
    assert len(broker_b.session.calls) == 2


# ---------------------------------------------------------------------------
# 6. Cleanup of a failed attempt and cancel_login
# ---------------------------------------------------------------------------

def test_failed_login_clears_pending_attempt():
    adapter, broker = make_adapter(login_outcome="bad_captcha")
    adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(LoginRejectedError):
        adapter.complete_login(CAPTCHA_TEXT)

    # A new login can be started again from a clean state.
    challenge = adapter.begin_login(USERNAME, PASSWORD)
    assert isinstance(challenge, LoginChallenge)


def test_complete_login_without_begin_is_rejected():
    adapter, _ = make_adapter()
    with pytest.raises(LoginNotInProgressError):
        adapter.complete_login(CAPTCHA_TEXT)


def test_cancel_login_clears_pending_state():
    adapter, broker = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    adapter.cancel_login()

    with pytest.raises(LoginNotInProgressError):
        adapter.complete_login(CAPTCHA_TEXT)


def test_cancel_login_twice_raises():
    adapter, _ = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    adapter.cancel_login()

    with pytest.raises(LoginNotInProgressError):
        adapter.cancel_login()


def test_cancel_without_begin_raises():
    adapter, _ = make_adapter()
    with pytest.raises(LoginNotInProgressError):
        adapter.cancel_login()


def test_second_begin_login_while_pending_raises():
    adapter, _ = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    with pytest.raises(LoginNotInProgressError):
        adapter.begin_login(USERNAME, PASSWORD)


def test_begin_login_after_cancel_works():
    adapter, _ = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    adapter.cancel_login()

    challenge = adapter.begin_login(USERNAME, PASSWORD)
    assert isinstance(challenge, LoginChallenge)
    adapter.complete_login(CAPTCHA_TEXT)
    assert adapter.is_authenticated() is True


def test_cancel_after_complete_login_raises():
    adapter, _ = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    adapter.complete_login(CAPTCHA_TEXT)

    with pytest.raises(LoginNotInProgressError):
        adapter.cancel_login()


def test_begin_login_after_success_is_rejected():
    adapter, broker = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    first = adapter.complete_login(CAPTCHA_TEXT)

    with pytest.raises(LoginNotInProgressError):
        adapter.begin_login(USERNAME, PASSWORD)

    # The established session, its tokens and the broker state are kept.
    assert adapter.is_authenticated() is True
    assert adapter.get_authenticated_session() is first
    assert first.access_token == ACCESS_TOKEN
    assert broker.access_token == ACCESS_TOKEN
    assert broker.refresh_token == REFRESH_TOKEN


def test_begin_login_rejects_invalid_credentials_input():
    adapter, _ = make_adapter()
    with pytest.raises(LoginNotInProgressError):
        adapter.begin_login("", PASSWORD)
    with pytest.raises(LoginNotInProgressError):
        adapter.begin_login(USERNAME, "")


# ---------------------------------------------------------------------------
# 7. No password or token leakage anywhere
# ---------------------------------------------------------------------------

def test_authenticated_session_repr_does_not_leak_tokens():
    adapter, _ = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    session = adapter.complete_login(CAPTCHA_TEXT)

    for text in (repr(session), str(session)):
        assert ACCESS_TOKEN not in text
        assert REFRESH_TOKEN not in text


def test_password_is_not_kept_after_success():
    adapter, _ = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    adapter.complete_login(CAPTCHA_TEXT)

    source = repr(adapter)
    assert PASSWORD not in source


def test_password_is_not_kept_after_failure():
    adapter, _ = make_adapter(login_outcome="bad_captcha")
    adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(LoginRejectedError):
        adapter.complete_login(CAPTCHA_TEXT)

    assert PASSWORD not in repr(adapter)


def test_challenge_error_message_does_not_leak_password():
    adapter, broker = make_adapter()
    # Force the captcha endpoint to fail with a message containing the secret.
    def failing_get(url, **kwargs):
        raise RuntimeError(f"captcha failed with {PASSWORD}")

    broker.session.get = failing_get

    with pytest.raises(LoginChallengeError) as excinfo:
        adapter.begin_login(USERNAME, PASSWORD)

    assert PASSWORD not in str(excinfo.value)
    assert PASSWORD not in repr(excinfo.value)


def test_rejected_error_chain_does_not_leak_password():
    adapter, _ = make_adapter(login_outcome="bad_captcha")
    adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(LoginRejectedError) as excinfo:
        adapter.complete_login(CAPTCHA_TEXT)

    error = excinfo.value
    assert PASSWORD not in str(error)
    # The original exception must not carry the secret through the chain.
    cause = error.__cause__
    context = error.__context__
    for exc in (cause, context):
        if exc is not None:
            assert PASSWORD not in str(exc)


def test_captcha_failure_leaves_no_pending_state():
    adapter, broker = make_adapter()
    broker.session.get = lambda url, **kwargs: (_ for _ in ()).throw(
        RuntimeError("captcha down")
    )

    with pytest.raises(LoginChallengeError):
        adapter.begin_login(USERNAME, PASSWORD)

    with pytest.raises(LoginNotInProgressError):
        adapter.complete_login(CAPTCHA_TEXT)


def test_incomplete_captcha_response_raises_challenge_error():
    adapter, broker = make_adapter()
    broker.session.get = lambda url, **kwargs: FakeResponse({
        "isSuccess": True,
        "data": {"captchaId": None, "captcha": CAPTCHA_IMAGE},
    })

    with pytest.raises(LoginChallengeError):
        adapter.begin_login(USERNAME, PASSWORD)


# ---------------------------------------------------------------------------
# 7b. Comprehensive secret redaction (password + broker tokens + chain)
# ---------------------------------------------------------------------------

def _iter_exception_chain(error):
    """
    Yield every exception reachable from ``error`` through ``__cause__`` and
    ``__context__`` exactly once. A set of ids guards against cycles.
    """
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


def _assert_no_secret_in_exception(error, secrets):
    for secret in secrets:
        for exc in _iter_exception_chain(error):
            assert secret not in str(exc), (secret, str(exc))
            assert secret not in repr(exc), (secret, repr(exc))


def test_complete_login_failure_never_leaks_password_or_tokens():
    """
    A failing login() must not leak the attempt password nor the broker's
    access/refresh tokens through the final error, its repr, or the whole
    __cause__/__context__ chain.
    """
    adapter, broker = make_adapter()
    # Tokens already present on the broker object: exercises the real
    # broker-token collection path in the redaction helper.
    broker.access_token = ACCESS_TOKEN
    broker.refresh_token = REFRESH_TOKEN

    def failing_login(**kwargs):
        raise RuntimeError(
            "login exploded "
            f"password={PASSWORD} "
            f"access={ACCESS_TOKEN} "
            f"refresh={REFRESH_TOKEN}"
        )

    broker.login = failing_login

    adapter.begin_login(USERNAME, PASSWORD)
    with pytest.raises(Exception) as excinfo:
        adapter.complete_login(CAPTCHA_TEXT)

    error = excinfo.value
    secrets = (PASSWORD, ACCESS_TOKEN, REFRESH_TOKEN)
    for secret in secrets:
        assert secret not in str(error)
        assert secret not in repr(error)
    _assert_no_secret_in_exception(error, secrets)


def test_captcha_failure_never_leaks_password_or_tokens():
    """
    A failing get_captcha() whose message contains the password and both
    tokens must be fully redacted in the final error, its repr and the
    whole exception chain.
    """
    adapter, broker = make_adapter()
    broker.access_token = ACCESS_TOKEN
    broker.refresh_token = REFRESH_TOKEN

    def failing_get(url, **kwargs):
        raise RuntimeError(
            "captcha exploded "
            f"password={PASSWORD} "
            f"access={ACCESS_TOKEN} "
            f"refresh={REFRESH_TOKEN}"
        )

    broker.session.get = failing_get

    with pytest.raises(LoginChallengeError) as excinfo:
        adapter.begin_login(USERNAME, PASSWORD)

    error = excinfo.value
    secrets = (PASSWORD, ACCESS_TOKEN, REFRESH_TOKEN)
    for secret in secrets:
        assert secret not in str(error)
        assert secret not in repr(error)
    _assert_no_secret_in_exception(error, secrets)


def test_clean_error_has_no_context_inside_outer_except():
    """
    Regression: when the adapter is invoked from inside an outer ``except``
    block whose exception message carries the password and both tokens, the
    final raised error must not recover any of them -- neither through
    ``__context__``/``__cause__`` (both must be ``None``) nor through the
    recursive exception chain.
    """
    adapter, broker = make_adapter()
    broker.access_token = ACCESS_TOKEN
    broker.refresh_token = REFRESH_TOKEN

    def failing_login(**kwargs):
        # Clean inner failure: the only source of secrets is the outer except.
        raise RuntimeError("login exploded")

    broker.login = failing_login
    adapter.begin_login(USERNAME, PASSWORD)

    secrets = (PASSWORD, ACCESS_TOKEN, REFRESH_TOKEN)

    with pytest.raises(Exception) as excinfo:
        try:
            raise RuntimeError(
                "outer failure "
                f"password={PASSWORD} "
                f"access={ACCESS_TOKEN} "
                f"refresh={REFRESH_TOKEN}"
            )
        except RuntimeError:
            adapter.complete_login(CAPTCHA_TEXT)

    error = excinfo.value
    assert error.__context__ is None
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    _assert_no_secret_in_exception(error, secrets)


def test_re_login_after_success_keeps_state_and_sends_no_captcha():
    """
    Once authenticated, a second begin_login() must be rejected without
    changing the existing session/tokens and without requesting a new
    captcha.
    """
    adapter, broker = make_adapter()
    adapter.begin_login(USERNAME, PASSWORD)
    first = adapter.complete_login(CAPTCHA_TEXT)

    captcha_calls_before = [c for c in broker.session.calls if c[0] == "get"]
    tokens_before = (broker.access_token, broker.refresh_token)

    with pytest.raises(LoginNotInProgressError):
        adapter.begin_login(USERNAME, PASSWORD)

    assert adapter.is_authenticated() is True
    assert adapter.get_authenticated_session() is first
    assert first.access_token == ACCESS_TOKEN
    assert (broker.access_token, broker.refresh_token) == tokens_before
    # No new captcha request and no pending attempt was opened.
    captcha_calls_after = [c for c in broker.session.calls if c[0] == "get"]
    assert captcha_calls_after == captcha_calls_before


# ---------------------------------------------------------------------------
# 8. Offline guarantees
# ---------------------------------------------------------------------------

def test_no_real_network_is_used():
    class NoNetwork(socket.socket):
        def __init__(self, *args, **kwargs):
            raise AssertionError("adapter must not open a socket")

    original = socket.socket
    socket.socket = NoNetwork
    try:
        adapter, _ = make_adapter()
        adapter.begin_login(USERNAME, PASSWORD)
        adapter.complete_login(CAPTCHA_TEXT)

        # Re-login on an authenticated adapter is rejected locally.
        with pytest.raises(LoginNotInProgressError):
            adapter.begin_login(USERNAME, PASSWORD)

        # A fresh pending attempt can be cancelled without any network use.
        other, _ = make_adapter()
        other.begin_login(USERNAME, PASSWORD)
        other.cancel_login()

        with pytest.raises(LoginNotInProgressError):
            other.cancel_login()
    finally:
        socket.socket = original


def test_adapter_uses_only_existing_agah_broker_api():
    """
    The adapter must reuse get_captcha()/login() and not invent endpoints.
    It is a thin wrapper over the existing AgaahBroker behavior.
    """
    adapter, broker = make_adapter()

    called = {"captcha": False, "login": False}
    original_get_captcha = broker.get_captcha
    original_login = broker.login

    def spy_get_captcha():
        called["captcha"] = True
        return original_get_captcha()

    def spy_login(**kwargs):
        called["login"] = True
        return original_login(**kwargs)

    broker.get_captcha = spy_get_captcha
    broker.login = spy_login

    adapter.begin_login(USERNAME, PASSWORD)
    adapter.complete_login(CAPTCHA_TEXT)

    assert called["captcha"] is True
    assert called["login"] is True
