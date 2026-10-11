"""
test_block9_task4_authentication_contract.py

Block 9 — Task 4, Stage 2: tests for the broker-independent authentication
contract in brokers/authentication.py (fully offline).

Contract coverage:

    1. LoginChallenge is a public, displayable challenge with NO secret and
       no broker-specific field (no captchaId leaks across the boundary).
    2. AuthenticatedSession never leaks the access/refresh token into repr
       or str.
    3. The error hierarchy maps onto the behavioral contract: challenge
       failure, rejected login, incomplete (apparently-successful) login,
       no pending login, unavailable service.
    4. AuthenticationAdapter is abstract: the contract cannot be used
       without a broker-specific implementation.

These tests never touch the network, never import a real broker and never
open a socket.

Run:
    pytest -q test_block9_task4_authentication_contract.py
"""

import ast
import inspect
import socket

import pytest

from brokers import authentication as auth_module
from brokers.authentication import (
    AuthenticationAdapter,
    AuthenticationError,
    AuthenticationUnavailableError,
    AuthenticatedSession,
    CHALLENGE_CAPTCHA_IMAGE,
    IncompleteLoginError,
    LoginChallenge,
    LoginChallengeError,
    LoginNotInProgressError,
    LoginRejectedError,
)


# ---------------------------------------------------------------------------
# 1. LoginChallenge is public, displayable, secret-free
# ---------------------------------------------------------------------------

def test_login_challenge_carries_displayable_content():
    challenge = LoginChallenge(
        kind=CHALLENGE_CAPTCHA_IMAGE,
        display_payload="iVBORw0KGgoAAAANSUhEUg==",
        prompt="کد تصویر کپچا را وارد کنید.",
    )
    assert challenge.kind == CHALLENGE_CAPTCHA_IMAGE
    assert challenge.display_payload == "iVBORw0KGgoAAAANSUhEUg=="
    assert "کپچا" in challenge.prompt


def test_login_challenge_is_immutable():
    challenge = LoginChallenge(
        kind=CHALLENGE_CAPTCHA_IMAGE,
        display_payload="img",
        prompt="p",
    )
    with pytest.raises(Exception):
        challenge.kind = "other"


def test_login_challenge_has_no_broker_specific_or_secret_field():
    from dataclasses import fields

    names = {f.name for f in fields(LoginChallenge)}
    assert names == {"kind", "display_payload", "prompt"}

    forbidden_words = ("captcha_id", "captchaId", "password", "token", "secret")
    for name in names:
        lowered = name.lower()
        assert not any(w.lower() in lowered for w in forbidden_words), (
            f"LoginChallenge must not carry a broker-specific/secret field: {name}"
        )


def test_login_challenge_repr_carries_no_secret():
    challenge = LoginChallenge(
        kind=CHALLENGE_CAPTCHA_IMAGE,
        display_payload="secret-image-data",
        prompt="p",
    )
    assert "secret-image-data" in repr(challenge)  # displayable by design
    assert "captchaId" not in repr(challenge)


# ---------------------------------------------------------------------------
# 2. AuthenticatedSession never leaks tokens
# ---------------------------------------------------------------------------

def test_authenticated_session_holds_the_real_values():
    session = AuthenticatedSession(
        access_token="ACCESS-SECRET-123",
        user_identifier="USER-456",
        refresh_token="REFRESH-789",
        user_name="trader",
    )
    assert session.access_token == "ACCESS-SECRET-123"
    assert session.user_identifier == "USER-456"
    assert session.refresh_token == "REFRESH-789"
    assert session.user_name == "trader"


def test_authenticated_session_repr_does_not_leak_tokens():
    session = AuthenticatedSession(
        access_token="ACCESS-SECRET-123",
        user_identifier="USER-456",
        refresh_token="REFRESH-789",
        user_name="trader",
    )
    text = repr(session)
    assert "ACCESS-SECRET-123" not in text
    assert "REFRESH-789" not in text
    assert "USER-456" in text  # non-secret identity is fine


def test_authenticated_session_str_does_not_leak_tokens():
    session = AuthenticatedSession(
        access_token="ACCESS-SECRET-123",
        user_identifier="USER-456",
        refresh_token="REFRESH-789",
        user_name="trader",
    )
    text = str(session)
    assert "ACCESS-SECRET-123" not in text
    assert "REFRESH-789" not in text


def test_authenticated_session_repr_without_optional_fields():
    session = AuthenticatedSession(
        access_token="AT",
        user_identifier="UI",
    )
    assert session.refresh_token is None
    text = repr(session)
    assert "AT" not in text
    assert "UI" in text


# ---------------------------------------------------------------------------
# 3. Error hierarchy mirrors the behavioral contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("error_class", [
    AuthenticationError,
    LoginNotInProgressError,
    LoginChallengeError,
    LoginRejectedError,
    IncompleteLoginError,
    AuthenticationUnavailableError,
])
def test_all_auth_errors_subclass_authentication_error(error_class):
    assert issubclass(error_class, AuthenticationError)
    assert issubclass(error_class, Exception)


def test_rejected_and_incomplete_are_distinct_errors():
    assert LoginRejectedError is not IncompleteLoginError
    assert not issubclass(LoginRejectedError, IncompleteLoginError)
    assert not issubclass(IncompleteLoginError, LoginRejectedError)


def test_auth_errors_can_carry_a_message_without_secrets():
    exc = LoginRejectedError("کپچا یا اعتبارنامه نامعتبر است")
    assert "کپچا" in str(exc)


# ---------------------------------------------------------------------------
# 4. The adapter contract is abstract
# ---------------------------------------------------------------------------

def test_adapter_cannot_be_instantiated_without_implementation():
    with pytest.raises(TypeError):
        AuthenticationAdapter()


def test_adapter_declares_the_full_contract():
    required = {
        "broker_name",
        "begin_login",
        "complete_login",
        "cancel_login",
        "is_authenticated",
        "get_authenticated_session",
    }
    own = {
        name
        for name in dir(AuthenticationAdapter)
        if not name.startswith("__")
    }
    assert required.issubset(own), required - own


class _MinimalAdapter(AuthenticationAdapter):
    """Minimal implementation used only to exercise the contract shape."""

    @property
    def broker_name(self):
        return "آگاه"

    def begin_login(self, username, password):
        return LoginChallenge(
            kind=CHALLENGE_CAPTCHA_IMAGE,
            display_payload="img",
            prompt="p",
        )

    def complete_login(self, response):
        return AuthenticatedSession(
            access_token="AT", user_identifier="UI"
        )

    def cancel_login(self):
        return None

    def is_authenticated(self):
        return True

    def get_authenticated_session(self):
        return None


def test_a_minimal_implementation_satisfies_the_contract():
    adapter = _MinimalAdapter()
    challenge = adapter.begin_login("u", "p")
    assert isinstance(challenge, LoginChallenge)
    assert isinstance(adapter.complete_login("1234"), AuthenticatedSession)
    assert adapter.cancel_login() is None
    assert adapter.is_authenticated() is True
    assert adapter.get_authenticated_session() is None


# ---------------------------------------------------------------------------
# 5. Standalone / offline guarantees
# ---------------------------------------------------------------------------

def test_authentication_module_imports_no_broker_specific_logic():
    """
    The contract module must stay broker-independent: it may not import the
    Agah broker or any concrete broker implementation, and may not reference
    a broker-specific identifier (like captchaId) in executable code.

    Docstrings may *mention* such identifiers only as examples of what must
    stay inside an adapter, so only real identifiers are inspected.
    """
    source = inspect.getsource(auth_module)
    tree = ast.parse(source)
    banned = {"brokers.agaah", "requests"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in banned, (
                    f"contract imports {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "") not in banned, (
                f"contract imports from {node.module}"
            )
        elif isinstance(node, ast.Name):
            assert node.id != "captchaId", (
                "contract must not reference the broker-specific captchaId"
            )
        elif isinstance(node, ast.Attribute):
            assert node.attr != "captchaId", (
                "contract must not reference the broker-specific captchaId"
            )
        elif isinstance(node, ast.keyword):
            assert node.arg != "captchaId", (
                "contract must not reference the broker-specific captchaId"
            )

    assert "AgaahBroker" not in source


def test_contract_operations_make_no_network_connection():
    class NoNetwork(socket.socket):
        def __init__(self, *args, **kwargs):
            raise AssertionError("contract must not open a socket")

    original = socket.socket
    socket.socket = NoNetwork
    try:
        challenge = LoginChallenge(
            kind=CHALLENGE_CAPTCHA_IMAGE,
            display_payload="img",
            prompt="p",
        )
        _ = repr(challenge)

        session = AuthenticatedSession(
            access_token="AT", user_identifier="UI"
        )
        _ = repr(session)
        _ = str(session)

        try:
            raise LoginRejectedError("nope")
        except LoginRejectedError:
            pass
    finally:
        socket.socket = original
