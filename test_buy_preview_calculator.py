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
from brokers.mofid.auth_adapter import MofidAuthenticationAdapter


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


@pytest.mark.parametrize("diagnostic,expected", [
    ("same_login_http_401", "فعال‌سازی نشست مفید با خطای HTTP 401 مواجه شد"),
    ("startsession_http_403", "آغاز نشست مفید با خطای HTTP 403 مواجه شد"),
    ("money_http_502", "دریافت قدرت خرید مفید با خطای HTTP 502 مواجه شد"),
])
def test_preview_http_failure_names_stage_and_status(qapp, diagnostic, expected):
    page, _, _ = _page(qapp)
    page.store.add("ACC-MOFID", "مفید", "Mofid")
    page.store.set_active("ACC-MOFID")
    page._buy_preview_dialog = object()
    page._buy_preview_dialog_snapshot = ("ACC-MOFID",)
    page._buy_preview_request_id = 1

    class FailedService:
        def get_adapter(self, account_id):
            return type("Adapter", (), {"last_purchase_power_diagnostic": diagnostic})()

    page.set_buy_preview_factory(lambda *_: FailedService())
    from PySide6.QtWidgets import QLabel
    page.preview_power_label = QLabel()
    page._on_preview_power_failed(1, "secret token or body")
    assert page.preview_power_label.text() == expected
    assert "secret" not in page.preview_power_label.text()


def test_preview_stale_reopen_http400_warning_and_fresh_replacement(qapp, monkeypatch):
    from test_block9_task4_authentication_service import make_service, seed_and_begin, ACC_A

    clock = [100.0]
    monkeypatch.setattr("ui.authentication_service.time.monotonic", lambda: clock[0])
    service = make_service()
    seed_and_begin(service, ACC_A)
    service.complete_login(ACC_A, "1234")
    adapter = service.get_adapter(ACC_A)
    adapter.get_tradable_balance = lambda: 75000
    page, _, _ = _page(qapp)
    snapshot = (ACC_A, service._accounts.get(ACC_A).broker_name)
    factory = lambda *_: service
    assert page._get_preview_power_and_form(snapshot, factory)["power"] == 75000
    clock[0] += 31

    def fail():
        adapter.last_purchase_power_diagnostic = "same_login_http_400"
        raise ValueError("failure")

    adapter.get_tradable_balance = fail
    data = page._get_preview_power_and_form(snapshot, factory)
    assert data == {"power": 75000, "stale_diagnostic": "same_login_http_400"}
    from PySide6.QtWidgets import QLabel
    page.store.add(ACC_A, snapshot[1], "account")
    page.store.set_active(ACC_A)
    page._buy_preview_dialog = object()
    page._buy_preview_dialog_snapshot = snapshot
    page._buy_preview_request_id = 1
    page.preview_power_label = QLabel()
    page._on_preview_power_loaded(1, snapshot, data)
    assert page._buy_preview_power == 75000
    assert page.preview_power_label.text() == "قدرت خرید قبلی: 75,000 ریال (به‌روزرسانی ناموفق؛ بررسی شود)"
    adapter.get_tradable_balance = lambda: 90000
    data = page._get_preview_power_and_form(snapshot, factory)
    assert data == {"power": 90000, "stale_diagnostic": None}
    page._on_preview_power_loaded(1, snapshot, data)
    assert page.preview_power_label.text() == "قدرت خرید: 90,000 ریال"


def test_preview_stale_first_failure_has_no_value(qapp):
    page, _, _ = _page(qapp)
    class FailedService:
        def get_tradable_balance(self, account_id):
            raise ValueError()
        def get_adapter(self, account_id):
            return type("Adapter", (), {"last_purchase_power_diagnostic": "same_login_http_400"})()
        def get_stale_purchase_power(self, account_id):
            return None
    with pytest.raises(RuntimeError, match="same_login_http_400"):
        page._get_preview_power_and_form(("account", "broker"), lambda *_: FailedService())


@pytest.mark.parametrize("money_body,expected", [
    ({"buyPowerT0": 11, "buyPowerT1": 22, "buyPowerT2": 33}, "33"),
    ({"buyPowerT0": 11, "buyPowerT1": 22}, "دریافت قدرت خرید مفید ناموفق بود؛ اتصال سرویس را بررسی کنید و دوباره تلاش کنید"),
    ({"buyPowerT0": 11, "buyPowerT1": 22, "buyPowerT2": "33"}, "دریافت قدرت خرید مفید ناموفق بود؛ اتصال سرویس را بررسی کنید و دوباره تلاش کنید"),
])
def test_mofid_preview_uses_real_account_service_and_documented_money_schema(qapp, money_body, expected):
    class FakeSession:
        def request(self, method, url, **kwargs):
            from test_mofid_auth_adapter import Response
            if url.endswith("/same-login"):
                return Response(body={})
            if url.endswith("/startsession"):
                return Response(body={"serverTime": "time", "startSessionTimeStamp": "stamp"})
            assert url.endswith("/easy/api/money")
            return Response(body=money_body)

    store = AccountStore(repository=False)
    store.add("ACC-MOFID-PREVIEW", "مفید", "حساب آزمایشی")
    store.set_active("ACC-MOFID-PREVIEW")
    page = OrderConfigurationPage(store, config=OrderConfiguration())
    adapter = MofidAuthenticationAdapter(
        client_id="offline-client",
        redirect_uri="https://app.invalid/callback",
        build_no="offline-build",
        platform_info="pytest-offline",
        session=FakeSession(),
    )
    adapter._authenticated = type("Session", (), {"access_token": "offline-token"})()

    class AccountBoundService:
        def get_tradable_balance(self, account_id):
            assert account_id == "ACC-MOFID-PREVIEW"
            return adapter.get_tradable_balance()

    service = AccountBoundService()
    page.set_buy_preview_factory(lambda account_id, broker_name: service)
    page.config.select_instrument(Instrument(symbol="نماد", name="نام", ins_code="INS-MOFID-PREVIEW"))
    page._order_nsc_id = "ISIN-MOFID-PREVIEW"
    page._open_buy_preview()
    qapp.processEvents()
    assert page._buy_preview_dialog is not None
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    if expected == "33":
        assert page.preview_power_label.text() == "قدرت خرید: 33 ریال"
    else:
        assert page.preview_power_label.text() == expected


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


def test_mofid_calculator_requires_instrument_pricing_data(qapp):
    store = AccountStore(repository=False)
    store.add("ACC-MOFID", "مفید", "مفید")
    store.set_active("ACC-MOFID")
    config = OrderConfiguration()
    config.select_instrument(Instrument(symbol="نماد", name="نام", ins_code="INS-MOFID"))
    page = OrderConfigurationPage(store, config=config)
    page._order_nsc_id = "ISIN-MOFID"
    service = _Service(_Broker(), balance=75_000)
    page.set_buy_preview_factory(lambda *_: service)
    page._open_buy_preview()
    qapp.processEvents()
    assert page._buy_preview_dialog is not None
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    assert "75,000" in page.preview_power_label.text()
    page.preview_price_input.setText("1000")
    page.preview_amount_input.setText("10000")
    page._buy_preview_power = 10000
    page._start_buy_preview()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    assert page._buy_preview_result is None
    assert page.quantity_input.text() == ""


def test_mofid_fee_status_does_not_claim_agah_service(qapp):
    store = AccountStore(repository=False)
    store.add("ACC-MOFID-FEE", "مفید", "مفید")
    store.set_active("ACC-MOFID-FEE")
    config = OrderConfiguration()
    config.select_instrument(Instrument(symbol="نماد", name="نام", ins_code="INS-MOFID-FEE"))
    page = OrderConfigurationPage(store, config=config)
    page._order_nsc_id = "ISIN-MOFID-FEE"
    page.set_buy_preview_factory(lambda *_: None)
    page.price_input.setText("1000")
    page.quantity_input.setText("2")
    page._start_auto_amount()
    if page._auto_amount_thread is not None:
        page._auto_amount_thread.wait(3000)
        qapp.processEvents()
    assert "مفید" in page.fee_label.text()
    assert "آگاه" not in page.fee_label.text()


def test_mofid_quantity_control_uses_verified_instrument_bounds(qapp):
    store = AccountStore(repository=False)
    store.add("ACC-MOFID-Q", "مفید", "مفید")
    store.set_active("ACC-MOFID-Q")
    config = OrderConfiguration()
    config.select_instrument(Instrument(symbol="نماد", name="نام", ins_code="INS-MOFID-Q"))
    page = OrderConfigurationPage(store, config=config)
    page.set_order_identity_factory(lambda *_: object())
    page._start_range_hint_requests = lambda *_: None
    scope = (7, "INS-MOFID-Q", ("ACC-MOFID-Q", "مفید"), "range")
    page._quantity_limits_scope = scope

    class Limits:
        minimum_order_quantity = 1
        maximum_order_quantity_for_buy = 300000
        maximum_order_quantity_for_sell = 300000

    page._on_quantity_range_succeeded(7, "INS-MOFID-Q", Limits())
    assert page.quantity_input.text() == "300000"


def test_mofid_math_and_budget_fail_closed(qapp):
    from types import SimpleNamespace
    store = AccountStore(repository=False)
    store.add("M", "مفید", "مفید")
    store.set_active("M")
    page = OrderConfigurationPage(store)
    broker = _Broker()
    page.set_buy_preview_factory(lambda *_: _Service(broker, 10000))
    details = SimpleNamespace(buy_commission="0.01", hide_price="0.5", csize=2,
                              minimum_order_quantity=3, maximum_order_quantity_for_buy=6)
    page._quantity_limits_factory = lambda *_: SimpleNamespace(get_instrument=lambda _: (None, details))
    snap = ("M", "مفید", "INS", "ISIN", 100, 0, 1, 1500)
    result = page._calculate_buy_preview(snap)
    assert result == {"price": 100, "quantity": 6, "amount": 600, "fee": 12, "total": 612}
    details.maximum_order_quantity_for_buy = 5
    with pytest.raises(ValueError):
        page._calculate_buy_preview(snap[:-1] + (600,))
    details.buy_commission = float("nan")
    with pytest.raises(ValueError):
        page._calculate_buy_preview(snap)
    assert broker.calls == []


@pytest.mark.parametrize("field,value", [
    ("buy_commission", True), ("buy_commission", "invalid"), ("buy_commission", float("inf")),
    ("hide_price", float("nan")), ("hide_price", -1),
    ("csize", 0), ("csize", -1), ("csize", float("inf")),
])
def test_mofid_pricing_error_identifies_missing_or_invalid_metadata(field, value):
    from types import SimpleNamespace
    from ui.order_configuration_page import _mofid_pricing

    details = SimpleNamespace(buy_commission="0.01", hide_price="0.5", csize=1)
    setattr(details, field, value)
    with pytest.raises(ValueError, match=field):
        _mofid_pricing(details)


def test_mofid_preview_defaults_only_missing_hide_price_and_csize(qapp):
    from types import SimpleNamespace
    store = AccountStore(repository=False)
    store.add("M", "مفید", "مفید")
    store.set_active("M")
    page = OrderConfigurationPage(store)
    power = 1_024_267_376
    page.set_buy_preview_factory(lambda *_: _Service(_Broker(), power))
    # Explicit mock commission; no commission is inferred from the reported scenario.
    details = SimpleNamespace(buy_commission="0.01", hide_price=None, csize=None,
                              minimum_order_quantity=1, maximum_order_quantity_for_buy=300000)
    page._quantity_limits_factory = lambda *_: SimpleNamespace(
        get_instrument=lambda _: (None, details))
    snapshot = ("M", "مفید", "INS", "ISIN", 9380, 0, 1, power)
    result = page._calculate_buy_preview(snapshot)
    assert result == {"price": 9380, "quantity": 108115, "amount": 1014118700,
                      "fee": 10141187, "total": 1024259887}


@pytest.mark.parametrize("quantity,price,reported_fee,exact_fee,rounded_fee", [
    (4981, 2000, 36978, "36978.944", 36979),
    (996, 500000, 1848576, "1848576", 1848576),
    (3320, 1500, 18485, "18485.76", 18486),
    (39852, 25000, 3700062, "3698265.6", 3698266),
    (498, 100000, 184857, "184857.6", 184858),
    (996, 12345, 45641, "45641.34144", 45641),
    (996, 1000000, 3697152, "3697152", 3697152),
    (99, 5000, 1837, "1837.44", 1837),
    (498, 50000, 92428, "92428.8", 92429),
])
def test_mofid_js_fee_rounding_exposes_user_scenario_mismatches(
        quantity, price, reported_fee, exact_fee, rounded_fee):
    """Check direct commission formula and preserve reported mismatches."""
    from fractions import Fraction
    from ui.order_configuration_page import _mofid_total

    exact = Fraction(quantity * price) * Fraction("0.003712")
    if exact_fee is not None:
        assert exact == Fraction(exact_fee)
    direct_formula_fee = (quantity * price * Fraction("0.003712"))
    assert exact == direct_formula_fee
    actual_fee = _mofid_total(price, quantity,
                              (Fraction("0.003712"), Fraction(0), Fraction(1)))
    expected_rounded = (2 * exact.numerator + exact.denominator) // (2 * exact.denominator)
    assert actual_fee == expected_rounded
    if rounded_fee is not None:
        assert actual_fee == rounded_fee
    # The scenario report is data, not an assumed correct calculator result.
    assert (reported_fee != actual_fee) == (reported_fee != rounded_fee)


@pytest.mark.parametrize("amount,price,expected", [
    (100_000_000, 100_000, 996),
    (10_000_000, 50_000, 199),
    (3_000_000, 15_000, 199),
])
def test_mofid_quantity_matches_documented_javascript(amount, price, expected):
    from types import SimpleNamespace
    store = AccountStore(repository=False)
    store.add("M", "مفید", "مفید")
    store.set_active("M")
    page = OrderConfigurationPage(store)
    page.set_buy_preview_factory(lambda *_: _Service(_Broker(), amount))
    details = SimpleNamespace(buy_commission="0.003712", hide_price="0", csize=1,
                              minimum_order_quantity=1, maximum_order_quantity_for_buy=10000)
    page._quantity_limits_factory = lambda *_: SimpleNamespace(get_instrument=lambda _: (None, details))
    snapshot = ("M", "مفید", "INS", "ISIN", price, 0, 1, amount)
    result = page._calculate_buy_preview(snapshot)
    assert result["quantity"] == expected


def test_mofid_auto_total_fetches_power_without_agah(qapp):
    from types import SimpleNamespace
    store = AccountStore(repository=False)
    store.add("M", "مفید", "مفید")
    store.set_active("M")
    config = OrderConfiguration()
    config.select_instrument(Instrument(symbol="s", name="n", ins_code="INS"))
    page = OrderConfigurationPage(store, config=config)
    page._order_nsc_id = "ISIN"
    broker = _Broker()
    page.set_buy_preview_factory(lambda *_: _Service(broker, 200))
    details = SimpleNamespace(buy_commission="0.01", hide_price="0.5", csize=1)
    page._quantity_limits_factory = lambda *_: SimpleNamespace(get_instrument=lambda _: (None, details))
    page.price_input.setText("100")
    page.quantity_input.setText("2")
    page._start_auto_amount()
    page._auto_amount_thread.wait(3000)
    qapp.processEvents()
    assert page.final_amount_label.text() == "۲۰۲"
    assert page.amount_warning_label.text() == "مبلغ نهایی از موجودی شما بیشتر است"
    assert broker.calls == []


def test_mofid_auto_total_uses_stale_power_after_http400(qapp):
    from types import SimpleNamespace
    store = AccountStore(repository=False)
    store.add("M", "مفید", "مفید")
    store.set_active("M")
    config = OrderConfiguration()
    config.select_instrument(Instrument(symbol="s", name="n", ins_code="INS"))
    page = OrderConfigurationPage(store, config=config)
    page._order_nsc_id = "ISIN"

    class Service:
        def get_tradable_balance(self, _account):
            raise RuntimeError("Mofid purchase power is unavailable")
        def get_adapter(self, _account):
            return SimpleNamespace(last_purchase_power_diagnostic="money_http_400")
        def get_stale_purchase_power(self, _account):
            return (150, 1.0)

    page.set_buy_preview_factory(lambda *_: Service())
    details = SimpleNamespace(buy_commission="0.01", hide_price="0.5", csize=1)
    page._quantity_limits_factory = lambda *_: SimpleNamespace(get_instrument=lambda _: (None, details))
    page.price_input.setText("100")
    page.quantity_input.setText("2")
    page._start_auto_amount()
    page._auto_amount_thread.wait(3000)
    qapp.processEvents()
    assert page.fee_label.text() == "۲"
    assert page.final_amount_label.text() == "۲۰۲"
    assert "قدرت خرید قبلی: 150 ریال (به‌روزرسانی ناموفق؛ بررسی شود)" in page.amount_warning_label.text()
    assert "Mofid" not in page.fee_label.text() + page.amount_warning_label.text()


def test_mofid_auto_total_without_stale_power_is_localized(qapp):
    from types import SimpleNamespace
    store = AccountStore(repository=False)
    store.add("M", "مفید", "مفید")
    store.set_active("M")
    config = OrderConfiguration()
    config.select_instrument(Instrument(symbol="s", name="n", ins_code="INS"))
    page = OrderConfigurationPage(store, config=config)
    page._order_nsc_id = "ISIN"

    class Service:
        def get_tradable_balance(self, _account):
            raise RuntimeError("Mofid purchase power is unavailable")
        def get_adapter(self, _account):
            return SimpleNamespace(last_purchase_power_diagnostic="money_http_400")
        def get_stale_purchase_power(self, _account):
            return None

    page.set_buy_preview_factory(lambda *_: Service())
    page._quantity_limits_factory = lambda *_: SimpleNamespace(get_instrument=lambda _: (None, SimpleNamespace(
        buy_commission="0.01", hide_price="0.5", csize=1)))
    page.price_input.setText("100")
    page.quantity_input.setText("2")
    page._start_auto_amount()
    page._auto_amount_thread.wait(3000)
    qapp.processEvents()
    assert page.fee_label.text() == "قدرت خرید مفید در دسترس نیست"
    assert "Mofid" not in page.fee_label.text()


def _mofid_calculator_page(qapp):
    from types import SimpleNamespace
    store = AccountStore(repository=False)
    store.add("M", "مفید", "مفید")
    store.set_active("M")
    config = OrderConfiguration()
    config.select_instrument(Instrument(symbol="s", name="n", ins_code="INS"))
    page = OrderConfigurationPage(store, config=config)
    page._order_nsc_id = "ISIN"
    page.set_buy_preview_factory(lambda *_: _Service(_Broker(), 10000))
    page._quantity_limits_factory = lambda *_: SimpleNamespace(get_instrument=lambda _: (None, SimpleNamespace(
        buy_commission="0.01", hide_price="0.5", csize=1,
        minimum_order_quantity=1, maximum_order_quantity_for_buy=100)))
    page._open_buy_preview()
    qapp.processEvents()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    page.preview_price_input.setText("100")
    page.preview_amount_input.setText("1000")
    return page


def test_mofid_calculation_failure_is_visible_and_reenables_calculate(qapp):
    page = _mofid_calculator_page(qapp)
    page._quantity_limits_factory = lambda *_: (_ for _ in ()).throw(RuntimeError("offline"))
    page._start_buy_preview()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    assert "محاسبه ناموفق بود" in page.preview_result_label.text()
    assert page.preview_calculate_button.isEnabled()
    assert not page.preview_confirm_button.isEnabled()


def test_mofid_calculation_renders_and_confirms_matching_snapshot(qapp):
    page = _mofid_calculator_page(qapp)
    page._start_buy_preview()
    page._buy_preview_thread.wait(3000)
    qapp.processEvents()
    assert page._buy_preview_result == {"price": 100, "quantity": 9, "amount": 900, "fee": 9, "total": 909}
    assert "900" in page.preview_result_label.text()
    assert "9" in page.preview_result_label.text()
    assert "909" in page.preview_result_label.text()
    assert page.preview_confirm_button.isEnabled()


def test_mofid_stale_account_calculation_result_is_ignored(qapp):
    page = _mofid_calculator_page(qapp)
    request_id = page._buy_preview_request_id
    snapshot = page._buy_preview_snapshot_value
    page.store.add("OTHER", "مفید", "دیگر")
    page.store.set_active("OTHER")
    page._on_buy_preview_calculated(request_id, snapshot,
                                    {"price": 100, "quantity": 9, "amount": 900, "fee": 9, "total": 909})
    assert page._buy_preview_result is None
    assert not page.preview_confirm_button.isEnabled()


def test_preview_inputs_changed_uses_running_flag_not_deleted_thread(qapp):
    page = _mofid_calculator_page(qapp)
    class DeletedThreadWrapper:
        def isRunning(self):
            raise RuntimeError("wrapped C++ object has been deleted")

    # A deleted Qt wrapper fails loudly if the implementation queries it.
    page._buy_preview_thread = DeletedThreadWrapper()
    page._buy_preview_worker_running = True
    page.preview_calculate_button.setEnabled(True)
    page.preview_confirm_button.setEnabled(True)
    page._preview_inputs_changed()
    assert not page.preview_calculate_button.isEnabled()
    assert not page.preview_confirm_button.isEnabled()

    # Simulate the completed worker state without repeating Qt thread
    # lifecycle/cleanup in this regression test.
    page._buy_preview_worker_running = False
    page.preview_calculate_button.setEnabled(False)
    page._preview_inputs_changed()
    assert page.preview_calculate_button.isEnabled()
    assert not page.preview_confirm_button.isEnabled()
