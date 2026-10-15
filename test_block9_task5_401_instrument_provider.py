"""
test_block9_task5_401_instrument_provider.py

Block 9 — Task 5, Stage 2C.2: bounded HTTP 401 recovery for the
authenticated Agah search request performed by
``AgaahInstrumentProvider._search_candidates``.

Everything is fully offline. No real Agah, no real TSETMC, no
socket. A fake HTTP session is injected into the real ``AgaahBroker``
and the real authentication stack (AccountStore / CredentialStore /
SessionManager / AuthenticationService with AgahAuthenticationAdapter)
is wired so the installed, account-scoped recovery handler is the
genuine one produced by login.

The provider's search now flows through the broker's
``_authed_get_with_recovery`` helper (Stage 2C.1). These tests prove:

  1. A real 401 invokes the installed handler and retries <= 1 time.
  2. The retry uses the refreshed token and keeps endpoint + params.
  3. A second 401 fails closed with no extra refresh or retry.
  4. Without an installed handler a 401 fails closed with no refresh.
  5. Other HTTP errors never trigger a refresh.
  6. A failed recovery leaks no access/refresh token through the
     public error, its repr, its exception chain, or the formatted
     traceback.
  7. A failed recovery does not poison the provider cache.
  8. The exact ``tse_id == ins_code`` mapping is preserved, and
     successful lookups still never hit the network.
"""
import socket
import traceback

import pytest

from brokers.agaah import AgaahBroker, AgaahInstrumentProvider
from brokers.agaah.auth_adapter import AgahAuthenticationAdapter
from brokers.agaah.instrument_provider import InstrumentLookupError
from models.instrument import Instrument
from ui.account_store import AccountStore
from ui.authentication_service import AuthenticationService
from ui.credential_store import CredentialStore
from ui.session_manager import SessionManager

BROKER_AGAH = "آگاه"
ACC_A = "ACC-401-IP-A"
USERNAME = "agah-user"
PASSWORD = "agah-pass-SECRET"
CAPTCHA_TEXT = "1234"
CAPTCHA_IMAGE = "ZmFrZS1jYXB0Y2hh"
CAPTCHA_ID = "captcha-id-ip"

OLD_ACCESS = "OLD-ACCESS-TOKEN-IP-111"
OLD_REFRESH = "OLD-REFRESH-TOKEN-IP-222"
NEW_ACCESS = "NEW-ACCESS-TOKEN-IP-333"
NEW_REFRESH = "NEW-REFRESH-TOKEN-IP-444"
USER_ID = "user-id-ip"

INS_CODE = "35366681030756042"
SYMBOL = "شبندر"
SEARCH_PATH = "instruments/all"
SEARCH_COUNT = 50

SECRET_VALUES = (
    OLD_ACCESS,
    OLD_REFRESH,
    NEW_ACCESS,
    NEW_REFRESH,
    PASSWORD,
)


# ---------------------------------------------------------------------------
# In-memory credential backend
# ---------------------------------------------------------------------------

class StubBackend:
    def __init__(self):
        self.entries = {}

    def set_password(self, service, account, password):
        self.entries[(service, account)] = password

    def get_password(self, service, account):
        return self.entries.get((service, account))

    def delete_password(self, service, account):
        del self.entries[(service, account)]


# ---------------------------------------------------------------------------
# Fake response
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


# ---------------------------------------------------------------------------
# Fake Agah session (provider-oriented)
# ---------------------------------------------------------------------------

class FakeProviderSession:
    """
    Offline stand-in for the Agah ``requests.Session``.

    Handles the captcha/authenticate/refresh-token endpoints used by the
    authentication stack plus the two read paths the provider relies on:
    ``instruments/all`` (search) and ``instruments`` (verification).
    """

    def __init__(self):
        self.calls = []
        self._get_counts = {}

        self._access = OLD_ACCESS
        self._refresh = OLD_REFRESH
        self._uid = USER_ID
        self._new_access = NEW_ACCESS
        self._new_refresh = NEW_REFRESH
        self.refresh_outcome = "success"

        self.search_candidates = [
            {"nscId": "IRO1PNBA0001", "name": "right"},
        ]
        self.instrument_by_nsc = {
            "IRO1PNBA0001": {
                "nscId": "IRO1PNBA0001",
                "tseId": INS_CODE,
                "name": SYMBOL,
                "companyName": "پالایش نفت بندرعباس",
            },
        }

        self.force_401_on_paths = set()
        self.force_second_401 = set()
        self.force_500_on_paths = set()

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _path(url):
        return url.split("/api/v1/")[-1].lstrip("/")

    def search_gets(self):
        return [
            c
            for c in self.calls
            if c["method"] == "get"
            and self._path(c["url"]) == SEARCH_PATH
        ]

    def refresh_calls(self):
        return [
            c
            for c in self.calls
            if c["method"] == "post" and "refresh-token" in c["url"]
        ]

    # -- HTTP verbs -------------------------------------------------------

    def get(self, url, **kwargs):
        self.calls.append({"method": "get", "url": url, **kwargs})
        path = self._path(url)
        self._get_counts[path] = self._get_counts.get(path, 0) + 1
        call_num = self._get_counts[path]

        if "captcha" in path:
            return FakeResponse(
                {
                    "isSuccess": True,
                    "data": {
                        "captchaId": CAPTCHA_ID,
                        "captcha": CAPTCHA_IMAGE,
                    },
                }
            )

        if path == SEARCH_PATH:
            if path in self.force_500_on_paths:
                return FakeResponse(payload=None, status_code=500)
            if path in self.force_401_on_paths and (
                path in self.force_second_401 or call_num == 1
            ):
                return FakeResponse(payload=None, status_code=401)
            return FakeResponse(
                {
                    "isSuccess": True,
                    "data": list(self.search_candidates),
                }
            )

        if path == "instruments":
            nsc_id = (kwargs.get("params") or {}).get("nscIds")
            item = self.instrument_by_nsc.get(nsc_id)
            if item is None:
                return FakeResponse(
                    {"isSuccess": True, "data": []}
                )
            return FakeResponse(
                {"isSuccess": True, "data": [dict(item)]}
            )

        return FakeResponse({"isSuccess": True, "data": {}})

    def post(self, url, **kwargs):
        self.calls.append({"method": "post", "url": url, **kwargs})
        if "refresh-token" in url:
            return self._refresh_response()
        body = kwargs.get("json") or {}
        return FakeResponse(
            {
                "isSuccess": True,
                "data": {
                    "accessToken": self._access,
                    "refreshToken": self._refresh,
                    "userIdentifier": self._uid,
                    "userName": body.get("userName"),
                },
            }
        )

    def _refresh_response(self):
        if self.refresh_outcome == "http_error":
            return FakeResponse(payload={}, status_code=500)
        if self.refresh_outcome == "malformed":
            return FakeResponse(
                {"isSuccess": True, "data": None}
            )
        return FakeResponse(
            {
                "isSuccess": True,
                "data": {
                    "accessToken": self._new_access,
                    "refreshToken": self._new_refresh,
                },
            }
        )


# ---------------------------------------------------------------------------
# Fake TSETMC + device info
# ---------------------------------------------------------------------------

class FakeTSETMC:
    def __init__(self, instrument=None, error=None):
        self._instrument = instrument
        self._error = error
        self.get_info_calls = []

    def get_info(self, ins_code):
        self.get_info_calls.append(ins_code)
        if self._error is not None:
            raise self._error
        return self._instrument


class _StaticDeviceInfo:
    def get(self):
        return {"clientId": "offline", "platform": "web"}


def _tsetmc_instrument():
    return Instrument(
        symbol=SYMBOL,
        name="پالایش نفت بندرعباس",
        ins_code=INS_CODE,
    )


# ---------------------------------------------------------------------------
# System setup
# ---------------------------------------------------------------------------

def build_provider_system():
    """
    Build the real authentication stack with a fake HTTP session and
    return the created broker/session so tests can drive 401 scenarios.
    """
    accounts = AccountStore()
    credentials = CredentialStore(backend=StubBackend())
    sessions = SessionManager()
    created = {}
    current = {"account_id": None}

    def adapter_factory():
        acc = current["account_id"]
        broker = AgaahBroker()
        broker.session = FakeProviderSession()
        broker.device_info_provider = _StaticDeviceInfo()
        adapter = AgahAuthenticationAdapter(broker=broker)
        created[acc] = {
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
    original_begin = service.begin_login

    def begin_login(acc):
        current["account_id"] = acc
        return original_begin(acc)

    service.begin_login = begin_login

    accounts.add(ACC_A, BROKER_AGAH, f"حساب {ACC_A}")
    credentials.save_credentials(
        ACC_A, BROKER_AGAH, USERNAME, PASSWORD
    )

    return {
        "service": service,
        "sessions": sessions,
        "created": created,
    }


def login_fully(system):
    service = system["service"]
    service.begin_login(ACC_A)
    return service.complete_login(ACC_A, CAPTCHA_TEXT)


def make_provider(broker):
    return AgaahInstrumentProvider(
        broker,
        FakeTSETMC(instrument=_tsetmc_instrument()),
    )


def _traceback_text(exc):
    return "".join(
        traceback.format_exception(
            type(exc), exc, exc.__traceback__
        )
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_real_401_triggers_handler_and_retries_once():
    system = build_provider_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(SEARCH_PATH)

    provider = make_provider(broker)
    assert provider.get_nsc_id(INS_CODE) == "IRO1PNBA0001"

    assert broker.access_token == NEW_ACCESS
    assert len(sess.refresh_calls()) == 1
    assert len(sess.search_gets()) == 2


def test_retry_uses_refreshed_token_and_retains_endpoint_and_params():
    system = build_provider_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(SEARCH_PATH)

    provider = make_provider(broker)
    provider.get_nsc_id(INS_CODE)

    search_calls = sess.search_gets()
    assert len(search_calls) == 2

    first, retry = search_calls
    assert first["url"].endswith(SEARCH_PATH)
    assert retry["url"].endswith(SEARCH_PATH)
    assert retry["url"] == first["url"]

    assert first["params"] == {
        "query": SYMBOL,
        "count": SEARCH_COUNT,
    }
    assert retry["params"] == first["params"]

    assert (
        retry["headers"]["Authorization"]
        == f"Bearer {NEW_ACCESS}"
    )
    assert (
        first["headers"]["Authorization"]
        == f"Bearer {OLD_ACCESS}"
    )
    assert (
        retry["headers"]["UserIdentifier"]
        == first["headers"]["UserIdentifier"]
    )


def test_second_401_fails_closed_no_extra_refresh():
    system = build_provider_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(SEARCH_PATH)
    sess.force_second_401.add(SEARCH_PATH)

    provider = make_provider(broker)

    with pytest.raises(InstrumentLookupError):
        provider.get_nsc_id(INS_CODE)

    assert len(sess.refresh_calls()) == 1
    assert len(sess.search_gets()) == 2


def test_no_handler_fails_closed_without_refresh():
    broker = AgaahBroker()
    sess = FakeProviderSession()
    broker.session = sess
    broker.access_token = OLD_ACCESS
    broker.refresh_token = OLD_REFRESH
    broker.user_identifier = USER_ID
    # No recovery handler installed.
    sess.force_401_on_paths.add(SEARCH_PATH)

    provider = make_provider(broker)

    with pytest.raises(InstrumentLookupError):
        provider.get_nsc_id(INS_CODE)

    assert len(sess.refresh_calls()) == 0
    assert len(sess.search_gets()) == 1
    assert broker.access_token == OLD_ACCESS


def test_non_401_http_error_does_not_refresh():
    system = build_provider_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    old_token = broker.access_token
    sess.force_500_on_paths.add(SEARCH_PATH)

    provider = make_provider(broker)

    with pytest.raises(InstrumentLookupError) as excinfo:
        provider.get_nsc_id(INS_CODE)

    assert len(sess.refresh_calls()) == 0
    assert len(sess.search_gets()) == 1
    assert broker.access_token == old_token

    import requests

    assert isinstance(
        excinfo.value.__cause__, requests.RequestException
    )


def test_recovery_failure_leaks_no_tokens():
    system = build_provider_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(SEARCH_PATH)
    sess.refresh_outcome = "http_error"

    provider = make_provider(broker)

    with pytest.raises(InstrumentLookupError) as excinfo:
        provider.get_nsc_id(INS_CODE)

    exc = excinfo.value
    surfaces = [str(exc), repr(exc), _traceback_text(exc)]

    chain = []
    cursor = exc
    while cursor is not None:
        chain.append(cursor)
        cursor = cursor.__cause__ or cursor.__context__
    for link in chain:
        surfaces.append(str(link))
        surfaces.append(repr(link))

    for surface in surfaces:
        for secret in SECRET_VALUES:
            assert secret not in surface, (
                f"secret leaked through provider error surface: "
                f"{surface!r}"
            )

    # One refresh attempt was made, the retry never happened.
    assert len(sess.refresh_calls()) == 1
    assert len(sess.search_gets()) == 1


def test_failed_recovery_does_not_poison_cache():
    system = build_provider_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(SEARCH_PATH)
    sess.refresh_outcome = "http_error"

    provider = make_provider(broker)

    with pytest.raises(InstrumentLookupError):
        provider.get_nsc_id(INS_CODE)

    assert INS_CODE not in provider._cache
    assert INS_CODE not in provider._nsc_cache

    # The failed attempt must not be remembered as a success: a second
    # call (still unauthenticated) must fail again, not return a value.
    with pytest.raises(InstrumentLookupError):
        provider.get_nsc_id(INS_CODE)

    # Restore a usable authenticated view on the SAME broker and prove a
    # subsequent lookup performs a fresh search and succeeds, i.e. the
    # earlier failure was never cached.
    sess.force_401_on_paths.discard(SEARCH_PATH)
    sess.refresh_outcome = "success"
    broker.access_token = OLD_ACCESS
    broker.refresh_token = OLD_REFRESH
    broker.user_identifier = USER_ID

    assert provider.get_nsc_id(INS_CODE) == "IRO1PNBA0001"
    assert INS_CODE in provider._nsc_cache


def test_exact_mapping_preserved_and_offline():
    system = build_provider_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]

    # The matching candidate is not first.
    sess.search_candidates = [
        {"nscId": "IRO1PNBA0003", "name": "wrong one"},
        {"nscId": "IRO1PNBA0001", "name": "right one"},
        {"nscId": "IRO1PNBA0007", "name": "another wrong"},
    ]
    sess.instrument_by_nsc = {
        "IRO1PNBA0003": {
            "nscId": "IRO1PNBA0003",
            "tseId": "39549984459336635",
        },
        "IRO1PNBA0001": {
            "nscId": "IRO1PNBA0001",
            "tseId": INS_CODE,
        },
        "IRO1PNBA0007": {
            "nscId": "IRO1PNBA0007",
            "tseId": "11111111111111111",
        },
    }

    # No socket may be created during a fully offline lookup.
    def _no_socket(*args, **kwargs):
        raise AssertionError("provider attempted real network I/O")

    original_socket = socket.socket
    socket.socket = _no_socket
    try:
        provider = make_provider(broker)
        assert provider.get_nsc_id(INS_CODE) == "IRO1PNBA0001"
        assert len(sess.refresh_calls()) == 0
    finally:
        socket.socket = original_socket
