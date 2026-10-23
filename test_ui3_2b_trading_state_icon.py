"""UI-3.2B — TSETMC market-status icon next to the symbol field.

The icon/colour/tooltip are rendered ONLY from the normalized
``TradingState.market_status`` / ``market_status_title`` carried through
the existing trading-state query path. The raw API status is never
interpreted by the UI, and the simple «وضعیت» row is left unchanged.
"""

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QApplication, QLabel

from models.instrument import Instrument
from models.trading_state import (
    MARKET_STATUS_GREEN,
    MARKET_STATUS_LABELS,
    MarketStatus,
    TradingState,
    TradingStateUnavailable,
)
from ui import strings as STRINGS
from ui.account_store import AccountStore
from ui.order_configuration_page import (
    STATUS_LABEL_TRADABLE,
    STATUS_LABEL_UNKNOWN,
    STATUS_PENDING_LABEL,
    OrderConfigurationPage,
    _market_status_icon_path,
)
from ui.theme import PALETTE

INSTRUMENT = Instrument(
    symbol="آکو",
    name="آکو باتري ايرانيان",
    ins_code="60235881999727383",
    market="بورس",
)
RESULT = {
    "symbol": "آکو",
    "name": "آکو باتري ايرانيان",
    "ins_code": "60235881999727383",
    "flow": 0,
    "market": "بورس",
}

DOCUMENTED_STATUSES = (
    ("A ", MarketStatus.PERMITTED, "مجاز"),
    ("AR", MarketStatus.PERMITTED_RESERVED, "مجاز-محفوظ"),
    ("AG", MarketStatus.PERMITTED_BLOCKED, "مجاز-مسدود"),
    ("AS", MarketStatus.PERMITTED_STOPPED, "مجاز-متوقف"),
    ("I ", MarketStatus.FORBIDDEN, "ممنوع"),
    ("IG", MarketStatus.FORBIDDEN_BLOCKED, "ممنوع-مسدود"),
    ("IS", MarketStatus.FORBIDDEN_STOPPED, "ممنوع-متوقف"),
    ("IR", MarketStatus.FORBIDDEN_RESERVED, "ممنوع-محفوظ"),
)


class _Resolver:
    def search(self, text):
        return [dict(RESULT)]

    def resolve(self, result):
        return INSTRUMENT


class _IdentityResolver:
    def get_nsc_id(self, ins_code):
        return "NSC-TEST"


class StubQuery:
    def __init__(self, state=None, error=None):
        self.state = state
        self.error = error
        self.calls = []

    def get_trading_state(self, ins_code):
        self.calls.append(ins_code)
        if self.error is not None:
            raise self.error
        return self.state


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def store():
    store = AccountStore()
    store.add("ACC-001", "آگاه", "ACC-001")
    store.set_active("ACC-001")
    return store


def _state(status, title=None, allowed=None):
    return TradingState(
        is_order_entry_allowed=(
            status in MARKET_STATUS_GREEN if allowed is None else allowed
        ),
        is_verified=True,
        source="tsetmc:cEtaval",
        market_status=status,
        market_status_title=title,
    )


def _configure_page(page):
    page.set_resolver_factory(lambda: _Resolver())
    page.set_order_identity_factory(lambda: _IdentityResolver())
    return page


def _settle(qapp, page):
    page.wait_for_workers(5000)
    page.wait_for_trading_state_workers(5000)
    page.wait_for_order_identity_workers(5000)
    for _ in range(50):
        qapp.processEvents()
        time.sleep(0.01)


def _select_symbol(qapp, page):
    page.symbol_input.setCurrentText("آکو")
    page._debounce_timer.stop()
    page._start_symbol_search()
    page.wait_for_workers(5000)
    qapp.processEvents()
    assert page.results_list.count() > 0
    page._on_result_selected(page.results_list.item(0))
    _settle(qapp, page)
    assert page.config.selected_instrument is INSTRUMENT


def _page_with_state(qapp, store, state):
    query = StubQuery(state=state)
    page = _configure_page(OrderConfigurationPage(store))
    page.set_trading_state_query_factory(lambda: query)
    _select_symbol(qapp, page)
    return page, query


COLOR_TOLERANCE = 24


def _show_page(qapp, page):
    page.resize(1200, 900)
    page.show()
    qapp.processEvents()
    page.repaint()
    qapp.processEvents()


def _page_icon_color_count(qapp, page, expected_color):
    _show_page(qapp, page)
    icon = page.trading_state_icon
    assert icon.isVisible() is True
    assert icon.visibleRegion().isEmpty() is False

    origin = icon.mapTo(page, QPoint(0, 0))
    image = page.grab().toImage()
    scale_x = image.width() / page.width()
    scale_y = image.height() / page.height()
    target = QColor(expected_color)
    count = 0
    for y in range(
        max(0, int(origin.y() * scale_y)),
        min(image.height(), int((origin.y() + icon.height()) * scale_y)),
    ):
        for x in range(
            max(0, int(origin.x() * scale_x)),
            min(image.width(), int((origin.x() + icon.width()) * scale_x)),
        ):
            pixel = image.pixelColor(x, y)
            if (
                pixel.alpha() > 0
                and abs(pixel.red() - target.red()) <= COLOR_TOLERANCE
                and abs(pixel.green() - target.green()) <= COLOR_TOLERANCE
                and abs(pixel.blue() - target.blue()) <= COLOR_TOLERANCE
            ):
                count += 1
    return count


def test_icon_is_hidden_before_a_symbol_is_selected(qapp, store):
    page = _configure_page(OrderConfigurationPage(store))
    assert page.trading_state_icon.isHidden() is True
    assert hasattr(page, "trading_state_display") is False
    assert hasattr(page, "market_status_text") is False


def test_only_the_icon_is_rendered_without_adjacent_text(qapp, store):
    page, _ = _page_with_state(qapp, store, _state(MarketStatus.PERMITTED))
    icon = page.trading_state_icon
    _show_page(qapp, page)

    assert icon.text() == ""
    assert icon.pixmap().isNull() is False
    assert icon.isVisible() is True
    assert icon.width() >= 16 and icon.height() >= 16
    assert page.findChild(QLabel, "marketStatusText") is None


def test_icon_does_not_add_a_text_status_row(qapp, store):
    page, _ = _page_with_state(qapp, store, _state(MarketStatus.PERMITTED))
    _show_page(qapp, page)

    assert page.trading_state_icon.isVisible() is True
    assert page.trading_state_icon.toolTip()
    assert not hasattr(page, "symbol_status_label")
    assert page.findChild(QLabel, "symbolStatusLabel") is None


@pytest.mark.parametrize(
    "status,asset_name,expected_color",
    (
        (
            MarketStatus.PERMITTED,
            "trading-status-green.svg",
            PALETTE["success"],
        ),
        (
            MarketStatus.PERMITTED_RESERVED,
            "trading-status-green.svg",
            PALETTE["success"],
        ),
        (
            MarketStatus.FORBIDDEN,
            "trading-status-red.svg",
            PALETTE["danger"],
        ),
        (
            MarketStatus.FORBIDDEN_STOPPED,
            "trading-status-red.svg",
            PALETTE["danger"],
        ),
        (
            None,
            "trading-status-neutral.svg",
            PALETTE["textMuted"],
        ),
    ),
)
def test_status_icon_is_visible_on_page_with_matching_svg_asset(
    qapp, store, status, asset_name, expected_color
):
    page, _ = _page_with_state(qapp, store, _state(status))
    icon = page.trading_state_icon

    icon_path = Path(icon.property("iconPath"))
    assert icon_path == _market_status_icon_path(status)
    assert icon_path.name == asset_name
    assert icon_path.suffix == ".svg"
    assert icon_path.is_file()

    loaded = QIcon(str(icon_path)).pixmap(icon.size())
    assert loaded.isNull() is False
    assert icon.size().width() >= 16
    assert _page_icon_color_count(qapp, page, expected_color) > 5


@pytest.mark.parametrize(
    "code,status,label",
    DOCUMENTED_STATUSES,
)
def test_each_documented_status_has_correct_icon_color_and_tooltip(
    qapp, store, code, status, label
):
    page, query = _page_with_state(qapp, store, _state(status, title=label))
    icon = page.trading_state_icon

    assert query.calls == [INSTRUMENT.ins_code]
    assert icon.isHidden() is False
    assert icon.toolTip() == label
    assert icon.property("marketStatus") == status.value
    expected_color = (
        PALETTE["success"]
        if status in MARKET_STATUS_GREEN
        else PALETTE["danger"]
    )
    assert icon.property("stateColor") == expected_color
    assert _page_icon_color_count(qapp, page, expected_color) > 5
    assert MARKET_STATUS_LABELS[status] == label


def test_tooltip_shows_exact_status_text(qapp, store):
    page, _ = _page_with_state(
        qapp,
        store,
        _state(MarketStatus.PERMITTED_RESERVED, title="مجاز محفوظ"),
    )
    assert page.trading_state_icon.toolTip() == "مجاز محفوظ"


def test_cetaval_title_is_shown_verbatim(qapp, store):
    page, _ = _page_with_state(
        qapp,
        store,
        _state(MarketStatus.PERMITTED_BLOCKED, title="عنوان دقیق وضعیت"),
    )
    assert page.trading_state_icon.toolTip() == "عنوان دقیق وضعیت"
    assert page.trading_state_icon.property("stateColor") == PALETTE["danger"]


def test_missing_title_falls_back_to_documented_label(qapp, store):
    page, _ = _page_with_state(
        qapp,
        store,
        _state(MarketStatus.FORBIDDEN_STOPPED),
    )
    assert page.trading_state_icon.toolTip() == "ممنوع-متوقف"
    assert page.trading_state_icon.property("stateColor") == PALETTE["danger"]


def test_unknown_status_is_neutral_and_keeps_api_title(qapp, store):
    page, _ = _page_with_state(
        qapp,
        store,
        _state(None, title="وضعیت ناشناخته"),
    )
    icon = page.trading_state_icon
    assert icon.isHidden() is False
    assert icon.toolTip() == "وضعیت ناشناخته"
    assert icon.property("marketStatus") is None
    assert icon.property("stateColor") == PALETTE["textMuted"]
    assert _page_icon_color_count(qapp, page, PALETTE["textMuted"]) > 5


def test_unknown_status_without_title_is_neutral_unknown(qapp, store):
    page, _ = _page_with_state(qapp, store, _state(None))
    icon = page.trading_state_icon
    assert icon.toolTip() == STATUS_LABEL_UNKNOWN
    assert icon.property("stateColor") == PALETTE["textMuted"]


def test_fetch_failure_is_neutral_unknown(qapp, store):
    query = StubQuery(error=TradingStateUnavailable("offline"))
    page = _configure_page(OrderConfigurationPage(store))
    page.set_trading_state_query_factory(lambda: query)
    _select_symbol(qapp, page)

    icon = page.trading_state_icon
    assert page.trading_state_label.text() == STATUS_LABEL_UNKNOWN
    assert icon.isHidden() is False
    assert icon.toolTip() == STATUS_LABEL_UNKNOWN
    assert icon.property("marketStatus") is None
    assert icon.property("stateColor") == PALETTE["textMuted"]


def test_status_query_runs_without_active_account(qapp):
    store = AccountStore()
    store.add("NO-ACTIVE-ACC", "آگاه", "No active account")
    query = StubQuery(state=_state(MarketStatus.PERMITTED, title="مجاز"))
    page = _configure_page(OrderConfigurationPage(store))
    page.set_trading_state_query_factory(lambda: query)
    _select_symbol(qapp, page)

    assert query.calls == ["60235881999727383"]
    assert page.trading_state_label.text() == STATUS_LABEL_TRADABLE
    assert page.trading_state_icon.property("stateColor") == PALETTE["success"]


def test_pending_status_is_neutral(qapp, store):
    release = threading.Event()
    started = threading.Event()

    class GatedQuery:
        def get_trading_state(self, ins_code):
            started.set()
            release.wait(timeout=5)
            return _state(MarketStatus.PERMITTED, title="مجاز")

    page = _configure_page(OrderConfigurationPage(store))
    page.set_trading_state_query_factory(lambda: GatedQuery())
    _show_page(qapp, page)

    page.symbol_input.setCurrentText("آکو")
    page._debounce_timer.stop()
    page._start_symbol_search()
    page.wait_for_workers(5000)
    qapp.processEvents()
    page._on_result_selected(page.results_list.item(0))
    page.wait_for_workers(5000)
    qapp.processEvents()

    try:
        assert started.wait(timeout=5) is True
        icon = page.trading_state_icon
        assert page.trading_state_label.text() == STATUS_PENDING_LABEL
        assert icon.isHidden() is False
        assert icon.toolTip() == STATUS_PENDING_LABEL
        assert icon.property("marketStatus") is None
        assert icon.property("stateColor") == PALETTE["textMuted"]
        assert (
            Path(icon.property("iconPath")).name
            == "trading-status-neutral.svg"
        )
        assert _page_icon_color_count(qapp, page, PALETTE["textMuted"]) > 5
    finally:
        release.set()
        page.wait_for_trading_state_workers(5000)
        page.wait_for_order_identity_workers(5000)
        for _ in range(50):
            qapp.processEvents()
            time.sleep(0.01)


def test_stale_result_never_updates_the_icon(qapp, store):
    release = threading.Event()
    started = threading.Event()

    class GatedQuery:
        def get_trading_state(self, ins_code):
            started.set()
            release.wait(timeout=5)
            return _state(MarketStatus.PERMITTED, title="مجاز")

    page = _configure_page(OrderConfigurationPage(store))
    page.set_trading_state_query_factory(lambda: GatedQuery())

    page.symbol_input.setCurrentText("آکو")
    page._debounce_timer.stop()
    page._start_symbol_search()
    page.wait_for_workers(5000)
    qapp.processEvents()
    page._on_result_selected(page.results_list.item(0))
    page.wait_for_workers(5000)
    qapp.processEvents()
    assert started.wait(timeout=5) is True

    page.symbol_input.setCurrentText("فولاد")
    page._debounce_timer.stop()
    qapp.processEvents()

    try:
        assert page.trading_state_icon.isHidden() is True
        release.set()
        page.wait_for_trading_state_workers(5000)
        page.wait_for_order_identity_workers(5000)
        for _ in range(50):
            qapp.processEvents()
            time.sleep(0.01)

        assert page.trading_state_icon.isHidden() is True
        assert page.trading_state_label.text() == STATUS_LABEL_UNKNOWN
        assert page.trading_state_icon.property("marketStatus") is None
    finally:
        release.set()
