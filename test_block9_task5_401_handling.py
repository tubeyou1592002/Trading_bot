"""
test_block9_task5_401_handling.py

Block 9 — Task 5, Stage 2C.1: bounded HTTP 401 recovery for four
authenticated read-only GET paths in brokers/agaah/broker.py.

Everything is fully offline. The tests inject a fake HTTP session
into the real AgaahBroker and wire the real authentication stack
(AccountStore/CredentialStore/SessionManager/AuthenticationService
with AgahAuthenticationAdapter) so the 401 recovery path exercises
the broker-independent hook (adapter + service + SessionManager sync).
"""
import socket
import threading
from typing import List, Tuple

import pytest
import requests

from brokers.agaah import AgaahBroker
from brokers.agaah.auth_adapter import AgahAuthenticationAdapter
from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge
from models.order import BUY, Order
from ui.account_store import AccountStore
from ui.authentication_service import AuthenticationService
from ui.credential_store import CredentialStore
from ui.session_manager import SessionManager, SessionState

BROKER_AGAH = "آگاه"
ACC_A = "ACC-401-A"
ACC_B = "ACC-401-B"
USERNAME = "agah-user"
PASSWORD = "agah-pass-SECRET"
CAPTCHA_TEXT = "1234"
CAPTCHA_IMAGE = "ZmFrZS1jYXB0Y2hh"

OLD_ACCESS_A = "OLD-ACCESS-TOKEN-A-111"
OLD_REFRESH_A = "OLD-REFRESH-TOKEN-A-222"
NEW_ACCESS_A = "NEW-ACCESS-TOKEN-A-333"
NEW_REFRESH_A = "NEW-REFRESH-TOKEN-A-444"

OLD_ACCESS_B = "OLD-ACCESS-TOKEN-B-111"
OLD_REFRESH_B = "OLD-REFRESH-TOKEN-B-222"
NEW_ACCESS_B = "NEW-ACCESS-TOKEN-B-333"
NEW_REFRESH_B = "NEW-REFRESH-TOKEN-B-444"

USER_ID_A = "user-id-A"
USER_ID_B = "user-id-B"


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
    def __init__(self, payload=None, status_code=200, status_ok=True, json_error=None):
        self._payload = payload
        self.status_code = status_code
        self._ok = status_ok
        self._json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400 or not self._ok:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


# ---------------------------------------------------------------------------
# Fake Agah session
# ---------------------------------------------------------------------------

class FakeAgahSession:
    def __init__(self, account_id: str):
        self.account_id = account_id
        self.calls: List[Tuple[str, str, dict]] = []
        self.captcha_id = f"captcha-id-{account_id}"
        if account_id == ACC_A:
            self._access = OLD_ACCESS_A
            self._refresh = OLD_REFRESH_A
            self._uid = USER_ID_A
            self._new_access = NEW_ACCESS_A
            self._new_refresh = NEW_REFRESH_A
        else:
            self._access = OLD_ACCESS_B
            self._refresh = OLD_REFRESH_B
            self._uid = USER_ID_B
            self._new_access = NEW_ACCESS_B
            self._new_refresh = NEW_REFRESH_B
        self.refresh_outcome = "success"
        # Track GET behavior: for the four paths, first call may return 401
        self._get_call_counts = {
            "financialaccounts/balances": 0,
            "portfolio": 0,
            "trades/calculatedquantity": 0,
            "instruments": 0,
        }
        self.force_401_on_paths = set()
        self.force_non401_on_first = set()
        self.force_second_401 = set()
        # Test-only: force a 401 on POST /order (the live order-submission path).
        self.force_401_on_order = False
        self.concurrent_refresh_block = False
        self._refresh_in_progress = threading.Event()
        self._refresh_complete = threading.Event()

    def _path_from_url(self, url: str) -> str:
        # BASE_URL is https://tseonlineapi.agah.com/api/v1
        suffix = url.split("/api/v1/")[-1]
        return suffix.lstrip("/")

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        path = self._path_from_url(url)
        self._get_call_counts.setdefault(path, 0)
        self._get_call_counts[path] += 1
        call_num = self._get_call_counts[path]

        # Determine if this is a 401 scenario for this path
        # Captcha is special (not in the 4 paths, and needs proper shape)
        if "captcha" in path:
            return FakeResponse(payload={
                "isSuccess": True,
                "data": {
                    "captchaId": self.captcha_id,
                    "captcha": CAPTCHA_IMAGE,
                },
            })
        if path in self.force_401_on_paths:
            if path in self.force_second_401:
                # Force 401 on first AND second call for this path
                return FakeResponse(payload=None, status_code=401)
            if call_num == 1 and path not in self.force_non401_on_first:
                return FakeResponse(payload=None, status_code=401)
            else:
                # Return a successful payload for that path
                return self._success_payload(path)
        # Default: return success
        return self._success_payload(path)

    def _success_payload(self, path):
        if path == "trades/calculatedquantity":
            return FakeResponse(payload={"isSuccess": True, "data": 100})
        if path == "portfolio":
            return FakeResponse(payload={"isSuccess": True, "portfolio": {"numberOfShares": 50}})
        if path == "financialaccounts/balances":
            return FakeResponse(payload={"isSuccess": True, "data": {"lastBalance": 1000000}})
        if path == "instruments":
            return FakeResponse(payload={"isSuccess": True, "data": [{"nscId": "123", "name": "X", "companyName": "Y", "tseId": "456"}]})
        return FakeResponse(payload={"isSuccess": True, "data": {}})

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if "refresh-token" in url:
            return self._refresh_response()
        # Test-only: simulate a 401 specifically for the live order endpoint.
        if self._path_from_url(url) == "order":
            if self.force_401_on_order:
                return FakeResponse(payload=None, status_code=401)
            return FakeResponse(payload={"isSuccess": True, "data": {}})
        # authenticate
        payload = kwargs.get("json", {})
        return FakeResponse(
            {
                "isSuccess": True,
                "data": {
                    "accessToken": self._access,
                    "refreshToken": self._refresh,
                    "userIdentifier": self._uid,
                    "userName": payload.get("userName"),
                },
            }
        )

    def _refresh_response(self):
        if self.refresh_outcome == "http_error":
            return FakeResponse(payload={}, status_ok=False, status_code=500)
        if self.refresh_outcome == "is_success_false":
            return FakeResponse(payload={"isSuccess": False, "message": "fail"})
        if self.refresh_outcome == "malformed":
            return FakeResponse(payload={"isSuccess": True, "data": None})
        if self.refresh_outcome == "missing_access":
            return FakeResponse(payload={"isSuccess": True, "data": {"refreshToken": self._new_refresh}})
        if self.refresh_outcome == "missing_refresh":
            return FakeResponse(payload={"isSuccess": True, "data": {"accessToken": self._new_access}})
        if self.refresh_outcome == "explode":
            raise RuntimeError("refresh exploded")
        return FakeResponse(
            payload={
                "isSuccess": True,
                "data": {"accessToken": self._new_access, "refreshToken": self._new_refresh},
            }
        )

    def refresh_calls(self):
        return [c for c in self.calls if c[0] == "post" and "refresh-token" in c[1]]


# ---------------------------------------------------------------------------
# System setup
# ---------------------------------------------------------------------------

class _StaticDeviceInfo:
    def get(self):
        return {"clientId": "offline", "platform": "web"}


def build_system(account_id=ACC_A, accounts_spec=None):
    if accounts_spec is None:
        accounts_spec = [(account_id, USERNAME, PASSWORD)]
    accounts = AccountStore()
    credential_backend = StubBackend()
    credentials = CredentialStore(backend=credential_backend)
    sessions = SessionManager()
    created = {}
    current = {"account_id": None}

    def adapter_factory():
        acc = current["account_id"]
        broker = AgaahBroker()
        broker.session = FakeAgahSession(acc)
        broker.device_info_provider = _StaticDeviceInfo()
        adapter = AgahAuthenticationAdapter(broker=broker)
        created[acc] = {"adapter": adapter, "broker": broker, "session": broker.session}
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
    for acc_id, username, password in accounts_spec:
        accounts.add(acc_id, BROKER_AGAH, f"حساب {acc_id}")
        credentials.save_credentials(acc_id, BROKER_AGAH, username, password)
    return {"service": service, "sessions": sessions, "created": created}


def login_fully(system, account_id=ACC_A):
    service = system["service"]
    service.begin_login(account_id)
    return service.complete_login(account_id, CAPTCHA_TEXT)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_401_retry_once_for_get_buy_capacity():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    sess = parts["session"]
    sess.force_401_on_paths.add("trades/calculatedquantity")
    broker = parts["broker"]

    cap = broker.get_buy_capacity("123", 1, 1000000, 1000)
    assert cap == 100
    # After refresh, broker token should be new
    assert broker.access_token == NEW_ACCESS_A
    # One refresh request
    refresh_calls = sess.refresh_calls()
    assert len(refresh_calls) == 1
    # Two GETs total for this path
    get_counts = sess._get_call_counts
    assert get_counts.get("trades/calculatedquantity", 0) == 2


def test_401_retry_once_for_get_sell_capacity():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    sess = parts["session"]
    sess.force_401_on_paths.add("portfolio")
    broker = parts["broker"]

    cap = broker.get_sell_capacity("123", 1, 1000000, 1000)
    assert cap == 50
    assert broker.access_token == NEW_ACCESS_A
    assert len(sess.refresh_calls()) == 1
    assert sess._get_call_counts.get("portfolio", 0) == 2


def test_401_retry_once_for_get_account():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    sess = parts["session"]
    sess.force_401_on_paths.add("financialaccounts/balances")
    broker = parts["broker"]

    acc = broker.get_account()
    assert acc.last_balance == 1000000
    assert broker.access_token == NEW_ACCESS_A
    assert len(sess.refresh_calls()) == 1
    assert sess._get_call_counts.get("financialaccounts/balances", 0) == 2


def test_401_retry_once_for_get_instrument():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    sess = parts["session"]
    sess.force_401_on_paths.add("instruments")
    broker = parts["broker"]

    inst = broker.get_instrument("123")
    assert inst.nsc_id == "123"
    assert broker.access_token == NEW_ACCESS_A
    assert len(sess.refresh_calls()) == 1
    assert sess._get_call_counts.get("instruments", 0) == 2


def test_non_401_no_refresh():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    sess = parts["session"]
    broker = parts["broker"]
    old_tok = broker.access_token

    broker.get_account()
    assert broker.access_token == old_tok
    assert len(sess.refresh_calls()) == 0


def test_second_401_no_extra_refresh():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    sess = parts["session"]
    sess.force_401_on_paths.add("financialaccounts/balances")
    sess.force_second_401.add("financialaccounts/balances")
    broker = parts["broker"]

    with pytest.raises(Exception) as excinfo:
        broker.get_account()
    # The failure is sanitized: only the HTTP status, never a token.
    assert OLD_ACCESS_A not in str(excinfo.value)
    assert NEW_ACCESS_A not in str(excinfo.value)
    assert broker.access_token == NEW_ACCESS_A
    assert len(sess.refresh_calls()) == 1
    assert sess._get_call_counts.get("financialaccounts/balances", 0) == 2


def test_missing_handler_fail_closed():
    # Simpler: no recovery installed via service; call directly on broker
    broker = AgaahBroker()
    sess = FakeAgahSession(ACC_A)
    broker.session = sess
    broker.access_token = OLD_ACCESS_A
    broker.user_identifier = USER_ID_A
    # no handler set
    sess.force_401_on_paths.add("financialaccounts/balances")
    with pytest.raises(Exception):
        broker.get_account()
    assert len(sess.refresh_calls()) == 0


def test_broker_adapter_sessionmanager_consistency_after_recovery():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    sess = parts["session"]
    sess.force_401_on_paths.add("financialaccounts/balances")
    broker = parts["broker"]
    adapter = parts["adapter"]
    service = system["service"]

    broker.get_account()
    assert broker.access_token == NEW_ACCESS_A
    assert adapter.get_authenticated_session().access_token == NEW_ACCESS_A
    assert system["sessions"].get_token(ACC_A) == NEW_ACCESS_A
    assert service.is_logged_in(ACC_A) is True


def test_concurrent_same_account_single_refresh():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    sess = parts["session"]
    sess.force_401_on_paths.add("financialaccounts/balances")
    broker = parts["broker"]

    results = []

    def call():
        results.append(broker.get_account())

    threads = [threading.Thread(target=call) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 3
    assert all(r.last_balance == 1000000 for r in results)
    assert broker.access_token == NEW_ACCESS_A
    # At most 1 refresh total due to locking
    assert len(sess.refresh_calls()) <= 1


def test_no_cross_account_mixing_on_recovery():
    system = build_system(accounts_spec=[(ACC_A, USERNAME, PASSWORD), (ACC_B, USERNAME, PASSWORD)])
    login_fully(system, ACC_A)
    login_fully(system, ACC_B)
    parts_a = system["created"][ACC_A]
    parts_b = system["created"][ACC_B]
    parts_a["session"].force_401_on_paths.add("financialaccounts/balances")
    old_a = system["sessions"].get_token(ACC_A)
    old_b = system["sessions"].get_token(ACC_B)
    parts_a["broker"].get_account()
    assert system["sessions"].get_token(ACC_A) != old_a
    assert system["sessions"].get_token(ACC_B) == old_b


def test_refresh_failure_isolates_affected_account():
    system = build_system(accounts_spec=[(ACC_A, USERNAME, PASSWORD), (ACC_B, USERNAME, PASSWORD)])
    login_fully(system, ACC_A)
    login_fully(system, ACC_B)
    parts_a = system["created"][ACC_A]
    parts_b = system["created"][ACC_B]
    sess_a = parts_a["session"]
    sess_a.force_401_on_paths.add("financialaccounts/balances")
    sess_a.refresh_outcome = "http_error"
    old_b = system["sessions"].get_token(ACC_B)
    with pytest.raises(Exception):
        parts_a["broker"].get_account()
    assert system["service"].is_logged_in(ACC_A) is False
    assert system["service"].is_logged_in(ACC_B) is True
    assert system["sessions"].get_token(ACC_B) == old_b


def test_post_never_retried():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    sess = parts["session"]
    # Ensure no POST refresh gets replayed by helper - the helper only does GETs
    broker = parts["broker"]
    sess.force_401_on_paths.add("financialaccounts/balances")
    broker.get_account()
    assert len(sess.refresh_calls()) == 1
    # no other POSTs
    post_calls = [c for c in sess.calls if c[0] == "post"]
    # After login, we have authenticate POST; after 401 recovery, we have refresh POST.
    # So exactly 2 POSTs total, and one of them is refresh.
    assert len(post_calls) == 2
    assert any("refresh-token" in c[1] for c in post_calls)


def test_no_token_leak_in_errors():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    sess = parts["session"]
    sess.force_401_on_paths.add("financialaccounts/balances")
    sess.refresh_outcome = "explode"
    old_tok = OLD_ACCESS_A
    try:
        parts["broker"].get_account()
    except Exception as exc:
        err_str = str(exc)
        err_repr = repr(exc)
        assert old_tok not in err_str
        assert old_tok not in err_repr


@pytest.mark.parametrize(
    "outcome",
    [
        "http_error",
        "is_success_false",
        "malformed",
        "missing_access",
        "missing_refresh",
        "explode",
    ],
)
def test_refresh_failure_isolates_affected_account_variants(outcome):
    system = build_system(
        accounts_spec=[(ACC_A, USERNAME, PASSWORD), (ACC_B, USERNAME, PASSWORD)]
    )
    login_fully(system, ACC_A)
    login_fully(system, ACC_B)
    parts_a = system["created"][ACC_A]
    parts_b = system["created"][ACC_B]
    sess_a = parts_a["session"]
    sess_a.force_401_on_paths.add("financialaccounts/balances")
    sess_a.refresh_outcome = outcome

    old_b_token = system["sessions"].get_token(ACC_B)
    b_calls_before = len(parts_b["session"].calls)

    with pytest.raises(Exception) as excinfo:
        parts_a["broker"].get_account()

    # Affected account isolated and requiring re-login.
    assert system["service"].is_logged_in(ACC_A) is False
    assert system["sessions"].get_token(ACC_A) is None
    assert system["service"].get_adapter(ACC_A) is None

    # Other account untouched.
    assert system["service"].is_logged_in(ACC_B) is True
    assert system["sessions"].get_token(ACC_B) == old_b_token
    assert len(parts_b["session"].calls) == b_calls_before

    # No token leaks through the raised error.
    for secret in (OLD_ACCESS_A, OLD_REFRESH_A, NEW_ACCESS_A, NEW_REFRESH_A):
        assert secret not in str(excinfo.value)
        assert secret not in repr(excinfo.value)


def test_refresh_failure_error_has_clean_chain_and_traceback():
    import traceback

    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    sess = parts["session"]
    sess.force_401_on_paths.add("financialaccounts/balances")
    sess.refresh_outcome = "explode"
    # Make the underlying fault carry a token, to prove redaction.
    secrets = (OLD_ACCESS_A, OLD_REFRESH_A, NEW_ACCESS_A, NEW_REFRESH_A)

    with pytest.raises(Exception) as excinfo:
        parts["broker"].get_account()

    error = excinfo.value
    assert error.__context__ is None
    assert error.__cause__ is None
    formatted = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    for secret in secrets:
        assert secret not in str(error)
        assert secret not in repr(error)
        assert secret not in formatted


def test_full_401_recovery_makes_no_real_socket():
    class NoNetwork(socket.socket):
        def __init__(self, *args, **kwargs):
            raise AssertionError("401 recovery must not open a socket")

    original = socket.socket
    socket.socket = NoNetwork
    try:
        system = build_system(ACC_A)
        login_fully(system, ACC_A)
        sess = system["created"][ACC_A]["session"]
        sess.force_401_on_paths.add("financialaccounts/balances")
        result = system["created"][ACC_A]["broker"].get_account()
        assert result.last_balance == 1000000
    finally:
        socket.socket = original


# ---------------------------------------------------------------------------
# Correction 1 — deterministic concurrent-refresh race regression
# ---------------------------------------------------------------------------

class RaceFakeSession:
    """
    Deterministic overlapping-401 session for the concurrent-refresh race.

    A protected GET authorized with ``OLD_ACCESS_A`` gets a 401; authorized
    with ``NEW_ACCESS_A`` it succeeds. The ``stale`` thread's first GET is held
    until the ``refresher`` thread has completed its single refresh, so the
    stale thread reads its 401 *after* the token already changed — exactly the
    timing the race concerns. The refresher waits until the stale thread has
    issued its request (and therefore captured the OLD token) before it
    refreshes, making the interleaving fully deterministic.
    """

    PROTECTED = "financialaccounts/balances"

    def __init__(self):
        self.calls = []
        self.t2_in_get = threading.Event()
        self.t1_refreshed = threading.Event()
        self._new_access = NEW_ACCESS_A
        self._new_refresh = NEW_REFRESH_A

    def _path_from_url(self, url):
        return url.split("/api/v1/")[-1].lstrip("/")

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        path = self._path_from_url(url)
        if "captcha" in path:
            return FakeResponse(
                payload={
                    "isSuccess": True,
                    "data": {"captchaId": "cid", "captcha": CAPTCHA_IMAGE},
                }
            )
        headers = kwargs.get("headers") or {}
        auth = headers.get("Authorization", "")
        token = auth[len("Bearer "):] if auth.startswith("Bearer ") else auth
        if path == self.PROTECTED and token == OLD_ACCESS_A:
            name = threading.current_thread().name
            if name == "stale":
                self.t2_in_get.set()
                assert self.t1_refreshed.wait(timeout=5), (
                    "refresher never completed its refresh"
                )
            elif name == "refresher":
                assert self.t2_in_get.wait(timeout=5), (
                    "stale thread never issued its original request"
                )
            return FakeResponse(payload=None, status_code=401)
        return self._success_payload(path)

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if "refresh-token" in url:
            return FakeResponse(
                payload={
                    "isSuccess": True,
                    "data": {
                        "accessToken": self._new_access,
                        "refreshToken": self._new_refresh,
                    },
                }
            )
        return FakeResponse(payload={"isSuccess": True, "data": {}})

    def _success_payload(self, path):
        if path == self.PROTECTED:
            return FakeResponse(
                payload={"isSuccess": True, "data": {"lastBalance": 1000000}}
            )
        return FakeResponse(payload={"isSuccess": True, "data": {}})

    def refresh_calls(self):
        return [
            c for c in self.calls if c[0] == "post" and "refresh-token" in c[1]
        ]


def test_overlapping_401_causes_exactly_one_refresh_deterministic():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    broker = parts["broker"]

    race = RaceFakeSession()
    broker.session = race

    # Wrap the real account-scoped recovery handler so the refresh completion
    # is signalled deterministically.
    real_handler = broker._unauthorized_recovery
    assert real_handler is not None

    def controlled_handler():
        real_handler()
        race.t1_refreshed.set()

    broker.set_unauthorized_recovery(controlled_handler)

    results = {}

    def stale_call():
        results["stale"] = broker.get_account()

    def refresher_call():
        results["refresher"] = broker.get_account()

    t_stale = threading.Thread(target=stale_call, name="stale")
    t_refresher = threading.Thread(target=refresher_call, name="refresher")

    t_stale.start()
    # The stale thread must have captured OLD and issued its request first.
    assert race.t2_in_get.wait(timeout=5)
    t_refresher.start()

    t_stale.join(timeout=10)
    t_refresher.join(timeout=10)

    assert not t_stale.is_alive()
    assert not t_refresher.is_alive()
    assert race.t1_refreshed.is_set()

    # Both overlapping callers ultimately succeed.
    assert results["stale"].last_balance == 1000000
    assert results["refresher"].last_balance == 1000000
    assert broker.access_token == NEW_ACCESS_A

    # The whole point: two overlapping 401 responses -> exactly one refresh.
    assert len(race.refresh_calls()) == 1


# ---------------------------------------------------------------------------
# Correction 2 — truthful, verified failed-session cleanup
# ---------------------------------------------------------------------------

def _force_refresh_failure(system, account_id):
    parts = system["created"][account_id]
    parts["session"].force_401_on_paths.add("financialaccounts/balances")
    parts["session"].refresh_outcome = "http_error"
    return parts


def test_logout_failure_falls_back_to_emergency_and_confirms_state():
    system = build_system(
        accounts_spec=[(ACC_A, USERNAME, PASSWORD), (ACC_B, USERNAME, PASSWORD)]
    )
    login_fully(system, ACC_A)
    login_fully(system, ACC_B)
    parts_a = _force_refresh_failure(system, ACC_A)
    sessions = system["sessions"]
    old_b_token = sessions.get_token(ACC_B)
    b_calls_before = len(system["created"][ACC_B]["session"].calls)

    def boom(account_id):
        raise RuntimeError("logout is broken")

    sessions.logout = boom

    with pytest.raises(Exception) as excinfo:
        parts_a["broker"].get_account()

    message = str(excinfo.value)
    # Emergency invalidation succeeded and is reported as confirmed.
    assert "تأیید نشد" not in message
    assert "باطل شد" in message
    assert system["service"].is_logged_in(ACC_A) is False
    assert sessions.get_token(ACC_A) is None
    assert system["service"].get_adapter(ACC_A) is None

    # The account-owned adapter/broker is neutralized, not left usable.
    assert parts_a["broker"]._unauthorized_recovery is None
    assert parts_a["broker"].access_token is None
    assert parts_a["adapter"].is_authenticated() is False
    assert parts_a["adapter"].get_authenticated_session() is None

    # Unaffected account preserved.
    assert system["service"].is_logged_in(ACC_B) is True
    assert sessions.get_token(ACC_B) == old_b_token
    assert len(system["created"][ACC_B]["session"].calls) == b_calls_before


def test_logout_and_emergency_failure_reports_unconfirmed_state():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts_a = _force_refresh_failure(system, ACC_A)
    sessions = system["sessions"]
    token_before = sessions.get_token(ACC_A)

    def boom(account_id):
        raise RuntimeError("cleanup is broken")

    sessions.logout = boom
    sessions.invalidate_session = boom

    with pytest.raises(Exception) as excinfo:
        parts_a["broker"].get_account()

    message = str(excinfo.value)
    # The safe state is NOT claimed: it is explicitly reported as unconfirmed.
    assert "تأیید نشد" in message

    # Local state could not be resolved, so no successful invalidation claim.
    assert system["service"].is_logged_in(ACC_A) is True
    assert sessions.get_token(ACC_A) == token_before

    # Nevertheless the account-owned adapter/broker is detached and cleared so
    # no stale authenticated view stays usable, and the adapter is unreachable.
    assert system["service"].get_adapter(ACC_A) is None
    assert parts_a["broker"]._unauthorized_recovery is None
    assert parts_a["broker"].access_token is None
    assert parts_a["adapter"].is_authenticated() is False

    # No token leaks through the error.
    for secret in (OLD_ACCESS_A, OLD_REFRESH_A, NEW_ACCESS_A, NEW_REFRESH_A):
        assert secret not in message


def test_cleanup_noop_is_not_accepted_as_success():
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts_a = _force_refresh_failure(system, ACC_A)
    sessions = system["sessions"]

    # Both cleanup paths silently do nothing: no exception, but the session is
    # NOT resolved to LOGGED_OUT. The service must verify the resulting state
    # and refuse to claim successful invalidation.
    sessions.logout = lambda account_id: None
    sessions.invalidate_session = lambda account_id: None

    with pytest.raises(Exception) as excinfo:
        parts_a["broker"].get_account()

    message = str(excinfo.value)
    assert "تأیید نشد" in message
    assert system["service"].is_logged_in(ACC_A) is True
    assert parts_a["broker"].access_token is None
    assert parts_a["adapter"].is_authenticated() is False


def test_inconsistent_refreshed_token_view_isolates_account():
    from brokers.authentication import AuthenticatedSession

    system = build_system(
        accounts_spec=[(ACC_A, USERNAME, PASSWORD), (ACC_B, USERNAME, PASSWORD)]
    )
    login_fully(system, ACC_A)
    login_fully(system, ACC_B)
    parts_a = system["created"][ACC_A]
    parts_b = system["created"][ACC_B]
    parts_a["session"].force_401_on_paths.add("financialaccounts/balances")
    sessions = system["sessions"]
    old_b_token = sessions.get_token(ACC_B)
    b_calls_before = len(parts_b["session"].calls)

    # The adapter reports a refreshed token that does not match the session it
    # then exposes: an inconsistent view that must fail closed.
    def fake_refresh():
        return AuthenticatedSession(
            access_token=NEW_ACCESS_A,
            user_identifier=USER_ID_A,
            refresh_token=NEW_REFRESH_A,
        )

    parts_a["adapter"].refresh_authenticated_session = fake_refresh

    with pytest.raises(Exception) as excinfo:
        parts_a["broker"].get_account()

    message = str(excinfo.value)
    assert "سازگار نبود" in message
    assert "تأیید نشد" not in message

    assert system["service"].is_logged_in(ACC_A) is False
    assert sessions.get_token(ACC_A) is None
    assert system["service"].get_adapter(ACC_A) is None
    assert parts_a["broker"].access_token is None

    # Unaffected account preserved.
    assert system["service"].is_logged_in(ACC_B) is True
    assert sessions.get_token(ACC_B) == old_b_token
    assert len(parts_b["session"].calls) == b_calls_before


# ---------------------------------------------------------------------------
# Stage 2C Security Guard: POST /order is NEVER auto-retried on 401,
# and never triggers a token refresh.
# ---------------------------------------------------------------------------

def test_post_order_401_is_not_retried_and_does_not_refresh():
    """
    Direct regression test for the live order-submission path.

    ``AgaahBroker.place_order`` is a write (POST /order) and must stay OUTSIDE
    the bounded 401 recovery helper: a 401 from POST /order must surface as an
    HTTP error, must NOT be retried, and must NOT trigger any token refresh —
    even though the account-scoped recovery handler IS installed on this broker.
    """
    system = build_system(ACC_A)
    login_fully(system, ACC_A)
    parts = system["created"][ACC_A]
    broker = parts["broker"]
    sess = parts["session"]

    # The genuine account-scoped handler is installed by login, so the recovery
    # machinery is live — yet the write path must ignore it.
    assert broker._unauthorized_recovery is not None

    # The injected fake session is the only HTTP transport.
    sess.force_401_on_order = True

    access_before = broker.access_token
    refresh_before = broker.refresh_token
    assert access_before == OLD_ACCESS_A
    assert refresh_before == OLD_REFRESH_A

    # Enable live submission ONLY on this in-memory test broker. No real
    # account, network or broker request is involved.
    broker.live_trading_enabled = True

    order = Order(
        nsc_id="123",
        side=BUY,
        price=1000,
        quantity=1,
        bank_account_id=0,
    )

    with pytest.raises(requests.HTTPError) as excinfo:
        broker.place_order(order, live=True)

    # The HTTP error propagates (fail-closed), never a silent recovery.
    assert "401" in str(excinfo.value)

    # Exactly one POST /order was sent — never retried.
    order_posts = [
        c
        for c in sess.calls
        if c[0] == "post" and sess._path_from_url(c[1]) == "order"
    ]
    assert len(order_posts) == 1

    # No refresh-token POST was triggered by the failed order request.
    assert len(sess.refresh_calls()) == 0

    # Tokens are unchanged: no refresh happened as a consequence.
    assert broker.access_token == access_before
    assert broker.refresh_token == refresh_before
