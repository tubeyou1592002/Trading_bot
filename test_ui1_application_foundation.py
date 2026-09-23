"""
test_ui1_application_foundation.py

UI-1 Application Foundation tests (fully offline, deterministic).

Contract coverage:

    Test 1  — `ui` is importable.
    Test 2  — MainWindow is constructible.
    Test 3  — Navigation contains exactly Home / Accounts / Settings.
    Test 4  — Home is the initial page.
    Test 5  — Navigation switches between the pages.
    Test 6  — Default mode is NORMAL.
    Test 7  — Mode can change to DIAGNOSTIC.
    Test 8  — Invalid mode values are rejected.
    Test 9  — Constructing MainWindow imports NO core/brokers/market/main
              (models: Account / Order side / Instrument / TradingState
              whitelisted domain reuse only).
              module (models is allowed only via the whitelisted reuse of
              domain models: Account, Order side BUY/SELL, Instrument).
    Test 10 — Constructing the UI performs no network/API/login operation
              (no socket, no urllib/requests/httpx import).
    Test 11 — The new User Application does not use main.py /
              SymbolSearchWindow.

    Extra   — create_app() contract: succeeds with no QApplication,
              RuntimeError when one already exists.

UI-2.1 note: the Accounts page is now the real AccountsPage (see
 test_ui2_1_account_management.py); Home and Settings remain placeholders.
 Home is still the initial page and the navigation/mode contracts are
 unchanged.

These tests are fully offline:
  - no network
  - no login
  - no broker API
  - no TSETMC call
  - no real order

Run:
    pytest -q test_ui1_application_foundation.py
"""

import os
import subprocess
import sys

import pytest

from PySide6.QtWidgets import QApplication

import ui  # noqa: F401  (Test 1: the package is importable)
import ui.app as ui_app
from ui.main_window import ApplicationMode, MainWindow


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

# The em dash is spelled as an escape so title comparisons can never be
# corrupted by editor/terminal encoding handling.
EXPECTED_TITLE = "Trading Bot \u2014 User Application"


@pytest.fixture(scope="module")
def qapp():
    """Reuse the process-wide QApplication if one exists, else create one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ============================================================
# Test 1 — importability
# ============================================================


def test_1_ui_package_is_importable():
    import ui
    import ui.__main__  # entry module must import cleanly (guard protects exec)
    import ui.app
    import ui.main_window

    assert ui.app is ui_app
    assert callable(ui_app.create_app)
    assert callable(ui_app.main)


# ============================================================
# Test 2 — MainWindow is constructible
# ============================================================


def test_2_main_window_is_constructible(qapp):
    window = MainWindow()

    assert window.windowTitle() == EXPECTED_TITLE
    assert window.centralWidget() is not None
    assert window.layout() is not None
    # logical initial size
    assert window.size().width() >= 800
    assert window.size().height() >= 560
    # designated, extensible content area exists
    assert window.content_area is not None
    # pages: Home, Accounts, Order Configuration, Settings
    assert window.content_area.count() == 4


# ============================================================
# Test 3 — Navigation contains exactly the three placeholders
# ============================================================


def test_3_navigation_placeholders_exact(qapp):
    window = MainWindow()

    assert window.navigation_area is not None
    # navigation: Home/Accounts/Settings plus Order Configuration
    # (added by UI-3.1); placeholders: Home/Settings only
    # (Accounts real since UI-2.1, Order Configuration since UI-3.1)
    assert set(window.nav_buttons) == {
        "Home", "Accounts", "Order Configuration", "Settings",
    }
    # pages: all four entries; placeholders: Home/Settings only
    # (Accounts real since UI-2.1, Order Configuration since UI-3.1)
    assert set(window.pages) == {
        "Home", "Accounts", "Order Configuration", "Settings",
    }
    assert set(window.placeholder_pages) == {"Home", "Settings"}


# ============================================================
# Test 4 — Home is the initial page
# ============================================================


def test_4_home_is_initial_page(qapp):
    window = MainWindow()

    assert window.content_area.currentWidget() is window.placeholder_pages["Home"]


# ============================================================
# Test 5 — Navigation switching works between pages
# ============================================================


def test_5_navigation_switching_works(qapp):
    window = MainWindow()

    window.nav_buttons["Settings"].click()
    assert window.content_area.currentWidget() is window.placeholder_pages["Settings"]
    window.nav_buttons["Accounts"].click()
    assert window.content_area.currentWidget() is window.accounts_page
    window.nav_buttons["Home"].click()
    assert window.content_area.currentWidget() is window.placeholder_pages["Home"]


# ============================================================
# Test 6 — default mode is NORMAL
# ============================================================


def test_6_default_mode_is_normal(qapp):
    window = MainWindow()

    assert window.mode is ApplicationMode.NORMAL


# ============================================================
# Test 7 — mode can change to DIAGNOSTIC
# ============================================================


def test_7_mode_can_change_to_diagnostic(qapp):
    window = MainWindow()

    window.set_mode(ApplicationMode.DIAGNOSTIC)
    assert window.mode is ApplicationMode.DIAGNOSTIC

    window.set_mode(ApplicationMode.NORMAL)
    assert window.mode is ApplicationMode.NORMAL


# ============================================================
# Test 8 — invalid mode values are rejected (state preserved)
# ============================================================


def test_8_invalid_mode_rejected(qapp):
    window = MainWindow()

    with pytest.raises(ValueError):
        window.set_mode("DIAGNOSTIC")
    with pytest.raises(ValueError):
        window.set_mode(None)
    with pytest.raises(ValueError):
        MainWindow(mode="NORMAL")
    # state preserved after rejections
    assert window.mode is ApplicationMode.NORMAL


# ============================================================
# Test 9 — construction imports NO trading module (clean subprocess)
# ============================================================


def test_9_construction_imports_no_trading_module():
    code = "\n".join(
        [
            "import sys",
            "import ui.app as ui_app",
            "from ui.main_window import MainWindow",
            "app = ui_app.create_app([])",
            "window = MainWindow()",
            "banned = ('brokers', 'market', 'core', 'main')",
            "leaked = sorted(m for m in sys.modules if m.split('.')[0] in banned)",
            "assert not leaked, f'UI foundation imported trading modules: {leaked}'",
            "# UI-2.1/UI-3.1/UI-3.2B: only whitelisted model modules",
            "allowed = {m for m in sys.modules if m.split('.')[0] == 'models'}",
            "whitelist = {'models', 'models.account', 'models.order', 'models.instrument', 'models.trading_state'}",
            "assert allowed <= whitelist, ("
            "f'unexpected models modules imported: {allowed - whitelist}')",
            "assert not hasattr(window, 'broker_manager')",
            "assert not hasattr(window, 'order_engine')",
            "print('NO_TRADING_MODULE_OK')",
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
    assert "NO_TRADING_MODULE_OK" in result.stdout


# ============================================================
# Test 10 — construction performs no network/API/login operation
# ============================================================


def test_10_construction_performs_no_network_or_login():
    code = "\n".join(
        [
            "import sys",
            "import socket",
            "import urllib.request, urllib.parse",
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
            "from ui.main_window import MainWindow",
            "app = ui_app.create_app([])",
            "window = MainWindow()",
            "window.show()",
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
    assert "requests" not in result.stdout


# ============================================================
# Test 11 — new UI does not use main.py / SymbolSearchWindow
# ============================================================


def test_11_new_ui_does_not_use_legacy_main(qapp):
    """
    The UI Foundation must not import or reuse the legacy main.py
    application (SymbolSearchWindow stays untouched and separate).

    Checked via AST: no real `import main` / `from main import ...` node
    may exist in any ui/ module (docstring mentions are harmless).
    UI-3.2A/3.2B: only the documented lazy seams (market.symbol_resolver,
    brokers.manager, core.trading_state_query) are allowed.
    """
    import ast

    banned_top = {"main", "brokers", "core"}
    # UI-3.2A seam: ui/main_window.py imports the real repository
    # resolver (market.symbol_resolver) LAZILY — inside a function, at
    # actual search time — keeping construction offline. No other
    # market.* import (e.g. market.tsetmc) is allowed anywhere in ui/.
    allowed_market = {"market.symbol_resolver"}
    # UI-3.2B seam: the trading-state display builds the EXISTING
    # read-only TradingStateQuery path LAZILY (inside the factory
    # function), so construction stays offline — same pattern as the
    # UI-3.2A resolver. No other brokers.* / core.* import is allowed.
    allowed_brokers = {"brokers.manager"}
    allowed_core = {"core.trading_state_query"}

    for module_name in ("__init__", "app", "main_window", "__main__"):
        path = os.path.join(REPO_ROOT, "ui", f"{module_name}.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root == "market":
                        assert alias.name in allowed_market, (
                            f"ui/{module_name}.py imports '{alias.name}' — "
                            f"only {sorted(allowed_market)} is allowed"
                        )
                    elif root == "brokers":
                        assert alias.name in allowed_brokers, (
                            f"ui/{module_name}.py imports '{alias.name}' — "
                            f"only {sorted(allowed_brokers)} is allowed"
                        )
                    elif root == "core":
                        assert alias.name in allowed_core, (
                            f"ui/{module_name}.py imports '{alias.name}' — "
                            f"only {sorted(allowed_core)} is allowed"
                        )
                    else:
                        assert root not in banned_top, (
                            f"ui/{module_name}.py imports '{alias.name}'"
                        )
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root == "market":
                    assert node.module in allowed_market, (
                        f"ui/{module_name}.py imports from '{node.module}' — "
                        f"only {sorted(allowed_market)} is allowed"
                    )
                elif root == "brokers":
                    assert node.module in allowed_brokers, (
                        f"ui/{module_name}.py imports from '{node.module}' — "
                        f"only {sorted(allowed_brokers)} is allowed"
                    )
                elif root == "core":
                    assert node.module in allowed_core, (
                        f"ui/{module_name}.py imports from '{node.module}' — "
                        f"only {sorted(allowed_core)} is allowed"
                    )
                else:
                    assert root not in banned_top, (
                        f"ui/{module_name}.py imports from '{node.module}'"
                    )

    import ui.main_window

    assert not hasattr(ui.main_window, "SymbolSearchWindow")


# ============================================================
# Extra — create_app() contract (single QApplication per process)
# ============================================================


def test_extra_create_app_raises_when_application_already_exists(qapp):
    """An existing QApplication in this process must make create_app() fail."""
    assert QApplication.instance() is qapp
    with pytest.raises(RuntimeError):
        ui_app.create_app([])


def test_extra_create_app_succeeds_without_existing_application():
    """In a fresh process with no QApplication, create_app() succeeds."""
    code = "\n".join(
        [
            "import ui.app as ui_app",
            "app = ui_app.create_app([])",
            "assert app is not None",
            "assert app.applicationName() == 'Trading Bot'",
            "assert ui_app.QApplication.instance() is app",
            "print('CREATE_APP_OK')",
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
    assert "CREATE_APP_OK" in result.stdout
