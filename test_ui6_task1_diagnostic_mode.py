"""
test_ui6_task1_diagnostic_mode.py

UI-6 Task 1 — Diagnostic Mode Foundation tests (fully offline).

Contract coverage:

    Test 1  — Default mode is NORMAL and the diagnostic section is hidden.
    Test 2  — NORMAL -> DIAGNOSTIC switch via the REAL UI toggle works.
    Test 3  — DIAGNOSTIC -> NORMAL switch back works.
    Test 4  — The diagnostic section is a REAL minimal section with REAL
              content (the last Test pass's per-order execution verdicts,
              built from the actual OrderExecutionResult objects), shown
              only in DIAGNOSTIC mode.
    Test 5  — No ordering behavior change: set_mode / apply_mode / the
              toggle never run, dispatch, or submit anything; queue
              entries, Test state, runner wiring and sent-order logging
              are untouched. Mode changes alone never populate the
              diagnostic section.

    Extra   — MainWindow.set_mode syncs the page's display boundary and
              the toggle; a page built without the window defaults to the
              hidden boundary; apply_mode is fail-closed against foreign
              values (an invalid value HIDES the section and syncs the
              internal state); no technical payload is attached to
              diagnostic items; MainWindow construction still imports no
              core/brokers/market module (UI-1 offline contract).

These tests are fully offline:
  - no network
  - no login
  - no broker API
  - no TSETMC call
  - no real order (the only "run" is a pure-Python stub runner with the
    runner's existing surface; ``live`` stays False everywhere)

Run:
    pytest -q test_ui6_task1_diagnostic_mode.py
"""

import os
import subprocess
import sys

import pytest

from PySide6.QtWidgets import QApplication

from core.order_engine import OrderExecutionResult
from core.order_queue import OrderQueue
from models.order import BUY, SELL, Order
from models.instrument import Instrument

from ui.account_store import AccountStore
from ui.main_window import ApplicationMode, MainWindow
from ui.order_configuration_page import (
    DIAGNOSTIC_EMPTY_STATE,
    DIAGNOSTIC_SECTION_TITLE,
    OrderConfigurationPage,
)


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

BROKER = "SIM"


@pytest.fixture(scope="module")
def qapp():
    """Reuse the process-wide QApplication if one exists, else create one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def make_page(qapp):
    """A real page with an active account and a real in-memory queue."""
    store = AccountStore()
    store.add("ACC-001", BROKER)
    store.set_active("ACC-001")
    return OrderConfigurationPage(store, order_queue=OrderQueue())


class _Entry:
    """Minimal entry surface the page reads (same convention as UI-5)."""

    def __init__(self, order, account_id="ACC-001", broker_name=BROKER):
        self.order = order
        self.account_id = account_id
        self.broker_name = broker_name


class _StubRunner:
    """
    The existing runner surface, offline and pure-Python: run() returns
    real OrderExecutionResult models (dry-run shaped, never live) and
    exposes ``last_order_results`` exactly like the real runner.
    """

    last_order_results = None

    def __init__(self, results):
        self._results = results
        self.run_calls = []

    def run(self, entries, account=None):
        self.run_calls.append((list(entries), account))
        self.last_order_results = list(self._results)
        # The existing runner returns (plan, execution_id, result); the
        # stub keeps that exact surface so the page's pass runs unchanged.
        return None, "EXEC-OFFLINE", None


def _dry_run_result(order, success=True):
    """A REAL core OrderExecutionResult in its existing dry-run shape."""
    return OrderExecutionResult(
        success=success,
        sent=True,
        mode="DRY_RUN" if success else "BLOCKED",
        order=order,
        broker_name=BROKER,
        message="dry-run" if success else "preflight blocked",
        response=None,
    )


def _wire_and_run(page, orders, results):
    """The EXISTING pass path: wire a stub runner, prepare the queue, run."""
    runner = _StubRunner(results)
    page.set_test_runner_factory(lambda: runner)
    page.config.select_instrument(
        Instrument(symbol="\u0622\u06a9\u0648", name="\u0622\u06a9\u0648", ins_code="1")
    )
    for order in orders:
        page.order_queue.enqueue(
            order, account_id="ACC-001", broker_name=BROKER
        )
    page._test_mode = True
    page._run_test_pass()
    return runner


# ============================================================
# Test 1 — default mode
# ============================================================


def test_1_default_mode_is_normal_and_section_hidden(qapp):
    window = MainWindow()
    page = window.order_configuration_page

    assert window.mode is ApplicationMode.NORMAL
    assert page.is_diagnostic_visible() is False
    # The real widget exists but is hidden (NORMAL is the shipped default).
    assert page.diagnostic_section.isVisibleTo(page) is False


# ============================================================
# Test 2 — NORMAL -> DIAGNOSTIC via the real toggle
# ============================================================


def test_2_switch_to_diagnostic_via_ui_toggle(qapp):
    window = MainWindow()
    page = window.order_configuration_page

    # A real user click on the toggle (unchecked -> checked).
    window.mode_toggle.click()

    assert window.mode is ApplicationMode.DIAGNOSTIC
    assert window.mode_toggle.isChecked() is True
    assert page.is_diagnostic_visible() is True


# ============================================================
# Test 3 — DIAGNOSTIC -> NORMAL via the real toggle
# ============================================================


def test_3_switch_back_to_normal_via_ui_toggle(qapp):
    window = MainWindow()
    page = window.order_configuration_page

    window.mode_toggle.click()   # -> DIAGNOSTIC
    window.mode_toggle.click()   # -> NORMAL

    assert window.mode is ApplicationMode.NORMAL
    assert window.mode_toggle.isChecked() is False
    assert page.is_diagnostic_visible() is False


# ============================================================
# Test 4 — the diagnostic section is real and mode-gated
# ============================================================


class TestDiagnosticSectionIsRealAndModeGated:
    def test_real_section_with_real_verdicts_shown_only_in_diagnostic(
        self, qapp
    ):
        page = make_page(qapp)
        order = Order(nsc_id="NSC-1", side=BUY, price=100, quantity=1)
        page._order_symbols[id(order)] = "\u0622\u06a9\u0648"
        _wire_and_run(page, [order], [_dry_run_result(order, success=True)])

        # Before any mode application: the shipped default (hidden).
        assert page.is_diagnostic_visible() is False
        # The content exists for real and comes from the REAL result model.
        assert page.diagnostic_list.count() == 1
        item_text = page.diagnostic_list.item(0).text()
        assert DIAGNOSTIC_SECTION_TITLE in page.diagnostic_section.title()
        assert "Order #1" in item_text
        assert "\u0622\u06a9\u0648" in item_text
        assert "\u0645\u0648\u0641\u0642" in item_text

        # NORMAL: hidden — the section's real content is not disclosed.
        window = MainWindow()
        window.order_configuration_page.apply_mode = (
            page.apply_mode  # drive the SAME page object's boundary
        )
        window.set_mode(ApplicationMode.NORMAL)
        assert page.is_diagnostic_visible() is False
        assert page.diagnostic_section.isVisibleTo(page) is False

        # DIAGNOSTIC: the same real content may be shown.
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        assert page.diagnostic_section.isVisibleTo(page) is True
        assert page.diagnostic_list.count() == 1

    def test_empty_state_before_any_test_pass(self, qapp):
        page = make_page(qapp)
        window = MainWindow()
        # Bind the window's mode propagation to this standalone page.
        real_apply = window.order_configuration_page.apply_mode

        def _redirect(mode):
            page.apply_mode(mode)
            return None

        real_apply.__self__  # keep a reference alive (style only)
        window.order_configuration_page.apply_mode = _redirect

        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        # Real empty state: no Test pass has run — nothing is invented.
        assert page.diagnostic_list.count() == 0
        assert page.diagnostic_status_label.text() == DIAGNOSTIC_EMPTY_STATE

    def test_fail_closed_against_foreign_mode_values(self, qapp):
        page = make_page(qapp)

        class _Foreign:
            name = "DIAGNOSTIC"  # a duck that is NOT the real enum

        # Baseline: NORMAL keeps the section hidden.
        for bad in (_Foreign(), "DIAGNOSTIC", None, 1):
            page.apply_mode(bad)
            assert page.is_diagnostic_visible() is False

        # A valid mode enables the section (unchanged behavior).
        page.apply_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        assert page.diagnostic_section.isVisibleTo(page) is True

        # ANY non-valid value (foreign duck, raw string, None, int) HIDES
        # the section and syncs the internal visibility state with it —
        # an unknown value never leaves the section unmasked.
        for bad in (_Foreign(), "DIAGNOSTIC", None, 1):
            page.apply_mode(bad)
            assert page.is_diagnostic_visible() is False
            assert page.diagnostic_section.isVisibleTo(page) is False

        # Valid modes keep behaving exactly as before.
        page.apply_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        page.apply_mode(ApplicationMode.NORMAL)
        assert page.is_diagnostic_visible() is False
        assert page.diagnostic_section.isVisibleTo(page) is False


# ============================================================
# Test 5 — no ordering-behavior impact
# ============================================================


class TestNoOrderingBehaviorImpact:
    def test_mode_changes_never_run_or_dispatch_anything(self, qapp):
        page = make_page(qapp)
        runner = _StubRunner([])  # counts run() calls
        page.set_test_runner_factory(lambda: runner)

        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        for mode in (
            ApplicationMode.DIAGNOSTIC,
            ApplicationMode.NORMAL,
            ApplicationMode.DIAGNOSTIC,
        ):
            window.set_mode(mode)
        # The runner was never invoked by any mode change.
        assert runner.run_calls == []
        # The queue is still empty and the Test toggle is OFF by default.
        assert page.order_queue.list_pending() == []
        assert page.test_button.isChecked() is False
        assert page._test_mode is False

    def test_full_send_pass_and_mode_change_are_orthogonal(self, qapp):
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        # 1) A real (offline, stubbed) dry-run pass in NORMAL mode.
        order = Order(nsc_id="NSC-2", side=BUY, price=50, quantity=2)
        page._order_symbols[id(order)] = "\u0622\u06a9\u0648"
        runner = _wire_and_run(
            page, [order], [_dry_run_result(order, success=True)]
        )
        assert len(runner.run_calls) == 1
        sent_at = runner.run_calls[0][1]  # account object handed to runner
        assert sent_at is not None
        # The order log got its one row (existing send behavior unchanged).
        assert len(page.order_log) == 1

        # 2) Mode changes around the pass change ONLY the boundary.
        window.set_mode(ApplicationMode.DIAGNOSTIC)
        assert page.is_diagnostic_visible() is True
        assert len(page.order_log) == 1
        window.set_mode(ApplicationMode.NORMAL)
        assert page.is_diagnostic_visible() is False
        assert len(page.order_log) == 1
        # The pass itself: still exactly one, queue still holds no extra
        # entries, and no retry happened.
        assert len(runner.run_calls) == 1
        assert page._test_mode is True  # Test Mode state untouched by mode
        page._test_mode = False  # restore the UI-5 toggle convention
        assert page.test_button.isChecked() is False

    def test_send_pass_with_blocked_result_stays_blocked_in_both_modes(
        self, qapp
    ):
        page = make_page(qapp)
        window = MainWindow()

        def _redirect(mode):
            page.apply_mode(mode)

        window.order_configuration_page.apply_mode = _redirect

        order = Order(nsc_id="NSC-3", side=SELL, price=10, quantity=1)
        page._order_symbols[id(order)] = "\u0622\u06a9\u0648"
        _wire_and_run(page, [order], [_dry_run_result(order, success=False)])

        # The verdict mirrors the REAL result model in both modes.
        for mode in (ApplicationMode.NORMAL, ApplicationMode.DIAGNOSTIC):
            window.set_mode(mode)
            assert page.diagnostic_list.count() == 1
            text = page.diagnostic_list.item(0).text()
            assert "\u0645\u0633\u062f\u0648\u062f\u0634\u062f\u0647" in text


# ============================================================
# Extra — mode-state consistency and UI-1 offline contracts
# ============================================================


def test_extra_set_mode_syncs_toggle_and_boundary(qapp):
    window = MainWindow()
    page = window.order_configuration_page

    window.set_mode(ApplicationMode.DIAGNOSTIC)
    assert window.mode_toggle.isChecked() is True
    assert page.is_diagnostic_visible() is True
    window.set_mode(ApplicationMode.NORMAL)
    assert window.mode_toggle.isChecked() is False
    assert page.is_diagnostic_visible() is False


def test_extra_standalone_page_defaults_hidden_and_diagnostic_items_carry_no_payload(
    qapp,
):
    page = make_page(qapp)
    assert page.is_diagnostic_visible() is False

    order = Order(nsc_id="NSC-4", side=BUY, price=1, quantity=1)
    _wire_and_run(page, [order], [_dry_run_result(order, success=True)])
    for row in range(page.diagnostic_list.count()):
        item = page.diagnostic_list.item(row)
        # No technical payload rides on the display items.
        assert item.data(0x20) in (None, "")  # Qt.UserRole stays empty
        assert "DEC-" not in item.text()      # no decisionId-like value


def test_extra_main_window_construction_stays_offline():
    code = "\n".join(
        [
            "import sys",
            "import ui.app as ui_app",
            "from ui.main_window import MainWindow",
            "app = ui_app.create_app([])",
            "window = MainWindow()",
            "banned = ('brokers', 'market', 'core', 'main')",
            "leaked = sorted(m for m in sys.modules if m.split('.')[0] in banned)",
            "assert not leaked, f'UI imported trading modules: {leaked}'",
            "assert window.mode_toggle is not None",
            "assert window.order_configuration_page.is_diagnostic_visible() is False",
            "print('UI6_OFFLINE_OK')",
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
    assert "UI6_OFFLINE_OK" in result.stdout
