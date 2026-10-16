"""Offline end-to-end acceptance for the integrated Accounts page."""

import base64
import struct
import zlib

import pytest
import requests
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.credential_store import CredentialStore
from ui import credential_store as credential_store_module
from ui.session_manager import SessionManager
from ui import session_manager as session_manager_module
from ui import authentication_service as authentication_service_module


BROKER = "آگاه"
ACCOUNT_A = "UI-PHASE3-A"
ACCOUNT_B = "UI-PHASE3-B"
USERNAME_A, PASSWORD_A = "user-a", "password-a-offline"
USERNAME_B, PASSWORD_B = "user-b", "password-b-offline"
CAPTCHA_A, CAPTCHA_B = "captcha-id-a", "captcha-id-b"
TOKEN_A, TOKEN_B = "offline-token-a", "offline-token-b"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class MemoryVault:
    def __init__(self):
        self.entries = {}

    def set_password(self, service, account, password):
        self.entries[(service, account)] = password

    def get_password(self, service, account):
        return self.entries.get((service, account))

    def delete_password(self, service, account):
        del self.entries[(service, account)]


def synthetic_png_base64():
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


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeHttpSession:
    """Requests-like offline transport bound to a single account identity."""

    def __init__(self, account_id):
        self.account_id = account_id
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        captcha_id = CAPTCHA_A if self.account_id == ACCOUNT_A else CAPTCHA_B
        return FakeResponse({
            "isSuccess": True,
            "data": {"captchaId": captcha_id, "captcha": synthetic_png_base64()},
        })

    def post(self, url, **kwargs):
        payload = kwargs["json"]
        self.calls.append(("POST", url, kwargs))
        expected_captcha = CAPTCHA_A if self.account_id == ACCOUNT_A else CAPTCHA_B
        expected_user, expected_password = (
            (USERNAME_A, PASSWORD_A)
            if self.account_id == ACCOUNT_A
            else (USERNAME_B, PASSWORD_B)
        )
        assert payload["userName"] == expected_user
        assert payload["password"] == expected_password
        assert payload["captchaId"] == expected_captcha
        assert payload["captcha"] == "answer-" + self.account_id
        token = TOKEN_A if self.account_id == ACCOUNT_A else TOKEN_B
        return FakeResponse({
            "isSuccess": True,
            "data": {
                "accessToken": token,
                "refreshToken": "refresh-" + self.account_id,
                "userIdentifier": "uid-" + self.account_id,
                "userName": expected_user,
            },
        })


class StaticDeviceInfo:
    def get(self):
        return {
            "clientId": "offline-client",
            "deviceModel": "offline",
            "osName": "offline",
            "osVersion": "0",
            "appVersion": "test",
            "platform": "test",
        }


def select_account(page, account_id):
    for row in range(page.accounts_table.rowCount()):
        if page.accounts_table.item(row, 0).text() == account_id:
            page.accounts_table.setCurrentCell(row, 0)
            return row
    raise AssertionError(f"missing account row: {account_id}")


def set_account_credentials(page, account_id, username, password):
    select_account(page, account_id)
    page.username_input.setText(username)
    page.password_input.setText(password)
    page.save_credentials_button.click()


def login_from_ui(page, account_id):
    select_account(page, account_id)
    page.begin_login_button.click()
    assert page.challenge_image_label.pixmap() is not None
    assert not page.challenge_image_label.pixmap().isNull()
    page.captcha_response_input.setText("answer-" + account_id)
    page.complete_login_button.click()
    assert page.captcha_response_input.text() == ""
    assert page._pending_login_account_id is None


def forbid_real_http(monkeypatch):
    def reject_request(*args, **kwargs):
        raise AssertionError("real HTTP requests are forbidden in this test")

    monkeypatch.setattr(requests.sessions.Session, "request", reject_request)


def test_real_main_window_accounts_ui_two_account_login_and_local_logout(
    qapp, monkeypatch
):
    forbid_real_http(monkeypatch)
    vault = MemoryVault()
    real_credential_store = CredentialStore
    created_adapters = {}

    monkeypatch.setattr(
        credential_store_module,
        "CredentialStore",
        lambda: real_credential_store(backend=vault),
    )

    adapter_module = __import__("brokers.agaah.auth_adapter", fromlist=["unused"])
    real_adapter_factory_builder = adapter_module.make_agah_adapter_factory

    def tracked_adapter_factory(manager):
        original_factory = real_adapter_factory_builder(manager)

        def create(account_id):
            adapter = original_factory(account_id)
            adapter.broker.session = FakeHttpSession(account_id)
            adapter.broker.device_info_provider = StaticDeviceInfo()
            created_adapters[account_id] = adapter
            return adapter

        return create

    monkeypatch.setattr(
        adapter_module, "make_agah_adapter_factory", tracked_adapter_factory
    )

    window = MainWindow()
    page = window.accounts_page
    assert window._authentication_service is None
    assert window._credential_store is None
    assert window._session_manager is None
    assert window._broker_manager_cache is None

    for account_id in (ACCOUNT_A, ACCOUNT_B):
        page.account_id_input.setText(account_id)
        page.display_name_input.setText(account_id)
        page.add_button.click()

    set_account_credentials(page, ACCOUNT_A, USERNAME_A, PASSWORD_A)
    set_account_credentials(page, ACCOUNT_B, USERNAME_B, PASSWORD_B)
    assert vault.entries
    assert page._authentication_service_factory
    assert window._authentication_service is None

    login_from_ui(page, ACCOUNT_A)
    # The explicit Login UI action lazily composed the cached service.
    service = window.authentication_service
    login_from_ui(page, ACCOUNT_B)

    page.refresh_status_button.click()
    row_a = select_account(page, ACCOUNT_A)
    row_b = select_account(page, ACCOUNT_B)
    assert page.accounts_table.item(row_a, 4).text() == "واردشده"
    assert page.accounts_table.item(row_b, 4).text() == "واردشده"

    adapter_a = created_adapters[ACCOUNT_A]
    adapter_b = created_adapters[ACCOUNT_B]
    broker_a, broker_b = adapter_a.broker, adapter_b.broker
    http_a, http_b = broker_a.session, broker_b.session
    sessions = window.session_manager
    assert adapter_a is not adapter_b
    assert broker_a is not broker_b
    assert http_a is not http_b
    assert http_a.account_id == ACCOUNT_A
    assert http_b.account_id == ACCOUNT_B
    assert service.get_adapter(ACCOUNT_A) is adapter_a
    assert service.get_adapter(ACCOUNT_B) is adapter_b
    assert sessions.is_logged_in(ACCOUNT_A) is True
    assert sessions.is_logged_in(ACCOUNT_B) is True
    assert sessions.get_token(ACCOUNT_A) == TOKEN_A
    assert sessions.get_token(ACCOUNT_B) == TOKEN_B

    post_a = [call for call in http_a.calls if call[0] == "POST"]
    post_b = [call for call in http_b.calls if call[0] == "POST"]
    assert len(post_a) == len(post_b) == 1
    assert post_a[0][2]["json"]["captchaId"] == CAPTCHA_A
    assert post_b[0][2]["json"]["captchaId"] == CAPTCHA_B
    assert post_a[0][2]["json"]["userName"] == USERNAME_A
    assert post_b[0][2]["json"]["userName"] == USERNAME_B

    row_a = select_account(page, ACCOUNT_A)
    page.logout_button.click()
    assert sessions.is_logged_in(ACCOUNT_A) is False
    assert sessions.get_token(ACCOUNT_A) is None
    assert page.accounts_table.item(row_a, 4).text() == "واردنشده"
    assert sessions.is_logged_in(ACCOUNT_B) is True
    assert sessions.get_token(ACCOUNT_B) == TOKEN_B
    assert service.get_adapter(ACCOUNT_B) is adapter_b
    assert broker_b.access_token == TOKEN_B
    assert broker_b.session is http_b
    window.close()


def test_main_window_construction_keeps_auth_composition_lazy_offline(
    qapp, monkeypatch
):
    forbid_real_http(monkeypatch)
    constructions = []

    class Forbidden:
        def __init__(self, *args, **kwargs):
            constructions.append(type(self).__name__)
            raise AssertionError("authentication construction must stay lazy")

    monkeypatch.setattr(authentication_service_module, "AuthenticationService", Forbidden)
    monkeypatch.setattr(credential_store_module, "CredentialStore", Forbidden)
    monkeypatch.setattr(session_manager_module, "SessionManager", Forbidden)

    window = MainWindow()
    assert window.accounts_page is not None
    assert window._authentication_service is None
    assert window._credential_store is None
    assert window._session_manager is None
    assert window._broker_manager_cache is None
    assert constructions == []
    window.close()
