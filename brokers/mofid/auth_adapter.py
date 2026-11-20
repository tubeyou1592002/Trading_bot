"""Fail-closed Mofid OIDC Authorization Code + PKCE adapter.

The observed Nexus client/redirect values are deliberately not defaults: their
acceptance by Mofid has not been verified. Supply them explicitly when that
runtime configuration is approved. This adapter never follows the callback.
"""

import base64
import hashlib
import html
import math
import re
import secrets
import uuid
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests

from brokers.authentication import (
    AuthenticatedSession,
    AuthenticationAdapter,
    AuthenticationUnavailableError,
    CHALLENGE_CAPTCHA_IMAGE,
    CHALLENGE_NONE,
    IncompleteLoginError,
    LoginChallenge,
    LoginChallengeError,
    LoginNotInProgressError,
    LoginRejectedError,
)


AUTH_ORIGIN = "https://login.emofid.com"
LOGIN_URL = AUTH_ORIGIN + "/Login"
AUTHORIZE_URL = AUTH_ORIGIN + "/connect/authorize"
TOKEN_URL = AUTH_ORIGIN + "/connect/token"
MONEY_URL = "https://api-mts.orbis.easytrader.ir/easy/api/money"
START_SESSION_URL = "https://api-mts.orbis.easytrader.ir/easy/api/startsession"
SAME_LOGIN_URL = "https://api-mts.orbis.easytrader.ir/easy/api/account/same-login"
_IDENTITY_ORIGIN = "https://api-mts.orbis.easytrader.ir"
_IDENTITY_PATHS = {
    "/symbols/api/symbols/all",
    "/symbols/api/marketdata/v2",
    "/symbols/api/MarketData/symbol-info-data",
}
SCOPE = "easy2_api mts_api openid profile login_delegation-api"
CAPTCHA_FIELD = "CaptchaInput"
_CSRF_NAME = "__RequestVerificationToken"
_TOKEN_KEYS = {"id_token", "access_token", "expires_in", "token_type", "scope"}


def _valid_https_url(value):
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password


class MofidAuthenticationAdapter(AuthenticationAdapter):
    """Account-scoped direct HTTP flow with injectable session for offline tests."""

    def __init__(self, *, client_id, redirect_uri, build_no, session=None, auth_origin=AUTH_ORIGIN,
                 viewport_width=1366, viewport_height=768, platform_info=None):
        if not isinstance(client_id, str) or not client_id.strip() or not _valid_https_url(redirect_uri):
            raise ValueError("Explicit valid Mofid OIDC configuration is required")
        if not _valid_https_url(auth_origin):
            raise ValueError("Invalid authentication origin")
        if not isinstance(build_no, str) or not build_no.strip():
            raise ValueError("Explicit Mofid app build configuration is required")
        if (isinstance(viewport_width, bool) or not isinstance(viewport_width, int) or viewport_width <= 0
                or isinstance(viewport_height, bool) or not isinstance(viewport_height, int) or viewport_height <= 0):
            raise ValueError("Invalid desktop viewport configuration")
        self._origin = auth_origin.rstrip("/")
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._session = session if session is not None else requests.Session()
        self._account_uuid = str(uuid.uuid4())
        self._build_no = build_no
        self._viewport_width = viewport_width
        self._viewport_height = viewport_height
        session_headers = getattr(self._session, "headers", {})
        self._platform_info = platform_info or session_headers.get("User-Agent", "")
        if not isinstance(self._platform_info, str) or not self._platform_info:
            raise ValueError("Explicit platform information is required")
        self._username = self._password = self._state = self._verifier = None
        self._csrf = None
        self._authenticated = None
        self._same_login_session = None
        self._same_login_token = None
        self._captcha_action = None
        self.last_purchase_power_diagnostic = "not_authenticated"

    @property
    def broker_name(self):
        return "مفید"

    def _clear_pending(self):
        self._username = self._password = self._state = self._verifier = None
        self._csrf = self._captcha_action = None

    def _url(self, value, base=None):
        absolute = urljoin(base or self._origin + "/", value)
        if not _valid_https_url(absolute) or urlparse(absolute).hostname != urlparse(self._origin).hostname:
            raise ValueError("Unexpected authentication redirect")
        return absolute

    def _request(self, method, url, **kwargs):
        # Disable automatic redirects; each hop is explicitly checked.
        return self._session.request(method, url, allow_redirects=False, **kwargs)

    def _captcha_challenge(self, response, text, form):
        captcha = re.search(r'<input\b(?=[^>]*\bname=["\']CaptchaInput["\'])[^>]*>', form.group(2), re.I)
        image = re.search(r'<img\b[^>]*\bsrc=["\']([^"\']*DNTCaptchaImage/Show[^"\']*)["\']', form.group(2), re.I) if captcha else None
        csrf = re.search(r'<input\b(?=[^>]*\bname=["\']__RequestVerificationToken["\'])(?=[^>]*\bvalue=["\']([^"\']+)["\'])[^>]*>', text, re.I)
        action_match = re.search(r'\baction=["\']([^"\']+)', form.group(1), re.I)
        if not (captcha and image and csrf and action_match):
            raise ValueError("CAPTCHA form was not structurally observed")
        action = self._url(html.unescape(action_match.group(1)), response.url)
        image_url = self._url(html.unescape(image.group(1)), response.url)
        image_response = self._request("GET", image_url)
        if image_response.status_code != 200 or not image_response.content:
            raise ValueError("Captcha image unavailable")
        self._csrf = html.unescape(csrf.group(1))
        self._captcha_action = action
        return LoginChallenge(CHALLENGE_CAPTCHA_IMAGE, base64.b64encode(image_response.content).decode("ascii"), "Enter the Mofid CAPTCHA")

    def _follow_auth_redirects(self, response):
        for _ in range(8):
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("Location")
            if not location:
                raise ValueError("Missing authentication redirect")
            absolute = urljoin(response.url, location)
            callback = urlparse(absolute)
            expected = urlparse(self._redirect_uri)
            if (callback.scheme, callback.hostname, callback.port, callback.path) == (expected.scheme, expected.hostname, expected.port, expected.path):
                return response
            target = self._url(location, response.url)
            response = self._request("GET", target)
        raise ValueError("Too many authentication redirects")

    def begin_login(self, username, password):
        if self._authenticated or self._username is not None:
            raise LoginNotInProgressError("A Mofid login is already active")
        if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
            raise LoginNotInProgressError("Username and password are required")
        self._username, self._password = username, password
        self._state = secrets.token_urlsafe(32)
        self._verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self._verifier.encode()).digest()).rstrip(b"=").decode()
        params = urlencode({"response_type": "code", "client_id": self._client_id, "redirect_uri": self._redirect_uri,
                            "scope": SCOPE, "state": self._state, "code_challenge": challenge,
                            "code_challenge_method": "S256"})
        try:
            response = self._request("GET", self._origin + "/connect/authorize?" + params)
            response = self._follow_auth_redirects(response)
            if not 200 <= response.status_code < 300:
                raise ValueError("Authorization page unavailable")
            text = response.text
            csrf = re.search(r'<input\b(?=[^>]*\bname=["\']__RequestVerificationToken["\'])(?=[^>]*\bvalue=["\']([^"\']+)["\'])[^>]*>', text, re.I)
            form = re.search(r'<form\b([^>]*)>(.*?)</form\s*>', text, re.I | re.S)
            if not csrf or not form:
                raise ValueError("Login form not observed")
            self._csrf = html.unescape(csrf.group(1))
            action_match = re.search(r'\baction=["\']([^"\']+)', form.group(1), re.I)
            action = self._url(html.unescape(action_match.group(1)), response.url) if action_match else response.url
            captcha = re.search(r'<input\b(?=[^>]*\bname=["\']CaptchaInput["\'])[^>]*>', form.group(2), re.I)
            if captcha:
                challenge = self._captcha_challenge(response, text, form)
                return challenge
            login = self._request("POST", action, data={"Username": self._username, "Password": self._password, _CSRF_NAME: self._csrf})
            if login.status_code not in (301, 302, 303, 307, 308):
                # Only an explicit successful HTTP response from the known
                # login endpoint with an unrecognized non-captcha form is
                # classified as rejected credentials. Errors and unfamiliar
                # pages remain generic failures.
                if login.status_code == 200 and urlparse(login.url).path == "/Login":
                    pass
                else:
                    raise ValueError("Unexpected login response")
                rejected_form = re.search(r'<form\b([^>]*)>(.*?)</form\s*>', login.text, re.I | re.S)
                if rejected_form and re.search(r'<input\b(?=[^>]*\bname=["\']CaptchaInput["\'])[^>]*>', rejected_form.group(2), re.I):
                    return self._captcha_challenge(login, login.text, rejected_form)
                if rejected_form:
                    raise LoginRejectedError("Mofid login was not accepted")
                raise ValueError("Unrecognized login response")
            self._finish_login(login)
            self._clear_pending()
            return LoginChallenge(CHALLENGE_NONE, "", "")
        except LoginRejectedError:
            self._clear_pending()
            raise
        except Exception:
            self._clear_pending()
            raise LoginChallengeError("Mofid authorization could not be safely started") from None

    def complete_login(self, response):
        if self._username is None:
            raise LoginNotInProgressError("No Mofid login is active")
        try:
            # A challenge answer is accepted only when the observed form exactly
            # contained CaptchaInput and its same-origin action/CSRF token.
            if self._captcha_action:
                if not isinstance(response, str) or not response.strip():
                    raise LoginRejectedError("CAPTCHA response is required")
                data = {"Username": self._username, "Password": self._password,
                        _CSRF_NAME: self._csrf, CAPTCHA_FIELD: response.strip()}
                login = self._request("POST", self._captcha_action, data=data)
            else:
                login = self._request("POST", self._origin + "/Login",
                                      data={"Username": self._username, "Password": self._password,
                                            _CSRF_NAME: self._csrf})
            self._finish_login(login)
            return self._authenticated
        except (LoginRejectedError, IncompleteLoginError):
            raise
        except Exception:
            raise AuthenticationUnavailableError("Mofid authentication failed safely") from None
        finally:
            self._clear_pending()

    def _finish_login(self, login):
        returned = self._follow_auth_redirects(login)
        if returned.status_code not in (301, 302, 303, 307, 308):
            raise LoginRejectedError("Mofid login was not accepted")
        location = returned.headers["Location"]
        callback = self._url(location, returned.url) if urlparse(location).hostname == urlparse(self._origin).hostname else location
        parsed = urlparse(callback)
        expected = urlparse(self._redirect_uri)
        if (parsed.scheme, parsed.hostname, parsed.port, parsed.path) != (expected.scheme, expected.hostname, expected.port, expected.path):
            raise LoginRejectedError("Unexpected authorization callback")
        params = parse_qs(parsed.query, strict_parsing=True)
        if params.get("state") != [self._state] or len(params.get("code", [])) != 1 or not params["code"][0]:
            raise LoginRejectedError("Invalid authorization response")
        token = self._request("POST", self._origin + "/connect/token", data={
            "grant_type": "authorization_code", "redirect_uri": self._redirect_uri,
            "code": params["code"][0], "code_verifier": self._verifier, "client_id": self._client_id,
        })
        body = token.json()
        if token.status_code != 200 or not isinstance(body, dict) or not _TOKEN_KEYS.issubset(body):
            raise IncompleteLoginError("Mofid token response is incomplete")
        string_keys = ("id_token", "access_token", "token_type", "scope")
        if any(not isinstance(body[key], str) or not body[key].strip() for key in string_keys):
            raise IncompleteLoginError("Mofid token response is incomplete")
        expires_in = body["expires_in"]
        if isinstance(expires_in, bool) or not isinstance(expires_in, int) or expires_in <= 0:
            raise IncompleteLoginError("Mofid token response is incomplete")
        self._authenticated = AuthenticatedSession(body["access_token"], self._username)
        self._same_login_session = None
        self._same_login_token = None

    def cancel_login(self):
        if self._username is None:
            raise LoginNotInProgressError("No Mofid login is active")
        self._clear_pending()

    def is_authenticated(self):
        return self._authenticated is not None

    def get_authenticated_session(self):
        return self._authenticated

    def clear_authenticated_session(self):
        self._authenticated = None
        self._same_login_session = None
        self._same_login_token = None

    def get_tradable_balance(self):
        """Read purchase power for this authenticated account only."""
        if self._authenticated is None:
            self.last_purchase_power_diagnostic = "not_authenticated"
            raise AuthenticationUnavailableError("Mofid account is not authenticated")
        self.last_purchase_power_diagnostic = "startsession_transport_error"
        try:
            authenticated = self._authenticated
            token = authenticated.access_token
            headers = {"Authorization": "Bearer " + token}
            if self._same_login_session is not authenticated or self._same_login_token != token:
                self._same_login_session = None
                self._same_login_token = None
                self.last_purchase_power_diagnostic = "same_login_transport_error"
                try:
                    handshake = self._session.request(
                        "POST", SAME_LOGIN_URL, headers=headers, json={
                            "uuid": self._account_uuid,
                            "userDeviceInfo": {
                                "appBuildNo": self._build_no,
                                "width": self._viewport_width,
                                "height": self._viewport_height,
                                "devicePlatform": "Desktop",
                                "platformInfo": self._platform_info,
                            },
                        }, allow_redirects=False, timeout=(5, 15),
                    )
                except Exception:
                    self.last_purchase_power_diagnostic = "same_login_transport_error"
                    raise
                if not 200 <= handshake.status_code < 300:
                    self.last_purchase_power_diagnostic = f"same_login_http_{handshake.status_code}"
                    raise ValueError
                self._same_login_session = authenticated
                self._same_login_token = token
            try:
                activation = self._session.request(
                    "GET", START_SESSION_URL, headers=headers,
                    allow_redirects=False, timeout=(5, 15),
                )
            except Exception:
                self.last_purchase_power_diagnostic = "startsession_transport_error"
                raise
            if activation.status_code != 200:
                self.last_purchase_power_diagnostic = f"startsession_http_{activation.status_code}"
                raise ValueError
            self.last_purchase_power_diagnostic = "startsession_schema_invalid"
            try:
                activation_body = activation.json()
                if (not isinstance(activation_body, dict)
                        or any(not isinstance(activation_body.get(key), str) or not activation_body[key].strip()
                               for key in ("serverTime", "startSessionTimeStamp"))):
                    raise ValueError
            except Exception:
                self.last_purchase_power_diagnostic = "startsession_schema_invalid"
                raise
            self.last_purchase_power_diagnostic = "money_transport_error"
            try:
                response = self._session.request(
                    "GET", MONEY_URL, headers=headers, allow_redirects=False, timeout=(5, 15),
                )
            except Exception:
                self.last_purchase_power_diagnostic = "money_transport_error"
                raise
            if response.status_code != 200:
                self.last_purchase_power_diagnostic = f"money_http_{response.status_code}"
                raise ValueError
            self.last_purchase_power_diagnostic = "money_schema_invalid"
            try:
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError
                value = body.get("buyPowerT2")
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value < 0
                        or (isinstance(value, float) and not value.is_integer())):
                    raise ValueError
                if isinstance(value, float):
                    value = int(value)
            except Exception:
                self.last_purchase_power_diagnostic = "money_schema_invalid"
                raise
            self.last_purchase_power_diagnostic = "ok"
            return value
        except Exception:
            raise AuthenticationUnavailableError("Mofid purchase power is unavailable") from None

    def _read_symbol_data(self, path, payload):
        """Read only the explicitly allowlisted, account-authenticated symbol APIs."""
        if path not in _IDENTITY_PATHS:
            raise ValueError("Unsupported Mofid read-only path")
        if path == "/symbols/api/symbols/all":
            valid = type(payload) is dict and set(payload) == {"hash"} and payload["hash"] == "null"
        elif path == "/symbols/api/marketdata/v2":
            valid = (type(payload) is list and len(payload) == 1
                     and isinstance(payload[0], str) and bool(payload[0].strip()))
        else:
            valid = (type(payload) is dict and set(payload) == {"isin"}
                     and isinstance(payload["isin"], str) and bool(payload["isin"].strip()))
        if not valid:
            raise ValueError("Invalid Mofid read-only request shape")
        authenticated = self._authenticated
        token = getattr(authenticated, "access_token", None)
        if not isinstance(token, str) or not token.strip():
            raise AuthenticationUnavailableError("Mofid account is not authenticated")
        try:
            response = self._session.request(
                "POST", _IDENTITY_ORIGIN + path,
                headers={"Authorization": "Bearer " + token}, json=payload,
                allow_redirects=False, timeout=(5, 15),
            )
            if response.status_code != 200:
                raise ValueError
            body = response.json()
            if path == "/symbols/api/symbols/all":
                if type(body) is not dict or type(body.get("symbols")) is not list:
                    raise ValueError
            elif path == "/symbols/api/marketdata/v2":
                if type(body) is not list or any(type(item) is not dict for item in body):
                    raise ValueError
            elif type(body) is not dict:
                raise ValueError
            return body
        except Exception:
            raise AuthenticationUnavailableError("Mofid symbol data is unavailable") from None

def make_mofid_adapter_factory(broker_manager=None, *, client_id, redirect_uri, build_no,
                               viewport_width=1366, viewport_height=768, platform_info=None):
    """Create an AuthenticationService factory; config is explicit and unverified."""
    return lambda account_id: MofidAuthenticationAdapter(
        client_id=client_id, redirect_uri=redirect_uri, build_no=build_no,
        viewport_width=viewport_width, viewport_height=viewport_height, platform_info=platform_info,
    )
