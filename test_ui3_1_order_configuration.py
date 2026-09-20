"""
test_ui3_1_order_configuration.py

UI-3.1 Order Configuration Foundation tests (fully offline, deterministic).

Contract coverage:

    Test 1  — Order Configuration page opens from MainWindow.
    Test 2  — Symbol input/selection state exists.
    Test 3  — Side is only BUY/SELL, bound to the real project constants.
    Test 4  — Price can be entered and stored.
    Test 5  — Quantity can be entered and stored.
    Test 6  — Base Amount == price * quantity.
    Test 7  — Final Amount is NOT computed while no fee contract exists.
    Test 8  — Fee is never fabricated.
    Test 9  — No nsc_id is guessed or produced by the UI.
    Test 10 — Active account comes from the existing AccountStore; no
              fallback.
    Test 11 — No active account is shown transparently.
    Test 12 — Symbol status is never reported as tradable/permitted
              without a verified source.
    Test 13 — Constructing the page performs no network/API/TSETMC/Broker
              operation (socket silence in a clean subprocess).
    Test 14 — main.py / SymbolSearchWindow stay untouched (AST import
              check over ui/).
    Test 15 — UI-1 and UI-2.1 regression contracts preserved
              (navigation, mode, placeholders, account store behavior).

These tests are fully offline:
  - no network
  - no login
  - no broker API
  - no TSETMC call
  - no real order

Run:
    pytest -q test_ui3_1_order_configuration.py
"""

import os
import subprocess
import sys

import pytest

from PySide6.QtWidgets import QApplication

from models.instrument import Instrument
from models.order import BUY, SELL

from ui.account_store import AccountStore
from ui.main_window import MainWindow
from ui.order_config_state import (
    SYMBOL_STATUS_NOT_AVAILABLE,
    OrderConfigError,
    OrderConfiguration,
)
from ui.order_configuration_page import OrderConfigurationPage


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


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


@pytest.fixture()
def window(qapp):
    return MainWindow()


# ============================================================
# Test 1 — Order Configuration page opens from MainWindow
# ============================================================


def test_1_order_configuration_page_opens(window):
    assert isinstance(window.order_configuration_page, OrderConfigurationPage)
    assert window.pages["Order Configuration"] is window.order_configuration_page
    assert "Order Configuration" in window.nav_buttons

    window.nav_buttons["Order Configuration"].click()
    assert (
        window.content_area.currentWidget() is window.order_configuration_page
    )


# ============================================================
# Test 2 — Symbol input/selection state exists
# ============================================================


def test_2_symbol_state_exists(qapp, store):
    page = OrderConfigurationPage(store)
    config = page.config

    # state exists (None until real data arrives)
    assert config.selected_instrument is None

    # a real Instrument can be stored as the selection
    real = Instrument(
        symbol="آکو",
        name="آکو باتري ايرانيان",
        ins_code="60235881999727383",
    )
    config.select_instrument(real)
    assert config.selected_instrument is real

    # typing a symbol only mirrors text state — no resolution happens
    page.symbol_input.setCurrentText("آکو")
    assert page.symbol_text == "آکو"
    assert config.selected_instrument is real  # untouched by typing

    # a non-instrument object is rejected — no fake instrument is created
    with pytest.raises(OrderConfigError):
        config.select_instrument("آکو")

    # a fake object merely carrying ins_code is rejected (strict
    # isinstance validation, not attribute sniffing)
    class FakeInstrument:
        ins_code = "FAKE"

    with pytest.raises(OrderConfigError):
        config.select_instrument(FakeInstrument())
    # rejected selection never replaced the stored state
    assert config.selected_instrument is real


# ============================================================
# Test 3 — Side only BUY/SELL, bound to real constants
# ============================================================


def test_3_side_uses_real_constants(qapp, store):
    page = OrderConfigurationPage(store)

    # exactly the two real sides, mapped to user-facing labels
    assert set(page.side_buttons) == {BUY, SELL}
    labels = [page.side_buttons[side].text() for side in (BUY, SELL)]
    assert labels == ["خرید", "فروش"]

    # bound to the real constants — nothing new was invented
    config = page.config
    config.set_side(BUY)
    assert config.side == 1
    page.side_buttons[SELL].click()
    assert config.side == SELL == 2

    with pytest.raises(OrderConfigError):
        config.set_side(3)
    with pytest.raises(OrderConfigError):
        config.set_side("BUY")


# ============================================================
# Test 4 — Price can be entered and stored
# ============================================================


def test_4_price_enter_and_store(qapp, store):
    page = OrderConfigurationPage(store)

    page.price_input.setText("15000")
    page.price_input.editingFinished.emit()
    assert page.config.price == 15000
    assert isinstance(page.config.price, int)  # Core Order contract: int

    # fractional input rejected, previous valid state preserved
    page.price_input.setText("15000.5")
    page.price_input.editingFinished.emit()
    assert page.config.price == 15000

    # invalid text rejected, previous valid state preserved
    page.price_input.setText("abc")
    page.price_input.editingFinished.emit()
    assert page.config.price == 15000

    with pytest.raises(OrderConfigError):
        page.config.set_price("15000")
    with pytest.raises(OrderConfigError):
        page.config.set_price(-1)

    # empty input clears the value (basic input handling)
    page.price_input.setText("")
    page.price_input.editingFinished.emit()
    assert page.config.price is None


# ============================================================
# Test 5 — Quantity can be entered and stored
# ============================================================


def test_5_quantity_enter_and_store(qapp, store):
    page = OrderConfigurationPage(store)

    page.quantity_input.setText("500")
    page.quantity_input.editingFinished.emit()
    assert page.config.quantity == 500
    assert isinstance(page.config.quantity, int)  # Core Order contract: int

    # fractional input rejected, previous valid state preserved
    page.quantity_input.setText("500.5")
    page.quantity_input.editingFinished.emit()
    assert page.config.quantity == 500

    page.quantity_input.setText("abc")
    page.quantity_input.editingFinished.emit()
    assert page.config.quantity == 500

    with pytest.raises(OrderConfigError):
        page.config.set_quantity(-5)

    page.quantity_input.setText("")
    page.quantity_input.editingFinished.emit()
    assert page.config.quantity is None


# ============================================================
# Test 6 — Base Amount == price * quantity
# ============================================================


def test_6_base_amount_is_price_times_quantity(qapp, store):
    page = OrderConfigurationPage(store)

    page.price_input.setText("15000")
    page.price_input.editingFinished.emit()
    page.quantity_input.setText("500")
    page.quantity_input.editingFinished.emit()

    base = page.config.base_amount()
    assert base == 15000 * 500
    assert isinstance(base, int)  # int * int -> int
    # displayed as a plain integer — scientific notation is never used
    # for the integer base amount
    assert "e" not in page.base_amount_label.text().lower()
    digits = page.base_amount_label.text().replace(",", "").replace("\u066c", "")
    assert digits == "7500000"


# ============================================================
# Test 7 — Final Amount NOT computed without a fee contract
# ============================================================


def test_7_final_amount_not_computed(qapp, store):
    page = OrderConfigurationPage(store)

    page.price_input.setText("15000")
    page.price_input.editingFinished.emit()
    page.quantity_input.setText("500")
    page.quantity_input.editingFinished.emit()

    assert page.config.final_amount() is None
    assert page.final_amount_label.text() == "Not available"


# ============================================================
# Test 8 — Fee never fabricated
# ============================================================


def test_8_fee_never_fabricated(qapp, store):
    page = OrderConfigurationPage(store)

    assert page.fee_label.text() == "Not available"
    # the config object carries no fee field/value at all
    assert not hasattr(page.config, "fee")
    assert not hasattr(page.config, "fee_rate")
    assert not hasattr(page.config, "commission")


# ============================================================
# Test 9 — no nsc_id guessed or produced by the UI
# ============================================================


def test_9_no_nsc_id_guessed_or_produced(qapp, store):
    page = OrderConfigurationPage(store)

    # fill everything the UI knows — still no nsc_id anywhere
    page.config.select_instrument(
        Instrument(symbol="آکو", name="آکو", ins_code="60235881999727383")
    )
    page.config.set_side(BUY)
    page.config.set_price(15000)
    page.config.set_quantity(500)

    config = page.config
    assert not hasattr(config, "nsc_id")
    assert not hasattr(config, "to_payload")
    assert not hasattr(config, "to_order")
    # not a Core Order object
    from models.order import Order

    assert not isinstance(config, Order)
    # the page holds no execution path either
    for attr in ("order_engine", "dispatch", "submit", "send"):
        assert not hasattr(page, attr), f"page has forbidden attribute: {attr}"


# ============================================================
# Test 10 — active account from the existing store; no fallback
# ============================================================


def test_10_active_account_from_store_no_fallback(qapp):
    window = MainWindow()

    # same store object shared between UI-2.1 page and UI-3.1 page
    assert window.order_configuration_page.store is window.account_store
    assert window.accounts_page.store is window.account_store

    # with no active account: no fallback is used
    window.account_store.add("ACC-001", "آگاه")
    window.order_configuration_page.refresh_active_account()
    text_no_active = window.order_configuration_page.active_account_label.text()
    assert "No active account" in text_no_active
    assert "ACC-001" not in text_no_active  # accounts[0] never used

    # explicit selection in UI-2.1 is what UI-3.1 shows
    window.account_store.set_active("ACC-001")
    window.order_configuration_page.refresh_active_account()
    assert "ACC-001" in window.order_configuration_page.active_account_label.text()


# ============================================================
# Test 11 — no active account is shown transparently
# ============================================================


def test_11_no_active_account_shown_transparently(qapp, store):
    page = OrderConfigurationPage(store)

    assert store.active_account_id() is None
    assert "No active account" in page.active_account_label.text()


# ============================================================
# Test 12 — symbol status never shown as tradable without data
# ============================================================


def test_12_symbol_status_fail_closed(qapp, store):
    page = OrderConfigurationPage(store)

    assert page.config.symbol_status() == SYMBOL_STATUS_NOT_AVAILABLE == "Not available"
    assert "tradable" not in page.symbol_status_label.text().lower()
    assert "permitted" not in page.symbol_status_label.text().lower()
    # even with a real instrument selected (no verified source connected yet)
    page.config.select_instrument(
        Instrument(symbol="آکو", name="آکو", ins_code="1")
    )
    page._refresh_symbol_info()
    assert "Status: Not available" in page.symbol_status_label.text()


# ============================================================
# Test 13 — no network/API/TSETMC/Broker operation on construction
# ============================================================


def test_13_page_construction_performs_no_network_or_broker_operation():
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
            "",
            "import ui.app as ui_app",
            "from ui.account_store import AccountStore",
            "from ui.main_window import MainWindow",
            "",
            "banned = ('brokers', 'market', 'core')",
            "leaked = sorted(m for m in sys.modules if m.split('.')[0] in banned)",
            "assert not leaked, f'UI imported forbidden modules: {leaked}'",
            "",
            "app = ui_app.create_app([])",
            "window = MainWindow()",
            "window.nav_buttons['Order Configuration'].click()",
            "page = window.order_configuration_page",
            "page.symbol_input.setCurrentText('آکو')",
            "page.price_input.setText('15000')",
            "page.price_input.editingFinished.emit()",
            "page.quantity_input.setText('500')",
            "page.quantity_input.editingFinished.emit()",
            "page.side_buttons[1].click()",
            "app.processEvents()",
            "assert page.config.base_amount() == 15000 * 500",
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
# Test 14 — main.py / SymbolSearchWindow stay untouched
# ============================================================


def test_14_ui_does_not_use_legacy_main():
    """AST check: no ui/ module may import main/brokers/market/core."""
    import ast

    banned_top = {"main", "brokers", "market", "core"}

    ui_dir = os.path.join(REPO_ROOT, "ui")
    for file_name in sorted(os.listdir(ui_dir)):
        if not file_name.endswith(".py"):
            continue
        path = os.path.join(ui_dir, file_name)
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in banned_top, (
                        f"ui/{file_name} imports '{alias.name}'"
                    )
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                assert root not in banned_top, (
                    f"ui/{file_name} imports from '{node.module}'"
                )

    import ui.main_window

    assert not hasattr(ui.main_window, "SymbolSearchWindow")


# ============================================================
# Test 15 — UI-1 and UI-2.1 regression contracts preserved
# ============================================================


def test_15_ui1_and_ui2_1_contracts_preserved(window):
    # UI-1: navigation, initial page, mode contracts
    assert set(window.pages) == {
        "Home", "Accounts", "Order Configuration", "Settings",
    }
    assert set(window.placeholder_pages) == {"Home", "Settings"}
    assert window.content_area.currentWidget() is window.pages["Home"]
    from ui.main_window import ApplicationMode

    assert window.mode is ApplicationMode.NORMAL
    window.set_mode(ApplicationMode.DIAGNOSTIC)
    assert window.mode is ApplicationMode.DIAGNOSTIC

    # UI-2.1: Accounts page still real, store still in-memory with the
    # same rules (no auto-active, duplicate rejection, single active)
    assert "Accounts" not in window.placeholder_pages
    store = window.account_store
    store.add("ACC-001", "آگاه")
    store.add("ACC-002", "آگاه")
    assert store.active_account_id() is None
    import pytest as _pytest
    from ui.account_store import AccountStoreError

    with _pytest.raises(AccountStoreError):
        store.add("ACC-001", "آگاه")
    store.set_active("ACC-002")
    assert store.is_active("ACC-001") is False
    assert store.is_active("ACC-002") is True


# ============================================================
# Extra — numeric type alignment (Core Order contract: price/quantity int)
# ============================================================


def test_extra_price_int_contract(qapp, store):
    """Price accepts only int; float/bool/str/negative are rejected."""
    config = OrderConfiguration()

    assert config.set_price(15000) == 15000
    assert isinstance(config.price, int)

    # float is rejected even when its value is integral (15000.0)
    with pytest.raises(OrderConfigError):
        config.set_price(15000.0)
    with pytest.raises(OrderConfigError):
        config.set_price(15000.5)
    with pytest.raises(OrderConfigError):
        config.set_price(True)
    with pytest.raises(OrderConfigError):
        config.set_price("15000")
    with pytest.raises(OrderConfigError):
        config.set_price(-1)
    assert config.price == 15000  # previous valid state preserved


def test_extra_quantity_int_contract(qapp, store):
    """Quantity accepts only int; float/bool/str/negative are rejected."""
    config = OrderConfiguration()

    assert config.set_quantity(500) == 500
    assert isinstance(config.quantity, int)

    # float is rejected even when its value is integral (500.0)
    with pytest.raises(OrderConfigError):
        config.set_quantity(500.0)
    with pytest.raises(OrderConfigError):
        config.set_quantity(500.5)
    with pytest.raises(OrderConfigError):
        config.set_quantity(True)
    with pytest.raises(OrderConfigError):
        config.set_quantity("500")
    with pytest.raises(OrderConfigError):
        config.set_quantity(-5)
    assert config.quantity == 500  # previous valid state preserved


def test_extra_page_preserves_state_on_fractional_input(qapp, store):
    """Mandatory: fractional entry keeps the previous valid int state."""
    page = OrderConfigurationPage(store)

    page.price_input.setText("15000")
    page.price_input.editingFinished.emit()
    page.quantity_input.setText("500")
    page.quantity_input.editingFinished.emit()

    page.price_input.setText("15000.5")
    page.price_input.editingFinished.emit()
    assert page.config.price == 15000

    page.quantity_input.setText("500.5")
    page.quantity_input.editingFinished.emit()
    assert page.config.quantity == 500

    # base amount remains the integer product
    assert page.config.base_amount() == 15000 * 500


# ============================================================
# Extra — mandatory: strict Instrument validation
# ============================================================


def test_extra_select_instrument_rejects_fake_object(qapp, store):
    """
    Only a genuine models.instrument.Instrument (or None) is accepted.
    A fake object with an ins_code attribute must raise OrderConfigError.
    """
    page = OrderConfigurationPage(store)
    config = page.config

    class FakeInstrument:
        ins_code = "FAKE"

    fake = FakeInstrument()
    with pytest.raises(OrderConfigError):
        config.select_instrument(fake)
    assert config.selected_instrument is None  # nothing was stored

    # a real project Instrument is accepted
    real = Instrument(symbol="S", name="N", ins_code="42")
    config.select_instrument(real)
    assert config.selected_instrument is real


# ============================================================
# Extra — mandatory: active-account refresh on re-entry
# ============================================================


def test_extra_active_account_refreshed_on_page_reentry(qapp):
    """
    Mandatory flow: changing the active account on the Accounts page and
    returning to Order Configuration must re-read the active account
    from the shared AccountStore (no fallback, no guessing).
    """
    window = MainWindow()
    store = window.account_store

    store.add("ACC-001", "آگاه")
    store.add("ACC-002", "آگاه")

    # 1. activate the first account
    store.set_active("ACC-001")

    # 2. open Order Configuration -> shows ACC-001
    window.nav_buttons["Order Configuration"].click()
    label = window.order_configuration_page.active_account_label.text()
    assert "ACC-001" in label
    assert "ACC-002" not in label

    # 3. switch the active account to the second one
    store.set_active("ACC-002")

    # 4. return to Order Configuration -> must now show ACC-002
    window.nav_buttons["Home"].click()
    window.nav_buttons["Order Configuration"].click()
    label = window.order_configuration_page.active_account_label.text()
    assert "ACC-002" in label
    assert "ACC-001" not in label
