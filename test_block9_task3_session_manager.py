"""
test_block9_task3_session_manager.py

Block 9 — Task 3: Account Session Manager tests (fully offline).

Contract coverage:

    1. Registration: an account opens a session in LOGGED_OUT; duplicate
       and invalid identities are rejected; unknown accounts raise
       SessionNotFoundError; unregister removes exactly one session.
    2. Independence: two accounts (same broker or different brokers) never
       share state or token — login/logout/fail/unregister of one never
       affects another.
    3. State machine: LOGGED_OUT -> LOGIN_PENDING -> LOGGED_IN, with
       fail_login/logout returning to LOGGED_OUT; every invalid transition
       raises SessionStateError and leaves the state unchanged.
    4. Token: an opaque, in-memory token per account, returned only while
       LOGGED_IN, cleared on fail_login/logout/unregister, never mixed.
    5. No leakage: the token never appears in a Session snapshot, a repr
       or an error message.
    6. Standalone + no persistence: the module imports no broker/core/
       market/main/models module, writes no file/JSON/SQLite, uses no
       keyring and opens no socket; Account/AccountRecord/AccountStore are
       unchanged and gain no session/token field.

Run:
    pytest -q test_block9_task3_session_manager.py
"""

import ast
import inspect
import socket

import pytest

from models.account import Account
from ui.account_store import AccountRecord, AccountStore
from ui import session_manager as session_manager_module
from ui.session_manager import (
    Session,
    SessionAlreadyExistsError,
    SessionManager,
    SessionManagerError,
    SessionNotFoundError,
    SessionState,
    SessionStateError,
    SessionValidationError,
)


ACC_A = "ACC-001"
ACC_B = "ACC-002"
ACC_C = "ACC-003"
BROKER_1 = "آگاه"
BROKER_2 = "دیگر"
TOKEN = "secret-access-token-xyz"


def make_manager():
    return SessionManager()


# ---------------------------------------------------------------------------
# 1. Registration + identity
# ---------------------------------------------------------------------------

def test_register_returns_logged_out_session():
    manager = make_manager()
    session = manager.register(ACC_A, BROKER_1)

    assert isinstance(session, Session)
    assert session.account_id == ACC_A
    assert session.broker_name == BROKER_1
    assert session.state is SessionState.LOGGED_OUT
    assert manager.state(ACC_A) is SessionState.LOGGED_OUT
    assert manager.is_logged_in(ACC_A) is False


def test_duplicate_registration_raises():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    with pytest.raises(SessionAlreadyExistsError):
        manager.register(ACC_A, BROKER_2)


def test_register_rejects_invalid_account_id():
    manager = make_manager()
    for bad in (None, "", "   ", 5, 3.14, []):
        with pytest.raises(SessionValidationError):
            manager.register(bad, BROKER_1)


def test_register_rejects_invalid_broker_name():
    manager = make_manager()
    for bad in (None, "", "   ", 5, 3.14, []):
        with pytest.raises(SessionValidationError):
            manager.register(ACC_A, bad)


def test_register_trims_broker_name_but_keeps_account_id_verbatim():
    manager = make_manager()
    session = manager.register("  ACC-001  ", "  آگاه  ")
    assert session.account_id == "  ACC-001  "
    assert session.broker_name == BROKER_1
    assert manager.state("  ACC-001  ") is SessionState.LOGGED_OUT


def test_all_sessions_in_registration_order():
    manager = make_manager()
    first = manager.register(ACC_A, BROKER_1)
    second = manager.register(ACC_B, BROKER_2)
    assert manager.all_sessions() == (first, second)


def test_get_returns_registered_session():
    manager = make_manager()
    session = manager.register(ACC_A, BROKER_1)
    assert manager.get(ACC_A) is session


def test_unknown_account_reads_raise_not_found():
    manager = make_manager()
    for call in (
        lambda: manager.get(ACC_A),
        lambda: manager.state(ACC_A),
        lambda: manager.is_logged_in(ACC_A),
        lambda: manager.get_token(ACC_A),
        lambda: manager.begin_login(ACC_A),
        lambda: manager.logout(ACC_A),
        lambda: manager.fail_login(ACC_A),
        lambda: manager.unregister(ACC_A),
    ):
        with pytest.raises(SessionNotFoundError):
            call()


def test_unregister_removes_session():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.register(ACC_B, BROKER_1)

    manager.unregister(ACC_A)

    with pytest.raises(SessionNotFoundError):
        manager.get(ACC_A)
    assert manager.get(ACC_B).account_id == ACC_B


def test_unregister_unknown_raises_not_found():
    manager = make_manager()
    with pytest.raises(SessionNotFoundError):
        manager.unregister(ACC_A)


def test_not_found_is_a_session_manager_error():
    manager = make_manager()
    with pytest.raises(SessionManagerError):
        manager.get(ACC_A)


def test_not_found_message_does_not_reveal_account_id():
    manager = make_manager()
    secret_ids = ("ACC-SECRET-98765", "  ACC-LEAK-001  ", "account-X")
    for unknown_id in secret_ids:
        with pytest.raises(SessionNotFoundError) as excinfo:
            manager.get(unknown_id)
        message = str(excinfo.value)
        assert unknown_id not in message
        assert unknown_id not in repr(excinfo.value)
        assert "account_id" not in message


def test_not_found_message_does_not_reveal_unhashable_id():
    manager = make_manager()
    secret = ["ACC-LEAK-UNHASHABLE"]
    with pytest.raises(SessionNotFoundError) as excinfo:
        manager.get(secret)
    assert "ACC-LEAK-UNHASHABLE" not in str(excinfo.value)
    assert "ACC-LEAK-UNHASHABLE" not in repr(excinfo.value)


def test_validation_error_is_manager_error_and_value_error():
    manager = make_manager()
    with pytest.raises(SessionManagerError):
        manager.register(None, BROKER_1)
    with pytest.raises(ValueError):
        manager.register(None, BROKER_1)


def test_validation_message_names_field_not_value():
    manager = make_manager()
    with pytest.raises(SessionValidationError) as excinfo:
        manager.register(None, BROKER_1)
    assert "account_id" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 2. Independent sessions — no mixing
# ---------------------------------------------------------------------------

def test_two_accounts_on_same_broker_are_independent():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.register(ACC_B, BROKER_1)

    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)

    assert manager.state(ACC_A) is SessionState.LOGGED_IN
    assert manager.state(ACC_B) is SessionState.LOGGED_OUT
    assert manager.get_token(ACC_A) == TOKEN
    assert manager.get_token(ACC_B) is None


def test_two_accounts_on_two_brokers_are_independent():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.register(ACC_B, BROKER_2)

    manager.begin_login(ACC_B)
    manager.mark_logged_in(ACC_B, TOKEN)

    assert manager.state(ACC_B) is SessionState.LOGGED_IN
    assert manager.state(ACC_A) is SessionState.LOGGED_OUT


def test_logging_in_one_does_not_log_in_another():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.register(ACC_B, BROKER_1)

    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)

    assert manager.is_logged_in(ACC_A) is True
    assert manager.is_logged_in(ACC_B) is False


def test_logout_of_one_does_not_affect_other():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.register(ACC_B, BROKER_1)
    for acc in (ACC_A, ACC_B):
        manager.begin_login(acc)
        manager.mark_logged_in(acc, acc)

    manager.logout(ACC_A)

    assert manager.state(ACC_A) is SessionState.LOGGED_OUT
    assert manager.state(ACC_B) is SessionState.LOGGED_IN
    assert manager.get_token(ACC_B) == ACC_B


def test_fail_login_of_one_does_not_affect_other():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.register(ACC_B, BROKER_1)

    manager.begin_login(ACC_A)
    manager.begin_login(ACC_B)
    manager.mark_logged_in(ACC_B, TOKEN)

    manager.fail_login(ACC_A)

    assert manager.state(ACC_A) is SessionState.LOGGED_OUT
    assert manager.state(ACC_B) is SessionState.LOGGED_IN
    assert manager.get_token(ACC_B) == TOKEN


def test_unregister_of_one_does_not_affect_other():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.register(ACC_B, BROKER_1)
    manager.begin_login(ACC_B)
    manager.mark_logged_in(ACC_B, TOKEN)

    manager.unregister(ACC_A)

    assert manager.state(ACC_B) is SessionState.LOGGED_IN
    assert manager.get_token(ACC_B) == TOKEN


# ---------------------------------------------------------------------------
# 3. State machine transitions
# ---------------------------------------------------------------------------

def test_begin_login_from_logged_out():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    session = manager.begin_login(ACC_A)
    assert session.state is SessionState.LOGIN_PENDING
    assert manager.state(ACC_A) is SessionState.LOGIN_PENDING


def test_begin_login_twice_raises():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    with pytest.raises(SessionStateError):
        manager.begin_login(ACC_A)


def test_begin_login_when_logged_in_raises():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)
    with pytest.raises(SessionStateError):
        manager.begin_login(ACC_A)


def test_mark_logged_in_from_logged_out_raises():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    with pytest.raises(SessionStateError):
        manager.mark_logged_in(ACC_A, TOKEN)


def test_mark_logged_in_twice_raises():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)
    with pytest.raises(SessionStateError):
        manager.mark_logged_in(ACC_A, TOKEN)


def test_logout_from_logged_out_raises():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    with pytest.raises(SessionStateError):
        manager.logout(ACC_A)


def test_logout_from_logged_in():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)
    session = manager.logout(ACC_A)
    assert session.state is SessionState.LOGGED_OUT


def test_logout_from_login_pending():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    session = manager.logout(ACC_A)
    assert session.state is SessionState.LOGGED_OUT


def test_fail_login_from_login_pending():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    session = manager.fail_login(ACC_A)
    assert session.state is SessionState.LOGGED_OUT


def test_fail_login_from_logged_out_raises():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    with pytest.raises(SessionStateError):
        manager.fail_login(ACC_A)


def test_fail_login_from_logged_in_raises():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)
    with pytest.raises(SessionStateError):
        manager.fail_login(ACC_A)


def test_state_error_leaves_state_unchanged():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)

    with pytest.raises(SessionStateError):
        manager.begin_login(ACC_A)

    assert manager.state(ACC_A) is SessionState.LOGGED_IN
    assert manager.get_token(ACC_A) == TOKEN


def test_full_cycle_login_logout_login():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)

    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, "token-1")
    manager.logout(ACC_A)
    assert manager.get_token(ACC_A) is None

    manager.begin_login(ACC_A)
    session = manager.mark_logged_in(ACC_A, "token-2")
    assert session.state is SessionState.LOGGED_IN
    assert manager.get_token(ACC_A) == "token-2"


def test_invalid_transition_is_a_session_manager_error():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    with pytest.raises(SessionManagerError):
        manager.logout(ACC_A)


# ---------------------------------------------------------------------------
# 4. Token handling (in-memory, opaque, per account)
# ---------------------------------------------------------------------------

def test_token_is_none_before_login():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    assert manager.get_token(ACC_A) is None


def test_token_is_none_while_login_pending():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    assert manager.get_token(ACC_A) is None


def test_token_available_after_login():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)
    assert manager.get_token(ACC_A) == TOKEN


def test_token_is_opaque_arbitrary_object():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    opaque = {"accessToken": "a", "refreshToken": "r"}
    manager.mark_logged_in(ACC_A, opaque)
    assert manager.get_token(ACC_A) is opaque


def test_token_may_be_none():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    session = manager.mark_logged_in(ACC_A)
    assert session.state is SessionState.LOGGED_IN
    assert manager.get_token(ACC_A) is None


def test_logout_clears_token():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)
    manager.logout(ACC_A)
    assert manager.get_token(ACC_A) is None


def test_fail_login_clears_token():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.fail_login(ACC_A)
    assert manager.get_token(ACC_A) is None


def test_token_is_per_account():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.register(ACC_B, BROKER_1)
    for acc, token in ((ACC_A, "token-a"), (ACC_B, "token-b")):
        manager.begin_login(acc)
        manager.mark_logged_in(acc, token)

    assert manager.get_token(ACC_A) == "token-a"
    assert manager.get_token(ACC_B) == "token-b"


def test_re_login_replaces_token():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, "old")
    manager.logout(ACC_A)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, "new")
    assert manager.get_token(ACC_A) == "new"


def test_unregister_drops_token():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)
    manager.unregister(ACC_A)
    with pytest.raises(SessionNotFoundError):
        manager.get_token(ACC_A)


# ---------------------------------------------------------------------------
# 5. No token leakage
# ---------------------------------------------------------------------------

def test_session_repr_contains_no_token():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    session = manager.mark_logged_in(ACC_A, TOKEN)
    assert TOKEN not in repr(session)
    assert TOKEN not in str(session)


def test_manager_repr_contains_no_token():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)
    assert TOKEN not in repr(manager)
    assert TOKEN not in str(manager)


def test_state_error_message_contains_no_token():
    manager = make_manager()
    manager.register(ACC_A, BROKER_1)
    manager.begin_login(ACC_A)
    manager.mark_logged_in(ACC_A, TOKEN)
    with pytest.raises(SessionStateError) as excinfo:
        manager.begin_login(ACC_A)
    assert TOKEN not in str(excinfo.value)
    assert TOKEN not in repr(excinfo.value)


def test_session_snapshot_has_no_token_field():
    from dataclasses import fields

    names = {f.name for f in fields(Session)}
    assert names == {"account_id", "broker_name", "state"}
    assert not any("token" in name.lower() for name in names)


# ---------------------------------------------------------------------------
# 6. Standalone, no persistence, no network, models untouched
# ---------------------------------------------------------------------------

def test_session_manager_imports_no_broker_core_market_module():
    source = inspect.getsource(session_manager_module)
    tree = ast.parse(source)
    banned_roots = {"brokers", "core", "market", "main", "models"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in banned_roots, (
                    f"session_manager imports {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in banned_roots, (
                f"session_manager imports from {node.module}"
            )


def test_session_manager_source_has_no_insecure_persistence():
    source = inspect.getsource(session_manager_module)
    tree = ast.parse(source)

    banned_modules = {
        "json", "sqlite3", "sqlite", "configparser", "pickle",
        "shelve", "dbm", "csv", "pathlib",
    }
    banned_calls = {"open", "loads", "dumps"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in banned_modules, (
                    f"session_manager imports {alias.name} — persistence "
                    "is forbidden"
                )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in banned_modules, (
                f"session_manager imports from {node.module} — persistence "
                "is forbidden"
            )
            for alias in node.names:
                assert alias.name not in banned_calls, (
                    f"session_manager imports {alias.name} from "
                    f"{node.module} — persistence is forbidden"
                )
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                assert func.id not in banned_calls, (
                    f"session_manager calls {func.id}(...) — persistence "
                    "is forbidden"
                )


def test_session_manager_source_has_no_keyring_reference():
    source = inspect.getsource(session_manager_module)
    assert "keyring" not in source
    assert "import keyring" not in source


def test_operations_make_no_network_connection():
    manager = make_manager()

    class NoNetwork(socket.socket):
        def __init__(self, *args, **kwargs):
            raise AssertionError("session manager must not open a socket")

    original = socket.socket
    socket.socket = NoNetwork
    try:
        manager.register(ACC_A, BROKER_1)
        manager.begin_login(ACC_A)
        manager.mark_logged_in(ACC_A, TOKEN)
        manager.get_token(ACC_A)
        manager.is_logged_in(ACC_A)
        manager.logout(ACC_A)
        manager.unregister(ACC_A)
    finally:
        socket.socket = original


def test_account_model_has_no_session_or_token_field():
    from dataclasses import fields

    names = {f.name.lower() for f in fields(Account)}
    for word in ("token", "session", "logged", "login", "expiry", "expires"):
        assert not any(word in name for name in names), (
            f"Account must not carry a session/token field: {word}"
        )


def test_account_record_fields_unchanged():
    from dataclasses import fields

    record_fields = {f.name for f in fields(AccountRecord)}
    assert record_fields == {"account", "broker_name", "display_name"}


def test_account_store_has_no_session_api():
    forbidden = ("session", "token", "login", "logout")
    for name in dir(AccountStore):
        lowered = name.lower()
        assert not any(word in lowered for word in forbidden), (
            f"AccountStore must not expose a session API: {name}"
        )
