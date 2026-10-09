"""
ui/session_manager.py — Block 9, Task 3: Account Session Manager.

Purpose
-------
Track the login/session state of each account INDEPENDENTLY at the
application layer, so that two accounts — including two accounts on the
same broker — never share a login state, and selecting or logging one
account in or out can never affect another account's session. This is the
foundation the later Tasks build on (Task 4 wires the real Agah
login/CAPTCHA flow, Task 5 the real token refresh/expiry lifecycle, Task 8
the Order Page access gate).

Task 3 boundary
---------------
    SessionManager (this module)
        register(account_id, broker_name)  -> Session
        unregister(account_id)             -> None
        get(account_id)                    -> Session
        state(account_id)                  -> SessionState
        is_logged_in(account_id)           -> bool
        all_sessions()                     -> tuple[Session, ...]
        begin_login(account_id)            -> Session
        mark_logged_in(account_id, token)  -> Session
        fail_login(account_id)             -> Session
        logout(account_id)                 -> Session
        get_token(account_id)              -> token | None

    * This module is a BROKER-INDEPENDENT primitive: it imports NOTHING
      from ``brokers/``, ``core/``, ``market/``, ``models/`` or ``main.py``
      and performs no network, broker, login, CAPTCHA, credential or order
      operation. It never instantiates a broker and never touches
      ``BrokerManager``.
    * Real Agah login/CAPTCHA integration is Task 4 and real
      token refresh/expiry is Task 5 — neither is implemented here. The
      state machine only records what the caller reports.
    * Purely in-memory: no SQLite, JSON, config file, environment variable
      or OS-vault write of any kind. Sessions and tokens exist only while
      the application runs.
    * The opaque token passed to ``mark_logged_in`` is held in memory for
      the lifetime of the session and is NEVER written to ``Session``, to
      a model, or to any persistent store. ``Session`` (the public
      snapshot) carries identity and state only. Tokens are secret and are
      therefore never echoed into an error message or a ``repr``.
    * ``models/account.py``, ``ui/account_store.py`` and
      ``ui/credential_store.py`` are NOT modified and gain NO session or
      token field.
    * Fail-closed: an operation on an unknown account raises
      ``SessionNotFoundError`` (an account is never guessed or
      substituted); an invalid state transition raises
      ``SessionStateError`` (a state is never silently accepted).

State model
-----------
    LOGGED_OUT --begin_login--> LOGIN_PENDING --mark_logged_in--> LOGGED_IN
                      ^                |                              |
                      |                +---------- fail_login -------+|
                      |                                              ||
                      +------------------- logout -------------------+|

    * A newly registered account starts in ``LOGGED_OUT``.
    * ``begin_login`` is only valid from ``LOGGED_OUT``; a second
      ``begin_login`` while ``LOGIN_PENDING`` or ``LOGGED_IN`` is rejected
      so two concurrent login flows for one account can never overlap.
    * ``mark_logged_in`` is only valid from ``LOGIN_PENDING``: a session
      is only ever marked logged in as the result of a login the caller
      actually performed.
    * ``fail_login`` and ``logout`` return the account to ``LOGGED_OUT``
      and clear that account's token; every other account is untouched.

Key scheme
----------
A session is addressed by the account's own ``account_id`` (the same
globally-unique identity ``AccountStore`` uses), and the associated
``broker_name`` is recorded on the session. ``broker_name`` is
whitespace-trimmed exactly like ``AccountStore``/``CredentialStore`` trim
it; ``account_id`` is used verbatim, exactly as the ``Account`` model
stores it.
"""

from dataclasses import dataclass
from enum import Enum


class SessionManagerError(Exception):
    """Base class for every error raised by :class:`SessionManager`."""


class SessionValidationError(SessionManagerError, ValueError):
    """
    Invalid input: a non-string, empty or whitespace-only ``account_id``
    or ``broker_name``.

    Follows the project's validation convention
    (``AccountValidationError``, ``AccountStoreError``,
    ``CredentialValidationError`` are ``ValueError``): fail-closed, and the
    value itself is never echoed into the message.
    """


class SessionAlreadyExistsError(SessionManagerError):
    """An account with this ``account_id`` is already registered."""


class SessionNotFoundError(SessionManagerError):
    """No session is registered for the requested ``account_id``."""


class SessionStateError(SessionManagerError):
    """
    A requested state transition is not allowed from the account's current
    state. The message names the account and the two states — never a
    token.
    """


class SessionState(Enum):
    """The login state of one account's session."""

    LOGGED_OUT = "logged_out"
    LOGIN_PENDING = "login_pending"
    LOGGED_IN = "logged_in"


@dataclass(frozen=True)
class Session:
    """
    Public, read-only snapshot of one account's session.

    Carries identity and state ONLY — the in-memory token is deliberately
    NOT part of this snapshot, so no ``repr``/serialisation of a
    ``Session`` can ever expose a secret.
    """

    account_id: str
    broker_name: str
    state: SessionState


def _require_text(value, field):
    """
    Validate one identifier field and return it VERBATIM.

    Non-strings, empty strings and whitespace-only strings are rejected
    with ``SessionValidationError``. The message names the field only.
    """
    if not isinstance(value, str) or not value.strip():
        raise SessionValidationError(
            f"{field} must be a non-empty, non-whitespace string"
        )
    return value


class SessionManager:
    """
    In-memory, broker-independent registry of per-account sessions.

    Contract:

        register(account_id, broker_name)  -> Session
        unregister(account_id)             -> None
        get(account_id)                    -> Session
        state(account_id)                  -> SessionState
        is_logged_in(account_id)           -> bool
        all_sessions()                     -> tuple[Session, ...]
        begin_login(account_id)            -> Session
        mark_logged_in(account_id, token)  -> Session
        fail_login(account_id)             -> Session
        logout(account_id)                 -> Session
        get_token(account_id)              -> token | None

    Rules:

        * ``account_id`` must be a non-empty, non-whitespace string and
          must be unique within the manager; a duplicate raises
          ``SessionAlreadyExistsError``.
        * ``broker_name`` must be a non-empty, non-whitespace string and
          is stored trimmed.
        * Every operation addresses exactly one account. No operation can
          change another account's state or token — sessions are fully
          independent.
        * Read/transition operations on an unknown account raise
          ``SessionNotFoundError``.
        * An invalid state transition raises ``SessionStateError`` and
          leaves the session unchanged.
    """

    def __init__(self):
        self._sessions = {}
        self._tokens = {}

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _get(self, account_id):
        """
        Return the registered ``Session`` for ``account_id``.

        Raises ``SessionNotFoundError`` for an unknown or unhashable id —
        a session is never guessed or substituted. The message is generic:
        it never echoes ``account_id`` or its ``repr``, so an identifier
        supplied by the caller cannot leak through logs, UI or traces.
        """
        try:
            return self._sessions[account_id]
        except (KeyError, TypeError) as exc:
            raise SessionNotFoundError(
                "no session is registered for the requested account"
            ) from exc

    def _transition(self, account_id, allowed_from, new_state):
        """
        Move one account to ``new_state`` when its current state is in
        ``allowed_from``; otherwise raise ``SessionStateError`` and leave
        the session untouched.
        """
        session = self._get(account_id)
        if session.state not in allowed_from:
            raise SessionStateError(
                f"account {account_id!r} cannot move from "
                f"{session.state.value!r} to {new_state.value!r}"
            )
        updated = Session(
            account_id=session.account_id,
            broker_name=session.broker_name,
            state=new_state,
        )
        self._sessions[account_id] = updated
        return updated

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------

    def register(self, account_id, broker_name):
        """
        Register a new account and open its session in ``LOGGED_OUT``.

        Returns the created ``Session``. Raises
        ``SessionAlreadyExistsError`` for a duplicate ``account_id`` and
        ``SessionValidationError`` for an invalid identifier.
        """
        account_id = _require_text(account_id, "account_id")
        broker_name = _require_text(broker_name, "broker_name").strip()

        if account_id in self._sessions:
            raise SessionAlreadyExistsError(
                f"account_id {account_id!r} is already registered"
            )

        session = Session(
            account_id=account_id,
            broker_name=broker_name,
            state=SessionState.LOGGED_OUT,
        )
        self._sessions[account_id] = session
        self._tokens[account_id] = None
        return session

    def unregister(self, account_id):
        """
        Remove the session of exactly one account and drop its token.

        Raises ``SessionNotFoundError`` when the account is unknown, so
        the behaviour after an unregister is explicit. Every other account
        is untouched.
        """
        self._get(account_id)
        del self._sessions[account_id]
        del self._tokens[account_id]

    # ------------------------------------------------------------------
    # read access
    # ------------------------------------------------------------------

    def get(self, account_id):
        """Return the ``Session`` of ``account_id`` (unknown raises)."""
        return self._get(account_id)

    def state(self, account_id):
        """Return the ``SessionState`` of ``account_id`` (unknown raises)."""
        return self._get(account_id).state

    def is_logged_in(self, account_id):
        """True exactly when the account's state is ``LOGGED_IN``."""
        return self._get(account_id).state is SessionState.LOGGED_IN

    def all_sessions(self):
        """All registered sessions, in registration order."""
        return tuple(self._sessions.values())

    def get_token(self, account_id):
        """
        Return the opaque in-memory token of ``account_id``.

        The token is returned only while the account is ``LOGGED_IN``;
        otherwise ``None``. Unknown accounts raise ``SessionNotFoundError``.
        The token is never included in a ``Session`` snapshot, an error
        message or a ``repr``.
        """
        session = self._get(account_id)
        if session.state is not SessionState.LOGGED_IN:
            return None
        return self._tokens[account_id]

    # ------------------------------------------------------------------
    # transitions
    # ------------------------------------------------------------------

    def begin_login(self, account_id):
        """
        Move the account from ``LOGGED_OUT`` to ``LOGIN_PENDING``.

        Only valid from ``LOGGED_OUT``; any other state raises
        ``SessionStateError`` so overlapping login flows for one account
        are impossible.
        """
        return self._transition(
            account_id,
            allowed_from={SessionState.LOGGED_OUT},
            new_state=SessionState.LOGIN_PENDING,
        )

    def mark_logged_in(self, account_id, token=None):
        """
        Move the account from ``LOGIN_PENDING`` to ``LOGGED_IN`` and hold
        ``token`` in memory for this account only.

        The token is opaque to this module (its shape is decided by the
        real login flow in Task 4) and may be ``None``. Only valid from
        ``LOGIN_PENDING``: a session is marked logged in only after a
        login the caller actually performed.
        """
        session = self._transition(
            account_id,
            allowed_from={SessionState.LOGIN_PENDING},
            new_state=SessionState.LOGGED_IN,
        )
        self._tokens[account_id] = token
        return session

    def fail_login(self, account_id):
        """
        Move the account from ``LOGIN_PENDING`` back to ``LOGGED_OUT`` and
        drop its token. Only valid from ``LOGIN_PENDING``.
        """
        session = self._transition(
            account_id,
            allowed_from={SessionState.LOGIN_PENDING},
            new_state=SessionState.LOGGED_OUT,
        )
        self._tokens[account_id] = None
        return session

    def logout(self, account_id):
        """
        Move the account from ``LOGGED_IN`` or ``LOGIN_PENDING`` to
        ``LOGGED_OUT`` and drop its token.

        Only valid from a non-logged-out state; logging out an account
        that is already ``LOGGED_OUT`` raises ``SessionStateError`` (the
        behaviour after a logout is explicit). No other account is
        affected.
        """
        session = self._transition(
            account_id,
            allowed_from={SessionState.LOGGED_IN, SessionState.LOGIN_PENDING},
            new_state=SessionState.LOGGED_OUT,
        )
        self._tokens[account_id] = None
        return session
