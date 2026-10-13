"""
test_block9_task5_refresh_token.py

Block 9 — Task 5, Stage 2A: offline tests for the Agah refresh-token
primitive ``AgaahBroker.refresh_tokens()``.

Everything here is fully offline:

    * a real ``AgaahBroker`` is constructed, but its HTTP transport
      (``broker.session``) is replaced by an in-memory fake session;
    * fake responses carry the confirmed API response shape
      (``isSuccess`` + ``data.accessToken`` / ``data.refreshToken``);
    * no real network request, credential, token or account is ever used.

Contract covered (Stage 2A):

    1. correct endpoint, HTTP method and JSON field names;
    2. a successful response replaces both tokens together;
    3. a missing/invalid current access token sends no request;
    4. a missing/invalid current refresh token sends no request;
    5. an HTTP error leaves both original tokens unchanged;
    6. an invalid JSON / malformed response leaves both unchanged;
    7. ``isSuccess`` false leaves both unchanged;
    8. missing / empty / non-string replacement tokens leave both unchanged;
    9. failure messages and the whole exception chain never leak either the
       old or the returned token values;
    10. exactly one refresh request is made per direct invocation.

What this file deliberately does NOT assert: automatic 401 interception,
retry, token rotation semantics, token lifetime, or persistence. Those are
out of scope for Stage 2A.

Run:
    python -m pytest -q test_block9_task5_refresh_token.py
"""

import socket

import pytest

from brokers.agaah.broker import AgaahBroker


OLD_ACCESS = "OLD-ACCESS-TOKEN-SECRET-111"
OLD_REFRESH = "OLD-REFRESH-TOKEN-SECRET-222"
NEW_ACCESS = "NEW-ACCESS-TOKEN-SECRET-333"
NEW_REFRESH = "NEW-REFRESH-TOKEN-SECRET-444"

REFRESH_URL = (
    "https://tseonlineapi.agah.com/api/v1/users/refresh-token"
)


# ---------------------------------------------------------------------------
# Fake HTTP layer
# ---------------------------------------------------------------------------

class FakeResponse:
    """Mimics the slice of ``requests.Response`` the primitive consumes."""

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


class FakeSession:
    """
    Fake ``requests.Session`` that records every call and serves one
    scripted response (or raises one scripted error).
    """

    def __init__(self, response=None, error=None):
        self.calls = []
        self._response = response
        self._error = error

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if self._error is not None:
            raise self._error
        return self._response

    def get(self, url, **kwargs):  # pragma: no cover - safety guard
        self.calls.append(("get", url, kwargs))
        raise AssertionError("refresh_tokens() must not issue a GET request")


def make_broker(session, access=OLD_ACCESS, refresh=OLD_REFRESH):
    """A real AgaahBroker with a fake HTTP session and preset tokens."""
    broker = AgaahBroker()
    broker.session = session
    broker.access_token = access
    broker.refresh_token = refresh
    return broker


def success_payload(access=NEW_ACCESS, refresh=NEW_REFRESH):
    return {
        "isSuccess": True,
        "data": {
            "accessToken": access,
            "refreshToken": refresh,
        },
    }


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
    for secret in secrets:
        for exc in _iter_exception_chain(error):
            assert secret not in str(exc), (secret, str(exc))
            assert secret not in repr(exc), (secret, repr(exc))


# ---------------------------------------------------------------------------
# 1. Endpoint, method and JSON field names
# ---------------------------------------------------------------------------

def test_sends_confirmed_endpoint_method_and_fields():
    session = FakeSession(FakeResponse(success_payload()))
    broker = make_broker(session)

    broker.refresh_tokens()

    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "post"
    assert url == REFRESH_URL
    assert kwargs["json"] == {
        "accessToken": OLD_ACCESS,
        "refreshToken": OLD_REFRESH,
    }
    # No unverified payload fields.
    assert set(kwargs["json"].keys()) == {"accessToken", "refreshToken"}


def test_sends_no_unverified_headers():
    session = FakeSession(FakeResponse(success_payload()))
    broker = make_broker(session)

    broker.refresh_tokens()

    _, _, kwargs = session.calls[0]
    assert "headers" not in kwargs


# ---------------------------------------------------------------------------
# 2. Successful refresh
# ---------------------------------------------------------------------------

def test_success_replaces_both_tokens():
    session = FakeSession(FakeResponse(success_payload()))
    broker = make_broker(session)

    broker.refresh_tokens()

    assert broker.access_token == NEW_ACCESS
    assert broker.refresh_token == NEW_REFRESH


def test_success_replaces_tokens_together_and_returns_none():
    session = FakeSession(FakeResponse(success_payload()))
    broker = make_broker(session)

    before = (broker.access_token, broker.refresh_token)
    result = broker.refresh_tokens()

    assert isinstance(before, tuple)
    assert broker.access_token == NEW_ACCESS
    assert broker.refresh_token == NEW_REFRESH
    assert result is None


# ---------------------------------------------------------------------------
# 3/4. Both current tokens are required; otherwise no request
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "access",
    [None, "", "   ", 12345, ["not", "a", "string"]],
)
def test_missing_or_invalid_access_token_sends_no_request(access):
    session = FakeSession(FakeResponse(success_payload()))
    broker = make_broker(session, access=access, refresh=OLD_REFRESH)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert session.calls == []
    assert broker.access_token == access
    assert broker.refresh_token == OLD_REFRESH


@pytest.mark.parametrize(
    "refresh",
    [None, "", "   ", 12345, ["not", "a", "string"]],
)
def test_missing_or_invalid_refresh_token_sends_no_request(refresh):
    session = FakeSession(FakeResponse(success_payload()))
    broker = make_broker(session, access=OLD_ACCESS, refresh=refresh)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert session.calls == []
    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == refresh


def test_missing_tokens_never_change_state():
    session = FakeSession(FakeResponse(success_payload()))
    broker = make_broker(session, access=None, refresh=None)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert broker.access_token is None
    assert broker.refresh_token is None
    assert session.calls == []


# ---------------------------------------------------------------------------
# 5. HTTP error
# ---------------------------------------------------------------------------

def test_http_error_keeps_both_tokens():
    session = FakeSession(FakeResponse({}, status_ok=False))
    broker = make_broker(session)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH
    assert len(session.calls) == 1


# ---------------------------------------------------------------------------
# 6. Invalid JSON / malformed response
# ---------------------------------------------------------------------------

def test_invalid_json_keeps_both_tokens():
    session = FakeSession(
        FakeResponse(json_error=ValueError("response is not JSON"))
    )
    broker = make_broker(session)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "not-a-dict",
        [1, 2, 3],
        {"isSuccess": True},                       # no data
        {"isSuccess": True, "data": None},         # data not a dict
        {"isSuccess": True, "data": "bad"},        # data not a dict
        {"isSuccess": True, "data": []},           # data not a dict
    ],
)
def test_malformed_response_keeps_both_tokens(payload):
    session = FakeSession(FakeResponse(payload))
    broker = make_broker(session)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH
    assert len(session.calls) == 1


# ---------------------------------------------------------------------------
# 7. isSuccess false
# ---------------------------------------------------------------------------

def test_is_success_false_keeps_both_tokens():
    session = FakeSession(FakeResponse({
        "isSuccess": False,
        "data": {
            "accessToken": NEW_ACCESS,
            "refreshToken": NEW_REFRESH,
        },
    }))
    broker = make_broker(session)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH


def test_missing_is_success_flag_keeps_both_tokens():
    session = FakeSession(FakeResponse({
        "data": {
            "accessToken": NEW_ACCESS,
            "refreshToken": NEW_REFRESH,
        },
    }))
    broker = make_broker(session)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH


@pytest.mark.parametrize(
    "is_success",
    [1, 0, "true", "false", "True", "1", [], [0], {}, {"x": 1}],
)
def test_malformed_truthy_is_success_is_rejected(is_success):
    # Only the JSON boolean true (``is True``) is accepted; any other
    # truthy value must fail closed and leave both tokens unchanged.
    session = FakeSession(FakeResponse({
        "isSuccess": is_success,
        "data": {
            "accessToken": NEW_ACCESS,
            "refreshToken": NEW_REFRESH,
        },
    }))
    broker = make_broker(session)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH
    assert len(session.calls) == 1


def test_json_boolean_true_is_accepted():
    session = FakeSession(FakeResponse({
        "isSuccess": True,
        "data": {
            "accessToken": NEW_ACCESS,
            "refreshToken": NEW_REFRESH,
        },
    }))
    broker = make_broker(session)

    broker.refresh_tokens()

    assert broker.access_token == NEW_ACCESS
    assert broker.refresh_token == NEW_REFRESH


# ---------------------------------------------------------------------------
# 8. Missing / empty / non-string replacement tokens
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_access",
    [None, "", "   ", 12345, ["x"]],
)
def test_invalid_replacement_access_token_keeps_both_tokens(bad_access):
    data = {"accessToken": bad_access, "refreshToken": NEW_REFRESH}
    session = FakeSession(FakeResponse({"isSuccess": True, "data": data}))
    broker = make_broker(session)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH


@pytest.mark.parametrize(
    "bad_refresh",
    [None, "", "   ", 12345, ["x"]],
)
def test_invalid_replacement_refresh_token_keeps_both_tokens(bad_refresh):
    data = {"accessToken": NEW_ACCESS, "refreshToken": bad_refresh}
    session = FakeSession(FakeResponse({"isSuccess": True, "data": data}))
    broker = make_broker(session)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH


def test_missing_replacement_tokens_keep_both_tokens():
    session = FakeSession(FakeResponse({"isSuccess": True, "data": {}}))
    broker = make_broker(session)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH


def test_valid_access_but_invalid_refresh_is_atomic():
    # A valid new access token must NOT be applied when the refresh token
    # is unusable: the pair is replaced together or not at all.
    session = FakeSession(FakeResponse({
        "isSuccess": True,
        "data": {"accessToken": NEW_ACCESS, "refreshToken": ""},
    }))
    broker = make_broker(session)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    assert broker.access_token == OLD_ACCESS
    assert broker.refresh_token == OLD_REFRESH


# ---------------------------------------------------------------------------
# 9. No secret leakage
# ---------------------------------------------------------------------------

def test_network_error_message_does_not_leak_old_tokens():
    error = RuntimeError(
        "boom "
        f"access={OLD_ACCESS} "
        f"refresh={OLD_REFRESH}"
    )
    session = FakeSession(error=error)
    broker = make_broker(session)

    with pytest.raises(RuntimeError) as excinfo:
        broker.refresh_tokens()

    _assert_no_secret(excinfo.value, (OLD_ACCESS, OLD_REFRESH))


def test_http_error_does_not_leak_tokens():
    session = FakeSession(FakeResponse({}, status_ok=False))
    broker = make_broker(session)

    with pytest.raises(RuntimeError) as excinfo:
        broker.refresh_tokens()

    _assert_no_secret(excinfo.value, (OLD_ACCESS, OLD_REFRESH))


def test_failed_response_does_not_leak_returned_tokens():
    # isSuccess true, valid new access token, missing refresh token:
    # the returned access token must not appear in the error output.
    session = FakeSession(FakeResponse({
        "isSuccess": True,
        "data": {"accessToken": NEW_ACCESS},
    }))
    broker = make_broker(session)

    with pytest.raises(RuntimeError) as excinfo:
        broker.refresh_tokens()

    _assert_no_secret(
        excinfo.value,
        (OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH),
    )


def test_is_success_false_does_not_leak_server_message_or_tokens():
    session = FakeSession(FakeResponse({
        "isSuccess": False,
        "message": (
            f"rejected {OLD_ACCESS} {OLD_REFRESH} "
            f"{NEW_ACCESS} {NEW_REFRESH}"
        ),
        "data": {
            "accessToken": NEW_ACCESS,
            "refreshToken": NEW_REFRESH,
        },
    }))
    broker = make_broker(session)

    with pytest.raises(RuntimeError) as excinfo:
        broker.refresh_tokens()

    _assert_no_secret(
        excinfo.value,
        (OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH),
    )


def test_no_exception_context_when_called_inside_outer_except():
    session = FakeSession(FakeResponse({}, status_ok=False))
    broker = make_broker(session)

    secrets = (OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH)

    with pytest.raises(RuntimeError) as excinfo:
        try:
            raise RuntimeError(
                "outer failure "
                f"access={OLD_ACCESS} "
                f"refresh={OLD_REFRESH}"
            )
        except RuntimeError:
            broker.refresh_tokens()

    error = excinfo.value
    assert error.__context__ is None
    assert error.__cause__ is None
    _assert_no_secret(error, secrets)


# ---------------------------------------------------------------------------
# 10. Exactly one request per direct invocation
# ---------------------------------------------------------------------------

def test_exactly_one_request_per_invocation():
    session = FakeSession(FakeResponse(success_payload()))
    broker = make_broker(session)

    broker.refresh_tokens()
    assert len(session.calls) == 1

    broker.refresh_tokens()
    assert len(session.calls) == 2

    assert all(call[0] == "post" for call in session.calls)
    assert all(call[1] == REFRESH_URL for call in session.calls)


def test_no_request_after_failed_validation_and_no_retry():
    session = FakeSession(FakeResponse({
        "isSuccess": False,
        "data": {"accessToken": NEW_ACCESS, "refreshToken": NEW_REFRESH},
    }))
    broker = make_broker(session)

    with pytest.raises(RuntimeError):
        broker.refresh_tokens()

    # One attempt, no automatic retry.
    assert len(session.calls) == 1


# ---------------------------------------------------------------------------
# Offline guarantee
# ---------------------------------------------------------------------------

def test_no_real_socket_is_used():
    class NoNetwork(socket.socket):
        def __init__(self, *args, **kwargs):
            raise AssertionError("refresh_tokens() must not open a socket")

    original = socket.socket
    socket.socket = NoNetwork
    try:
        session = FakeSession(FakeResponse(success_payload()))
        broker = make_broker(session)
        broker.refresh_tokens()

        assert broker.access_token == NEW_ACCESS
        assert broker.refresh_token == NEW_REFRESH
    finally:
        socket.socket = original
