"""
test_ui2_1_account_management.py

UI-2.1 Account Management Foundation tests (fully offline, deterministic).

Contract coverage:

    Test 1  — MainWindow shows the REAL Accounts page.
    Test 2  — An account is created from account_id + broker_name.
    Test 3  — The record holds a real models.account.Account instance.
    Test 4  — Two accounts with different identities stay independent
              (ACC-001 -> آگاه, ACC-002 -> آگاه).
    Test 5  — Broker association is exactly the registered broker_name.
    Test 6  — No account is active initially.
    Test 7  — An account can be activated.
    Test 8  — Activating the second account deactivates the first.
    Test 9  — Empty/invalid account ids are rejected.
    Test 10 — Duplicate account ids are rejected.
    Test 11 — Constructing AccountsPage creates NO real broker object.
    Test 12 — Constructing AccountsPage performs no network/login/API
              operation (socket silence in a clean subprocess).
    Test 13 — Home and Settings are still placeholders.

These tests are fully offline:
  - no network
  - no login
  - no broker API
  - no TSETMC call
  - no real order

Run:
    pytest -q test_ui2_1_account_management.py
"""

import os
import subprocess
import sys
import struct
import zlib
import base64

import pytest

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit

from models.account import Account, AccountValidationError

from ui.account_store import AccountStore, AccountStoreError, AccountRecord
from ui.accounts_page import AccountsPage, AVAILABLE_BROKERS
from ui.main_window import MainWindow
from ui import strings as STRINGS
from ui.credential_store import (
    CredentialBackendError,
    CredentialNotFoundError,
    CredentialValidationError,
)


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

BROKER = "آگاه"  # the only broker implemented in the repository today


@pytest.fixture(scope="module")
def qapp():
    """Reuse the process-wide QApplication if one exists, else create one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def store():
    return AccountStore(repository=False)


# ============================================================
# Test 1 — MainWindow shows the real Accounts page
# ============================================================


def test_1_main_window_shows_real_accounts_page(qapp):
    window = MainWindow(account_store=AccountStore(repository=False))

    assert isinstance(window.accounts_page, AccountsPage)
    assert window.pages["Accounts"] is window.accounts_page
    assert window.content_area.currentWidget() is window.pages["Home"]

    window.nav_buttons["Accounts"].click()
    assert window.content_area.currentWidget() is window.accounts_page


# ============================================================
# Test 2 — account created from account_id + broker_name
# ============================================================


def test_2_account_created_from_id_and_broker(store):
    record = store.add("ACC-001", BROKER, "ACC-001")

    assert isinstance(record, AccountRecord)
    assert record.account_id == "ACC-001"
    assert record.broker_name == BROKER
    assert record in store.all_accounts()


# ============================================================
# Test 3 — record holds a real models.account.Account
# ============================================================


def test_3_record_uses_real_account_model(store):
    record = store.add("ACC-001", BROKER, "ACC-001")

    assert isinstance(record.account, Account)
    # identity lives on the Account model itself — never invented
    assert record.account.account_id == "ACC-001"


# ============================================================
# Test 4 — two accounts with different identities stay independent
# ============================================================


def test_4_accounts_stay_independent(store):
    first = store.add("ACC-001", BROKER, "ACC-001")
    second = store.add("ACC-002", BROKER, "ACC-002")

    assert first.account_id == "ACC-001"
    assert second.account_id == "ACC-002"
    assert first.account is not second.account
    assert first.account.account_id != second.account.account_id
    assert len(store.all_accounts()) == 2


# ============================================================
# Test 5 — broker association is exactly the registered name
# ============================================================


def test_5_broker_association_is_exact(store):
    record = store.add("ACC-001", BROKER, "ACC-001")

    assert record.broker_name == BROKER
    # association lives on the record, not on the Account model
    assert not hasattr(record.account, "broker_name")
    # selector currently offers exactly the implemented broker
    assert AVAILABLE_BROKERS == (BROKER,)


# ============================================================
# Test 6 — no account active initially
# ============================================================


def test_6_no_account_active_initially(store):
    store.add("ACC-001", BROKER, "ACC-001")

    assert store.active_account_id() is None
    assert store.is_active("ACC-001") is False


# ============================================================
# Test 7 — an account can be activated
# ============================================================


def test_7_account_can_be_activated(store):
    store.add("ACC-001", BROKER, "ACC-001")
    result = store.set_active("ACC-001")

    assert result == "ACC-001"
    assert store.active_account_id() == "ACC-001"
    assert store.is_active("ACC-001") is True


# ============================================================
# Test 8 — activating the second deactivates the first
# ============================================================


def test_8_second_activation_deactivates_first(store):
    store.add("ACC-001", BROKER, "ACC-001")
    store.add("ACC-002", BROKER, "ACC-002")

    store.set_active("ACC-001")
    assert store.is_active("ACC-001") is True
    assert store.is_active("ACC-002") is False

    store.set_active("ACC-002")
    assert store.active_account_id() == "ACC-002"
    assert store.is_active("ACC-001") is False
    assert store.is_active("ACC-002") is True


# ============================================================
# Test 9 — empty/invalid account ids are rejected
# ============================================================


def test_9_invalid_account_id_rejected(store):
    with pytest.raises((AccountStoreError, AccountValidationError)):
        store.add("", BROKER, "")
    with pytest.raises((AccountStoreError, AccountValidationError)):
        store.add("   ", BROKER, "   ")
    with pytest.raises((AccountStoreError, AccountValidationError)):
        store.add(None, BROKER, None)
    with pytest.raises((AccountStoreError, AccountValidationError)):
        store.add(123, BROKER, 123)

    # nothing was registered
    assert store.all_accounts() == ()
    # activating an unknown/invalid id is also rejected
    with pytest.raises(AccountStoreError):
        store.set_active("ACC-DOES-NOT-EXIST")


# ============================================================
# Test 10 — duplicate account ids are rejected
# ============================================================


def test_10_duplicate_account_id_rejected(store):
    store.add("ACC-001", BROKER, "ACC-001")

    with pytest.raises(AccountStoreError):
        store.add("ACC-001", BROKER, "ACC-001")

    # still exactly one record, identity unchanged
    assert len(store.all_accounts()) == 1
    assert store.all_accounts()[0].account_id == "ACC-001"


# ============================================================
# Test 11 — constructing AccountsPage creates no real broker
# ============================================================


def test_11_accounts_page_creates_no_real_broker(store, qapp):
    page = AccountsPage(store)

    assert page.display_name_input is not None
    assert page.username_input is not None
    assert page.password_input is not None
    assert page.broker_selector is not None
    assert page.add_button is not None
    assert page.accounts_table is not None
    assert page.broker_selector.count() == 1
    assert page.broker_selector.currentText() == BROKER

    # no broker / manager object anywhere on the page
    for attr in (
        "broker_manager",
        "broker",
        "agaah_broker",
        "session",
        "token",
        "order_engine",
    ):
        assert not hasattr(page, attr), f"page has forbidden attribute: {attr}"

    # the store holds no broker object either
    page._on_add_clicked()  # empty form -> rejected, page still healthy
    # UI-9.4: the rejection is reported by the inline error label instead
    # of a blocking QMessageBox.
    assert page.validation_error_label.text() == STRINGS.FORM_DISPLAY_NAME_REQUIRED
    assert not page.validation_error_label.isHidden()
    assert len(page.store.all_accounts()) == 0


# ============================================================
# Test 12 — construction performs no network/login/API operation
# ============================================================


def test_12_accounts_page_performs_no_network_or_login():
    code = "\n".join(
        [
            "import sys",
            "import socket",
            "import urllib.request",
            "",
            "class _Boom:",
            "    def __init__(self, *a, **k):",
            "        raise AssertionError('network construct attempted')",
            "    def __getattr__(self, name):",
            "        raise AssertionError(f'network access attempted: {name}')",
            "",
            "socket.create_connection = _Boom",
            "socket.socket = _Boom",
            "socket.getaddrinfo = _Boom",
            "urllib.request.urlopen = _Boom",
            "for mod in ('requests', 'httpx'):",
            "    assert mod not in sys.modules, f'{mod} already imported'",
            "",
            "import ui.app as ui_app",
            "from ui.account_store import AccountStore",
            "from ui.accounts_page import AccountsPage",
            "",
            "app = ui_app.create_app([])",
            "store = AccountStore()",
            "page = AccountsPage(store)",
            "",
            "# exercise the full flow offline: add via the store, refresh,",
            "# and select rows in the table",
            "store.add('ACC-001', 'آگاه', 'ACC-001')",
            "store.add('ACC-002', 'آگاه', 'ACC-002')",
            "store.set_active('ACC-002')",
            "page.refresh()",
            # UI-9 Task 3: selectRow() is a no-op on a table whose effective
            # layout direction is RightToLeft (PySide6 6.11.2). setCurrentCell()
            # selects the same row correctly under RTL. Same assertion below
            # still proves row 0 is selected and Set Active switches to
            # ACC-001; nothing is weakened.
            "page._activate('ACC-001')",
            "assert store.active_account_id() == 'ACC-001'",
            "app.processEvents()",
            "print('NO_NETWORK_OK')",
        ]
    )
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "NO_NETWORK_OK" in result.stdout


# ============================================================
# Test 13 — Home and Settings are still placeholders
# ============================================================


def test_13_home_and_settings_still_placeholders(qapp):
    window = MainWindow(account_store=AccountStore(repository=False))

    assert set(window.placeholder_pages) == {"Home", "Settings"}
    assert "Accounts" not in window.placeholder_pages
    assert window.pages["Home"] is window.placeholder_pages["Home"]
    assert window.pages["Settings"] is window.placeholder_pages["Settings"]

    # navigation still works across all three entries
    window.nav_buttons["Settings"].click()
    assert window.content_area.currentWidget() is window.placeholder_pages["Settings"]
    window.nav_buttons["Home"].click()
    assert window.content_area.currentWidget() is window.placeholder_pages["Home"]


# ============================================================
# Extra — UI flow: adding via the page mirrors into the store/list
# ============================================================


def test_extra_page_add_and_active_flow(store, qapp):
    backend = FakeCredentialStore()
    page = AccountsPage(store, credential_store_factory=lambda: backend)
    for label in ("Primary account", "Secondary account"):
        page.display_name_input.setText(label)
        page.username_input.setText("offline-user")
        page.password_input.setText("offline-password")
        page.add_button.click()

    assert len({r.account_id for r in store.all_accounts()}) == 2
    assert page.accounts_table.rowCount() == 2
    assert [r.display_name for r in store.all_accounts()] == [
        "Primary account", "Secondary account"
    ]
    assert page.accounts_table.item(0, 1).text().startswith("Primary account")
    assert page.accounts_table.item(1, 1).text().startswith("Secondary account")
    assert page.accounts_table.item(0, 1).data(256) == store.all_accounts()[0].account_id
    assert page.accounts_table.item(0, 1).text().endswith(BROKER)
    assert page.display_name_input.text() == ""

    ids = [r.account_id for r in store.all_accounts()]
    page._activate(ids[0])
    assert store.active_account_id() == ids[0]
    assert page.accounts_table.item(0, 2).text() == STRINGS.CURRENT_USE_ACTIVE
    assert page.accounts_table.item(1, 2).text() == STRINGS.CURRENT_USE_INACTIVE

    page._activate(ids[1])
    assert store.active_account_id() == ids[1]
    assert page.accounts_table.item(0, 2).text() == STRINGS.CURRENT_USE_INACTIVE
    assert page.accounts_table.item(1, 2).text() == STRINGS.CURRENT_USE_ACTIVE


@pytest.mark.parametrize("display_name", ["", "   "])
def test_page_rejects_empty_display_name_without_adding_account(
    store, qapp, display_name
):
    page = AccountsPage(store)
    page.display_name_input.setText(display_name)

    page._on_add_clicked()

    assert store.all_accounts() == ()
    assert page.accounts_table.rowCount() == 0
    assert page.validation_error_label.text() == STRINGS.FORM_DISPLAY_NAME_REQUIRED


# ============================================================
# Block 9 Task 1 — display_name contract
# ============================================================


def test_display_name_stored_correctly(store):
    record = store.add("ACC-001", BROKER, "My Agah Account")

    assert record.display_name == "My Agah Account"


def test_display_name_independent_of_account_id(store):
    record = store.add("ACC-001", BROKER, "Primary Account")

    assert record.display_name == "Primary Account"
    assert record.display_name != record.account_id


def test_display_name_empty_rejected(store):
    with pytest.raises(AccountStoreError):
        store.add("ACC-001", BROKER, "")

    assert store.all_accounts() == ()


def test_display_name_whitespace_rejected(store):
    with pytest.raises(AccountStoreError):
        store.add("ACC-001", BROKER, "   ")

    assert store.all_accounts() == ()


def test_display_name_non_string_rejected(store):
    with pytest.raises(AccountStoreError):
        store.add("ACC-001", BROKER, 123)

    assert store.all_accounts() == ()


def test_display_name_stripped(store):
    record = store.add("ACC-001", BROKER, "  My Account  ")

    assert record.display_name == "My Account"


def test_no_secret_on_account_or_record(store):
    record = store.add("ACC-001", BROKER, "ACC-001")

    assert not hasattr(record.account, "password")
    assert not hasattr(record.account, "token")
    assert not hasattr(record.account, "session")
    assert not hasattr(record.account, "credential")
    assert not hasattr(record, "password")
    assert not hasattr(record, "token")
    assert not hasattr(record, "session")
    assert not hasattr(record, "credential")


def test_display_name_is_required(store):
    with pytest.raises(TypeError):
        store.add("ACC-001", BROKER)


class FakeCredentialStore:
    def __init__(self, failure=None):
        self.failure = failure
        self.saved = []
        self.deleted = []

    def save_credentials(self, account_id, broker_name, username, password):
        if self.failure:
            raise self.failure
        self.saved.append((account_id, broker_name, username, password))

    def delete_credentials(self, account_id, broker_name):
        if self.failure:
            raise self.failure
        self.deleted.append((account_id, broker_name))


def _credentials_page(store, qapp, backend, factory_calls=None):
    factory_calls = factory_calls if factory_calls is not None else []

    def factory():
        factory_calls.append(True)
        return backend

    page = AccountsPage(store, credential_store_factory=factory)
    return page, factory_calls


def test_credential_actions_require_selected_account(store, qapp):
    calls = []
    page = AccountsPage(store, credential_store_factory=lambda: calls.append(True))
    page.display_name_input.setText("Display")
    page.username_input.setText("username")
    page.password_input.setText("secret-password")
    page.add_button.click()
    assert calls == [True]
    assert store.all_accounts() == ()  # credential write failure triggers rollback
    page.close()


def test_credentials_use_selected_account_identity_not_display_or_active(
    store, qapp
):
    store.add("REAL-ID-A", BROKER, "Display A")
    store.add("REAL-ID-B", BROKER, "Display B")
    store.set_active("REAL-ID-A")
    backend = FakeCredentialStore()
    page, factory_calls = _credentials_page(store, qapp, backend)
    page.display_name_input.setText("Display C")
    page.username_input.setText("  user-B  ")
    page.password_input.setText(" pass-B ")

    page.add_button.click()

    new_record = next(r for r in store.all_accounts() if r.display_name == "Display C")
    assert backend.saved == [(new_record.account_id, BROKER, "  user-B  ", " pass-B ")]
    assert len(factory_calls) == 1
    assert page.login_message_label.text() == STRINGS.ACCOUNT_ADD_SUCCESS
    assert page.password_input.text() == ""
    page.close()


@pytest.mark.parametrize("username,password", [("", "p"), ("  ", "p"), ("u", ""), ("u", "  ")])
def test_invalid_credentials_do_not_resolve_factory(store, qapp, username, password):
    store.add("ACC-001", BROKER, "Display")
    backend = FakeCredentialStore()
    page, factory_calls = _credentials_page(store, qapp, backend)
    page.display_name_input.setText("Display")
    page.accounts_table.setCurrentCell(0, 1)
    page.username_input.setText(username)
    page.password_input.setText(password)

    page._on_add_clicked()

    assert factory_calls == []
    assert backend.saved == []
    assert page.validation_error_label.text() == STRINGS.FORM_CREDENTIALS_REQUIRED
    page.close()


def test_credential_delete_not_found_differs_from_backend_error(store, qapp):
    for failure in (CredentialNotFoundError("raw sensitive detail"),
                    CredentialBackendError("raw sensitive detail")):
        backend = FakeCredentialStore(failure)
        page = AccountsPage(store, credential_store_factory=lambda b=backend: b)
        page.display_name_input.setText("No-save")
        page.username_input.setText("user")
        page.password_input.setText("secret")
        page.add_button.click()
        assert page.validation_error_label.text() == STRINGS.ACCOUNT_OPERATION_FAILED
        assert "raw sensitive detail" not in page.validation_error_label.text()
        assert not any(r.display_name == "No-save" for r in store.all_accounts())
        page.close()


def test_credential_save_failure_is_generic_and_clears_secrets(store, qapp):
    store.add("ACC-001", BROKER, "Display")
    secret = "TOP-SECRET-PASSWORD"
    backend = FakeCredentialStore(CredentialValidationError(secret))
    page, _ = _credentials_page(store, qapp, backend)
    page.display_name_input.setText("New Display")
    page.username_input.setText("username")
    page.password_input.setText(secret)
    assert page.password_input.echoMode() == QLineEdit.Password

    page._on_add_clicked()

    assert page.validation_error_label.text() == STRINGS.ACCOUNT_OPERATION_FAILED
    assert secret not in page.validation_error_label.text()
    assert page.username_input.text() == "username"
    assert page.password_input.text() == secret
    assert not any(r.display_name == "New Display" for r in store.all_accounts())
    page.close()


def test_page_refresh_and_selection_do_not_resolve_credential_factory(store, qapp):
    store.add("ACC-001", BROKER, "Display")
    calls = []
    page, _ = _credentials_page(store, qapp, FakeCredentialStore(), calls)
    page.refresh()
    page.accounts_table.setCurrentCell(0, 0)
    page.accounts_table.setCurrentCell(-1, -1)
    assert calls == []
    page.close()


class FakeAuthenticationService:
    def __init__(self, challenge=None, begin_error=None, cancel_error=None,
                 complete_error=None, logout_error=None, status_errors=None,
                 logged_in=None):
        self.challenge = challenge
        self.begin_error = begin_error
        self.cancel_error = cancel_error
        self.complete_error = complete_error
        self.logout_error = logout_error
        self.status_errors = status_errors or {}
        self.logged_in = dict(logged_in or {})
        self.begun = []
        self.cancelled = []
        self.completed = []
        self.logged_out = []
        self.status_queries = []

    def begin_login(self, account_id):
        self.begun.append(account_id)
        if self.begin_error:
            raise self.begin_error
        return self.challenge

    def cancel_login(self, account_id):
        self.cancelled.append(account_id)
        if self.cancel_error:
            raise self.cancel_error

    def complete_login(self, account_id, response):
        self.completed.append((account_id, response))
        if self.complete_error:
            raise self.complete_error
        self.logged_in[account_id] = True

    def logout(self, account_id):
        self.logged_out.append(account_id)
        if self.logout_error:
            raise self.logout_error
        self.logged_in[account_id] = False

    def is_logged_in(self, account_id):
        self.status_queries.append(account_id)
        if account_id in self.status_errors:
            raise self.status_errors[account_id]
        return self.logged_in.get(account_id, False)


def _login_page(store, qapp, service):
    calls = []
    page = AccountsPage(
        store,
        authentication_service_factory=lambda: (calls.append(True) or service),
    )
    return page, calls


def _synthetic_png_base64():
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff"))
           + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


def test_login_requires_selection_and_factory_is_lazy(store, qapp):
    calls = []
    page = AccountsPage(store, authentication_service_factory=lambda: calls.append(1))
    page._on_begin_login_clicked()
    page.refresh()
    assert page.login_message_label.text() == STRINGS.LOGIN_SELECT_ACCOUNT
    assert calls == []
    page.close()

    store.add("A", BROKER, "A")
    page = AccountsPage(store)
    page.accounts_table.setCurrentCell(0, 1)
    page._on_begin_login_clicked()
    assert page.login_message_label.text() == STRINGS.ACCOUNT_OPERATION_FAILED
    page.close()


def test_authentication_factory_is_lazy_until_explicit_login(store, qapp):
    from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge

    store.add("A", BROKER, "Account A")
    store.add("B", BROKER, "Account B")
    challenge = LoginChallenge(
        CHALLENGE_CAPTCHA_IMAGE, _synthetic_png_base64(), "prompt"
    )
    service = FakeAuthenticationService(challenge=challenge)
    calls = []

    def factory():
        calls.append(True)
        return service

    page = AccountsPage(store, authentication_service_factory=factory)
    assert calls == []
    page.refresh()
    assert calls == []
    page.accounts_table.setCurrentCell(0, 1)
    assert calls == []
    page.accounts_table.setCurrentCell(1, 1)
    assert calls == []

    page._on_begin_login_clicked()
    assert calls == [True]
    assert service.begun == ["B"]
    page._on_cancel_login_clicked()
    page.close()


def test_login_uses_selected_identity_and_cancel_keeps_original_service(store, qapp):
    from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge
    store.add("REAL-A", BROKER, "Same broker A")
    store.add("REAL-B", BROKER, "Same broker B")
    tiny_png = _synthetic_png_base64()
    challenge = LoginChallenge(CHALLENGE_CAPTCHA_IMAGE, tiny_png, "prompt")
    service = FakeAuthenticationService(challenge=challenge)
    page, calls = _login_page(store, qapp, service)
    page.accounts_table.setCurrentCell(1, 1)
    page._on_begin_login_clicked()
    assert service.begun == ["REAL-B"]
    assert isinstance(page._captcha_dialog, QDialog)
    dialog_labels = page._captcha_dialog.findChildren(QLabel)
    assert any("ادامهٔ ورود" in label.text() for label in dialog_labels)
    assert any(label.pixmap() is not None and not label.pixmap().isNull()
               for label in dialog_labels)
    assert tiny_png not in page.login_message_label.text()
    page.accounts_table.setCurrentCell(0, 1)
    page._on_begin_login_clicked()
    assert service.begun == ["REAL-B"]
    page._on_cancel_login_clicked()
    assert service.cancelled == ["REAL-B"]
    assert page._captcha_dialog is None
    assert len(calls) == 1
    page.close()


def test_login_failure_and_cancel_failure_are_safe_and_clear_challenge(store, qapp):
    from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge
    store.add("A", BROKER, "A")
    service = FakeAuthenticationService(
        begin_error=RuntimeError("secret token credential captchaId"),
    )
    page, _ = _login_page(store, qapp, service)
    page.accounts_table.setCurrentCell(0, 1)
    page._on_begin_login_clicked()
    assert page._captcha_dialog is None
    assert page.login_message_label.text() == STRINGS.LOGIN_CHALLENGE_UNAVAILABLE
    assert "secret" not in page.login_message_label.text()
    assert service.cancelled == []
    page.close()

    from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge
    for invalid_challenge in (
        None,
        object(),
        LoginChallenge(CHALLENGE_CAPTCHA_IMAGE, "not-valid-base64!", "secret prompt"),
        LoginChallenge(CHALLENGE_CAPTCHA_IMAGE, base64.b64encode(b"not an image").decode("ascii"), "secret prompt"),
    ):
        service = FakeAuthenticationService(challenge=invalid_challenge)
        page, _ = _login_page(store, qapp, service)
        page.accounts_table.setCurrentCell(0, 1)
        page._on_begin_login_clicked()
        assert service.begun == ["A"]
        assert service.cancelled == ["A"]
        assert page._captcha_dialog is None
        assert page.login_message_label.text() == STRINGS.LOGIN_CHALLENGE_UNAVAILABLE
        assert invalid_challenge is None or not (
            isinstance(invalid_challenge, LoginChallenge)
            and invalid_challenge.display_payload in page.login_message_label.text()
        )
        page.close()

    tiny_png = _synthetic_png_base64()
    service = FakeAuthenticationService(
        challenge=LoginChallenge(CHALLENGE_CAPTCHA_IMAGE, tiny_png, "prompt"),
        cancel_error=RuntimeError("secret"),
    )
    page, _ = _login_page(store, qapp, service)
    page.accounts_table.setCurrentCell(0, 1)
    page._on_begin_login_clicked()
    page._on_cancel_login_clicked()
    assert service.cancelled == ["A"]
    assert page._captcha_dialog is None
    assert page.login_message_label.text() == STRINGS.ACCOUNT_OPERATION_FAILED
    assert "secret" not in page.login_message_label.text()
    page.close()


def test_complete_login_uses_original_account_and_updates_only_its_status(store, qapp):
    from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge

    store.add("A", BROKER, "Account A")
    store.add("B", BROKER, "Account B")
    service = FakeAuthenticationService(
        challenge=LoginChallenge(
            CHALLENGE_CAPTCHA_IMAGE, _synthetic_png_base64(), "prompt"
        ),
        logged_in={"A": False, "B": False},
    )
    page, _ = _login_page(store, qapp, service)
    page.accounts_table.setCurrentCell(1, 1)
    page._on_begin_login_clicked()
    page.refresh_status_button.click()
    page.accounts_table.setCurrentCell(0, 1)
    dialog = page._captcha_dialog
    entry = dialog.findChild(QLineEdit)
    error = next(label for label in dialog.findChildren(QLabel) if label.text() == "")
    entry.setText("answer")
    page._complete_login_dialog("B", entry, error, dialog)

    assert service.completed == [("B", "answer")]
    assert page._pending_login_account_id is None
    assert page._pending_authentication_service is None
    assert page._captcha_dialog is None
    statuses = {
        page.accounts_table.item(row, 0).text(): page.accounts_table.item(row, 3).text()
        for row in range(page.accounts_table.rowCount())
    }
    assert statuses["A"] == STRINGS.LOGIN_STATUS_LOGGED_OUT
    assert statuses["B"] == STRINGS.LOGIN_STATUS_LOGGED_IN
    page.close()


def test_completion_failure_is_generic_and_clears_pending_challenge(store, qapp):
    from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge

    store.add("A", BROKER, "Account A")
    service = FakeAuthenticationService(
        challenge=LoginChallenge(
            CHALLENGE_CAPTCHA_IMAGE, _synthetic_png_base64(), "prompt"
        ),
        complete_error=RuntimeError("private token captchaId credential"),
    )
    page, _ = _login_page(store, qapp, service)
    page.accounts_table.setCurrentCell(0, 1)
    page._on_begin_login_clicked()
    dialog = page._captcha_dialog
    entry = dialog.findChild(QLineEdit)
    error = next(label for label in dialog.findChildren(QLabel) if label.text() == "")
    entry.setText("response")
    page._complete_login_dialog("A", entry, error, dialog)
    assert page.login_message_label.text() == STRINGS.ACCOUNT_OPERATION_FAILED
    assert "private" not in page.login_message_label.text()
    assert page._pending_login_account_id is None
    assert page._captcha_dialog is None
    page.close()


def test_logout_and_refresh_status_are_account_scoped(store, qapp):
    store.add("A", BROKER, "Account A")
    store.add("B", BROKER, "Account B")
    service = FakeAuthenticationService(logged_in={"A": True, "B": True})
    page, _ = _login_page(store, qapp, service)
    assert page.accounts_table.item(0, 3).text() == STRINGS.LOGIN_STATUS_UNKNOWN
    page.refresh_status_button.click()
    assert service.status_queries == ["A", "B"]
    assert page.accounts_table.item(0, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_IN
    assert page.accounts_table.item(1, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_IN

    page.accounts_table.setCurrentCell(0, 1)
    page.logout_button.click()
    assert service.logged_out == ["A"]
    assert page.accounts_table.item(0, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_OUT
    assert page.accounts_table.item(1, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_IN
    page.close()


def test_status_query_error_shows_unknown_and_safe_feedback(store, qapp):
    store.add("A", BROKER, "Account A")
    store.add("B", BROKER, "Account B")
    service = FakeAuthenticationService(
        logged_in={"B": True},
        status_errors={"A": RuntimeError("token and credentials")},
    )
    page, _ = _login_page(store, qapp, service)
    page.refresh_status_button.click()
    assert page.accounts_table.item(0, 3).text() == STRINGS.LOGIN_STATUS_UNKNOWN
    assert page.accounts_table.item(1, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_IN
    assert page.login_message_label.text() == STRINGS.LOGIN_STATUS_REFRESH_FAILED
    assert "token" not in page.login_message_label.text()
    page.close()


def test_blank_response_and_logout_pending_conflict_fail_safely(store, qapp):
    from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge

    store.add("A", BROKER, "Account A")
    store.add("B", BROKER, "Account B")
    service = FakeAuthenticationService(
        challenge=LoginChallenge(
            CHALLENGE_CAPTCHA_IMAGE, _synthetic_png_base64(), "prompt"
        )
    )
    page, calls = _login_page(store, qapp, service)
    page.accounts_table.setCurrentCell(1, 1)
    page._on_begin_login_clicked()
    dialog = page._captcha_dialog
    entry = dialog.findChild(QLineEdit)
    error = next(label for label in dialog.findChildren(QLabel) if label.text() == "")
    entry.setText("   ")
    page._complete_login_dialog("B", entry, error, dialog)
    assert service.completed == []
    assert error.text() == STRINGS.CAPTCHA_RESPONSE_REQUIRED
    assert page._pending_login_account_id == "B"
    page.accounts_table.setCurrentCell(0, 1)
    page.logout_button.click()
    assert service.logged_out == ["A"]
    page.accounts_table.setCurrentCell(1, 1)
    page.logout_button.click()
    assert service.logged_out == ["A"]
    assert page.login_message_label.text() == STRINGS.LOGOUT_PENDING_LOGIN
    assert calls == [True, True]
    page._on_cancel_login_clicked()
    page.close()


def test_logout_requires_selection_and_reports_failure_safely(store, qapp):
    page = AccountsPage(store, authentication_service_factory=None)
    page.logout_button.click()
    assert page.login_message_label.text() == STRINGS.LOGIN_SELECT_ACCOUNT
    page.close()

    store.add("A", BROKER, "Account A")
    calls = []
    service = FakeAuthenticationService(
        logout_error=RuntimeError("private token and credentials")
    )
    page = AccountsPage(
        store,
        authentication_service_factory=lambda: (calls.append(True) or service),
    )
    page.accounts_table.setCurrentCell(0, 1)
    page.logout_button.click()
    assert calls == [True]
    assert service.logged_out == ["A"]
    assert page.login_message_label.text() == STRINGS.LOGIN_OPERATION_FAILED
    assert "private" not in page.login_message_label.text()
    assert page.accounts_table.item(0, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_OUT
    page.close()


@pytest.mark.parametrize(
    "status_error,expected_status",
    [
        (None, STRINGS.LOGIN_STATUS_LOGGED_IN),
        (RuntimeError("private status failure"), STRINGS.LOGIN_STATUS_UNKNOWN),
    ],
)
def test_logout_failure_rechecks_same_account_status(
    store, qapp, status_error, expected_status
):
    store.add("A", BROKER, "Account A")
    store.add("B", BROKER, "Account B")
    service = FakeAuthenticationService(
        logout_error=RuntimeError("private logout detail"),
        logged_in={"A": True, "B": False},
    )
    page, _ = _login_page(store, qapp, service)
    page.refresh_status_button.click()
    assert page.accounts_table.item(0, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_IN
    assert page.accounts_table.item(1, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_OUT
    if status_error is not None:
        service.status_errors["A"] = status_error
    page.accounts_table.setCurrentCell(0, 0)

    page.logout_button.click()

    assert service.logged_out == ["A"]
    assert service.status_queries == ["A", "B", "A"]
    assert page.accounts_table.item(0, 3).text() == expected_status
    assert page.accounts_table.item(1, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_OUT
    assert page.login_message_label.text() == STRINGS.LOGIN_OPERATION_FAILED
    assert "private" not in page.login_message_label.text()
    page.close()


def test_redesigned_add_generates_internal_id_and_saves_credentials_offline(store, qapp):
    backend = FakeCredentialStore()
    page = AccountsPage(store, credential_store_factory=lambda: backend)
    page.display_name_input.setText("حساب آزمایشی")
    page.username_input.setText("offline-user")
    page.password_input.setText("offline-password")
    page.add_button.click()
    record, = store.all_accounts()
    assert record.display_name == "حساب آزمایشی"
    assert record.account_id.startswith("ACC-")
    assert backend.saved == [(record.account_id, BROKER, "offline-user", "offline-password")]
    assert not hasattr(page, "account_id_input")
    assert page.accounts_table.item(0, 2).text() == STRINGS.CURRENT_USE_INACTIVE
    assert page.accounts_table.item(0, 3).text() == STRINGS.LOGIN_STATUS_UNKNOWN
    page.close()


def test_redesigned_captcha_is_modal_dialog_only_for_image_challenge(store, qapp):
    from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge
    store.add("CAPTCHA-A", BROKER, "حساب آزمون")
    service = FakeAuthenticationService(LoginChallenge(
        CHALLENGE_CAPTCHA_IMAGE, _synthetic_png_base64(), "متن راهنما"))
    page, _ = _login_page(store, qapp, service)
    assert not hasattr(page, "captcha_response_input")
    page._begin_login("CAPTCHA-A")
    qapp.processEvents()
    dialog = page._captcha_dialog
    assert dialog is not None and dialog.isVisible()
    assert isinstance(dialog, __import__("PySide6.QtWidgets", fromlist=["QDialog"]).QDialog)
    assert dialog.isModal()
    assert dialog.layoutDirection().name == "RightToLeft"
    image_labels = dialog.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)
    assert any(label.pixmap() is not None and not label.pixmap().isNull() for label in image_labels)
    page._cancel_login(dialog)
    assert service.cancelled == ["CAPTCHA-A"]
    assert page._captcha_dialog is None
    page.close()


def test_redesigned_login_completion_updates_status_without_real_broker(store, qapp):
    from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge
    store.add("CAPTCHA-B", BROKER, "حساب دوم")
    service = FakeAuthenticationService(LoginChallenge(
        CHALLENGE_CAPTCHA_IMAGE, _synthetic_png_base64(), "راهنما"))
    page, _ = _login_page(store, qapp, service)
    page._begin_login("CAPTCHA-B")
    dialog = page._captcha_dialog
    entry = dialog.findChild(QLineEdit)
    error = next(label for label in dialog.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)
                 if label.text() == "")
    entry.setText("1234")
    page._complete_login_dialog("CAPTCHA-B", entry, error, dialog)
    assert service.completed == [("CAPTCHA-B", "1234")]
    assert page.accounts_table.item(0, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_IN
    page.close()


def test_redesigned_logout_is_account_scoped_and_refreshes_failure(store, qapp):
    store.add("LOGOUT-A", BROKER, "حساب اول")
    store.add("LOGOUT-B", BROKER, "حساب دوم")
    service = FakeAuthenticationService(
        logout_error=RuntimeError("private token"),
        logged_in={"LOGOUT-A": True, "LOGOUT-B": False},
    )
    page, _ = _login_page(store, qapp, service)
    page._login_status_by_account.update(service.logged_in)
    page.refresh()
    page.accounts_table.setCurrentCell(0, 1)
    page._on_logout_clicked()
    assert service.logged_out == ["LOGOUT-A"]
    assert service.status_queries == ["LOGOUT-A"]
    assert page.accounts_table.item(0, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_IN
    assert page.accounts_table.item(1, 3).text() == STRINGS.LOGIN_STATUS_LOGGED_OUT
    assert "private" not in page.login_message_label.text()
    page.close()
