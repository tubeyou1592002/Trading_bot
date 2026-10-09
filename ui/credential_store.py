"""
ui/credential_store.py — Block 9, Task 2A: Secure Credential Store.

Purpose
-------
Store and retrieve the login credentials (username + password) of a broker
account in the OPERATING SYSTEM's secure credential store via the
``keyring`` package (on Windows: the Windows Credential Manager, backed by
DPAPI) — never in any file, JSON document, SQLite database, settings or
environment variable owned by the application.

Task 2A boundary
----------------
    CredentialStore (this module)
        save_credentials(account_id, broker_name, username, password)
        get_credentials(account_id, broker_name)   -> Credentials
        delete_credentials(account_id, broker_name)

    * This module is standalone: it imports NOTHING from ``brokers/``,
      ``core/``, ``market/``, ``models/`` or ``main.py`` and performs no
      network, broker, login, CAPTCHA, session or token operation.
    * ``models/account.py``, ``ui/account_store.py`` and
      ``ui/accounts_page.py`` are NOT modified and gain NO credential
      field: credentials live only in the OS vault, addressed by the
      pair (service id, account id).
    * Fail-closed: if ``keyring`` cannot be imported, or the OS backend
      is missing / unusable / locked, every operation raises
      ``CredentialBackendUnavailable``. There is NO insecure fallback,
      no memory cache and no partial write. Backend operation failures
      raise ``CredentialBackendError``; both never carry the username or
      the password in their message. The public errors are raised OUTSIDE
      the ``except`` block, so neither ``__cause__`` nor ``__context__``
      can expose a backend message that might have echoed the credentials.
    * Tests inject a stub backend through ``CredentialStore(backend=...)``
      and never touch a real vault, a real broker or the network.

Key scheme (stable, explicit, separated)
----------------------------------------
    service id : "Trading Bot/{broker_name}"   <- broker scope, stable
    account id : "{account_id}"                <- the account's own id

The two identifiers always live in separate ``keyring`` fields, so the
pair ``(service id, account id)`` is unique per (broker, account): two
accounts on one broker and one account id across two brokers can never
collide, no matter what characters the identifiers contain. ``broker_name``
is whitespace-trimmed exactly like ``AccountStore`` trims it; ``account_id``
is used verbatim, exactly as the ``Account`` model stores it.

Payload (username + password = ONE logical unit)
------------------------------------------------
A single vault entry holds both halves, length-prefixed:

    "{len(username)}:{username}{password}"

One ``get_password`` call therefore returns the username and the password
of the same account together — they are never split across two stores,
and the encoding is injective for any character (newlines, colons,
non-ASCII) with no delimiter guessing.
"""

from typing import NamedTuple

#: Stable application-level service name (matches the QApplication
#: application name set in ``ui/app.py``).
SERVICE_NAME = "Trading Bot"

#: The single allowed keyring backend for this project (Windows).
#: Any other backend (including other Windows backends, macOS Keychain,
#: Linux Secret Service, or mock/test backends in production) is rejected.
_ALLOWED_BACKEND_CLASS = "keyring.backends.Windows.WinVaultKeyring"

#: Backend exception class names that mean "the secure backend itself is
#: not available" (locked / uninitialized / absent). Checked by class NAME
#: so classifying an error never requires importing ``keyring`` — the
#: classification works identically for the real backend and for a stub.
_UNAVAILABLE_BACKEND_ERRORS = frozenset(
    {"NoKeyringError", "InitError", "KeyringLocked"}
)

_CORRUPT_PAYLOAD = "stored credential payload is malformed"


class CredentialStoreError(Exception):
    """Base class for every error raised by :class:`CredentialStore`."""


class CredentialValidationError(CredentialStoreError, ValueError):
    """
    Invalid input: a non-string, empty or whitespace-only ``account_id``,
    ``broker_name``, ``username`` or ``password``.

    Follows the project's validation convention (``AccountValidationError``,
    ``AccountStoreError`` are ``ValueError``): fail-closed, the value itself
    is never echoed into the message.
    """


class CredentialBackendError(CredentialStoreError):
    """The secure backend failed while performing the operation."""


class CredentialBackendUnavailable(CredentialBackendError):
    """The secure backend cannot be used — the operation stops, fail-closed."""


class CredentialNotFoundError(CredentialStoreError):
    """No credential is stored for the requested (account, broker) pair."""


class Credentials(NamedTuple):
    """Username and password of one account, retrieved as one unit."""

    username: str
    password: str


def _require_text(value, field):
    """
    Validate one identifier/credential field and return it VERBATIM.

    Non-strings, empty strings and whitespace-only strings are rejected
    with ``CredentialValidationError``. The message names the field only —
    the submitted value is never echoed (it may be a secret).
    """
    if not isinstance(value, str) or not value.strip():
        raise CredentialValidationError(
            f"{field} must be a non-empty, non-whitespace string"
        )
    return value


def service_id(broker_name):
    """
    Stable, explicit service identifier for one broker scope.

    Used verbatim as the ``keyring`` service field:
    ``"Trading Bot/{broker_name}"``. Contains no account information.
    """
    return f"{SERVICE_NAME}/{broker_name}"


def _pack(username, password):
    """Pack username + password into ONE vault payload (injective)."""
    return f"{len(username)}:{username}{password}"


def _unpack(payload):
    """
    Inverse of :func:`_pack`. A malformed payload raises
    ``CredentialBackendError`` WITHOUT echoing the payload (it is secret).
    """
    if not isinstance(payload, str):
        raise CredentialBackendError(_CORRUPT_PAYLOAD)
    head, sep, rest = payload.partition(":")
    if not sep or not head.isdigit():
        raise CredentialBackendError(_CORRUPT_PAYLOAD)
    try:
        length = int(head)
    except ValueError:  # pragma: no cover — isdigit() already gates this
        raise CredentialBackendError(_CORRUPT_PAYLOAD) from None
    if len(rest) < length:
        raise CredentialBackendError(_CORRUPT_PAYLOAD)
    username, password = rest[:length], rest[length:]
    if not username or not password:
        raise CredentialBackendError(_CORRUPT_PAYLOAD)
    return Credentials(username, password)


def _allowed_backend_class():
    """
    Import and return the REAL ``keyring.backends.Windows.WinVaultKeyring``
    class from the installed keyring package.

    The policy compares the active backend object against THIS class by
    exact type identity (``type(backend) is WinVaultKeyring``), never by a
    ``"module.ClassName"`` string and never by ``isinstance``. A look-alike
    class that merely copies ``__module__`` / ``__name__`` — or even a
    subclass of ``WinVaultKeyring`` — therefore cannot impersonate the
    allowed backend.

    Returns ``None`` when the class cannot be imported — keyring absent,
    or a non-Windows platform where ``keyring.backends.Windows`` is not
    usable. The caller treats that as fail-closed.
    """
    try:
        from keyring.backends.Windows import WinVaultKeyring
    except Exception:
        return None
    return WinVaultKeyring


def _load_keyring():
    """
    Resolve the real secure backend lazily and enforce the allowed backend
    policy by CLASS IDENTITY (not by class name / module string).

    Importing :mod:`ui.credential_store` therefore never requires
    ``keyring`` and never touches the vault; only an actual operation on
    the DEFAULT (non-stub) store does. A missing/broken ``keyring``
    installation raises ``CredentialBackendUnavailable`` — there is no
    insecure fallback of any kind.

    The ONLY allowed backend is the concrete
    ``keyring.backends.Windows.WinVaultKeyring`` class (Windows Credential
    Manager). The active backend must be EXACTLY that class
    (``type(backend) is WinVaultKeyring``); subclasses and any other
    backend are rejected with ``CredentialBackendUnavailable``.
    """
    try:
        import keyring
    except Exception:
        keyring = None
    if keyring is None:
        raise CredentialBackendUnavailable(
            "secure credential backend (keyring) is not available"
        ) from None

    # Enforce the explicit allowed backend policy by class identity.
    backend = keyring.get_keyring()
    if backend is None:
        raise CredentialBackendUnavailable(
            "secure credential backend returned None (no backend available)"
        ) from None

    allowed_class = _allowed_backend_class()
    if allowed_class is None or type(backend) is not allowed_class:
        backend_class = f"{backend.__class__.__module__}.{backend.__class__.__name__}"
        raise CredentialBackendUnavailable(
            f"credential backend '{backend_class}' is not permitted; "
            f"only '{_ALLOWED_BACKEND_CLASS}' is allowed"
        ) from None

    return keyring


class CredentialStore:
    """
    Save / get / delete broker account credentials in the OS secure store.

    Contract:

        save_credentials(account_id, broker_name, username, password) -> None
        get_credentials(account_id, broker_name)                      -> Credentials
        delete_credentials(account_id, broker_name)                   -> None

    Rules:

        * All four ``save`` fields and both ``get``/``delete`` identifiers
          must be non-empty, non-whitespace strings; anything else raises
          ``CredentialValidationError`` BEFORE the backend is touched.
        * ``save`` overwrites the credential of exactly that
          (broker, account) pair and leaves every other pair untouched.
        * ``get`` returns username + password as one ``Credentials`` unit;
          when nothing is stored it raises ``CredentialNotFoundError``.
        * ``delete`` removes exactly that pair; when nothing is stored it
          raises ``CredentialNotFoundError`` (the behaviour after a
          delete is therefore explicit, not silent).
        * Any backend failure raises ``CredentialBackendError``; an
          unavailable/locked/absent backend raises
          ``CredentialBackendUnavailable``. Both fail closed, and neither
          message nor any log ever contains the username or password.
    """

    def __init__(self, backend=None):
        """
        ``backend``: optional keyring-compatible object exposing
        ``set_password`` / ``get_password`` / ``delete_password`` — the
        seam tests use for their in-memory stub. ``None`` (default)
        resolves the real ``keyring`` package lazily on every operation;
        construction itself never touches any backend.

        If ``backend`` is ``None``, the real keyring backend is loaded
        lazily and MUST be the allowed class (``_ALLOWED_BACKEND_CLASS``).
        """
        self._backend = backend

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _call(self, operation, account_id, broker_name, method_name, *args):
        """
        One backend call, uniformly error-mapped.

        * our own ``CredentialStoreError`` passes through unchanged;
        * a backend error classed as unavailable (by name) becomes
          ``CredentialBackendUnavailable``;
        * anything else becomes ``CredentialBackendError`` carrying only
          the operation, the non-secret identifiers and the error CLASS
          name — never the error text (a backend may echo the payload).

        The mapped error is raised OUTSIDE the ``except`` block (see
        below). Because no exception is being handled at that point,
        Python attaches neither ``__cause__`` nor ``__context__``: a
        backend message that echoed the username/password cannot be
        reached through the raised exception's chain, even
        programmatically.
        """
        if self._backend is not None:
            backend = self._backend
        else:
            backend = _load_keyring()
        where = f"account {account_id!r}, broker {broker_name!r}"
        error_class = None
        unavailable = False
        try:
            method = getattr(backend, method_name)
            return method(*args)
        except CredentialStoreError:
            raise
        except Exception as exc:
            error_class = type(exc).__name__
            unavailable = error_class in _UNAVAILABLE_BACKEND_ERRORS

        # Raised outside the ``except`` block: the original backend error
        # is not attached, not even as ``__context__``.
        if unavailable:
            raise CredentialBackendUnavailable(
                f"secure credential backend is unavailable during "
                f"{operation} ({where})"
            ) from None
        raise CredentialBackendError(
            f"credential backend failed during {operation} "
            f"({where}): {error_class}"
        ) from None

    def _keys(self, account_id, broker_name):
        """Validate both identifiers and return (account_id, service)."""
        account_id = _require_text(account_id, "account_id")
        broker_name = _require_text(broker_name, "broker_name").strip()
        return account_id, service_id(broker_name)

    # ------------------------------------------------------------------
    # public operations
    # ------------------------------------------------------------------

    def save_credentials(self, account_id, broker_name, username, password):
        """
        Store username + password as ONE vault entry for exactly this
        (broker, account) pair, overwriting any previous entry of that
        pair. Returns ``None``.

        Validation happens before the backend is resolved: invalid input
        can never cause a vault write.
        """
        account_id = _require_text(account_id, "account_id")
        broker_name = _require_text(broker_name, "broker_name").strip()
        username = _require_text(username, "username")
        password = _require_text(password, "password")
        payload = _pack(username, password)
        self._call(
            "save", account_id, broker_name, "set_password",
            service_id(broker_name), account_id, payload,
        )

    def get_credentials(self, account_id, broker_name):
        """
        Return the stored username + password of this (broker, account)
        pair as ONE ``Credentials`` unit (a single backend read).

        Raises ``CredentialNotFoundError`` when nothing is stored, and
        ``CredentialBackendError`` when the stored payload is unreadable.
        """
        account_id, service = self._keys(account_id, broker_name)
        payload = self._call(
            "get", account_id, broker_name, "get_password",
            service, account_id,
        )
        if payload is None:
            raise CredentialNotFoundError(
                f"no credential stored for account {account_id!r} "
                f"(broker {broker_name!r})"
            )
        try:
            return _unpack(payload)
        except CredentialBackendError:
            pass
        # Raised outside the ``except`` block: no ``__cause__`` /
        # ``__context__`` chain is attached to the public error.
        raise CredentialBackendError(
            f"stored credential for account {account_id!r} "
            f"(broker {broker_name!r}) is unreadable"
        ) from None

    def delete_credentials(self, account_id, broker_name):
        """
        Remove the credential of exactly this (broker, account) pair.
        Every other pair is untouched. Returns ``None``.

        Raises ``CredentialNotFoundError`` when there is nothing to
        delete, so the behaviour after a delete is explicit on both the
        delete and the subsequent get.
        """
        account_id, service = self._keys(account_id, broker_name)
        payload = self._call(
            "existence check", account_id, broker_name, "get_password",
            service, account_id,
        )
        if payload is None:
            raise CredentialNotFoundError(
                f"no credential stored for account {account_id!r} "
                f"(broker {broker_name!r})"
            )
        self._call(
            "delete", account_id, broker_name, "delete_password",
            service, account_id,
        )
