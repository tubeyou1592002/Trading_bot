"""Offline fake-transport tests for the constrained Mofid auth flow."""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest

from brokers.authentication import CHALLENGE_NONE, IncompleteLoginError, LoginChallengeError, LoginRejectedError
from brokers.mofid.auth_adapter import MofidAuthenticationAdapter


class Response:
    def __init__(self, status=200, text="", headers=None, content=b"", body=None, url="https://login.emofid.com/Login"):
        self.status_code, self.text, self.headers = status, text, headers or {}
        self.content, self.body, self.url = content, body, url

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, captcha=True, bad_state=False, body=None, rejected_captcha=False, unknown_html=False):
        self.calls, self.captcha, self.bad_state, self.body = [], captcha, bad_state, body
        self.rejected_captcha, self.unknown_html = rejected_captcha, unknown_html
        self.captcha_answer_submitted = False
        self.cookie_hosts = set()

    def request(self, method, url, allow_redirects=False, **kwargs):
        assert allow_redirects is False
        self.calls.append((method, url, kwargs))
        parsed = urlparse(url)
        if parsed.path == "/connect/authorize":
            q = parse_qs(parsed.query)
            assert q["scope"] == ["easy2_api mts_api openid profile login_delegation-api"]
            assert q["code_challenge_method"] == ["S256"]
            self.state = q["state"][0]
            self.redirect = q["redirect_uri"][0]
            self.challenge = q["code_challenge"][0]
            return Response(text='<form action="/Login"><input name="__RequestVerificationToken" value="csrf">' + ('<input name="CaptchaInput"><img src="/DNTCaptchaImage/Show">' if self.captcha else '') + '</form>', url=url)
        if parsed.path == "/DNTCaptchaImage/Show":
            return Response(content=b"fake-image", url=url)
        if parsed.path == "/Login":
            if self.calls[-1][0] == "POST":
                if self.rejected_captcha:
                    if "CaptchaInput" in kwargs.get("data", {}):
                        self.captcha_answer_submitted = True
                        return Response(302, headers={"Location": self.redirect + "?code=fake-code&state=" + ("bad" if self.bad_state else self.state)}, url=url)
                    return Response(200, text='<form action="/Login"><input name="__RequestVerificationToken" value="csrf2"><input name="CaptchaInput"><img src="/DNTCaptchaImage/Show"></form>', url=url)
                if self.unknown_html:
                    return Response(200, text="<html>invalid credentials</html>", url=url)
                return Response(302, headers={"Location": self.redirect + "?code=fake-code&state=" + ("bad" if self.bad_state else self.state)}, url=url)
            return Response(302, headers={"Location": self.redirect + "?code=fake-code&state=" + ("bad" if self.bad_state else self.state)}, url=url)
        if parsed.path == "/connect/token":
            data = kwargs["data"]
            assert "client_secret" not in data
            assert data["grant_type"] == "authorization_code"
            assert base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest()).rstrip(b"=").decode() == self.challenge
            return Response(body=self.body or {"id_token": "id-secret", "access_token": "access-secret", "expires_in": 300, "token_type": "Bearer", "scope": "openid"}, url=url)
        raise AssertionError(f"unexpected URL: {url}")


def create(session):
    return MofidAuthenticationAdapter(client_id="fake-client", redirect_uri="https://d.easytrader.ir/auth-callback",
                                      build_no="offline-build", platform_info="offline-agent", session=session)


def test_captcha_and_valid_pkce_flow_offline():
    transport = FakeSession(captcha=True)
    adapter = create(transport)
    challenge = adapter.begin_login("fake-user", "password-secret")
    assert challenge.display_payload == base64.b64encode(b"fake-image").decode()
    session = adapter.complete_login("answer")
    assert session.access_token == "access-secret"
    token_call = transport.calls[-1]
    assert token_call[2]["data"]["code"] == "fake-code"
    assert all(urlparse(url).hostname != "d.easytrader.ir" for _, url, _ in transport.calls)
    assert transport.calls[2][2]["data"] == {
        "Username": "fake-user", "Password": "password-secret",
        "__RequestVerificationToken": "csrf", "CaptchaInput": "answer",
    }


def test_bad_state_fails_before_token_exchange():
    transport = FakeSession(bad_state=True)
    adapter = create(transport)
    adapter.begin_login("user", "pw")
    with pytest.raises(LoginRejectedError):
        adapter.complete_login("answer")
    assert not any(urlparse(url).path == "/connect/token" for _, url, _ in transport.calls)


def test_no_captcha_posts_credentials_and_finishes_during_begin_login():
    transport = FakeSession(captcha=False)
    adapter = create(transport)
    challenge = adapter.begin_login("fake-user", "password-secret")
    assert challenge.kind == CHALLENGE_NONE
    assert adapter.is_authenticated()
    login_call = next(call for call in transport.calls if call[0] == "POST" and urlparse(call[1]).path == "/Login")
    assert login_call[2]["data"] == {"Username": "fake-user", "Password": "password-secret", "__RequestVerificationToken": "csrf"}


def test_authentication_service_registers_mofid_no_captcha_session_without_logging_secrets(caplog):
    from ui.account_store import AccountStore
    from ui.authentication_service import AuthenticationService
    from ui.credential_store import CredentialStore
    from ui.session_manager import SessionManager, SessionState

    class CredentialBackend:
        def set_password(self, service, account, password):
            self.value = password

        def get_password(self, service, account):
            return self.value

        def delete_password(self, service, account):
            self.value = None

    accounts = AccountStore()
    credentials = CredentialStore(backend=CredentialBackend())
    sessions = SessionManager()
    account_id = "MOFID-OFFLINE"
    broker_name = "مفید"
    accounts.add(account_id, broker_name, "Offline Mofid account")
    credentials.save_credentials(account_id, broker_name, "fake-user", "password-secret")
    transport = FakeSession(captcha=False)
    adapter = create(transport)
    service = AuthenticationService(
        accounts, credentials, sessions,
        adapter_factories={broker_name: lambda _: adapter},
    )

    challenge = service.begin_login(account_id)

    assert challenge.kind == CHALLENGE_NONE
    assert service.is_logged_in(account_id)
    assert sessions.state(account_id) is SessionState.LOGGED_IN
    assert sessions.get_token(account_id) == "access-secret"
    assert service.get_adapter(account_id) is adapter
    assert not caplog.records
    assert "access-secret" not in caplog.text
    assert "password-secret" not in caplog.text


def test_rejected_credentials_can_return_recognized_captcha():
    transport = FakeSession(captcha=False, rejected_captcha=True)
    adapter = create(transport)
    challenge = adapter.begin_login("user", "pw")
    assert challenge.display_payload == base64.b64encode(b"fake-image").decode()
    assert adapter.complete_login("answer").access_token == "access-secret"
    assert transport.captcha_answer_submitted


def test_unsuccessful_login_form_is_classified_as_rejected_credentials():
    class RejectedLoginSession(FakeSession):
        def request(self, method, url, allow_redirects=False, **kwargs):
            if method == "POST" and urlparse(url).path == "/Login":
                assert allow_redirects is False
                return Response(200, text='<form action="/Login"><input name="__RequestVerificationToken" value="csrf2"></form>', url=url)
            return super().request(method, url, allow_redirects=allow_redirects, **kwargs)

    adapter = create(RejectedLoginSession(captcha=False))
    with pytest.raises(LoginRejectedError):
        adapter.begin_login("user", "pw")


def test_unknown_rejection_html_fails_closed():
    adapter = create(FakeSession(captcha=False, unknown_html=True))
    with pytest.raises(LoginChallengeError):
        adapter.begin_login("user", "pw")


def test_network_failure_during_login_remains_generic():
    class NetworkFailure(FakeSession):
        def request(self, method, url, allow_redirects=False, **kwargs):
            if urlparse(url).path == "/Login" and method == "POST":
                raise RuntimeError("transport failure")
            return super().request(method, url, allow_redirects=allow_redirects, **kwargs)

    with pytest.raises(LoginChallengeError):
        create(NetworkFailure(captcha=False)).begin_login("user", "pw")


def test_incomplete_token_response_is_not_authenticated():
    transport = FakeSession(body={"access_token": "token"})
    adapter = create(transport)
    adapter.begin_login("user", "pw")
    with pytest.raises(IncompleteLoginError):
        adapter.complete_login("answer")
    assert not adapter.is_authenticated()


@pytest.mark.parametrize("key,value", [
    ("expires_in", 0), ("expires_in", -1), ("expires_in", True),
    ("expires_in", "300"), ("expires_in", 1.5),
    ("token_type", ""), ("token_type", 1),
    ("scope", ""), ("scope", None),
    ("id_token", ""), ("access_token", ""),
])
def test_invalid_token_response_fields_are_not_authenticated(key, value):
    body = {"id_token": "id-secret", "access_token": "access-secret",
            "expires_in": 300, "token_type": "Bearer", "scope": "openid"}
    body[key] = value
    adapter = create(FakeSession(body=body))
    adapter.begin_login("user", "pw")
    with pytest.raises(IncompleteLoginError, match="Mofid token response is incomplete"):
        adapter.complete_login("answer")
    assert not adapter.is_authenticated()
    assert adapter.get_authenticated_session() is None


@pytest.mark.parametrize("body", [
    {"buyPowerT0": 11, "buyPowerT1": 22, "buyPowerT2": 33},
    {"buyPowerT2": 0},
    {"buyPowerT2": 33.0},
])
def test_purchase_power_reads_t2_from_exact_account_endpoint(body):
    class MoneySession:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if url.endswith("/same-login"):
                return Response(body={})
            if url.endswith("/startsession"):
                return Response(body={"serverTime": "time", "startSessionTimeStamp": "stamp"})
            return Response(body=body)

    transport = MoneySession()
    adapter = create(transport)
    adapter._authenticated = type("Session", (), {"access_token": "offline-token"})()
    expected = int(body["buyPowerT2"])
    assert adapter.get_tradable_balance() == expected
    expected_headers = {"Authorization": "Bearer offline-token"}
    assert transport.calls == [
        ("POST", "https://api-mts.orbis.easytrader.ir/easy/api/account/same-login", {
            "headers": expected_headers, "allow_redirects": False,
            "timeout": (5, 15),
            "json": {"uuid": adapter._account_uuid, "userDeviceInfo": {
                "appBuildNo": "offline-build", "width": 1366, "height": 768,
                "devicePlatform": "Desktop", "platformInfo": "offline-agent",
            }},
        }),
        ("GET", "https://api-mts.orbis.easytrader.ir/easy/api/startsession", {
            "headers": expected_headers, "allow_redirects": False,
            "timeout": (5, 15),
        }),
        ("GET", "https://api-mts.orbis.easytrader.ir/easy/api/money", {
            "headers": expected_headers, "allow_redirects": False,
            "timeout": (5, 15),
        }),
    ]


def test_same_login_runs_once_per_authenticated_session_and_adapter():
    class MoneySession:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if url.endswith("/startsession"):
                return Response(body={"serverTime": "t", "startSessionTimeStamp": "s"})
            if url.endswith("/money") or url.endswith("/same-login"):
                return Response(body={"buyPowerT2": 10})
            return Response(body={})

    transport = MoneySession()
    adapter = create(transport)
    adapter._authenticated = type("Session", (), {"access_token": "offline-token"})()
    adapter.get_tradable_balance()
    adapter.get_tradable_balance()
    assert [url.rsplit("/", 1)[-1] for _, url, _ in transport.calls] == [
        "same-login", "startsession", "money", "startsession", "money"
    ]
    adapter._authenticated = type("Session", (), {"access_token": "replacement-token"})()
    adapter.get_tradable_balance()
    assert [url.rsplit("/", 1)[-1] for _, url, _ in transport.calls][-3:] == [
        "same-login", "startsession", "money"
    ]


def test_same_login_failure_retries_and_adapters_are_isolated():
    class MoneySession:
        def __init__(self):
            self.calls = []
            self.fail_once = True

        def request(self, method, url, **kwargs):
            self.calls.append(url)
            if url.endswith("/same-login") and self.fail_once:
                self.fail_once = False
                return Response(status=503)
            if url.endswith("/startsession"):
                return Response(body={"serverTime": "t", "startSessionTimeStamp": "s"})
            if url.endswith("/money"):
                return Response(body={"buyPowerT2": 10})
            return Response(body={})

    transport = MoneySession()
    adapter = create(transport)
    adapter._authenticated = type("Session", (), {"access_token": "offline-token"})()
    with pytest.raises(Exception):
        adapter.get_tradable_balance()
    adapter.get_tradable_balance()
    other_transport = MoneySession()
    other_transport.fail_once = False
    other = create(other_transport)
    other._authenticated = type("Session", (), {"access_token": "offline-token"})()
    other.get_tradable_balance()
    assert sum(url.endswith("/same-login") for url in transport.calls) == 2
    assert sum(url.endswith("/same-login") for url in other_transport.calls) == 1


def test_same_login_marker_cleared_on_logout_and_successful_login():
    class LoginMoneySession(FakeSession):
        def request(self, method, url, allow_redirects=False, **kwargs):
            if url.endswith("/same-login"):
                self.calls.append((method, url, kwargs))
                return Response(body={})
            if url.endswith("/startsession"):
                return Response(body={"serverTime": "t", "startSessionTimeStamp": "s"})
            if url.endswith("/money"):
                return Response(body={"buyPowerT2": 10})
            return super().request(method, url, allow_redirects=allow_redirects, **kwargs)

    transport = LoginMoneySession(captcha=False)
    adapter = create(transport)
    adapter.begin_login("user", "pw")
    adapter.get_tradable_balance()
    adapter.clear_authenticated_session()
    assert adapter._same_login_session is None
    assert adapter._same_login_token is None
    # Seed stale markers to verify successful login independently of logout.
    adapter._same_login_session = object()
    adapter._same_login_token = "stale-token"
    adapter.begin_login("user", "pw")
    assert adapter._same_login_session is None
    assert adapter._same_login_token is None
    adapter.get_tradable_balance()
    assert sum(url.endswith("/same-login") for _, url, _ in transport.calls) == 2


@pytest.mark.parametrize("body", [
    None, [], {}, {"buyPowerT0": 1, "buyPowerT1": 2}, {"buyPowerT2": True},
    {"buyPowerT2": -1}, {"buyPowerT2": float("inf")}, {"buyPowerT2": "3"},
    {"buyPowerT2": 3.5},
])
def test_purchase_power_malformed_response_fails_closed(body):
    class MoneySession:
        def request(self, method, url, **kwargs):
            if url.endswith("/same-login"):
                return Response(body={})
            if url.endswith("/startsession"):
                return Response(body={"serverTime": "time", "startSessionTimeStamp": "stamp"})
            return Response(body=body)

    adapter = create(MoneySession())
    adapter._authenticated = type("Session", (), {"access_token": "offline-token"})()
    with pytest.raises(Exception, match="Mofid purchase power is unavailable"):
        adapter.get_tradable_balance()


@pytest.mark.parametrize("status,body", [
    (500, {"serverTime": "time", "startSessionTimeStamp": "stamp"}),
    (200, None), (200, {}), (200, {"serverTime": "", "startSessionTimeStamp": "stamp"}),
    (200, {"serverTime": "time", "startSessionTimeStamp": 1}),
])
def test_session_activation_failure_prevents_money_request(status, body):
    class ActivationSession:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if url.endswith("/same-login"):
                return Response(body={})
            return Response(status=status, body=body)

    transport = ActivationSession()
    adapter = create(transport)
    adapter._authenticated = type("Session", (), {"access_token": "offline-token"})()
    with pytest.raises(Exception, match="Mofid purchase power is unavailable"):
        adapter.get_tradable_balance()
    assert [call[1] for call in transport.calls] == [
        "https://api-mts.orbis.easytrader.ir/easy/api/account/same-login",
        "https://api-mts.orbis.easytrader.ir/easy/api/startsession",
    ]
    assert transport.calls[0][2] == {
        "headers": {"Authorization": "Bearer offline-token"}, "allow_redirects": False,
        "timeout": (5, 15),
        "json": {"uuid": adapter._account_uuid, "userDeviceInfo": {
            "appBuildNo": "offline-build", "width": 1366, "height": 768,
            "devicePlatform": "Desktop", "platformInfo": "offline-agent",
        }},
    }


def test_same_login_failure_prevents_startsession_and_money_requests():
    class FailedHandshake:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return Response(status=503)

    transport = FailedHandshake()
    adapter = create(transport)
    adapter._authenticated = type("Session", (), {"access_token": "offline-token"})()
    with pytest.raises(Exception, match="Mofid purchase power is unavailable"):
        adapter.get_tradable_balance()
    assert len(transport.calls) == 1
    assert transport.calls[0][0] == "POST"
    assert transport.calls[0][1].endswith("/account/same-login")
    assert adapter.last_purchase_power_diagnostic == "same_login_http_503"


def test_purchase_power_requires_authenticated_adapter_without_request():
    class NoCallSession:
        def request(self, *args, **kwargs):
            pytest.fail("request must not run for logged-out account")

    adapter = create(NoCallSession())
    with pytest.raises(Exception, match="Mofid account is not authenticated"):
        adapter.get_tradable_balance()
    assert adapter.last_purchase_power_diagnostic == "not_authenticated"


@pytest.mark.parametrize("failure,expected", [
    ("activation_transport", "startsession_transport_error"),
    ("activation_http", "startsession_http_503"),
    ("activation_schema", "startsession_schema_invalid"),
    ("money_transport", "money_transport_error"),
    ("money_http", "money_http_502"),
    ("money_schema", "money_schema_invalid"),
])
def test_purchase_power_records_safe_stage_diagnostic(failure, expected):
    class DiagnosticSession:
        def request(self, method, url, **kwargs):
            if url.endswith("/same-login"):
                return Response(body={})
            if failure == "activation_transport" and url.endswith("/startsession"):
                raise RuntimeError("secret token Cookie request body")
            if url.endswith("/startsession"):
                if failure == "activation_http":
                    return Response(status=503)
                if failure == "activation_schema":
                    return Response(body={})
                return Response(body={"serverTime": "t", "startSessionTimeStamp": "s"})
            if failure == "money_transport":
                raise RuntimeError("secret token Cookie response body")
            if failure == "money_http":
                return Response(status=502)
            if failure == "money_schema":
                return Response(body={"buyPowerT2": "secret"})
            return Response(body={"buyPowerT2": 12})

    adapter = create(DiagnosticSession())
    adapter._authenticated = type("Session", (), {"access_token": "offline-token"})()
    if expected == "ok":
        assert adapter.get_tradable_balance() == 12
    else:
        with pytest.raises(Exception, match="Mofid purchase power is unavailable"):
            adapter.get_tradable_balance()
    assert adapter.last_purchase_power_diagnostic == expected
    assert "secret" not in adapter.last_purchase_power_diagnostic
