"""
UI-9 Task 1 — dark theme foundation tests.

Verifies the ``ui.theme`` module:

    * it exists and imports,
    * ``apply_theme`` is callable and works on a QApplication AND on a
      plain widget,
    * the generated QSS is non-empty and contains every palette colour,
    * the token / spacing API is present and returns sane values,
    * importing ``ui.theme`` pulls in NO market / brokers / core / main
      module (tested both by AST scan and by inspecting ``sys.modules``).

The tests are presentation-only assertions: nothing here touches the order
path, and no test assertion of any existing test file is modified (C11).
"""

import ast
import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

from ui import theme as ui_theme

THEME_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ui", "theme.py"
)


@pytest.fixture(scope="module")
def qapp():
    """Reuse the process-wide QApplication if one exists, else create one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ============================================================
# Test 1 — the module exists
# ============================================================


def test_1_theme_module_exists():
    """ui/theme.py is present and non-empty."""
    assert os.path.isfile(THEME_PATH), f"missing theme module: {THEME_PATH}"
    assert os.path.getsize(THEME_PATH) > 0, "ui/theme.py is empty"


# ============================================================
# Test 2 — import contract (C6)
# ============================================================


def test_2_theme_imports_nothing_from_trading_layers():
    """
    AST scan: ui/theme.py imports PySide6 and stdlib only.

    Importing a ui/ module must never pull market / brokers / core / main
    into the process (UI-3.1 test_14 contract, C6).
    """
    with open(THEME_PATH, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=THEME_PATH)

    banned_roots = {"main", "brokers", "core", "market"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in banned_roots, (
                    f"ui/theme.py imports '{alias.name}' — banned by C6"
                )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in banned_roots, (
                f"ui/theme.py imports from '{node.module}' — banned by C6"
            )


def test_3_importing_theme_does_not_load_trading_modules():
    """
    Importing ui.theme must not put market/brokers/core/main into
    sys.modules.
    """
    # A fresh subprocess keeps this honest: the modules may legitimately be
    # in sys.modules already because of an earlier test in this session.
    import subprocess

    code = (
        "import sys; import ui.theme; "
        "leaked = sorted(m for m in ('main', 'brokers', 'core', 'market') "
        "if m in sys.modules or any(k.startswith(m + '.') for k in sys.modules)); "
        "print(','.join(leaked))"
    )
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=env,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    leaked = completed.stdout.strip()
    assert leaked == "", (
        f"importing ui.theme loaded trading modules: {leaked}"
    )


# ============================================================
# Test 4 — tokens
# ============================================================


def test_4_token_api_is_present_and_sane():
    """The palette / spacing / geometry token API exists with sane values."""
    tokens = ui_theme.tokens()
    assert set(tokens) >= {
        "palette",
        "spacing",
        "geometry",
        "fontFamily",
        "baseFontSize",
    }

    palette = ui_theme.palette()
    for key in (
        "background",
        "surface",
        "surfaceAlt",
        "border",
        "text",
        "textMuted",
        "accent",
        "success",
        "warning",
        "danger",
    ):
        assert key in palette, f"palette token missing: {key}"
        value = palette[key]
        assert value.startswith("#") and len(value) == 7, (
            f"palette[{key}] is not a #rrggbb colour: {value}"
        )

    spacing = ui_theme.spacing()
    # The approved scale: 4 / 8 / 12 / 16 / 24.
    assert sorted(spacing.values()) == [4, 8, 12, 16, 24]

    geometry = ui_theme.geometry()
    assert geometry["controlHeight"] > 0
    assert 6 <= geometry["radius"] <= 8
    assert 6 <= geometry["radiusSmall"] <= 8


def test_5_token_lookups_return_copies():
    """Mutating a returned mapping must never corrupt the source tokens."""
    palette = ui_theme.palette()
    palette["background"] = "#000000"
    assert ui_theme.PALETTE["background"] == "#12141a"


def test_6_font_chain_matches_the_approved_decision():
    """The font chain is the one approved in UI-9 section 0."""
    assert ui_theme.FONT_FAMILY_CHAIN[0] == "IRANSansX"
    assert "Tahoma" in ui_theme.FONT_FAMILY_CHAIN
    assert "Segoe UI" in ui_theme.FONT_FAMILY_CHAIN
    assert ui_theme.BASE_FONT_SIZE > 0


# ============================================================
# Test 5 — stylesheet
# ============================================================


def test_7_stylesheet_is_non_empty():
    """The generated QSS is a non-empty string."""
    qss = ui_theme.stylesheet()
    assert isinstance(qss, str)
    assert len(qss.strip()) > 0


def test_8_stylesheet_contains_every_palette_colour():
    """Every palette colour appears somewhere in the QSS."""
    qss = ui_theme.stylesheet()
    for key, value in ui_theme.PALETTE.items():
        assert value in qss, f"palette colour {key}={value} missing from QSS"


def test_9_stylesheet_covers_every_required_widget():
    """The QSS styles every widget type named in the UI-9.1 contract."""
    qss = ui_theme.stylesheet()
    for selector in (
        "QWidget",
        "QMainWindow",
        "QGroupBox",
        "QGroupBox::title",
        "QLabel",
        "QPushButton",
        "QPushButton:hover",
        "QPushButton:pressed",
        "QPushButton:disabled",
        "QPushButton:checked",
        'QPushButton[variant="primary"]',
        'QPushButton[variant="danger"]',
        "QLineEdit",
        "QLineEdit:focus",
        "QLineEdit:read-only",
        'QLineEdit[variant="invalid"]',
        "QComboBox",
        "QComboBox::drop-down",
        "QListWidget",
        "QTableWidget",
        "QTableWidget::item",
        "QTableWidget::item:selected",
        "QHeaderView::section",
        "QStatusBar",
        "QScrollArea",
        "QScrollBar:vertical",
        "QCheckBox",
    ):
        assert selector in qss, f"QSS is missing a rule for {selector}"


# ============================================================
# Test 6 — apply_theme
# ============================================================


def test_10_apply_theme_is_callable_and_tolerant(qapp):
    """apply_theme is callable, returns its target and tolerates None."""
    assert callable(ui_theme.apply_theme)

    from PySide6.QtWidgets import QWidget

    widget = QWidget()
    try:
        assert ui_theme.apply_theme(widget) is widget
        assert widget.styleSheet() == ui_theme.stylesheet()

        # A QApplication is accepted too (create_app path).
        assert ui_theme.apply_theme(qapp) is qapp
        assert qapp.styleSheet() == ui_theme.stylesheet()

        # None must not raise — it is a no-op.
        assert ui_theme.apply_theme(None) is None
    finally:
        widget.deleteLater()


def test_11_main_window_is_themed_without_create_app(qapp):
    """
    A directly-constructed MainWindow carries the dark stylesheet.

    This is the reason apply_theme works on a widget and not only on the
    QApplication: several existing tests build the window directly.
    """
    from ui.main_window import MainWindow

    window = MainWindow()
    try:
        assert window.styleSheet() == ui_theme.stylesheet()
        assert ui_theme.PALETTE["background"] in window.styleSheet()
    finally:
        window.close()
        window.deleteLater()


def test_12_create_app_sets_stylesheet_and_font():
    """
    ``python -m ui``'s create_app() applies the stylesheet and the font
    chain on the QApplication.

    NOTE on RTL: the UI-9.1 text also mentions ``Qt.RightToLeft`` here, but
    it is deliberately NOT applied here. Under PySide6 6.11.2 a
    RightToLeft layout direction makes ``QTableWidget.selectRow()`` a
    no-op (``currentRow()`` returns -1), which breaks
    ``test_ui2_1_account_management.py::test_12_accounts_page_performs_no_network_or_login``.
    RTL belongs to Task UI-9.3, where it is applied deliberately and the
    selection contract can be handled with the Architect's approval. See
    the UI-9.1 report, "Known issues".
    """
    import subprocess

    code = (
        "from ui.app import create_app\n"
        "from ui import theme\n"
        "app = create_app([])\n"
        "print('QSS', app.styleSheet() == theme.stylesheet())\n"
        "print('FONT', 'IRANSansX' in app.font().families())\n"
    )
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=env,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "QSS True" in completed.stdout, completed.stdout
    assert "FONT True" in completed.stdout, completed.stdout


def test_13_theme_does_not_enable_live_trading():
    """C3: the theme module enables nothing and opens no connection."""
    source = open(THEME_PATH, "r", encoding="utf-8").read()
    for forbidden in (
        "live_trading_enabled",
        "requests",
        "urllib",
        "socket",
        "AgaahBroker",
        "DispatchCore",
    ):
        assert forbidden not in source, (
            f"ui/theme.py must not reference '{forbidden}' (C3)"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
