"""Offline-only generic OIDC Authorization Code + PKCE mechanics spike.

This exercises a synthetic protocol against an in-process transport. It makes
no network requests and makes no claim about any broker or callback support.
"""

import base64
import hashlib
import html
import re
import secrets
from urllib.parse import parse_qs, urlencode, urljoin, urlparse


class FakeResponse:
    def __init__(self, status, headers=None, text="", json_body=None):
        self.status_code = status
        self.headers = headers or {}
        self.text = text
        self._json_body = json_body

    def json(self):
        return self._json_body


class FakeOidcServer:
    """A scripted local server; dispatches URLs without opening sockets."""

    origin = "https://oidc.invalid"

    def __init__(self):
        self.requests = []
        self.codes = {}
        self.callback_state = None
        self.callback_code = "synthetic-authorization-code"

    def dispatch(self, method, url, headers=None, data=None):
        headers = headers or {}
        parsed = urlparse(url)
        assert parsed.netloc == "oidc.invalid"
        self.requests.append((method, parsed.path, dict(headers), data))

        if method == "GET" and parsed.path == "/authorize":
            params = parse_qs(parsed.query)
            assert params["code_challenge_method"] == ["S256"]
            assert "code_challenge" in params
            return FakeResponse(302, {"Location": "/login", "Set-Cookie": "flow=session-1; Path=/"})
        if method == "GET" and parsed.path == "/login":
            assert headers.get("Cookie") == "flow=session-1"
            return FakeResponse(200, text='<form><input name="csrf" value="synthetic-csrf"></form>')
        if method == "POST" and parsed.path == "/login":
            assert headers.get("Cookie") == "flow=session-1"
            assert data == {"csrf": "synthetic-csrf", "user": "synthetic-user", "password": "synthetic-password"}
            query = parse_qs(urlparse(self.authorization_url).query)
            state = query["state"][0]
            code = self.callback_code
            self.codes[code] = (query["code_challenge"][0], query["redirect_uri"][0])
            callback_params = {"code": code}
            returned_state = state if self.callback_state is None else self.callback_state
            if returned_state is not False:
                callback_params["state"] = returned_state
            return FakeResponse(302, {"Location": query["redirect_uri"][0] + "?" + urlencode(callback_params)})
        if method == "POST" and parsed.path == "/token":
            assert data["grant_type"] == "authorization_code"
            assert "client_secret" not in data
            code = data["code"]
            challenge, redirect_uri = self.codes[code]
            assert data["redirect_uri"] == redirect_uri
            expected = base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest()).rstrip(b"=").decode()
            assert challenge == expected
            return FakeResponse(200, json_body={"access_token": "synthetic-access-token", "token_type": "Bearer"})
        raise AssertionError(f"Unexpected fake request: {method} {parsed.path}")


class FakeSession:
    def __init__(self, server):
        self.server = server
        self.cookies = {}
        self.requested_urls = []

    def request(self, method, url, data=None):
        headers = {}
        host = urlparse(url).hostname
        if host in self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies[host].items())
        self.requested_urls.append(url)
        response = self.server.dispatch(method, url, headers, data)
        cookie = response.headers.get("Set-Cookie")
        if cookie:
            pair = cookie.split(";", 1)[0]
            key, value = pair.split("=", 1)
            self.cookies.setdefault(host, {})[key] = value
        return response

    def get(self, url):
        return self.request("GET", url)

    def post(self, url, data):
        return self.request("POST", url, data)


class OidcError(Exception):
    """Safe generic failure for invalid authorization responses."""


def perform_offline_oidc_flow(client, server, returned_state=None):
    state = "synthetic-state"
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    redirect_uri = "https://client.invalid/callback"
    query = urlencode({"response_type": "code", "client_id": "synthetic-client", "redirect_uri": redirect_uri, "scope": "openid", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    server.authorization_url = f"{server.origin}/authorize?{query}"
    server.callback_state = returned_state

    authorize = client.get(server.authorization_url)
    if authorize.status_code != 302:
        raise OidcError("Authorization failed")
    login = client.get(urljoin(server.origin, authorize.headers["Location"]))
    csrf_match = re.search(r'name="csrf" value="([^"]+)"', login.text)
    if not csrf_match:
        raise OidcError("Authorization failed")
    csrf = html.unescape(csrf_match.group(1))
    submitted = client.post(f"{server.origin}/login", {"csrf": csrf, "user": "synthetic-user", "password": "synthetic-password"})
    callback_url = submitted.headers.get("Location", "")
    callback = urlparse(callback_url)
    callback_params = parse_qs(callback.query)
    if callback.scheme != "https" or callback.netloc != "client.invalid" or callback.path != "/callback":
        raise OidcError("Authorization failed")
    if callback_params.get("state") != [state]:
        raise OidcError("Authorization failed")
    if callback_url in client.requested_urls:
        raise OidcError("Authorization failed")
    code = callback_params.get("code", [None])[0]
    if not code:
        raise OidcError("Authorization failed")

    token_response = client.post(f"{server.origin}/token", {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": "synthetic-client", "code_verifier": verifier})
    return token_response, code


def test_generic_authorization_code_pkce_flow_is_fully_offline():
    server = FakeOidcServer()
    client = FakeSession(server)
    token_response, code = perform_offline_oidc_flow(client, server)

    assert token_response.json() == {"access_token": "synthetic-access-token", "token_type": "Bearer"}
    assert code == server.callback_code
    assert server.requests[-1][3]["code"] == code
    assert "client_secret" not in server.requests[-1][3]
    assert [path for _, path, _, _ in server.requests] == ["/authorize", "/login", "/login", "/token"]
    assert all(urlparse(server.origin).netloc == "oidc.invalid" for _ in server.requests)
    assert server.requests[1][2].get("Cookie") == "flow=session-1"
    assert server.requests[2][2].get("Cookie") == "flow=session-1"
    assert client.cookies["oidc.invalid"] == {"flow": "session-1"}
    assert "client.invalid" not in client.cookies
    assert all(urlparse(url).netloc != "client.invalid" for url in client.requested_urls)


def test_generic_pkce_rejects_wrong_or_missing_state_before_token_exchange():
    for returned_state in ("wrong-state", False):
        server = FakeOidcServer()
        client = FakeSession(server)
        try:
            perform_offline_oidc_flow(client, server, returned_state)
        except OidcError as error:
            assert str(error) == "Authorization failed"
        else:
            raise AssertionError("Invalid callback state was accepted")
        assert not any(path == "/token" for _, path, _, _ in server.requests)
        assert [path for _, path, _, _ in server.requests] == ["/authorize", "/login", "/login"]
