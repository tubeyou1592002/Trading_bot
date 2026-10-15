"""
test_block9_task5_401_queue_position.py

Block 9 — Task 5, Stage 2C.3b: bounded HTTP 401 recovery for the Agah
queue-position request performed by ``AgahQueuePositionService``:

  * ``GET /api/v1/order/getorderposition``   (get_queue_position)

It now flows through the broker's existing
``AgaahBroker._authed_get_with_recovery`` helper (Stage 2C.1) instead of
``session.get`` directly. These tests prove, fully offline:

  1. A real 401 invokes the installed handler and retries <= 1 time, and the
     retry succeeds with the refreshed token.
  2. The retry keeps the URL and all three params and uses the NEW
     Authorization header.
  3. A second 401 fails closed with no extra refresh/retry; result is None.
  4. Without an installed handler a 401 fails closed with no refresh; the
     result is None and the token is unchanged.
  5. A non-401 HTTP error (500) never triggers a refresh; result is None.
  6. A failed recovery leaks no password/access/refresh token through the
     logs or any observable output.
  7. The success / invalid-position / missing-position / incomplete-input
     contract is unchanged.
  8. At most one retry per operation and no order POST is ever issued.

No real Agah, no real NATS, no socket. A fake HTTP session is injected into
the real ``AgaahBroker`` and the real authentication stack (AccountStore /
CredentialStore / SessionManager / AuthenticationService with
AgahAuthenticationAdapter) is wired so the installed, account-scoped recovery
handler is the genuine one produced by login.

NOTE: ``brokers/agaah/nats_transport.py`` imports the ``nats`` package at
module scope. In an environment without ``nats-py`` installed this module
cannot be collected; that is an environment limitation, not a test failure.
"""
import logging
import traceback

import requests

from brokers.agaah import AgaahBroker
from brokers.agaah.auth_adapter import AgahAuthenticationAdapter
from brokers.agaah.nats_transport import AgahQueuePositionService
from ui.account_store import AccountStore
from ui.authentication_service import AuthenticationService
from ui.credential_store import CredentialStore
from ui.session_manager import SessionManager

BROKER_AGAH = "آگاه"
ACC_A = "ACC-401-QP-A"
USERNAME = "agah-user"
PASSWORD = "agah-pass-SECRET"
CAPTCHA_TEXT = "1234"
CAPTCHA_IMAGE = "ZmFrZS1jYXB0Y2hh"
CAPTCHA_ID = "captcha-id-qp"

OLD_ACCESS = "OLD-ACCESS-TOKEN-QP-111"
OLD_REFRESH = "OLD-REFRESH-TOKEN-QP-222"
NEW_ACCESS = "NEW-ACCESS-TOKEN-QP-333"
NEW_REFRESH = "NEW-REFRESH-TOKEN-QP-444"
USER_ID = "user-id-qp"

QP_PATH = "order/getorderposition"

NSC_ID = "NSC-1"
HOST_ORDER_NUMBER = "12345"
ORDER_DATE = "2026-09-26T10:00:00Z"
SUCCESS_POSITION = 7

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


class FakeQpSession:
    """
    Offline stand-in for the Agah ``requests.Session`` covering the
    authentication stack endpoints plus the queue-position read path.
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

        self.success_position = SUCCESS_POSITION
        # When set, this exact payload is returned for the queue-position
        # endpoint (used to exercise invalid/missing-position contracts).
        self.qp_override_payload = None

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _path(url):
        return url.split("/api/v1/")[-1].lstrip("/")

    def qp_gets(self):
        return [
            c
            for c in self.calls
            if c["method"] == "get" and self._path(c["url"]) == QP_PATH
        ]

    def refresh_calls(self):
        return [
            c
            for c in self.calls
            if c["method"] == "post" and "refresh-token" in c["url"]
        ]

    def order_posts(self):
        """Any POST that is not authentication/refresh — must always be empty."""
        return [
            c
            for c in self.calls
            if c["method"] == "post"
            and "refresh-token" not in c["url"]
            and "authenticate" not in c["url"]
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

        if path == QP_PATH:
            if path in self.force_500_on_paths:
                return FakeResponse(payload=None, status_code=500)
            if path in self.force_401_on_paths and (
                path in self.force_second_401 or call_num == 1
            ):
                return FakeResponse(payload=None, status_code=401)
            if self.qp_override_payload is not None:
                return FakeResponse(self.qp_override_payload)
            return FakeResponse(
                {
                    "isSuccess": True,
                    "data": {"position": self.success_position},
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

def build_qp_system():
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
        broker.session = FakeQpSession()
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

    return service, created


def login_fully(service):
    service.begin_login(ACC_A)
    service.complete_login(ACC_A, CAPTCHA_TEXT)


def make_service(broker):
    return AgahQueuePositionService(broker)


def call_position(service):
    return service.get_queue_position(
        NSC_ID, HOST_ORDER_NUMBER, ORDER_DATE
    )


def _traceback_text(exc):
    return "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )


# ---------------------------------------------------------------------------
# 1-2) 401 recovery succeeds and keeps URL + params with the new token
# ---------------------------------------------------------------------------

def test_401_triggers_handler_and_retries_once_with_new_token():
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]
    sess.force_401_on_paths.add(QP_PATH)

    result = call_position(make_service(broker))

    assert result == SUCCESS_POSITION
    assert broker.access_token == NEW_ACCESS
    assert len(sess.refresh_calls()) == 1
    assert len(sess.qp_gets()) == 2


def test_retry_preserves_url_and_params_and_uses_new_header():
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]
    sess.force_401_on_paths.add(QP_PATH)

    call_position(make_service(broker))

    qp_calls = sess.qp_gets()
    assert len(qp_calls) == 2

    first, retry = qp_calls
    assert first["url"].endswith(QP_PATH)
    assert retry["url"] == first["url"]

    expected_params = {
        "nscId": NSC_ID,
        "hostOrderNumber": HOST_ORDER_NUMBER,
        "orderDate": ORDER_DATE,
    }
    assert first["params"] == expected_params
    assert retry["params"] == expected_params

    assert first["timeout"] == 10
    assert retry["timeout"] == 10

    assert first["headers"]["Authorization"] == f"Bearer {OLD_ACCESS}"
    assert retry["headers"]["Authorization"] == f"Bearer {NEW_ACCESS}"
    assert (
        retry["headers"]["UserIdentifier"]
        == first["headers"]["UserIdentifier"]
    )


# ---------------------------------------------------------------------------
# 3) A second 401 fails closed (None, no extra refresh/retry)
# ---------------------------------------------------------------------------

def test_second_401_returns_none_without_extra_retry():
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]
    sess.force_401_on_paths.add(QP_PATH)
    sess.force_second_401.add(QP_PATH)

    result = call_position(make_service(broker))

    assert result is None
    assert len(sess.refresh_calls()) == 1
    assert len(sess.qp_gets()) == 2


# ---------------------------------------------------------------------------
# 4) No handler -> fail closed (None, no refresh)
# ---------------------------------------------------------------------------

def test_no_handler_returns_none_without_refresh():
    broker = AgaahBroker()
    sess = FakeQpSession()
    broker.session = sess
    broker.access_token = OLD_ACCESS
    broker.refresh_token = OLD_REFRESH
    broker.user_identifier = USER_ID
    # No recovery handler installed on this broker.
    sess.force_401_on_paths.add(QP_PATH)

    result = call_position(make_service(broker))

    assert result is None
    assert len(sess.refresh_calls()) == 0
    assert len(sess.qp_gets()) == 1
    assert broker.access_token == OLD_ACCESS


# ---------------------------------------------------------------------------
# 5) Non-401 HTTP error -> no refresh, contract stays None
# ---------------------------------------------------------------------------

def test_non_401_http_error_returns_none_without_refresh():
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]
    old_token = broker.access_token
    sess.force_500_on_paths.add(QP_PATH)

    result = call_position(make_service(broker))

    assert result is None
    assert len(sess.refresh_calls()) == 0
    assert len(sess.qp_gets()) == 1
    assert broker.access_token == old_token


# ---------------------------------------------------------------------------
# 6) Failed recovery leaks no secrets (logs + observable outputs)
# ---------------------------------------------------------------------------

def test_recovery_failure_leaks_no_secrets(caplog):
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]
    sess.force_401_on_paths.add(QP_PATH)
    sess.refresh_outcome = "http_error"

    # Wrap the REAL installed handler to record any exception it raises,
    # then delegate to it unchanged (no test authentication logic is built).
    real_handler = broker._unauthorized_recovery
    recorded = []

    def recording_handler():
        try:
            real_handler()
        except Exception as exc:  # noqa: BLE001 - recorded for leak check
            recorded.append(exc)
            raise

    broker.set_unauthorized_recovery(recording_handler)

    with caplog.at_level(logging.DEBUG):
        result = call_position(make_service(broker))

    assert result is None
    assert len(sess.refresh_calls()) == 1
    assert len(sess.qp_gets()) == 1

    surfaces = [rec.getMessage() for rec in caplog.records]

    for exc in recorded:
        surfaces.append(str(exc))
        surfaces.append(repr(exc))
        surfaces.append(_traceback_text(exc))
        cursor = exc
        while cursor is not None:
            surfaces.append(str(cursor))
            surfaces.append(repr(cursor))
            cursor = cursor.__cause__ or cursor.__context__

    for surface in surfaces:
        for secret in SECRET_VALUES:
            assert secret not in surface, (
                f"secret leaked through queue-position surface: {surface!r}"
            )


# ---------------------------------------------------------------------------
# 7) Success / invalid / missing / incomplete-input contract is preserved
# ---------------------------------------------------------------------------

def test_success_returns_int_position():
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]

    result = call_position(make_service(broker))

    assert result == SUCCESS_POSITION
    assert isinstance(result, int)
    assert len(sess.qp_gets()) == 1
    assert len(sess.refresh_calls()) == 0


def test_is_success_false_returns_none():
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]
    sess.qp_override_payload = {"isSuccess": False, "message": "error"}

    result = call_position(make_service(broker))

    assert result is None


def test_missing_position_returns_none():
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]
    sess.qp_override_payload = {"isSuccess": True, "data": {}}

    assert call_position(make_service(broker)) is None

    sess.qp_override_payload = {
        "isSuccess": True,
        "data": {"position": None},
    }
    assert call_position(make_service(broker)) is None


def test_invalid_position_type_returns_none():
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]

    for invalid in ("invalid", True, False, [1]):
        sess.qp_override_payload = {
            "isSuccess": True,
            "data": {"position": invalid},
        }
        assert call_position(make_service(broker)) is None


def test_incomplete_input_returns_none_without_http():
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]
    svc = make_service(broker)

    assert svc.get_queue_position("", HOST_ORDER_NUMBER, ORDER_DATE) is None
    assert svc.get_queue_position(NSC_ID, "", ORDER_DATE) is None
    assert svc.get_queue_position(NSC_ID, HOST_ORDER_NUMBER, "") is None
    assert svc.get_queue_position(None, HOST_ORDER_NUMBER, ORDER_DATE) is None

    assert len(sess.qp_gets()) == 0
    assert len(sess.refresh_calls()) == 0


def test_float_position_is_truncated_to_int():
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]
    sess.qp_override_payload = {
        "isSuccess": True,
        "data": {"position": 3.9},
    }

    result = call_position(make_service(broker))

    assert result == 3
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# 8) At most one retry; no order POST is ever issued
# ---------------------------------------------------------------------------

def test_at_most_one_retry_and_no_order_post():
    service, created = build_qp_system()
    login_fully(service)
    broker, sess = created[ACC_A]["broker"], created[ACC_A]["session"]
    sess.force_401_on_paths.add(QP_PATH)
    sess.force_second_401.add(QP_PATH)

    call_position(make_service(broker))

    qp_calls = sess.qp_gets()
    # Exactly the original request plus one retry — never more.
    assert len(qp_calls) == 2
    assert len(sess.refresh_calls()) == 1

    # No order-registration (POST /order) request is ever made or repeated.
    assert sess.order_posts() == []
