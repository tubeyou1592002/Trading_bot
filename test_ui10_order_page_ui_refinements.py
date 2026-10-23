"""UI-10 regression tests for the order-page presentation refinements.

Covers only display concerns: the removed orphan status label, the amounts
box sized to its own content, the fixed schedule box with no clipped rows,
the normal typography of the schedule state/countdown, the exact three-line
summary, and the symbol-search placeholder. No broker request, no live send
and no real order is exercised here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtWidgets import QApplication, QLabel

import ui.order_configuration_page as page_module
from core.timing_contracts import DispatchTiming
from models.order import Order
from ui import strings as STRINGS
from ui.account_store import AccountStore
from ui.order_configuration_page import OrderConfigurationPage
from ui.schedule_settings import (
    ParsedScheduleInputs,
    assess_schedule_window,
    build_schedule_summary,
    count_planned_turns,
    describe_summary,
    generate_schedule_times,
)
from ui.theme import apply_theme

TEHRAN = ZoneInfo("Asia/Tehran")
FIXED_NOW = datetime(2026, 10, 2, 9, 29, 0, tzinfo=ZoneInfo("UTC"))


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    apply_theme(app)
    yield app


def _page(qapp, now=FIXED_NOW):
    tehran_now = now.astimezone(TEHRAN)
    page_module.system_wall_now = lambda: tehran_now
    page_module.sample_system_clocks = lambda: (tehran_now, 0.0)
    page_module.system_monotonic = lambda: 0.0
    page = OrderConfigurationPage(AccountStore())
    # A usual desktop window, not the tiny default top-level size.
    page.resize(1200, 800)
    page.show()
    qapp.processEvents()
    return page


def _applied_page(qapp):
    page = _page(qapp)
    page.store.add("ACC-UI10", "SIM", "ACC-UI10")
    page.order_queue.enqueue(
        Order(nsc_id="nsc-ui10", side=1, price=1000, quantity=10),
        "ACC-UI10",
        "SIM",
    )
    page.schedule_start_input.setText("13:00:00")
    page.schedule_end_input.setText("13:01:00")
    page.schedule_interval_input.setText("15")
    page.dispatch_interval_input.setText("100")
    page._on_apply_schedule()
    qapp.processEvents()
    return page


def test_orphan_symbol_status_label_is_gone(qapp):
    page = _page(qapp)
    try:
        assert not hasattr(page, "symbol_status_label")
        texts = [label.text() for label in page.findChildren(QLabel)]
        assert "وضعیت: ناموجود" not in texts
        # The trading-state icon and its tooltip are the surviving display.
        assert page.trading_state_icon.isHidden() is True
        page._render_market_status(tooltip="قابل معامله")
        assert page.trading_state_icon.toolTip() == "قابل معامله"
    finally:
        page.close()


def test_amounts_panel_is_sized_to_its_own_content(qapp):
    page = _page(qapp)
    try:
        # The amounts box is NOT forced to the order-details height.
        assert page.amounts_group.height() == page.amounts_group.sizeHint().height()
        assert page.amounts_group.height() != page.form_group.height()
        assert (
            page.amounts_group.minimumHeight()
            == page.amounts_group.maximumHeight()
            == page.amounts_group.height()
        )

        for label in (
            page.base_amount_label,
            page.fee_label,
            page.final_amount_label,
        ):
            assert label.height() >= label.sizeHint().height()
            assert label.height() >= label.heightForWidth(label.width())

        # The warning is hidden while empty, and when shown it is neither
        # clipped nor given extra empty space below.
        assert page.amount_warning_label.isVisible() is False
        page._set_amount_warning("مبلغ نهایی از موجودی شما بیشتر است")
        qapp.processEvents()
        assert page.amount_warning_label.isVisible() is True
        assert page.amount_warning_label.height() >= (
            page.amount_warning_label.sizeHint().height()
        )
        assert page.amount_warning_label.height() >= (
            page.amount_warning_label.heightForWidth(
                page.amount_warning_label.width()
            )
        )
        assert page.amounts_group.height() == page.amounts_group.sizeHint().height()

        page._set_amount_warning("")
        qapp.processEvents()
        assert page.amount_warning_label.isVisible() is False
        assert page.amounts_group.height() == page.amounts_group.sizeHint().height()
    finally:
        page.close()


def test_schedule_group_has_a_fixed_height_that_fits_its_content(qapp):
    page = _applied_page(qapp)
    try:
        group = page.schedule_group
        assert group.minimumHeight() == group.maximumHeight() == group.height()
        assert group.height() == group.sizeHint().height()

        for label in (
            page.schedule_timezone_label,
            page.schedule_start_input,
            page.schedule_end_input,
            page.schedule_interval_input,
            page.dispatch_interval_input,
            page.apply_schedule_button,
            page.schedule_state_label,
            page.countdown_label,
            page.schedule_summary_label,
        ):
            assert label.height() >= min(
                label.sizeHint().height(), label.minimumHeight()
            )
            assert label.height() > 0
            if hasattr(label, "heightForWidth"):
                assert label.height() >= max(
                    0, label.heightForWidth(label.width())
                )

        # The summary is the final three-line content, so its rows fit and
        # the box has no leftover space from the old extra summary notes.
        assert len(page.schedule_summary_label.text().splitlines()) == 3
    finally:
        page.close()


def test_schedule_state_and_countdown_use_normal_typography(qapp):
    page = _page(qapp)
    try:
        for label in (page.schedule_state_label, page.countdown_label):
            style = label.styleSheet().lower()
            assert "monospace" not in style
            assert "font-size" not in style
            assert "font-weight" not in style
            # Normal body text size, same as another ordinary label.
            assert label.font().pointSizeF() == page.validation_error_label.font().pointSizeF()
    finally:
        page.close()


def test_symbol_search_placeholder_is_exact(qapp):
    page = _page(qapp)
    try:
        assert page.symbol_input.lineEdit().placeholderText() == "بطور مثال شستا"
    finally:
        page.close()


def _summary(dispatch_ms=100.0):
    start = datetime(2026, 10, 23, 8, 44, 58, tzinfo=TEHRAN)
    end = datetime(2026, 10, 23, 8, 45, 5, tzinfo=TEHRAN)
    parsed = ParsedScheduleInputs(
        start_text="08:44:58",
        end_text="08:45:05",
        interval_text="1",
        start_time_of_day=timedelta(hours=8, minutes=44, seconds=58),
        end_time_of_day=timedelta(hours=8, minutes=45, seconds=5),
        interval=timedelta(seconds=1),
    )
    timing = DispatchTiming(
        start_time=start, end_time=end, interval=timedelta(seconds=1)
    )
    moments = generate_schedule_times(timing)
    assessment = assess_schedule_window(
        timing, start - timedelta(seconds=1), moments
    )
    return build_schedule_summary(
        parsed,
        timing,
        assessment,
        "clock",
        moments=moments,
        dispatch_interval_ms=dispatch_ms,
    )


def test_planned_turns_include_both_endpoints_and_use_dispatch_interval():
    start = datetime(2026, 10, 23, 8, 44, 58, tzinfo=TEHRAN)
    end = datetime(2026, 10, 23, 8, 45, 5, tzinfo=TEHRAN)
    assert count_planned_turns(start, end, 100) == 71
    assert count_planned_turns(start, end, 1000) == 8

    summary = _summary()
    assert summary.duration_seconds == 7
    assert summary.planned_turns == 71
    assert summary.internal_interval_seconds == 1


def test_summary_has_exactly_three_lines_and_nothing_else():
    text = describe_summary(_summary())
    lines = text.splitlines()
    assert len(lines) == 3, text

    # 1) window, 2) dispatch cadence, 3) planned turns.
    assert lines[0] == STRINGS.SUMMARY_WINDOW.format(
        start="08:44:58", end="08:45:05"
    )
    assert lines[1] == STRINGS.SUMMARY_DISPATCH_INTERVAL.format(
        interval=STRINGS.format_persian_digits(100)
    )
    assert lines[2] == STRINGS.SUMMARY_PLANNED_TURNS.format(
        count=STRINGS.format_persian_digits(71)
    )

    for forbidden in (
        "مدت:",
        STRINGS.SUMMARY_PER_TURN,
        STRINGS.SUMMARY_PLANNED_TURNS_NOTE,
        STRINGS.SUMMARY_INTERNAL_INTERVAL.split("{", 1)[0].strip(),
        STRINGS.SUMMARY_STATE.split("{", 1)[0].strip(),
        STRINGS.SUMMARY_NEXT_MOMENTS.split("{", 1)[0].strip(),
        STRINGS.SUMMARY_CLOCK.split("{", 1)[0].strip(),
        STRINGS.SUMMARY_SKIPPED.split("{", 1)[0].strip(),
        STRINGS.SUMMARY_IMMEDIATE_START,
        STRINGS.CLOCK_SOURCE_DESCRIPTION,
    ):
        assert forbidden not in text, text
