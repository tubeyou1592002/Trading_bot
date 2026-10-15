"""
test_block9_task5_401_nats_transport.py

Block 9 — Task 5, Stage 2C.3a: bounded HTTP 401 recovery for the two
Agah NATS bootstrap requests performed by ``AgahNatsTransport``:

  * ``GET /api/v1/pusher/nats``            (_fetch_connection_info)
  * ``GET /api/v1/Pusher/message-types``   (_fetch_message_types)

Both now flow through the broker's existing
``AgaahBroker._authed_get_with_recovery`` helper (Stage 2C.1) instead of
``session.get`` directly. These tests prove, fully offline:

  1. A real 401 invokes the installed handler and retries <= 1 time.
  2. The retry uses the refreshed token and keeps endpoint (and no params).
  3. A second 401 fails closed with no extra refresh or retry.
  4. Without an installed handler a 401 fails closed with no refresh.
  5. Other HTTP errors never trigger a refresh.
  6. A failed recovery leaks no password/access/refresh token through the
     public error, its repr, its exception chain, or the formatted traceback.
  7. HTTP in both paths still goes through ``asyncio.to_thread``.
  8. A successful response still extracts NATS connection info and the OMS
     message schema per the current contract.

No real Agah, no real NATS, no socket. A fake HTTP session is injected into
the real ``AgaahBroker`` and the real authentication stack (AccountStore /
CredentialStore / SessionManager / AuthenticationService with
AgahAuthenticationAdapter) is wired so the installed, account-scoped recovery
handler is the genuine one produced by login.

NOTE: ``brokers/agaah/nats_transport.py`` imports the ``nats`` package at
module scope. In an environment without ``nats-py`` installed this module
cannot be collected; that is an environment limitation, not a test failure.
"""
import asyncio
import traceback
from unittest.mock import patch

import pytest
import requests

from brokers.agaah import AgaahBroker
from brokers.agaah.auth_adapter import AgahAuthenticationAdapter
from brokers.agaah.nats_transport import AgahNatsTransport
from ui.account_store import AccountStore
from ui.authentication_service import (
    AuthenticationService,
    AuthenticationServiceError,
)
from ui.credential_store import CredentialStore
from ui.session_manager import SessionManager

BROKER_AGAH = "آگاه"
ACC_A = "ACC-401-NATS-A"
USERNAME = "agah-user"
PASSWORD = "agah-pass-SECRET"
CAPTCHA_TEXT = "1234"
CAPTCHA_IMAGE = "ZmFrZS1jYXB0Y2hh"
CAPTCHA_ID = "captcha-id-nats"

OLD_ACCESS = "OLD-ACCESS-TOKEN-NATS-111"
OLD_REFRESH = "OLD-REFRESH-TOKEN-NATS-222"
NEW_ACCESS = "NEW-ACCESS-TOKEN-NATS-333"
NEW_REFRESH = "NEW-REFRESH-TOKEN-NATS-444"
USER_ID = "user-id-nats"

CONN_PATH = "pusher/nats"
MSGTYPES_PATH = "Pusher/message-types"

NATS_URL = "npush101://npush101.agah.com:4222"
NATS_TOKEN = "nats-token-abc"
OMS_SUBJECT = "oms.state.changed.AGAH"
OMS_FIELDS = [
    "code",
    "action",
    "decisionId",
    "requestId",
    "currentTradeCount",
    "message",
    "channel",
    "nscId",
]

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
# Fake response / session
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeNatsSession:
    """
    Offline stand-in for the Agah ``requests.Session`` covering the
    authentication stack endpoints plus the two NATS bootstrap paths.
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

        self.force_401_on_paths = set()
        self.force_second_401 = set()
        self.force_500_on_paths = set()

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _path(url):
        return url.split("/api/v1/")[-1].lstrip("/")

    def conn_gets(self):
        return [
            c
            for c in self.calls
            if c["method"] == "get" and self._path(c["url"]) == CONN_PATH
        ]

    def msgtype_gets(self):
        return [
            c
            for c in self.calls
            if c["method"] == "get"
            and self._path(c["url"]) == MSGTYPES_PATH
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

        if path == CONN_PATH:
            if path in self.force_500_on_paths:
                return FakeResponse(payload=None, status_code=500)
            if path in self.force_401_on_paths and (
                path in self.force_second_401 or call_num == 1
            ):
                return FakeResponse(payload=None, status_code=401)
            return FakeResponse(
                {
                    "isSuccess": True,
                    "data": {
                        "urls": [NATS_URL],
                        "token": NATS_TOKEN,
                        "privateKey": "",
                    },
                }
            )

        if path == MSGTYPES_PATH:
            if path in self.force_500_on_paths:
                return FakeResponse(payload=None, status_code=500)
            if path in self.force_401_on_paths and (
                path in self.force_second_401 or call_num == 1
            ):
                return FakeResponse(payload=None, status_code=401)
            return FakeResponse(
                {
                    "isSuccess": True,
                    "data": {
                        "groups": [
                            {
                                "code": 100,
                                "groupNames": [OMS_SUBJECT],
                                "schema": list(OMS_FIELDS),
                            }
                        ]
                    },
                }
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
        return FakeResponse(
            {
                "isSuccess": True,
                "data": {
                    "accessToken": self._new_access,
                    "refreshToken": self._new_refresh,
                },
            }
        )


class _StaticDeviceInfo:
    def get(self):
        return {"clientId": "offline", "platform": "web"}


# ---------------------------------------------------------------------------
# System setup
# ---------------------------------------------------------------------------

def build_nats_system():
    """
    Build the real authentication stack with a fake HTTP session and return
    the created broker/session so tests can drive 401 scenarios.
    """
    accounts = AccountStore()
    credentials = CredentialStore(backend=StubBackend())
    sessions = SessionManager()
    created = {}
    current = {"account_id": None}

    def adapter_factory():
        acc = current["account_id"]
        broker = AgaahBroker()
        broker.session = FakeNatsSession()
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
    credentials.save_credentials(ACC_A, BROKER_AGAH, USERNAME, PASSWORD)

    return {
        "service": service,
        "sessions": sessions,
        "created": created,
    }


def login_fully(system):
    system["service"].begin_login(ACC_A)
    system["service"].complete_login(ACC_A, CAPTCHA_TEXT)


def make_transport(broker):
    return AgahNatsTransport(broker)


def _run(coro):
    return asyncio.run(coro)


def _traceback_text(exc):
    return "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )


# ---------------------------------------------------------------------------
# Request 1: GET pusher/nats  (_fetch_connection_info)
# ---------------------------------------------------------------------------

def test_connection_info_401_triggers_handler_and_retries_once():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(CONN_PATH)

    transport = make_transport(broker)

    async def run():
        await transport._fetch_connection_info()

    _run(run())

    assert broker.access_token == NEW_ACCESS
    assert len(sess.refresh_calls()) == 1
    assert len(sess.conn_gets()) == 2
    assert transport._connection_info.urls == [NATS_URL]
    assert transport._connection_info.token == NATS_TOKEN


def test_connection_info_retry_uses_refreshed_token_and_endpoint():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(CONN_PATH)

    transport = make_transport(broker)

    async def run():
        await transport._fetch_connection_info()

    _run(run())

    conn_calls = sess.conn_gets()
    assert len(conn_calls) == 2

    first, retry = conn_calls
    assert first["url"].endswith(CONN_PATH)
    assert retry["url"].endswith(CONN_PATH)
    assert retry["url"] == first["url"]

    assert first["params"] is None
    assert retry["params"] is None

    assert first["timeout"] == 10
    assert retry["timeout"] == 10

    assert first["headers"]["Authorization"] == f"Bearer {OLD_ACCESS}"
    assert retry["headers"]["Authorization"] == f"Bearer {NEW_ACCESS}"
    assert (
        retry["headers"]["UserIdentifier"]
        == first["headers"]["UserIdentifier"]
    )


def test_connection_info_second_401_fails_closed():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(CONN_PATH)
    sess.force_second_401.add(CONN_PATH)

    transport = make_transport(broker)

    async def run():
        await transport._fetch_connection_info()

    with pytest.raises(requests.HTTPError):
        _run(run())

    assert len(sess.refresh_calls()) == 1
    assert len(sess.conn_gets()) == 2


def test_connection_info_no_handler_fails_closed_without_refresh():
    broker = AgaahBroker()
    sess = FakeNatsSession()
    broker.session = sess
    broker.access_token = OLD_ACCESS
    broker.refresh_token = OLD_REFRESH
    broker.user_identifier = USER_ID
    # No recovery handler installed on this broker.
    sess.force_401_on_paths.add(CONN_PATH)

    transport = make_transport(broker)

    async def run():
        await transport._fetch_connection_info()

    with pytest.raises(requests.HTTPError):
        _run(run())

    assert len(sess.refresh_calls()) == 0
    assert len(sess.conn_gets()) == 1
    assert broker.access_token == OLD_ACCESS


def test_connection_info_non_401_http_error_does_not_refresh():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    old_token = broker.access_token
    sess.force_500_on_paths.add(CONN_PATH)

    transport = make_transport(broker)

    async def run():
        await transport._fetch_connection_info()

    with pytest.raises(requests.HTTPError):
        _run(run())

    assert len(sess.refresh_calls()) == 0
    assert len(sess.conn_gets()) == 1
    assert broker.access_token == old_token


# ---------------------------------------------------------------------------
# Request 2: GET Pusher/message-types  (_fetch_message_types)
# ---------------------------------------------------------------------------

def test_message_types_401_triggers_handler_and_retries_once():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(MSGTYPES_PATH)

    transport = make_transport(broker)

    async def run():
        await transport._fetch_message_types()

    _run(run())

    assert broker.access_token == NEW_ACCESS
    assert len(sess.refresh_calls()) == 1
    assert len(sess.msgtype_gets()) == 2
    assert transport._oms_schema.group_names == [OMS_SUBJECT]
    assert transport._decoder.field_names == OMS_FIELDS


def test_message_types_retry_uses_refreshed_token_and_endpoint():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(MSGTYPES_PATH)

    transport = make_transport(broker)

    async def run():
        await transport._fetch_message_types()

    _run(run())

    msg_calls = sess.msgtype_gets()
    assert len(msg_calls) == 2

    first, retry = msg_calls
    assert first["url"].endswith(MSGTYPES_PATH)
    assert retry["url"] == first["url"]
    assert first["params"] is None
    assert retry["params"] is None
    assert first["timeout"] == 10
    assert retry["timeout"] == 10
    assert first["headers"]["Authorization"] == f"Bearer {OLD_ACCESS}"
    assert retry["headers"]["Authorization"] == f"Bearer {NEW_ACCESS}"


def test_message_types_second_401_fails_closed():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(MSGTYPES_PATH)
    sess.force_second_401.add(MSGTYPES_PATH)

    transport = make_transport(broker)

    async def run():
        await transport._fetch_message_types()

    with pytest.raises(requests.HTTPError):
        _run(run())

    assert len(sess.refresh_calls()) == 1
    assert len(sess.msgtype_gets()) == 2


def test_message_types_no_handler_fails_closed_without_refresh():
    broker = AgaahBroker()
    sess = FakeNatsSession()
    broker.session = sess
    broker.access_token = OLD_ACCESS
    broker.refresh_token = OLD_REFRESH
    broker.user_identifier = USER_ID
    sess.force_401_on_paths.add(MSGTYPES_PATH)

    transport = make_transport(broker)

    async def run():
        await transport._fetch_message_types()

    with pytest.raises(requests.HTTPError):
        _run(run())

    assert len(sess.refresh_calls()) == 0
    assert len(sess.msgtype_gets()) == 1
    assert broker.access_token == OLD_ACCESS


def test_message_types_non_401_http_error_does_not_refresh():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    old_token = broker.access_token
    sess.force_500_on_paths.add(MSGTYPES_PATH)

    transport = make_transport(broker)

    async def run():
        await transport._fetch_message_types()

    with pytest.raises(requests.HTTPError):
        _run(run())

    assert len(sess.refresh_calls()) == 0
    assert len(sess.msgtype_gets()) == 1
    assert broker.access_token == old_token


# ---------------------------------------------------------------------------
# Secret-leak check on failed recovery
# ---------------------------------------------------------------------------

def test_recovery_failure_leaks_no_secrets():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]
    sess.force_401_on_paths.add(CONN_PATH)
    sess.refresh_outcome = "http_error"

    transport = make_transport(broker)

    async def run():
        await transport._fetch_connection_info()

    with pytest.raises(AuthenticationServiceError) as excinfo:
        _run(run())

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
                f"secret leaked through NATS error surface: {surface!r}"
            )

    # One refresh attempt was made, the retry never happened.
    assert len(sess.refresh_calls()) == 1
    assert len(sess.conn_gets()) == 1


# ---------------------------------------------------------------------------
# Thread boundary: both fetches must run HTTP via asyncio.to_thread
# ---------------------------------------------------------------------------

def test_both_fetches_run_http_via_asyncio_to_thread():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]

    transport = make_transport(broker)

    seen = []
    real_to_thread = asyncio.to_thread

    async def spy(func, /, *args, **kwargs):
        seen.append(func)
        return await real_to_thread(func, *args, **kwargs)

    async def run():
        await transport._fetch_connection_info()
        await transport._fetch_message_types()

    with patch("asyncio.to_thread", spy):
        _run(run())

    assert len(seen) == 2
    assert all(
        getattr(f, "__name__", None) == "_authed_get_with_recovery"
        for f in seen
    )
    # No direct session.get was issued on the event-loop thread itself.
    assert len(sess.conn_gets()) == 1
    assert len(sess.msgtype_gets()) == 1


# ---------------------------------------------------------------------------
# Successful path still extracts the current contract
# ---------------------------------------------------------------------------

def test_success_extracts_connection_info():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]

    transport = make_transport(broker)

    async def run():
        await transport._fetch_connection_info()

    _run(run())

    assert transport._connection_info.urls == [NATS_URL]
    assert transport._connection_info.token == NATS_TOKEN
    assert transport._connection_info.private_key == ""
    assert len(sess.conn_gets()) == 1
    assert len(sess.refresh_calls()) == 0


def test_success_extracts_message_schema():
    system = build_nats_system()
    login_fully(system)
    parts = system["created"][ACC_A]
    broker, sess = parts["broker"], parts["session"]

    transport = make_transport(broker)

    async def run():
        await transport._fetch_message_types()

    _run(run())

    assert transport._oms_schema.code == 100
    assert transport._oms_schema.group_names == [OMS_SUBJECT]
    assert transport._decoder.field_names == OMS_FIELDS
    assert len(sess.msgtype_gets()) == 1
    assert len(sess.refresh_calls()) == 0
