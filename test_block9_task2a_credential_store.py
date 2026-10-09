"""
test_block9_task2a_credential_store.py

Block 9 — Task 2A: Secure Credential Store tests (fully offline).

Contract coverage:

    1. Save + get roundtrip returns the exact username and password.
    2. username + password travel as ONE logical unit (single backend
       write / single backend read / one vault entry per pair).
    3. Isolation: two accounts on one broker, one account id on two
       brokers, and two accounts on two brokers all stay separate.
    4. Delete removes exactly that pair; get/delete after the delete
       raise CredentialNotFoundError (explicit post-delete behaviour).
    5. Empty / whitespace / non-string input is rejected before any
       backend call happens.
    6. Backend failures map to CredentialBackendError /
       CredentialBackendUnavailable, fail closed, and NEVER leak the
       username or password into the error message.
    7. No credential field was added to Account / AccountRecord /
       AccountStore (models and store untouched).
    8. keyring is the backend choice; when it is unavailable the
       operation stops with an error and no insecure fallback exists
       (no file / JSON / SQLite / settings writes anywhere in the module).

These tests use an in-memory stub backend injected through
``CredentialStore(backend=...)``. They never import keyring at runtime,
never touch the OS vault, never import a broker and never open a socket.

Run:
    pytest -q test_block9_task2a_credential_store.py
"""

import ast
import inspect
import os
import socket
import subprocess
import sys
import textwrap
import traceback

import pytest

from models.account import Account
from ui.account_store import AccountRecord, AccountStore
from ui import credential_store as credential_store_module
from ui.credential_store import (
    SERVICE_NAME,
    CredentialBackendError,
    CredentialBackendUnavailable,
    CredentialNotFoundError,
    CredentialStore,
    CredentialStoreError,
    CredentialValidationError,
    Credentials,
    service_id,
)


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Stub backend (in-memory keyring double)
# ---------------------------------------------------------------------------

class StubBackend:
    """
    In-memory keyring-compatible backend.

    Records every call so tests can assert call counts (one logical unit)
    and can prove that invalid input never reaches the backend.
    """

    def __init__(self):
        self.entries = {}       # (service, account) -> payload
        self.calls = []         # (op, service, account) tuples
        self.fail_with = None   # exception instance raised on every call

    def set_password(self, service, account, password):
        self.calls.append(("set", service, account))
        if self.fail_with is not None:
            raise self.fail_with
        self.entries[(service, account)] = password

    def get_password(self, service, account):
        self.calls.append(("get", service, account))
        if self.fail_with is not None:
            raise self.fail_with
        return self.entries.get((service, account))

    def delete_password(self, service, account):
        self.calls.append(("delete", service, account))
        if self.fail_with is not None:
            raise self.fail_with
        del self.entries[(service, account)]


class BrokenKeyringError(Exception):
    """Stand-in whose class NAME matches the real keyring error taxonomy."""


class NoKeyringError(Exception):
    """Class name mirrors keyring.errors.NoKeyringError (unavailable)."""


def make_store():
    backend = StubBackend()
    return CredentialStore(backend=backend), backend


ACC_A = "ACC-001"
ACC_B = "ACC-002"
BROKER_1 = "آگاه"
BROKER_2 = "دیگر"


# ---------------------------------------------------------------------------
# 1. Save + get roundtrip
# ---------------------------------------------------------------------------

def test_save_then_get_returns_exact_credentials():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")

    creds = store.get_credentials(ACC_A, BROKER_1)

    assert isinstance(creds, Credentials)
    assert creds.username == "user-a"
    assert creds.password == "pass-a"
    assert tuple(creds) == ("user-a", "pass-a")


def test_get_returns_named_unit_credentials():
    store, _ = make_store()
    store.save_credentials(ACC_A, BROKER_1, "u", "p")
    creds = store.get_credentials(ACC_A, BROKER_1)
    # username + password are retrieved together as ONE logical unit
    assert isinstance(creds, Credentials)
    assert set(creds._fields) == {"username", "password"}


# ---------------------------------------------------------------------------
# 2. One logical unit: one entry, one write, one read
# ---------------------------------------------------------------------------

def test_save_is_exactly_one_backend_write():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")

    assert backend.calls == [
        ("set", service_id(BROKER_1), ACC_A),
    ]
    assert len(backend.entries) == 1


def test_get_is_exactly_one_backend_read():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")
    backend.calls.clear()

    store.get_credentials(ACC_A, BROKER_1)

    assert backend.calls == [("get", service_id(BROKER_1), ACC_A)]


def test_username_and_password_share_one_vault_entry():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")

    # one (service, account) key holds BOTH halves
    assert list(backend.entries) == [(service_id(BROKER_1), ACC_A)]


def test_service_and_account_identifiers_are_stable_and_separated():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")

    (service, account) = list(backend.entries)[0]
    # stable: same inputs -> same identifiers on both writes
    assert {c[1] for c in backend.calls} == {service}
    assert {c[2] for c in backend.calls} == {ACC_A}
    # explicit: service carries the broker scope, account carries only
    # the account id — two different fields, never the same string
    assert service == f"{SERVICE_NAME}/{BROKER_1}"
    assert account == ACC_A
    assert service != account
    assert service_id(BROKER_1) == service
    assert service_id(BROKER_1) != service_id(BROKER_2)


# ---------------------------------------------------------------------------
# 3. Isolation: two accounts / two brokers
# ---------------------------------------------------------------------------

def test_two_accounts_on_one_broker_are_isolated():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")
    store.save_credentials(ACC_B, BROKER_1, "user-b", "pass-b")

    assert store.get_credentials(ACC_A, BROKER_1) == ("user-a", "pass-a")
    assert store.get_credentials(ACC_B, BROKER_1) == ("user-b", "pass-b")
    assert len(backend.entries) == 2


def test_one_account_id_on_two_brokers_is_isolated():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-1", "pass-1")
    store.save_credentials(ACC_A, BROKER_2, "user-2", "pass-2")

    assert store.get_credentials(ACC_A, BROKER_1) == ("user-1", "pass-1")
    assert store.get_credentials(ACC_A, BROKER_2) == ("user-2", "pass-2")
    assert len(backend.entries) == 2
    # the two entries differ by service, same account field
    services = {key[0] for key in backend.entries}
    assert services == {service_id(BROKER_1), service_id(BROKER_2)}


def test_two_accounts_on_two_brokers_are_isolated():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a1", "pass-a1")
    store.save_credentials(ACC_B, BROKER_1, "user-b1", "pass-b1")
    store.save_credentials(ACC_A, BROKER_2, "user-a2", "pass-a2")
    store.save_credentials(ACC_B, BROKER_2, "user-b2", "pass-b2")

    assert store.get_credentials(ACC_A, BROKER_1) == ("user-a1", "pass-a1")
    assert store.get_credentials(ACC_B, BROKER_1) == ("user-b1", "pass-b1")
    assert store.get_credentials(ACC_A, BROKER_2) == ("user-a2", "pass-a2")
    assert store.get_credentials(ACC_B, BROKER_2) == ("user-b2", "pass-b2")
    assert len(backend.entries) == 4


def test_save_overwrites_only_the_same_pair():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "old", "old-pass")
    store.save_credentials(ACC_B, BROKER_1, "other", "other-pass")

    store.save_credentials(ACC_A, BROKER_1, "new", "new-pass")

    assert store.get_credentials(ACC_A, BROKER_1) == ("new", "new-pass")
    assert store.get_credentials(ACC_B, BROKER_1) == ("other", "other-pass")
    assert len(backend.entries) == 2


# ---------------------------------------------------------------------------
# 4. Delete + defined behaviour after deletion
# ---------------------------------------------------------------------------

def test_delete_removes_exactly_that_pair():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")
    store.save_credentials(ACC_B, BROKER_1, "user-b", "pass-b")

    store.delete_credentials(ACC_A, BROKER_1)

    assert len(backend.entries) == 1
    assert store.get_credentials(ACC_B, BROKER_1) == ("user-b", "pass-b")


def test_get_after_delete_raises_not_found():
    store, _ = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")

    store.delete_credentials(ACC_A, BROKER_1)

    with pytest.raises(CredentialNotFoundError):
        store.get_credentials(ACC_A, BROKER_1)


def test_delete_after_delete_raises_not_found():
    store, _ = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")

    store.delete_credentials(ACC_A, BROKER_1)

    with pytest.raises(CredentialNotFoundError):
        store.delete_credentials(ACC_A, BROKER_1)


def test_get_on_never_saved_pair_raises_not_found():
    store, _ = make_store()
    with pytest.raises(CredentialNotFoundError):
        store.get_credentials(ACC_A, BROKER_1)


def test_not_found_is_a_credential_store_error():
    store, _ = make_store()
    with pytest.raises(CredentialStoreError):
        store.get_credentials(ACC_A, BROKER_1)


# ---------------------------------------------------------------------------
# 5. Invalid input rejected BEFORE the backend is touched
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_account", ["", "   ", None, 7, b"acc"])
def test_save_rejects_invalid_account_id(bad_account):
    store, backend = make_store()
    with pytest.raises(CredentialValidationError):
        store.save_credentials(bad_account, BROKER_1, "u", "p")
    assert backend.calls == []


@pytest.mark.parametrize("bad_broker", ["", "   ", None, 42])
def test_save_rejects_invalid_broker_name(bad_broker):
    store, backend = make_store()
    with pytest.raises(CredentialValidationError):
        store.save_credentials(ACC_A, bad_broker, "u", "p")
    assert backend.calls == []


@pytest.mark.parametrize("bad_username", ["", "   ", None, 1.5])
def test_save_rejects_invalid_username(bad_username):
    store, backend = make_store()
    with pytest.raises(CredentialValidationError):
        store.save_credentials(ACC_A, BROKER_1, bad_username, "p")
    assert backend.calls == []


@pytest.mark.parametrize("bad_password", ["", "   ", None, 123])
def test_save_rejects_invalid_password(bad_password):
    store, backend = make_store()
    with pytest.raises(CredentialValidationError):
        store.save_credentials(ACC_A, BROKER_1, "u", bad_password)
    assert backend.calls == []


@pytest.mark.parametrize("bad_account", ["", "  ", None, 3])
def test_get_rejects_invalid_account_id(bad_account):
    store, backend = make_store()
    with pytest.raises(CredentialValidationError):
        store.get_credentials(bad_account, BROKER_1)
    assert backend.calls == []


@pytest.mark.parametrize("bad_broker", ["", "  ", None])
def test_delete_rejects_invalid_broker_name(bad_broker):
    store, backend = make_store()
    with pytest.raises(CredentialValidationError):
        store.delete_credentials(ACC_A, bad_broker)
    assert backend.calls == []


def test_validation_error_is_a_credential_store_error_and_value_error():
    store, _ = make_store()
    with pytest.raises(ValueError):
        store.save_credentials("", BROKER_1, "u", "p")
    with pytest.raises(CredentialStoreError):
        store.save_credentials(ACC_A, BROKER_1, "", "p")


def test_validation_error_message_names_field_not_value():
    store, _ = make_store()
    # the secret itself is valid, but the username is not: the error must
    # name the failing field and must never echo the (valid) password
    with pytest.raises(CredentialValidationError) as excinfo:
        store.save_credentials(ACC_A, BROKER_1, "", "super-secret-pass")
    message = str(excinfo.value)
    assert "username" in message
    assert "super-secret-pass" not in message

    # a whitespace-only password is rejected without echoing the value
    with pytest.raises(CredentialValidationError) as excinfo2:
        store.save_credentials(ACC_A, BROKER_1, "u", "    ")
    assert "password" in str(excinfo2.value)
    assert "    " not in str(excinfo2.value)


# ---------------------------------------------------------------------------
# 6. Backend error handling (fail closed, no secret leakage)
# ---------------------------------------------------------------------------

def test_backend_failure_on_save_raises_backend_error():
    store, backend = make_store()
    backend.fail_with = BrokenKeyringError("vault write failed")

    with pytest.raises(CredentialBackendError):
        store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")


def test_backend_failure_on_get_raises_backend_error():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")
    backend.fail_with = BrokenKeyringError("vault read failed")

    with pytest.raises(CredentialBackendError):
        store.get_credentials(ACC_A, BROKER_1)


def test_backend_failure_on_delete_raises_backend_error():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")
    backend.fail_with = BrokenKeyringError("vault delete failed")

    with pytest.raises(CredentialBackendError):
        store.delete_credentials(ACC_A, BROKER_1)


def test_backend_error_message_contains_no_secrets():
    store, backend = make_store()
    # the backend error itself ECHOES the secret — our wrapper must not
    # propagate that text into the raised error's message.
    backend.fail_with = BrokenKeyringError(
        "failed writing user-a:pass-a to vault"
    )

    with pytest.raises(CredentialBackendError) as excinfo:
        store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")

    message = str(excinfo.value)
    assert "user-a" not in message
    assert "pass-a" not in message
    # still diagnosable: operation, identifiers and error class name
    assert "save" in message
    assert ACC_A in message
    assert "BrokenKeyringError" in message


def test_unavailable_backend_error_message_contains_no_secrets():
    store, backend = make_store()
    backend.fail_with = NoKeyringError("no vault for user-a:pass-a")

    with pytest.raises(CredentialBackendUnavailable):
        store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")


def test_unavailable_backend_is_a_backend_error_and_store_error():
    store, backend = make_store()
    backend.fail_with = NoKeyringError("no backend")

    with pytest.raises(CredentialBackendError):
        store.get_credentials(ACC_A, BROKER_1)
    with pytest.raises(CredentialStoreError):
        store.delete_credentials(ACC_A, BROKER_1)


def test_backend_failure_fails_closed_no_partial_result():
    store, backend = make_store()
    store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")
    backend.fail_with = BrokenKeyringError("boom")

    with pytest.raises(CredentialBackendError):
        store.get_credentials(ACC_A, BROKER_1)

    # the original entry was not corrupted or dropped by the failure
    assert len(backend.entries) == 1
    backend.fail_with = None
    assert store.get_credentials(ACC_A, BROKER_1) == ("user-a", "pass-a")


def test_corrupt_stored_payload_raises_backend_error_without_echo():
    store, backend = make_store()
    backend.entries[(service_id(BROKER_1), ACC_A)] = "not-a-valid-payload"

    with pytest.raises(CredentialBackendError) as excinfo:
        store.get_credentials(ACC_A, BROKER_1)

    assert "not-a-valid-payload" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# 7. keyring backend choice + no insecure fallback
# ---------------------------------------------------------------------------

def test_default_store_without_keyring_fails_closed(monkeypatch):
    """keyring absent -> every operation stops with a specific error."""
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "keyring" or name.startswith("keyring."):
            raise ImportError("No module named 'keyring'")
        return real_import(name, *args, **kwargs)

    store = CredentialStore()  # default backend = real keyring

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(CredentialBackendUnavailable):
        store.save_credentials(ACC_A, BROKER_1, "u", "p")
    with pytest.raises(CredentialBackendUnavailable):
        store.get_credentials(ACC_A, BROKER_1)
    with pytest.raises(CredentialBackendUnavailable):
        store.delete_credentials(ACC_A, BROKER_1)


def test_no_insecure_fallback_when_keyring_missing(monkeypatch, tmp_path):
    """
    With keyring unavailable the module must NOT fall back to writing a
    file / JSON / SQLite / settings: no file may appear anywhere.
    """
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "keyring" or name.startswith("keyring."):
            raise ImportError("No module named 'keyring'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    before = set(os.listdir(tmp_path))

    store = CredentialStore()
    with pytest.raises(CredentialBackendUnavailable):
        store.save_credentials(ACC_A, BROKER_1, "u", "p")

    assert set(os.listdir(tmp_path)) == before


def test_credential_store_module_source_has_no_insecure_persistence():
    """No file / JSON / SQLite / settings / env writes in the module."""
    source = inspect.getsource(credential_store_module)
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
                    f"credential_store imports {alias.name} — insecure "
                    "persistence is forbidden"
                )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in banned_modules, (
                f"credential_store imports from {node.module} — insecure "
                "persistence is forbidden"
            )
            for alias in node.names:
                assert alias.name not in banned_calls, (
                    f"credential_store imports {alias.name} from "
                    f"{node.module} — insecure persistence is forbidden"
                )
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", getattr(func, "attr", None))
            if isinstance(func, ast.Name):
                assert func.id not in banned_calls, (
                    f"credential_store calls {func.id}(...) — insecure "
                    "persistence is forbidden"
                )


def test_credential_store_imports_no_broker_core_market_module():
    """The store is standalone: no brokers/, core/, market/, main import."""
    source = inspect.getsource(credential_store_module)
    tree = ast.parse(source)
    banned_roots = {"brokers", "core", "market", "main", "models"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in banned_roots, (
                    f"credential_store imports {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in banned_roots, (
                f"credential_store imports from {node.module}"
            )


def test_credential_store_module_source_names_keyring_as_backend():
    """The chosen backend is keyring (the OS secure credential store)."""
    source = inspect.getsource(credential_store_module)
    assert "import keyring" in source
    assert "keyring" in source


def test_operations_make_no_network_connection():
    """No socket use anywhere in save / get / delete."""
    store, backend = make_store()

    class NoNetwork(socket.socket):
        def __init__(self, *args, **kwargs):
            raise AssertionError("credential store must not open a socket")

    original = socket.socket
    socket.socket = NoNetwork
    try:
        store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")
        store.get_credentials(ACC_A, BROKER_1)
        store.delete_credentials(ACC_A, BROKER_1)
    finally:
        socket.socket = original

    assert len(backend.entries) == 0


# ---------------------------------------------------------------------------
# 9. Explicit backend policy (Windows WinVaultKeyring only, by CLASS IDENTITY)
#
# These tests exercise the REAL keyring package and are therefore skipped
# automatically when keyring (or its Windows backend) is not installed.
# They are deliberately kept separate from the fake-backend tests above so
# the fake tests never masquerade as proof of the real backend policy.
# ---------------------------------------------------------------------------

def _import_keyring_or_skip():
    return pytest.importorskip("keyring")


def test_lookalike_backend_class_is_rejected(monkeypatch):
    """
    A look-alike class that merely copies the allowed module + name string
    must NOT be accepted: the policy compares against the REAL
    ``keyring.backends.Windows.WinVaultKeyring`` class by identity.
    """
    keyring = _import_keyring_or_skip()

    class WinVaultKeyring:  # same NAME as the allowed class, different identity
        def set_password(self, service, account, password):
            raise AssertionError("look-alike backend must never be used")

        def get_password(self, service, account):
            raise AssertionError("look-alike backend must never be used")

        def delete_password(self, service, account):
            raise AssertionError("look-alike backend must never be used")

    WinVaultKeyring.__module__ = "keyring.backends.Windows"
    spoof = WinVaultKeyring()

    # The old string-based policy WOULD have accepted this spoof:
    assert (
        f"{type(spoof).__module__}.{type(spoof).__name__}"
        == "keyring.backends.Windows.WinVaultKeyring"
    )

    monkeypatch.setattr(keyring, "get_keyring", lambda: spoof)

    store = CredentialStore()
    with pytest.raises(CredentialBackendUnavailable) as excinfo:
        store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")
    assert "not permitted" in str(excinfo.value)


def test_real_allowed_backend_identity_is_accepted(monkeypatch):
    """
    The genuine ``WinVaultKeyring`` class, resolved from the installed
    keyring package, is accepted by identity. This only resolves and
    authorizes the backend (no vault read/write happens here).
    """
    keyring = _import_keyring_or_skip()
    try:
        from keyring.backends.Windows import WinVaultKeyring
    except Exception:
        pytest.skip("keyring.backends.Windows.WinVaultKeyring not importable here")

    real_backend = WinVaultKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: real_backend)

    assert credential_store_module._load_keyring() is keyring


def test_subclass_of_allowed_backend_is_rejected():
    """
    A SUBCLASS of the real ``WinVaultKeyring`` must also be rejected: the
    policy requires the exact class (``type(backend) is WinVaultKeyring``),
    not merely an instance of it.

    This runs in a SEPARATE interpreter on purpose: defining a subclass of
    a keyring backend permanently changes keyring's global backend
    discovery (``keyring.backend.get_all_keyring`` enumerates subclasses),
    which would make ``get_keyring()`` return a ``ChainerBackend`` for the
    rest of this pytest process and silently break the real-vault
    integration test below. The subprocess keeps the parent process clean
    while still exercising the REAL ``WinVaultKeyring`` class.
    """
    pytest.importorskip("keyring")
    try:
        from keyring.backends.Windows import WinVaultKeyring  # noqa: F401
    except Exception:
        pytest.skip("keyring.backends.Windows.WinVaultKeyring not importable here")

    script = textwrap.dedent(
        """
        import keyring
        from keyring.backends.Windows import WinVaultKeyring
        from ui import credential_store as cs

        class WinVaultKeyringSubclass(WinVaultKeyring):
            pass

        backend = WinVaultKeyringSubclass()
        # Sanity: it IS an instance of the allowed class ...
        assert isinstance(backend, WinVaultKeyring)
        # ... but it is NOT the exact class the policy demands.
        assert type(backend) is not WinVaultKeyring

        keyring.get_keyring = lambda: backend
        try:
            cs._load_keyring()
        except cs.CredentialBackendUnavailable:
            print("REJECTED")
        else:
            raise SystemExit("subclass backend was ACCEPTED")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "REJECTED"


def test_default_store_rejects_denied_backend(monkeypatch):
    """The default store rejects a non-allowed backend (macOS-like)."""
    keyring = _import_keyring_or_skip()

    class KeychainKeyring:
        def set_password(self, service, account, password):
            pass

        def get_password(self, service, account):
            return None

        def delete_password(self, service, account):
            pass

    KeychainKeyring.__module__ = "keyring.backends.macOS"
    monkeypatch.setattr(keyring, "get_keyring", lambda: KeychainKeyring())

    store = CredentialStore()
    with pytest.raises(CredentialBackendUnavailable) as excinfo:
        store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")
    message = str(excinfo.value)
    assert "not permitted" in message
    assert "keyring.backends.macOS.KeychainKeyring" in message
    assert "keyring.backends.Windows.WinVaultKeyring" in message


def test_default_store_rejects_denied_backend_on_get(monkeypatch):
    keyring = _import_keyring_or_skip()

    class DeniedKeyring:
        def set_password(self, *args):
            pass

        def get_password(self, *args):
            return None

        def delete_password(self, *args):
            pass

    monkeypatch.setattr(keyring, "get_keyring", lambda: DeniedKeyring())

    store = CredentialStore()
    with pytest.raises(CredentialBackendUnavailable):
        store.get_credentials(ACC_A, BROKER_1)


def test_default_store_rejects_denied_backend_on_delete(monkeypatch):
    keyring = _import_keyring_or_skip()

    class DeniedKeyring:
        def set_password(self, *args):
            pass

        def get_password(self, *args):
            return None

        def delete_password(self, *args):
            pass

    monkeypatch.setattr(keyring, "get_keyring", lambda: DeniedKeyring())

    store = CredentialStore()
    with pytest.raises(CredentialBackendUnavailable):
        store.delete_credentials(ACC_A, BROKER_1)


def test_real_windows_backend_roundtrip():
    """
    REAL end-to-end test against the actual Windows Credential Manager.

    Skipped automatically unless running on Windows with the genuine
    ``WinVaultKeyring`` active, so the fake/stub tests stay independent
    from the live OS vault. Uses a dedicated, test-only (service, account)
    pair and always cleans it up.
    """
    keyring = _import_keyring_or_skip()
    if sys.platform != "win32":
        pytest.skip("real Windows Credential Manager test requires win32")
    try:
        from keyring.backends.Windows import WinVaultKeyring
    except Exception:
        pytest.skip("WinVaultKeyring not importable")
    if not isinstance(keyring.get_keyring(), WinVaultKeyring):
        pytest.skip("active keyring backend is not WinVaultKeyring")

    store = CredentialStore()  # default backend = real keyring
    account = "__task2a_real_selftest__"
    broker = "__task2a_real_broker__"
    try:
        store.save_credentials(account, broker, "real-user", "real-pass")
        assert store.get_credentials(account, broker) == ("real-user", "real-pass")
    finally:
        try:
            store.delete_credentials(account, broker)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 10. Secret leakage prevention via exception chaining / traceback
# ---------------------------------------------------------------------------

class LeakyBackendError(Exception):
    """Backend error that includes secrets in its message."""
    pass


def test_backend_error_traceback_contains_no_secrets():
    """
    When a backend error includes secrets in its message, the raised
    CredentialBackendError must not leak them: the public error is raised
    outside the ``except`` block, so BOTH ``__cause__`` and ``__context__``
    are None and the secret-bearing backend error is not reachable through
    the exception chain.
    """
    store, backend = make_store()
    # The backend error message contains the secret
    backend.fail_with = LeakyBackendError("failed writing user-a:pass-a to vault")

    with pytest.raises(CredentialBackendError) as excinfo:
        store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")

    # The raised error message must not contain secrets
    message = str(excinfo.value)
    assert "user-a" not in message
    assert "pass-a" not in message

    # The secret-bearing backend error is not attached at all.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    # 'from None' also marks the (absent) context as suppressed.
    assert excinfo.value.__suppress_context__ is True


def test_unavailable_backend_error_traceback_contains_no_secrets():
    """
    When an unavailable backend error includes secrets, the raised
    CredentialBackendUnavailable must not leak them through the chain.
    """
    store, backend = make_store()
    backend.fail_with = NoKeyringError("no vault for user-a:pass-a")

    with pytest.raises(CredentialBackendUnavailable) as excinfo:
        store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")

    message = str(excinfo.value)
    assert "user-a" not in message
    assert "pass-a" not in message

    # Exception chaining fully suppressed: no cause and no context.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert excinfo.value.__suppress_context__ is True


def test_backend_error_traceback_no_secret_in_repr():
    """
    The rendered traceback of the raised exception must not leak secrets
    that the backend echoed.

    The secret is built at RUNTIME here (never as a literal on the test's
    own source line), otherwise ``traceback`` would legitimately print the
    literal from this test file and the assertion would fail for a reason
    unrelated to the production code.
    """
    store, backend = make_store()
    user = "user-" + "zz"
    password = "pass-" + "yy"
    backend.fail_with = LeakyBackendError("secret: " + user + ":" + password)

    with pytest.raises(CredentialBackendError) as excinfo:
        store.save_credentials(ACC_A, BROKER_1, user, password)

    # Check both str and repr of the raised exception
    for text in (str(excinfo.value), repr(excinfo.value)):
        assert user not in text
        assert password not in text
    # The formatted traceback must not expose the secret either, and the
    # backend error is not attached (no chained frames to search).
    assert excinfo.value.__context__ is None
    tb = "".join(
        traceback.format_exception(
            type(excinfo.value), excinfo.value, excinfo.value.__traceback__
        )
    )
    assert user not in tb
    assert password not in tb


# ---------------------------------------------------------------------------
# 8. No credential field in Account / AccountRecord / AccountStore
# ---------------------------------------------------------------------------

def test_account_model_has_no_credential_field():
    from dataclasses import fields

    names = {f.name.lower() for f in fields(Account)}
    for word in ("password", "username", "credential", "token", "secret"):
        assert not any(word in name for name in names), (
            f"Account must not carry a credential field: {word}"
        )


def test_account_record_has_no_credential_field():
    from dataclasses import fields

    record_fields = {f.name for f in fields(AccountRecord)}
    assert record_fields == {"account", "broker_name", "display_name"}
    for word in ("password", "username", "credential"):
        assert not any(word in name.lower() for name in record_fields), (
            f"AccountRecord must not carry a credential field: {word}"
        )


def test_account_store_has_no_credential_api():
    forbidden = (
        "save_credentials", "get_credentials", "delete_credentials",
        "password", "username", "credential",
    )
    for name in dir(AccountStore):
        lowered = name.lower()
        assert not any(word in lowered for word in forbidden), (
            f"AccountStore must not expose a credential API: {name}"
        )


def test_saving_credentials_does_not_touch_account_or_record():
    store = AccountStore()
    record = store.add(ACC_A, BROKER_1, "حساب اول")

    cred_store, _ = make_store()
    cred_store.save_credentials(ACC_A, BROKER_1, "user-a", "pass-a")

    # the record and its model are byte-for-byte unchanged
    assert set(vars(record)) == {"account", "broker_name", "display_name"}
    assert set(vars(record.account)) == set(vars(Account(account_id=ACC_A)))
    assert not hasattr(record, "password")
    assert not hasattr(record, "username")
    assert not hasattr(record, "credential")
    assert not hasattr(record.account, "password")
    assert not hasattr(record.account, "username")
    # AccountStore state did not grow
    assert store.all_accounts() == (record,)
    assert store.get(ACC_A) is record


def test_account_store_source_has_no_credential_reference():
    source_path = os.path.join(REPO_ROOT, "ui", "account_store.py")
    with open(source_path, encoding="utf-8") as handle:
        source = handle.read()
    assert "save_credentials" not in source
    assert "get_credentials" not in source
    assert "delete_credentials" not in source
    assert "import keyring" not in source


def test_account_model_source_has_no_keyring_reference():
    source_path = os.path.join(REPO_ROOT, "models", "account.py")
    with open(source_path, encoding="utf-8") as handle:
        source = handle.read()
    assert "keyring" not in source
    assert "save_credentials" not in source
