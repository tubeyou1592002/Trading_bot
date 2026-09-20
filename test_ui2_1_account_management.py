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

import pytest

from PySide6.QtWidgets import QApplication

from models.account import Account, AccountValidationError

from ui.account_store import AccountStore, AccountStoreError, AccountRecord
from ui.accounts_page import AccountsPage, AVAILABLE_BROKERS
from ui.main_window import MainWindow


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
    return AccountStore()


# ============================================================
# Test 1 — MainWindow shows the real Accounts page
# ============================================================


def test_1_main_window_shows_real_accounts_page(qapp):
    window = MainWindow()

    assert isinstance(window.accounts_page, AccountsPage)
    assert window.pages["Accounts"] is window.accounts_page
    assert window.content_area.currentWidget() is window.pages["Home"]

    window.nav_buttons["Accounts"].click()
    assert window.content_area.currentWidget() is window.accounts_page


# ============================================================
# Test 2 — account created from account_id + broker_name
# ============================================================


def test_2_account_created_from_id_and_broker(store):
    record = store.add("ACC-001", BROKER)

    assert isinstance(record, AccountRecord)
    assert record.account_id == "ACC-001"
    assert record.broker_name == BROKER
    assert record in store.all_accounts()


# ============================================================
# Test 3 — record holds a real models.account.Account
# ============================================================


def test_3_record_uses_real_account_model(store):
    record = store.add("ACC-001", BROKER)

    assert isinstance(record.account, Account)
    # identity lives on the Account model itself — never invented
    assert record.account.account_id == "ACC-001"


# ============================================================
# Test 4 — two accounts with different identities stay independent
# ============================================================


def test_4_accounts_stay_independent(store):
    first = store.add("ACC-001", BROKER)
    second = store.add("ACC-002", BROKER)

    assert first.account_id == "ACC-001"
    assert second.account_id == "ACC-002"
    assert first.account is not second.account
    assert first.account.account_id != second.account.account_id
    assert len(store.all_accounts()) == 2


# ============================================================
# Test 5 — broker association is exactly the registered name
# ============================================================


def test_5_broker_association_is_exact(store):
    record = store.add("ACC-001", BROKER)

    assert record.broker_name == BROKER
    # association lives on the record, not on the Account model
    assert not hasattr(record.account, "broker_name")
    # selector currently offers exactly the implemented broker
    assert AVAILABLE_BROKERS == (BROKER,)


# ============================================================
# Test 6 — no account active initially
# ============================================================


def test_6_no_account_active_initially(store):
    store.add("ACC-001", BROKER)

    assert store.active_account_id() is None
    assert store.is_active("ACC-001") is False


# ============================================================
# Test 7 — an account can be activated
# ============================================================


def test_7_account_can_be_activated(store):
    store.add("ACC-001", BROKER)
    result = store.set_active("ACC-001")

    assert result == "ACC-001"
    assert store.active_account_id() == "ACC-001"
    assert store.is_active("ACC-001") is True


# ============================================================
# Test 8 — activating the second deactivates the first
# ============================================================


def test_8_second_activation_deactivates_first(store):
    store.add("ACC-001", BROKER)
    store.add("ACC-002", BROKER)

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
        store.add("", BROKER)
    with pytest.raises((AccountStoreError, AccountValidationError)):
        store.add("   ", BROKER)
    with pytest.raises((AccountStoreError, AccountValidationError)):
        store.add(None, BROKER)
    with pytest.raises((AccountStoreError, AccountValidationError)):
        store.add(123, BROKER)

    # nothing was registered
    assert store.all_accounts() == ()
    # activating an unknown/invalid id is also rejected
    with pytest.raises(AccountStoreError):
        store.set_active("ACC-DOES-NOT-EXIST")


# ============================================================
# Test 10 — duplicate account ids are rejected
# ============================================================


def test_10_duplicate_account_id_rejected(store):
    store.add("ACC-001", BROKER)

    with pytest.raises(AccountStoreError):
        store.add("ACC-001", BROKER)

    # still exactly one record, identity unchanged
    assert len(store.all_accounts()) == 1
    assert store.all_accounts()[0].account_id == "ACC-001"


# ============================================================
# Test 11 — constructing AccountsPage creates no real broker
# ============================================================


def test_11_accounts_page_creates_no_real_broker(store, qapp):
    page = AccountsPage(store)

    assert page.account_id_input is not None
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
            "store.add('ACC-001', 'آگاه')",
            "store.add('ACC-002', 'آگاه')",
            "store.set_active('ACC-002')",
            "page.refresh()",
            "page.accounts_table.selectRow(0)",
            "page._on_set_active_clicked()",
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
    window = MainWindow()

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
    page = AccountsPage(store)

    page.account_id_input.setText("ACC-001")
    page.add_button.click()
    page.account_id_input.setText("ACC-002")
    page.add_button.click()

    assert [r.account_id for r in store.all_accounts()] == ["ACC-001", "ACC-002"]
    assert page.accounts_table.rowCount() == 2

    page.accounts_table.selectRow(0)
    page.set_active_button.click()
    assert store.active_account_id() == "ACC-001"
    assert page.accounts_table.item(0, 2).text() == "Yes"
    assert page.accounts_table.item(1, 2).text() == ""

    page.accounts_table.selectRow(1)
    page.set_active_button.click()
    assert store.active_account_id() == "ACC-002"
    assert page.accounts_table.item(0, 2).text() == ""
    assert page.accounts_table.item(1, 2).text() == "Yes"
