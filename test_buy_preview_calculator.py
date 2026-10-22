"""Focused regression tests for the read-only buy preview calculator."""

import pytest
from PySide6.QtWidgets import QApplication, QGroupBox, QVBoxLayout, QWidget
from PySide6.QtGui import QIcon

from models.instrument import Instrument
from ui.account_store import AccountStore
from ui.order_config_state import OrderConfiguration
from ui.order_configuration_page import OrderConfigurationPage
from ui.main_window import MainWindow
from ui.theme import apply_theme
from market.tsetmc import PriceLimits


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


class _Broker:
    def __init__(self):
        self.calls = []
        self.submitted = False

    def get_buy_capacity(self, nsc_id, side_code, fund, price):
        self.calls.append(("quantity", nsc_id, side_code, fund, price))
        return 10

    def get_commission_info(self, nsc_id, price, quantity, side_code):
        self.calls.append(("commission", nsc_id, price, quantity, side_code))
        return {"commissionSum": 123}


class _Adapter:
    def __init__(self, broker):
        self._broker = broker


class _Service:
    def __init__(self, broker, balance=100_000):
        self.broker = broker
        self.balance = balance

    def get_tradable_balance(self, account_id):
        return self.balance

    def get_adapter(self, account_id):
        return _Adapter(self.broker)


def _page(qapp, price=""):
    store = AccountStore(repository=False)
    store.add("ACC-PREVIEW", "آگاه", "حساب آزمایشی")
    store.set_active("ACC-PREVIEW")
    instrument = Instrument(symbol="نماد", name="نام نماد", ins_code="INS-PREVIEW")
    config = OrderConfiguration()
    config.select_instrument(instrument)
    page = OrderConfigurationPage(store, config=config)
    page._order_nsc_id = "NSC-PREVIEW"
    page.price_input.setText(price)
    broker = _Broker()
    service = _Service(broker)
    page.set_buy_preview_factory(lambda account, broker_name: service)
    return page, broker, service


def test_preview_opens_without_form_price_and_calculates_without_submission(qapp):
    page, broker, _ = _page(qapp)
    page._open_buy_preview()
    qapp.processEvents()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    assert page._buy_preview_dialog is not None
    assert page.preview_price_input.text() == ""
    page.preview_price_input.setText("1000")
    page.preview_amount_input.setText("20000")
    page._start_buy_preview()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    assert page._buy_preview_result == {
        "price": 1000, "quantity": 10, "amount": 10000,
        "fee": 123, "total": 10123,
    }
    assert broker.calls == [
        ("quantity", "NSC-PREVIEW", 1, 20000, 1000),
        ("commission", "NSC-PREVIEW", 1000, 10, 1),
    ]
    before = list(broker.calls)
    page._apply_buy_preview()
    assert page.price_input.text() == "1000"
    assert page.quantity_input.text() == "10"
    assert page.base_amount_label.text() == "10,000"
    assert page.fee_label.text() == "123"
    assert page.final_amount_label.text() == "10,123"
    assert broker.calls == before
    assert broker.submitted is False


def test_amount_over_power_is_rejected_before_broker_calls(qapp):
    page, broker, _ = _page(qapp, "1000")
    page._open_buy_preview()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    page.preview_amount_input.setText("100001")
    page._start_buy_preview()
    assert "قدرت خرید" in page.preview_result_label.text()
    assert broker.calls == []


@pytest.mark.parametrize("changed", ["symbol", "price", "amount", "account"])
def test_preview_result_is_invalidated_by_input_or_account_change(qapp, changed):
    page, broker, _ = _page(qapp, "1000")
    page._open_buy_preview()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    page.preview_amount_input.setText("20000")
    page._start_buy_preview()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    assert page._buy_preview_result is not None
    if changed == "symbol":
        page.config.select_instrument(Instrument(symbol="new", name="new", ins_code="INS-NEW"))
    elif changed == "price":
        page.preview_price_input.setText("1100")
    elif changed == "amount":
        page.preview_amount_input.setText("21000")
    else:
        page.store.add("ACC-OTHER", "آگاه", "حساب دیگر")
        page.store.set_active("ACC-OTHER")
        page.refresh_active_account()
    page._apply_buy_preview()
    assert page.quantity_input.text() == ""
    assert page._buy_preview_result is None
    assert broker.calls


def test_symbol_information_group_is_not_created_and_calculator_is_separate(qapp):
    page, _, _ = _page(qapp, "1000")
    assert not any(
        isinstance(widget, QGroupBox) and widget.title() == "اطلاعات نماد"
        for widget in page.findChildren(QGroupBox)
    )
    assert page.calculator_button.parent() is page.form_group
    assert page.calculator_button.size().width() > 30
    assert page.side_buttons[next(iter(page.side_buttons))].parent() is not page.calculator_button
    assert page.symbol_name_label.parent() is page.symbol_input.parent()
    assert page.findChildren(type(page.symbol_name_label), "selectedSymbolName") == [page.symbol_name_label]
    field_layout = page.symbol_input.parentWidget().layout()
    assert isinstance(field_layout, QVBoxLayout)
    assert field_layout.itemAt(1).widget() is page.symbol_name_label
    assert page.symbol_name_label.styleSheet().find("border: 0px") >= 0
    assert page.symbol_name_label.styleSheet().find("background-color: transparent") >= 0
    assert "نام نماد" in page.symbol_name_label.text()


def test_active_account_row_height_is_fixed_for_long_text(qapp):
    page, _, _ = _page(qapp, "1000")
    group = page.active_account_group
    fixed_height = group.height()
    page.active_account_label.setText("نام بسیار طولانی حساب آزمایشی " * 10)
    qapp.processEvents()
    assert group.height() == fixed_height
    assert group.minimumHeight() == group.maximumHeight() == fixed_height
    assert page.active_account_label.wordWrap() is False


def test_returning_to_order_page_refreshes_active_account_name(qapp):
    store = AccountStore(repository=False)
    store.add("ACC-A", "آگاه", "نام حساب بلند و فعال")
    store.set_active("ACC-A")
    window = MainWindow(account_store=store)
    window.select_page("Accounts")
    store.add("ACC-B", "آگاه", "حساب تازه")
    store.set_active("ACC-B")
    window.select_page("Order Configuration")
    page = window.order_configuration_page
    assert page.active_account_label.text() == "حساب تازه"
    assert page.active_account_group.height() == page.active_account_group.maximumHeight()


def test_symbol_label_has_scoped_plain_text_style_under_global_theme(qapp):
    apply_theme(qapp)
    page, _, _ = _page(qapp, "1000")
    label = page.symbol_name_label
    assert label.parent() is page.symbol_input.parent()
    assert label.objectName() == "selectedSymbolName"
    assert "QLabel#selectedSymbolName" in label.styleSheet()
    assert "border: 0px" in label.styleSheet()
    assert "background-color: transparent" in label.styleSheet()
    assert label.text() == "نماد - نام نماد"


def test_popup_price_limit_buttons_are_icon_only_with_tooltips(qapp):
    page, _, _ = _page(qapp, "1000")
    page._open_buy_preview()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    assert page.preview_price_max_button.text() == ""
    assert page.preview_price_min_button.text() == ""
    assert not page.preview_price_max_button.icon().isNull()
    assert not page.preview_price_min_button.icon().isNull()
    assert page.preview_price_max_button.toolTip() == "حداکثر قیمت مجاز"
    assert page.preview_price_min_button.toolTip() == "حداقل قیمت مجاز"


def test_auto_amount_uses_commission_and_warns_when_over_power(qapp):
    page, broker, service = _page(qapp, "1000")
    service.balance = 10_000
    page.price_input.setText("1000")
    page.quantity_input.setText("10")
    page._on_price_changed()
    page._on_quantity_changed()
    page._auto_amount_thread.wait(3000)
    qapp.processEvents()
    assert page.base_amount_label.text() == "۱۰٬۰۰۰"
    assert page.fee_label.text() == "۱۲۳"
    assert page.final_amount_label.text() == "۱۰٬۱۲۳"
    assert page.amount_warning_label.text() == "مبلغ نهایی از موجودی شما بیشتر است"
    assert broker.calls
    assert all(call == ("commission", "NSC-PREVIEW", 1000, 10, 1)
               for call in broker.calls)
    assert not broker.submitted


def test_auto_amount_debounces_typing_to_one_commission_request(qapp):
    page, broker, _ = _page(qapp, "")
    page.price_input.setText("1")
    page.price_input.setText("10")
    page.price_input.setText("1000")
    page.quantity_input.setText("1")
    page.quantity_input.setText("10")
    assert page._auto_amount_timer.isActive()
    qapp.processEvents()
    assert broker.calls == []
    assert page._auto_amount_timer.remainingTime() > 0
    from PySide6.QtTest import QTest
    QTest.qWait(300)
    page._auto_amount_thread.wait(3000)
    qapp.processEvents()
    assert broker.calls == [("commission", "NSC-PREVIEW", 1000, 10, 1)]


def test_auto_amount_rejects_stale_worker_and_clears_result_on_invalid_input(qapp):
    page, broker, _ = _page(qapp, "1000")
    page.quantity_input.setText("10")
    page._start_auto_amount()
    worker = page._auto_amount_worker
    snapshot = worker.snapshot
    page.price_input.setText("invalid")
    qapp.processEvents()
    page._on_auto_amount_succeeded(worker.request_id, snapshot,
                                   {"fee": 1, "total": 10001, "power": 50000})
    assert page.fee_label.text() != "1"
    assert page.final_amount_label.text() != "10,001"
    assert page.fee_label.text() != "1"


@pytest.mark.parametrize(("kind", "minimum", "maximum", "expected"), [
    ("min", 1250, 1980, "1250"),
    ("max", 1250, 1980, "1980"),
])
def test_popup_price_limits_use_existing_resolver_factory(qapp, kind, minimum, maximum, expected):
    page, _, _ = _page(qapp, "1000")

    class Resolver:
        def __init__(self):
            self.codes = []

        def get_price_limits(self, ins_code):
            self.codes.append(ins_code)
            return PriceLimits(price_min=minimum, price_max=maximum)

    resolver = Resolver()
    page.set_resolver_factory(lambda: resolver)
    page._open_buy_preview()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    page._set_preview_price_limit(kind)
    page._preview_price_limit_worker.wait(3000)
    qapp.processEvents()
    assert resolver.codes == ["INS-PREVIEW"]
    assert page.preview_price_input.text() == expected


def test_popup_price_limit_failure_is_reported_and_stale_response_is_ignored(qapp):
    page, _, _ = _page(qapp, "1000")

    class BadResolver:
        def get_price_limits(self, ins_code):
            raise RuntimeError("TSETMC test failure")

    page.set_resolver_factory(lambda: BadResolver())
    page._open_buy_preview()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    page._set_preview_price_limit("max")
    worker = page._preview_price_limit_worker
    worker.wait(3000)
    qapp.processEvents()
    assert "TSETMC test failure" in page.preview_result_label.text()

    page._set_preview_price_limit("max")
    request_id = page._buy_preview_request_id
    old_dialog = page._buy_preview_dialog
    old_snapshot = page._buy_preview_dialog_snapshot
    page._buy_preview_dialog = None
    page._on_preview_price_limits(request_id, "INS-PREVIEW", PriceLimits(price_max=9999),
                                  "max", old_dialog, old_snapshot)
    assert page.preview_price_input.text() == "1000"
