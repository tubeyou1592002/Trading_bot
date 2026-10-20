"""Offline regression: purchase power must stay isolated per Agah account.

The test drives the real AccountsPage -> AuthenticationService -> account-scoped
Agah adapter/broker path. Each broker gets its own fake HTTP session that
rejects any request carrying another account's token or userIdentifier.
"""

import base64
import struct
import zlib

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit

from brokers.agaah.auth_adapter import make_agah_adapter_factory
from brokers.manager import BrokerManager
from ui.account_store import AccountStore
from ui.accounts_page import AccountsPage, _PURCHASE_POWER
from ui.authentication_service import AuthenticationService
from ui.credential_store import Credentials
from ui.session_manager import SessionManager
from ui import strings as STRINGS


BROKER = "آگاه"
ACCOUNT_A = "POWER-A"
ACCOUNT_B = "POWER-B"
TOKEN_A, TOKEN_B = "offline-token-a", "offline-token-b"
USER_ID_A, USER_ID_B = "offline-user-id-a", "offline-user-id-b"
BALANCE_A, BALANCE_B = 1_234_000, 9_876_000


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _synthetic_png_base64():
    def chunk(kind, data):
        payload = kind + data
        return (
            struct.pack(">I", len(data)) + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        )

    image = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff"))
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(image).decode("ascii")


class _Response:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _StaticDeviceInfo:
    def get(self):
        return {
            "clientId": "offline-client",
            "deviceModel": "offline",
            "osName": "offline",
            "osVersion": "0",
            "appVersion": "test",
            "platform": "test",
        }


class _AccountHttpSession:
    """One account's isolated HTTP runtime; other identities are rejected."""

    def __init__(self, username, password, token, user_identifier, balance):
        self.username = username
        self.password = password
        self.token = token
        self.user_identifier = user_identifier
        self.balance = balance
        self.calls = []
        self.balance_requests = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url))
        headers = dict(headers or {})
        if url.endswith("captcha/getcaptcha"):
            return _Response({
                "isSuccess": True,
                "data": {
                    "captchaId": "captcha-" + self.username,
                    "captcha": _synthetic_png_base64(),
                },
            })
        if url.endswith("financialaccounts/balances"):
            assert headers == {
                "Authorization": "Bearer " + self.token,
                "UserIdentifier": self.user_identifier,
            }
            self.balance_requests.append(headers)
            return _Response({
                "isSuccess": True,
                "data": {"tradableBalanceT1": self.balance},
            })
        raise AssertionError("unexpected GET: " + url)

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url))
        payload = dict(json or {})
        if url.endswith("users/authenticate"):
            assert payload["userName"] == self.username
            assert payload["password"] == self.password
            return _Response({
                "isSuccess": True,
                "data": {
                    "accessToken": self.token,
                    "refreshToken": "refresh-" + self.username,
                    "userIdentifier": self.user_identifier,
                    "userName": self.username,
                },
            })
        raise AssertionError("unexpected POST: " + url)


class _MemoryCredentials:
    def save_credentials(self, *args):
        return None

    def delete_credentials(self, *args):
        return None

    def get_credentials(self, account_id, broker_name):
        return Credentials("user-" + account_id, "password-" + account_id)


def _row_for(page, account_id):
    for row in range(page.accounts_table.rowCount()):
        item = page.accounts_table.item(row, 0)
        if item is not None and item.data(Qt.UserRole) == account_id:
            return row
    raise AssertionError("missing account row: " + account_id)


def _login(page, account_id):
    page._begin_login(account_id)
    dialog = page._captcha_dialog
    assert dialog is not None, page.login_message_label.text()
    entry = dialog.findChild(QLineEdit)
    error = next(
        label for label in dialog.findChildren(QLabel)
        if label.property("role") == "danger"
    )
    entry.setText("answer")
    page._complete_login_dialog(account_id, entry, error, dialog)
    assert page._pending_login_account_id is None


def test_two_agah_accounts_keep_purchase_power_and_requests_isolated(qapp):
    store = AccountStore(repository=False)
    store.add(ACCOUNT_A, BROKER, "Zeta account")
    store.add(ACCOUNT_B, BROKER, "Alpha account")

    http = {
        ACCOUNT_A: _AccountHttpSession(
            "user-" + ACCOUNT_A, "password-" + ACCOUNT_A,
            TOKEN_A, USER_ID_A, BALANCE_A,
        ),
        ACCOUNT_B: _AccountHttpSession(
            "user-" + ACCOUNT_B, "password-" + ACCOUNT_B,
            TOKEN_B, USER_ID_B, BALANCE_B,
        ),
    }

    manager = BrokerManager()
    create_adapter = make_agah_adapter_factory(manager)

    def account_scoped_adapter(account_id):
        adapter = create_adapter(account_id)
        adapter.broker.session = http[account_id]
        adapter.broker.device_info_provider = _StaticDeviceInfo()
        return adapter

    service = AuthenticationService(
        store,
        _MemoryCredentials(),
        SessionManager(),
        {BROKER: account_scoped_adapter},
    )
    page = AccountsPage(
        store,
        authentication_service_factory=lambda: service,
    )

    _login(page, ACCOUNT_A)
    _login(page, ACCOUNT_B)

    adapter_a = service.get_adapter(ACCOUNT_A)
    adapter_b = service.get_adapter(ACCOUNT_B)
    assert adapter_a is not adapter_b
    assert adapter_a.broker is not adapter_b.broker
    assert adapter_a.broker.session is http[ACCOUNT_A]
    assert adapter_a.broker.session is not http[ACCOUNT_B]
    assert adapter_a.broker.access_token == TOKEN_A
    assert adapter_a.broker.user_identifier == USER_ID_A
    assert adapter_b.broker.access_token == TOKEN_B
    assert adapter_b.broker.user_identifier == USER_ID_B

    row_a = _row_for(page, ACCOUNT_A)
    row_b = _row_for(page, ACCOUNT_B)
    assert page.accounts_table.item(row_a, _PURCHASE_POWER).text() == (
        STRINGS.format_grouped(BALANCE_A)
    )
    assert page.accounts_table.item(row_b, _PURCHASE_POWER).text() == (
        STRINGS.format_grouped(BALANCE_B)
    )
    assert page.accounts_table.item(row_a, _PURCHASE_POWER).text() != (
        page.accounts_table.item(row_b, _PURCHASE_POWER).text()
    )

    assert http[ACCOUNT_A].balance_requests == [{
        "Authorization": "Bearer " + TOKEN_A,
        "UserIdentifier": USER_ID_A,
    }]
    assert http[ACCOUNT_B].balance_requests == [{
        "Authorization": "Bearer " + TOKEN_B,
        "UserIdentifier": USER_ID_B,
    }]
    calls_after_login = {
        account_id: len(session.balance_requests)
        for account_id, session in http.items()
    }

    # A sort rebuilds the table and then an explicit refresh rebuilds it again;
    # neither may call the balance API or move values between accounts.
    page.sort_selector.setCurrentIndex(1)
    page.refresh_status_button.click()
    page.refresh()

    assert {
        account_id: len(session.balance_requests)
        for account_id, session in http.items()
    } == calls_after_login

    row_a = _row_for(page, ACCOUNT_A)
    row_b = _row_for(page, ACCOUNT_B)
    assert page.accounts_table.item(row_a, _PURCHASE_POWER).text() == (
        STRINGS.format_grouped(BALANCE_A)
    )
    assert page.accounts_table.item(row_b, _PURCHASE_POWER).text() == (
        STRINGS.format_grouped(BALANCE_B)
    )
    assert page.accounts_table.item(row_a, _PURCHASE_POWER).data(Qt.UserRole) == BALANCE_A
    assert page.accounts_table.item(row_b, _PURCHASE_POWER).data(Qt.UserRole) == BALANCE_B

    message = page.login_message_label.text()
    for secret in (TOKEN_A, TOKEN_B, USER_ID_A, USER_ID_B):
        assert secret not in message

    page.close()
