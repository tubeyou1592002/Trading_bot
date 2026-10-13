"""
test_block9_task4_authentication_service.py

Block 9 — Task 4, Stage 2: tests for ui/authentication_service.py
(fully offline).

The service coordinates the REAL AccountStore, CredentialStore and
SessionManager with injectable broker/adapter factories, so:

    * no network request is ever sent,
    * no real credentials are used (a stub backend feeds them in),
    * real per-account session state transitions are exercised.

Contract coverage:

    1. Successful Agah login → session registered as LOGGED_IN with the
       real token, adapter retained for later use.
    2. Failed captcha / rejected login → session back to LOGGED_OUT,
       temp state cleared, failed instance discarded.
    3. Apparently-successful but incomplete API response → session stays
       out of LOGGED_IN.
    4. Full independence of two accounts on one broker: broker instance,
       HTTP session, login state and token.
    5. Cleanup of a failed attempt state and cancel_login.
    6. No password or token leakage in outputs and errors.
    7. Unknown broker name is fail-closed (no guesswork).
    8. Session/account broker consistency enforcement.

Run:
    pytest -q test_block9_task4_authentication_service.py
"""

import socket

import pytest

from brokers.authentication import (
    AuthenticationAdapter,
    AuthenticatedSession,
    AuthenticationUnavailableError,
    CHALLENGE_CAPTCHA_IMAGE,
    IncompleteLoginError,
    LoginChallenge,
    LoginChallengeError,
    LoginNotInProgressError,
    LoginRejectedError,
)
from ui.account_store import AccountStore
from ui.authentication_service import (
    AuthenticationService,
    AuthenticationServiceError,
    InconsistentSessionError,
    NoPendingLoginError,
    UnknownBrokerError,
)
from ui.credential_store import CredentialStore
from ui.session_manager import (
    SessionManager,
    SessionState,
)


ACC_A = "ACC-001"
ACC_B = "ACC-002"
BROKER_AGAH = "آگاه"
BROKER_UNKNOWN = "نامعلوم"
USERNAME = "agah-user"
PASSWORD = "agah-pass-SECRET"
ACCESS_TOKEN = "ACCESS-TOKEN-SECRET-123"
REFRESH_TOKEN = "REFRESH-TOKEN-SECRET-456"
USER_IDENTIFIER = "user-identifier-789"


# ---------------------------------------------------------------------------
# Stub credential backend (in-memory, mirrors the project's test convention)
# ---------------------------------------------------------------------------

class StubBackend:
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


def make_stores():
    accounts = AccountStore()
    credentials = CredentialStore(backend=StubBackend())
    sessions = SessionManager()
    return accounts, credentials, sessions


def seed_account(accounts, credentials, account_id=ACC_A,
                 broker_name=BROKER_AGAH, username=USERNAME, password=PASSWORD):
    accounts.add(account_id, broker_name, f"حساب {account_id}")
    credentials.save_credentials(account_id, broker_name, username, password)
    return account_id


# ---------------------------------------------------------------------------
# Fake adapter factory: fully offline, records what happened per account
# ---------------------------------------------------------------------------

class FakeAgahAdapter(AuthenticationAdapter):
    """
    Offline double of AgahAuthenticationAdapter. Implements the contract
    with scripted outcomes and records enough state for independence tests.
    """

    def __init__(self, login_outcome="success"):
        self._login_outcome = login_outcome
        self.begin_login_count = 0
        self.complete_login_count = 0
        self.cancel_login_count = 0
        self.last_username = None
        self.last_password = None
        self.last_response = None
        self.pending = False
        self.authenticated_session = None
        self.instance_id = id(self)

    @property
    def broker_name(self):
        return BROKER_AGAH

    def begin_login(self, username, password):
        self.begin_login_count += 1
        self.last_username = username
        self.last_password = password
        self.pending = True
        return LoginChallenge(
            kind=CHALLENGE_CAPTCHA_IMAGE,
            display_payload="fake-captcha-image",
            prompt="کد کپچا را وارد کنید.",
        )

    def complete_login(self, response):
        self.complete_login_count += 1
        self.last_response = response
        self.pending = False

        if not response or not str(response).strip():
            raise LoginRejectedError("پاسخ کپچا خالی است")

        if self._login_outcome == "bad_captcha":
            raise LoginRejectedError("کپچا یا اعتبارنامه نامعتبر است")
        if self._login_outcome == "incomplete":
            raise IncompleteLoginError("پاسخ کامل نبود")
        if self._login_outcome == "unavailable":
            raise AuthenticationUnavailableError("سرویس در دسترس نیست")

        self.authenticated_session = AuthenticatedSession(
            access_token=ACCESS_TOKEN,
            user_identifier=USER_IDENTIFIER,
            refresh_token=REFRESH_TOKEN,
            user_name=self.last_username,
        )
        return self.authenticated_session

    def cancel_login(self):
        self.cancel_login_count += 1
        self.pending = False

    def is_authenticated(self):
        return self.authenticated_session is not None

    def get_authenticated_session(self):
        return self.authenticated_session


def make_service(adapter_outcomes=None):
    """
    Builds the service with real stores and a registered fake adapter
    factory for "آگاه". adapter_outcomes maps account_id -> scripted
    outcome.
    """
    accounts, credentials, sessions = make_stores()
    outcomes = dict(adapter_outcomes or {})

    created = []
    _current_account = [None]

    def adapter_factory():
        adapter = FakeAgahAdapter()
        adapter._login_outcome = outcomes.get(
            _current_account[0], "success"
        )
        created.append(adapter)
        return adapter

    service = AuthenticationService(
        accounts, credentials, sessions,
        adapter_factories={BROKER_AGAH: adapter_factory},
    )

    # Track which account is being logged in so the factory can script
    # per-account outcomes.
    original_begin = service.begin_login

    def begin_login(account_id):
        _current_account[0] = account_id
        return original_begin(account_id)

    service.begin_login = begin_login
    service.created_adapters = created
    return service


def make_service_with_real_agah_factories():
    """
    Service wired with the REAL Agah adapter factories, but with stores
    that never hold real credentials. Proves the production wiring seam
    (AGAH_ADAPTER_FACTORIES) works end-to-end offline.
    """
    from brokers.agaah.auth_adapter import AGAH_ADAPTER_FACTORIES

    accounts, credentials, sessions = make_stores()
    return AuthenticationService(
        accounts, credentials, sessions,
        adapter_factories=AGAH_ADAPTER_FACTORIES,
    )


def seed_and_begin(service, account_id=ACC_A, outcome=None):
    if outcome is not None:
        service  # outcomes are pre-scripted via make_service
    seed_account(
        service._accounts, service._credentials, account_id=account_id
    )
    return service.begin_login(account_id)


# ---------------------------------------------------------------------------
# 1. Successful login
# ---------------------------------------------------------------------------

def test_begin_login_returns_displayable_challenge():
    service = make_service()
    challenge = seed_and_begin(service)

    assert isinstance(challenge, LoginChallenge)
    assert challenge.kind == CHALLENGE_CAPTCHA_IMAGE
    assert "captchaId" not in repr(challenge)


def test_begin_login_marks_session_pending():
    service = make_service()
    seed_and_begin(service)

    assert service._sessions.state(ACC_A) is SessionState.LOGIN_PENDING
    assert service.is_logged_in(ACC_A) is False


def test_begin_login_reads_account_and_credentials_by_pair():
    service = make_service()
    seed_account(service._accounts, service._credentials)
    service.begin_login(ACC_A)

    adapter = service.created_adapters[-1]
    assert adapter.last_username == USERNAME
    assert adapter.last_password == PASSWORD


def test_begin_login_registers_missing_session_with_account_broker():
    service = make_service()
    seed_account(service._accounts, service._credentials)

    session = service._sessions.get(ACC_A) if ACC_A in {
        s.account_id for s in service._sessions.all_sessions()
    } else None
    assert session is None

    service.begin_login(ACC_A)

    registered = service._sessions.get(ACC_A)
    assert registered.account_id == ACC_A
    assert registered.broker_name == BROKER_AGAH


def test_complete_login_marks_session_logged_in_with_token():
    service = make_service()
    seed_and_begin(service)
    session = service.complete_login(ACC_A, "1234")

    assert session.state is SessionState.LOGGED_IN
    assert service._sessions.get_token(ACC_A) == ACCESS_TOKEN
    assert service.is_logged_in(ACC_A) is True


def test_complete_login_retains_authenticated_adapter():
    service = make_service()
    seed_and_begin(service)
    service.complete_login(ACC_A, "1234")

    adapter = service.get_adapter(ACC_A)
    assert adapter is not None
    assert isinstance(adapter, AuthenticationAdapter)
    assert adapter.is_authenticated() is True


def test_get_adapter_returns_none_before_login():
    service = make_service()
    seed_account(service._accounts, service._credentials)
    assert service.get_adapter(ACC_A) is None


def test_get_adapter_returns_none_while_pending():
    service = make_service()
    seed_and_begin(service)
    assert service.get_adapter(ACC_A) is None


def test_get_adapter_returns_none_after_failed_login():
    service = make_service({ACC_A: "bad_captcha"})
    seed_and_begin(service)
    with pytest.raises(LoginRejectedError):
        service.complete_login(ACC_A, "bad")
    assert service.get_adapter(ACC_A) is None


# ---------------------------------------------------------------------------
# 2. Failed login cleanup
# ---------------------------------------------------------------------------

def test_failed_login_returns_session_to_logged_out():
    service = make_service({ACC_A: "bad_captcha"})
    seed_and_begin(service)

    with pytest.raises(LoginRejectedError):
        service.complete_login(ACC_A, "bad")

    assert service._sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert service.is_logged_in(ACC_A) is False
    assert service._sessions.get_token(ACC_A) is None


def test_failed_login_discards_failed_adapter():
    service = make_service({ACC_A: "bad_captcha"})
    seed_and_begin(service)
    failed = service.created_adapters[-1]

    with pytest.raises(LoginRejectedError):
        service.complete_login(ACC_A, "bad")

    # The failed attempt's adapter is gone; a new login builds a new one.
    service.begin_login(ACC_A)
    assert service.created_adapters[-1] is not failed


def test_failed_login_can_retry():
    service = make_service()
    seed_account(service._accounts, service._credentials)

    # First attempt fails.
    service._outcomes = None
    service.begin_login(ACC_A)
    service.created_adapters[-1]._login_outcome = "bad_captcha"
    with pytest.raises(LoginRejectedError):
        service.complete_login(ACC_A, "bad")

    # Second attempt succeeds.
    challenge = service.begin_login(ACC_A)
    assert isinstance(challenge, LoginChallenge)
    session = service.complete_login(ACC_A, "1234")
    assert session.state is SessionState.LOGGED_IN


def test_incomplete_login_does_not_log_in():
    service = make_service({ACC_A: "incomplete"})
    seed_and_begin(service)

    with pytest.raises(IncompleteLoginError):
        service.complete_login(ACC_A, "1234")

    assert service._sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert service.get_adapter(ACC_A) is None


def test_unavailable_login_does_not_log_in():
    service = make_service({ACC_A: "unavailable"})
    seed_and_begin(service)

    with pytest.raises(AuthenticationUnavailableError):
        service.complete_login(ACC_A, "1234")

    assert service._sessions.state(ACC_A) is SessionState.LOGGED_OUT


def test_complete_login_without_begin_raises():
    service = make_service()
    seed_account(service._accounts, service._credentials)

    with pytest.raises(NoPendingLoginError):
        service.complete_login(ACC_A, "1234")


def test_complete_login_after_failure_raises_no_pending():
    service = make_service({ACC_A: "bad_captcha"})
    seed_and_begin(service)
    with pytest.raises(LoginRejectedError):
        service.complete_login(ACC_A, "bad")

    with pytest.raises(NoPendingLoginError):
        service.complete_login(ACC_A, "1234")


# ---------------------------------------------------------------------------
# 3. Cancel login
# ---------------------------------------------------------------------------

def test_cancel_login_returns_session_to_logged_out():
    service = make_service()
    seed_and_begin(service)
    service.cancel_login(ACC_A)

    assert service._sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert service.get_adapter(ACC_A) is None


def test_cancel_login_calls_adapter_cancel():
    service = make_service()
    seed_and_begin(service)
    adapter = service.created_adapters[-1]

    service.cancel_login(ACC_A)

    assert adapter.cancel_login_count == 1


def test_cancel_login_without_begin_raises():
    service = make_service()
    seed_account(service._accounts, service._credentials)

    with pytest.raises(NoPendingLoginError):
        service.cancel_login(ACC_A)


def test_cancel_after_complete_login_raises():
    service = make_service()
    seed_and_begin(service)
    service.complete_login(ACC_A, "1234")

    with pytest.raises(NoPendingLoginError):
        service.cancel_login(ACC_A)


def test_login_after_cancel_works():
    service = make_service()
    seed_and_begin(service)
    service.cancel_login(ACC_A)

    service.begin_login(ACC_A)
    session = service.complete_login(ACC_A, "1234")
    assert session.state is SessionState.LOGGED_IN


# ---------------------------------------------------------------------------
# 4. Two accounts on one broker are fully independent
# ---------------------------------------------------------------------------

def test_two_accounts_get_independent_adapters():
    service = make_service()
    seed_and_begin(service, ACC_A)
    seed_and_begin(service, ACC_B)

    adapter_a = service.created_adapters[-2]
    adapter_b = service.created_adapters[-1]
    assert adapter_a is not adapter_b
    assert adapter_a.instance_id != adapter_b.instance_id


def test_two_accounts_have_independent_login_state():
    service = make_service()
    seed_and_begin(service, ACC_A)
    seed_and_begin(service, ACC_B)

    service.complete_login(ACC_A, "1234")

    assert service._sessions.state(ACC_A) is SessionState.LOGGED_IN
    assert service._sessions.state(ACC_B) is SessionState.LOGIN_PENDING
    assert service.is_logged_in(ACC_A) is True
    assert service.is_logged_in(ACC_B) is False


def test_two_accounts_have_independent_tokens():
    service = make_service()
    seed_and_begin(service, ACC_A)
    seed_and_begin(service, ACC_B)

    service.complete_login(ACC_A, "1234")
    service.complete_login(ACC_B, "5678")

    assert service._sessions.get_token(ACC_A) == ACCESS_TOKEN
    assert service._sessions.get_token(ACC_B) == ACCESS_TOKEN
    # Distinct adapter instances retained per account.
    assert service.get_adapter(ACC_A) is not service.get_adapter(ACC_B)


def test_failure_of_one_account_does_not_affect_other():
    service = make_service({ACC_A: "bad_captcha"})
    seed_and_begin(service, ACC_A)
    seed_and_begin(service, ACC_B)

    with pytest.raises(LoginRejectedError):
        service.complete_login(ACC_A, "bad")

    assert service._sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert service._sessions.state(ACC_B) is SessionState.LOGIN_PENDING

    session_b = service.complete_login(ACC_B, "1234")
    assert session_b.state is SessionState.LOGGED_IN


def test_logout_of_one_does_not_affect_other_service_state():
    service = make_service()
    seed_and_begin(service, ACC_A)
    seed_and_begin(service, ACC_B)
    service.complete_login(ACC_A, "1234")
    service.complete_login(ACC_B, "5678")

    service._sessions.logout(ACC_A)

    assert service.is_logged_in(ACC_A) is False
    assert service.is_logged_in(ACC_B) is True
    assert service.get_adapter(ACC_A) is None
    assert service.get_adapter(ACC_B) is not None


# ---------------------------------------------------------------------------
# 5. No leakage
# ---------------------------------------------------------------------------

def test_no_secret_in_session_snapshot():
    service = make_service()
    seed_and_begin(service)
    service.complete_login(ACC_A, "1234")

    for session in service._sessions.all_sessions():
        assert ACCESS_TOKEN not in repr(session)
        assert PASSWORD not in repr(session)


def test_no_secret_in_service_error_messages():
    service = make_service({ACC_A: "bad_captcha"})
    seed_and_begin(service)

    with pytest.raises(LoginRejectedError) as excinfo:
        service.complete_login(ACC_A, "bad")

    assert PASSWORD not in str(excinfo.value)
    assert ACCESS_TOKEN not in str(excinfo.value)


def test_account_not_found_error_is_service_error():
    """
    An unknown account must fail closed through the service error type.
    No password or token is involved (credentials are never loaded for an
    unknown account), so nothing secret can leak.
    """
    service = make_service()
    with pytest.raises(AuthenticationServiceError) as excinfo:
        service.begin_login("ACC-UNKNOWN-1")

    message = str(excinfo.value)
    assert PASSWORD not in message
    assert ACCESS_TOKEN not in message
    assert REFRESH_TOKEN not in message
    # No adapter was ever built for an unknown account.
    assert service.created_adapters == []


def test_missing_credentials_raise_service_error():
    service = make_service()
    service._accounts.add(ACC_A, BROKER_AGAH, "حساب")

    with pytest.raises(AuthenticationServiceError):
        service.begin_login(ACC_A)


# ---------------------------------------------------------------------------
# 6. Unknown broker is fail-closed
# ---------------------------------------------------------------------------

def test_service_with_no_factories_rejects_every_broker():
    accounts, credentials, sessions = make_stores()
    accounts.add(ACC_A, BROKER_AGAH, "حساب")
    credentials.save_credentials(ACC_A, BROKER_AGAH, USERNAME, PASSWORD)

    # No adapter_factories at all → fail-closed for even the known name.
    service = AuthenticationService(accounts, credentials, sessions)

    with pytest.raises(UnknownBrokerError):
        service.begin_login(ACC_A)

    assert service.is_logged_in(ACC_A) is False
    assert service.get_adapter(ACC_A) is None


def test_service_rejects_account_with_unregistered_broker():
    accounts, credentials, sessions = make_stores()
    accounts.add(ACC_A, BROKER_UNKNOWN, "حساب ناشناخته")
    credentials.save_credentials(ACC_A, BROKER_UNKNOWN, USERNAME, PASSWORD)

    service = AuthenticationService(
        accounts, credentials, sessions,
        adapter_factories={BROKER_AGAH: FakeAgahAdapter},
    )

    with pytest.raises(UnknownBrokerError):
        service.begin_login(ACC_A)

    # Fail-closed: nothing logged in, no adapter retained.
    assert service.is_logged_in(ACC_A) is False
    assert service.get_adapter(ACC_A) is None


def test_agah_factory_builds_independent_adapters():
    from brokers.agaah import AgaahBroker
    from brokers.agaah.auth_adapter import (
        AGAH_ADAPTER_FACTORIES,
        AgahAuthenticationAdapter,
    )

    factory = AGAH_ADAPTER_FACTORIES[BROKER_AGAH]

    adapter_a = factory()
    adapter_b = factory()

    assert isinstance(adapter_a, AgahAuthenticationAdapter)
    assert adapter_a is not adapter_b
    # Each adapter owns its own broker instance and HTTP session.
    assert adapter_a.broker is not adapter_b.broker
    assert isinstance(adapter_a.broker, AgaahBroker)
    assert adapter_a.broker.session is not adapter_b.broker.session
    assert adapter_a.broker_name == BROKER_AGAH


def test_agah_factories_map_only_contains_agah():
    from brokers.agaah.auth_adapter import AGAH_ADAPTER_FACTORIES

    assert set(AGAH_ADAPTER_FACTORIES) == {BROKER_AGAH}


def test_real_agah_factory_wiring_is_offline_and_fail_closed():
    """
    The production wiring seam (AGAH_ADAPTER_FACTORIES) must work offline:
    building adapters performs no network I/O, and an unregistered broker
    name stays fail-closed.
    """
    service = make_service_with_real_agah_factories()
    service._accounts.add(ACC_A, BROKER_AGAH, "حساب")

    # Building the adapter via the registered factory performs no network
    # I/O and yields a fresh, unauthenticated adapter.
    adapter = service._adapter_factories[BROKER_AGAH]()
    assert adapter.is_authenticated() is False

    # An unregistered broker name is rejected fail-closed BEFORE any
    # credential lookup or network call happens.
    service._accounts.add(ACC_B, BROKER_UNKNOWN, "حساب ناشناخته")
    with pytest.raises(UnknownBrokerError):
        service.begin_login(ACC_B)
    assert service.is_logged_in(ACC_B) is False


# ---------------------------------------------------------------------------
# 7. Session/account broker consistency
# ---------------------------------------------------------------------------

def test_inconsistent_existing_session_is_rejected():
    accounts, credentials, sessions = make_stores()
    accounts.add(ACC_A, BROKER_AGAH, "حساب")
    credentials.save_credentials(ACC_A, BROKER_AGAH, USERNAME, PASSWORD)

    # A session already registered with a DIFFERENT broker.
    sessions.register(ACC_A, "بروکر دیگر")

    service = AuthenticationService(
        accounts, credentials, sessions,
        adapter_factories={BROKER_AGAH: FakeAgahAdapter},
    )

    with pytest.raises(InconsistentSessionError):
        service.begin_login(ACC_A)


def test_consistent_existing_session_is_reused():
    accounts, credentials, sessions = make_stores()
    accounts.add(ACC_A, BROKER_AGAH, "حساب")
    credentials.save_credentials(ACC_A, BROKER_AGAH, USERNAME, PASSWORD)
    sessions.register(ACC_A, BROKER_AGAH)

    service = make_service()
    service._accounts = accounts
    service._credentials = credentials
    service._sessions = sessions

    service.begin_login(ACC_A)

    session = service._sessions.get(ACC_A)
    assert session.broker_name == BROKER_AGAH
    assert service._sessions.all_sessions().__len__() == 1


def test_challenge_failure_keeps_session_logged_out():
    service = make_service()
    seed_account(service._accounts, service._credentials)

    challenge_error = LoginChallengeError("captcha down")

    def failing_begin_login(username, password):
        raise challenge_error

    # Patch the factory to hand out an adapter whose challenge fails.
    def adapter_factory():
        adapter = FakeAgahAdapter()
        adapter.begin_login = failing_begin_login
        return adapter

    service._adapter_factories[BROKER_AGAH] = adapter_factory

    with pytest.raises(LoginChallengeError):
        service.begin_login(ACC_A)

    # No pending login, session untouched, nothing retained.
    assert service._sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert service.get_adapter(ACC_A) is None
    with pytest.raises(NoPendingLoginError):
        service.complete_login(ACC_A, "1234")


# ---------------------------------------------------------------------------
# 9. Repeated / simultaneous login attempts are rejected with no side effects
# ---------------------------------------------------------------------------

def test_repeated_login_while_logged_in_rejected_with_no_factory_call():
    """
    Logging in again while already LOGGED_IN must raise the generic
    AuthenticationServiceError. It must NOT build a new adapter, read
    credentials, or touch the session; the established login is untouched.
    """
    service = make_service()
    seed_and_begin(service)
    service.complete_login(ACC_A, "1234")

    adapter_before = service.get_adapter(ACC_A)
    adapters_before = len(service.created_adapters)
    session_state_before = service._sessions.state(ACC_A)
    token_before = service._sessions.get_token(ACC_A)

    with pytest.raises(AuthenticationServiceError):
        service.begin_login(ACC_A)

    # No new adapter instance was built by the failed re-login attempt.
    assert len(service.created_adapters) == adapters_before

    # State, token and adapter identity are unchanged.
    assert service._sessions.state(ACC_A) is session_state_before
    assert service._sessions.get_token(ACC_A) == token_before
    assert service.get_adapter(ACC_A) is adapter_before
    assert service._sessions.state(ACC_A) is SessionState.LOGGED_IN


def test_concurrent_login_attempt_rejected_and_first_still_completable():
    """
    Starting a second login for an account that already has a pending
    attempt must be rejected with no extra factory/credential work, while
    the first attempt remains completable. A different account must be
    unaffected.
    """
    service = make_service()
    seed_account(service._accounts, service._credentials)

    adapters_before = len(service.created_adapters)

    # First attempt goes fully through: factory -> credentials -> challenge.
    challenge_a = service.begin_login(ACC_A)
    adapters_after_first = len(service.created_adapters)
    assert adapters_after_first == adapters_before + 1
    adapter_a = service.created_adapters[-1]
    assert adapter_a is service._pending_logins[ACC_A]

    # Second attempt for the same account: rejected immediately.
    with pytest.raises(AuthenticationServiceError):
        service.begin_login(ACC_A)

    # No new factory call and no credential read happened for the second
    # attempt (tracked via the service's in-memory credential backend).
    credential_backend = service._credentials._backend
    reads_during = len(
        [c for c in credential_backend.calls if c[0] == "get"]
    )
    # Exactly one read: the first attempt's credential lookup. The rejected
    # second attempt added no further read.
    assert reads_during == 1

    assert len(service.created_adapters) == adapters_after_first
    assert service._pending_logins[ACC_A] is adapter_a
    assert service._sessions.state(ACC_A) is SessionState.LOGIN_PENDING

    # The first attempt is still completable.
    session_b = service.complete_login(ACC_A, "1234")
    assert session_b.state is SessionState.LOGGED_IN
    assert service.is_logged_in(ACC_A) is True


def test_credential_read_not_repeated_on_rejected_relogin():
    """
    A rejected re-login (already logged in) must not re-read credentials:
    credential reads happen only during the successful begin_login.
    """
    service = make_service()
    seed_account(service._accounts, service._credentials)
    service.begin_login(ACC_A)
    service.complete_login(ACC_A, "1234")

    reads_before = len(
        [c for c in service._credentials._backend.calls if c[0] == "get"]
    )

    with pytest.raises(AuthenticationServiceError):
        service.begin_login(ACC_A)

    reads_after = len(
        [c for c in service._credentials._backend.calls if c[0] == "get"]
    )
    assert reads_after == reads_before


def test_adapter_build_failure_resets_session_to_logged_out():
    """
    Failure while building the adapter (after session reservation) must
    reset the session to LOGGED_OUT and clear the temp attempt.
    """
    accounts, credentials, sessions = make_stores()
    accounts.add(ACC_A, BROKER_AGAH, "حساب")
    credentials.save_credentials(ACC_A, BROKER_AGAH, USERNAME, PASSWORD)

    factory_calls = []

    def failing_factory():
        factory_calls.append(1)
        raise UnknownBrokerError("آداپتر ساخته نشد")

    service = AuthenticationService(
        accounts, credentials, sessions,
        adapter_factories={BROKER_AGAH: failing_factory},
    )

    with pytest.raises(UnknownBrokerError):
        service.begin_login(ACC_A)

    assert factory_calls == [1]
    assert service._sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert service._sessions.get_token(ACC_A) is None
    assert service.get_adapter(ACC_A) is None
    assert ACC_A not in service._pending_logins


def test_missing_credentials_after_reservation_resets_session():
    """
    Missing credentials (read after session reservation) must reset the
    session to LOGGED_OUT and clear the temp attempt; the service error
    propagates unchanged.
    """
    service = make_service()
    # Account exists, credentials intentionally NOT saved.
    service._accounts.add(ACC_A, BROKER_AGAH, "حساب")

    with pytest.raises(AuthenticationServiceError):
        service.begin_login(ACC_A)

    # Session was registered during _resolve_account, then reset to LOGGED_OUT.
    assert service._sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert service._sessions.get_token(ACC_A) is None
    assert service.get_adapter(ACC_A) is None
    assert ACC_A not in service._pending_logins
    # Session remains registered (count = 1), just in LOGGED_OUT state.
    assert len(service._sessions.all_sessions()) == 1


def test_challenge_failure_resets_session_and_re_retry_after_fix():
    """
    A challenge failure (after session reservation) must reset the session
    to LOGGED_OUT and clear the temp attempt, and the original error must
    propagate unchanged.
    """
    service = make_service()
    seed_account(service._accounts, service._credentials)

    challenge_error = LoginChallengeError("captcha down")
    built = []
    outcome = ["fail"]

    def failing_begin_login(username, password):
        raise challenge_error

    def adapter_factory():
        adapter = FakeAgahAdapter()
        if outcome[0] == "fail":
            adapter.begin_login = failing_begin_login
        built.append(adapter)
        return adapter

    service._adapter_factories[BROKER_AGAH] = adapter_factory

    with pytest.raises(LoginChallengeError):
        service.begin_login(ACC_A)

    assert len(built) == 1
    assert service._sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert service._sessions.get_token(ACC_A) is None
    assert service.get_adapter(ACC_A) is None
    assert ACC_A not in service._pending_logins

    # After the cause is fixed, a fresh login attempt works.
    outcome[0] = "success"
    challenge = service.begin_login(ACC_A)
    assert isinstance(challenge, LoginChallenge)
    session = service.complete_login(ACC_A, "1234")
    assert session.state is SessionState.LOGGED_IN


def test_failure_of_one_account_does_not_touch_the_other_after_reservation():
    """
    A failure that happens after session reservation must only affect the
    failing account: another account's state and token remain unchanged.
    """
    service = make_service({ACC_A: "bad_captcha", ACC_B: "success"})
    seed_account(service._accounts, service._credentials, account_id=ACC_A)
    seed_account(service._accounts, service._credentials, account_id=ACC_B)

    service.begin_login(ACC_A)
    with pytest.raises(LoginRejectedError):
        service.complete_login(ACC_A, "bad")

    # A is back to a clean logged-out state.
    assert service._sessions.state(ACC_A) is SessionState.LOGGED_OUT
    assert service._sessions.get_token(ACC_A) is None
    assert service.is_logged_in(ACC_A) is False
    assert service.get_adapter(ACC_A) is None

    # B is completely unaffected (no session yet, so no state to check).
    assert service.is_logged_in(ACC_B) is False
    assert service.get_adapter(ACC_B) is None

    service.begin_login(ACC_B)
    session_b = service.complete_login(ACC_B, "1234")
    assert session_b.state is SessionState.LOGGED_IN
    assert service._sessions.get_token(ACC_B) == ACCESS_TOKEN
    assert service.get_adapter(ACC_B) is not None

def test_no_real_network_is_used():
    class NoNetwork(socket.socket):
        def __init__(self, *args, **kwargs):
            raise AssertionError("service must not open a socket")

    original = socket.socket
    socket.socket = NoNetwork
    try:
        service = make_service()
        seed_and_begin(service)
        service.complete_login(ACC_A, "1234")

        # Re-login requires logout first (SessionManager contract), and a
        # fresh pending attempt can then be cancelled without any network.
        service._sessions.logout(ACC_A)
        service.begin_login(ACC_A)
        service.cancel_login(ACC_A)

        with pytest.raises(NoPendingLoginError):
            service.cancel_login(ACC_A)
    finally:
        socket.socket = original


def test_service_does_not_modify_session_manager_contract():
    service = make_service()
    seed_and_begin(service)

    manager = service._sessions
    # The real SessionManager API is intact and used as-is.
    assert manager.state(ACC_A) is SessionState.LOGIN_PENDING
    assert manager.is_logged_in(ACC_A) is False

    service.complete_login(ACC_A, "1234")
    assert manager.state(ACC_A) is SessionState.LOGGED_IN
    assert manager.get_token(ACC_A) == ACCESS_TOKEN
