"""
Offline tests for the price/quantity limit arrows on the order form.

Covered contracts:
  * TSETMC old Loader PSGelStaMin/PSGelStaMax -> allowed lower/upper price.
  * The price request uses the selected Instrument's TSETMC InsCode.
  * Quantity limits come from the exact active (account, broker) provider.
  * Buy/sell side selects the right broker quantity ceiling.
  * Missing/invalid data never changes the field and shows a message.
  * Late responses for a replaced symbol or side are discarded.
"""

from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from market.tsetmc import (
    PRICE_LIMITS_URL,
    PriceLimits,
    PriceLimitsUnavailable,
    TSETMC,
)
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, SELL

from ui import strings as STRINGS
from ui.account_store import AccountStore
from ui.order_config_state import OrderConfiguration
from ui.order_configuration_page import OrderConfigurationPage
from market.symbol_resolver import SymbolResolver


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _process(qapp, rounds=5):
    for _ in range(rounds):
        qapp.processEvents()


def _wait_limits(page, qapp):
    page.wait_for_limit_workers(timeout_ms=3000)
    _process(qapp)


def _make_page(ins_code="INS-100"):
    store = AccountStore()
    store.add("ACC-1", "آگاه", "حساب یک")
    store.set_active("ACC-1")
    config = OrderConfiguration()
    instrument = Instrument(
        symbol="آکو",
        name="آکو باتری",
        ins_code=ins_code,
    )
    config.select_instrument(instrument)
    return OrderConfigurationPage(store, config=config), instrument


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    @property
    def text(self):
        return self._payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return _Response(self.payload)


class _FailingSession:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        raise RuntimeError("network failed")


class _PriceClient:
    def __init__(self, limits):
        self.limits = limits
        self.calls = []

    def get_price_limits(self, ins_code):
        self.calls.append(ins_code)
        return self.limits


class _Provider:
    def __init__(self, broker_instrument):
        self.broker_instrument = broker_instrument
        self.calls = []

    def get_instrument(self, ins_code):
        self.calls.append(ins_code)
        return (Instrument("آکو", "آکو", ins_code), self.broker_instrument)


# ---------------------------------------------------------------------------
# TSETMC mapping
# ---------------------------------------------------------------------------

INS_CODE = "35366681030756042"
REAL_INS_CODE = "39485921411827022"

# Sanitized excerpt from the real old Loader response for REAL_INS_CODE.
# The field values are the actual PSGelStaMin/PSGelStaMax pair; unrelated
# page fields were omitted.
_SANITIZED_REAL_LOADER_HTML = """<!doctype html>
<html><body><script type="text/javascript">
var TopInst='0',LVal18AFC='...',InsCode='39485921411827022',
PdrCotVal='',PClosing='',PSGelStaMax='14240.00',PSGelStaMin='13420.00',
Title='...',PriceMin=0,PriceMax=0,PriceYesterday=0;
</script></body></html>
"""

_SANITIZED_LOADER_HTML = """<!doctype html>
<html><body><script type="text/javascript">
var PSGelStaMax = 7900;
var PSGelStaMin = 7630;
</script></body></html>
"""

# Regression shape: the Loader is JavaScript, so whole prices can arrive as
# integral decimal numbers/strings. The fraction must be accepted only when
# it is exactly zero.
_SANITIZED_LOADER_HTML_INTEGRAL_DECIMALS = """<!doctype html>
<html><body><script type="text/javascript">
var PSGelStaMin = 7630.0;
var PSGelStaMax = "7900.00";
</script></body></html>
"""


def test_tsetmc_old_loader_endpoint_and_allowed_range_mapping():
    client = TSETMC()
    session = _Session(_SANITIZED_REAL_LOADER_HTML)
    client.session = session

    limits = client.get_price_limits(REAL_INS_CODE)

    assert PRICE_LIMITS_URL.startswith("https://old.tsetmc.com/")
    assert session.urls == [PRICE_LIMITS_URL.format(ins_code=REAL_INS_CODE)]
    assert limits == PriceLimits(price_min=13420, price_max=14240)
    assert isinstance(limits.price_min, int)
    assert isinstance(limits.price_max, int)


def test_tsetmc_accepts_quoted_digit_js_values():
    client = TSETMC()
    client.session = _Session(
        "<script>var PSGelStaMin = ' 7630 ';"
        ' var PSGelStaMax = "7900";</script>'
    )

    assert client.get_price_limits(INS_CODE) == PriceLimits(7630, 7900)


def test_tsetmc_accepts_integral_decimal_js_values():
    client = TSETMC()
    client.session = _Session(_SANITIZED_LOADER_HTML_INTEGRAL_DECIMALS)

    limits = client.get_price_limits(INS_CODE)

    assert limits == PriceLimits(price_min=7630, price_max=7900)
    assert isinstance(limits.price_min, int)
    assert isinstance(limits.price_max, int)


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<html><body>no price fields</body></html>",
        "<script>var PSGelStaMax = 7900;</script>",  # missing lower
        "<script>var PSGelStaMin = 7630;</script>",  # missing upper
    ],
)
def test_tsetmc_missing_loader_fields_raise_unavailable(html):
    client = TSETMC()
    client.session = _Session(html)

    with pytest.raises(PriceLimitsUnavailable):
        client.get_price_limits(INS_CODE)


@pytest.mark.parametrize(
    "html",
    [
        "<script>var PSGelStaMin = 0; var PSGelStaMax = 7900;</script>",
        "<script>var PSGelStaMin = 8000; var PSGelStaMax = 7900;</script>",
        "<script>var PSGelStaMin = -7630; var PSGelStaMax = 7900;</script>",
        "<script>var PSGelStaMin = '7630.5'; var PSGelStaMax = '7900';</script>",
        "<script>var PSGelStaMin = '7630.10'; var PSGelStaMax = '7900';</script>",
        "<script>var PSGelStaMin = '7630.'; var PSGelStaMax = '7900';</script>",
        "<script>var PSGelStaMin = '7.63e3'; var PSGelStaMax = '7900';</script>",
        "<script>var PSGelStaMin = 'bad'; var PSGelStaMax = '7900';</script>",
        "<script>var PSGelStaMin = '1,234'; var PSGelStaMax = '7900';</script>",
        "<script>var PSGelStaMin = ''; var PSGelStaMax = '7900';</script>",
        "<script>var PSGelStaMin = 7630; var PSGelStaMax = '';</script>",
        "<script>var PSGelStaMin = ; var PSGelStaMax = 7900;</script>",
        "<script>var PSGelStaMin = 7630; var PSGelStaMax = ;</script>",
    ],
)
def test_tsetmc_present_but_invalid_loader_values_stay_none(html):
    client = TSETMC()
    client.session = _Session(html)

    assert client.get_price_limits(INS_CODE) == PriceLimits(None, None)


# ---------------------------------------------------------------------------
# Price arrows
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "html, ins_code, expected_min, expected_max",
    [
        (
            _SANITIZED_REAL_LOADER_HTML,
            REAL_INS_CODE,
            13420,
            14240,
        ),
        (_SANITIZED_LOADER_HTML, INS_CODE, 7630, 7900),
        (
            _SANITIZED_LOADER_HTML_INTEGRAL_DECIMALS,
            INS_CODE,
            7630,
            7900,
        ),
    ],
)
def test_price_arrows_apply_loader_allowed_range_end_to_end(
    qapp, html, ins_code, expected_min, expected_max
):
    client = TSETMC()
    client.session = _Session(html)
    resolver = SymbolResolver.__new__(SymbolResolver)
    resolver.tsetmc = client

    page, instrument = _make_page(ins_code)
    page.set_price_limits_factory(lambda: resolver)

    page.price_max_button.click()
    _wait_limits(page, qapp)
    assert page.price_input.text() == str(expected_max)
    assert page.config.price == expected_max

    page.price_min_button.click()
    _wait_limits(page, qapp)
    assert page.price_input.text() == str(expected_min)
    assert page.config.price == expected_min
    expected_url = PRICE_LIMITS_URL.format(ins_code=ins_code)
    assert client.session.urls[-2:] == [expected_url, expected_url]
    assert instrument.ins_code == ins_code


@pytest.mark.parametrize(
    "limits",
    [
        PriceLimits(price_min=1200.0, price_max=3400.0),
        PriceLimits(price_min="1200.0", price_max="3400.00"),
    ],
)
def test_price_arrows_use_ins_code_and_existing_validation(qapp, limits):
    page, instrument = _make_page("INS-123")
    # Raw Loader shapes (integral float + integral-decimal string) must be
    # accepted once and for all, not rejected by the UI's second validator.
    client = _PriceClient(limits)
    page.set_price_limits_factory(lambda: client)

    page.price_max_button.click()
    _wait_limits(page, qapp)
    assert client.calls[-1] == instrument.ins_code
    assert page.price_input.text() == "3400"
    assert page.config.price == 3400

    page.price_min_button.click()
    _wait_limits(page, qapp)
    assert page.price_input.text() == "1200"
    assert page.config.price == 1200


def test_price_uses_the_existing_symbol_resolver_seam(qapp):
    page, instrument = _make_page("INS-SEAM")
    resolver = _PriceClient(PriceLimits(price_min=700, price_max=900))
    page.set_resolver_factory(lambda: resolver)

    page.price_max_button.click()
    _wait_limits(page, qapp)

    assert resolver.calls == [instrument.ins_code]
    assert page.price_input.text() == "900"


def test_symbol_resolver_delegates_price_limits():
    resolver = SymbolResolver.__new__(SymbolResolver)
    resolver.tsetmc = _PriceClient(PriceLimits(price_min=1, price_max=2))

    assert resolver.get_price_limits("INS-X") == PriceLimits(1, 2)


@pytest.mark.parametrize(
    "limits",
    [
        PriceLimits(price_min=None, price_max=None),
        PriceLimits(price_min=0, price_max=0.5),
        PriceLimits(price_min="", price_max="unknown"),
    ],
)
def test_invalid_price_limit_preserves_previous_input(qapp, limits):
    page, _instrument = _make_page()
    page.price_input.setText("999")
    page._on_price_changed()
    page.set_price_limits_factory(lambda: _PriceClient(limits))

    page.price_max_button.click()
    _wait_limits(page, qapp)

    assert page.price_input.text() == "999"
    assert page.config.price == 999
    assert page.validation_error_label.text() == STRINGS.LIMIT_PRICE_INVALID


def test_missing_loader_fields_show_unavailable_and_preserve_input(qapp):
    page, _instrument = _make_page()
    page.price_input.setText("999")
    page._on_price_changed()
    client = TSETMC()
    client.session = _Session("<html><body>no price fields</body></html>")
    page.set_price_limits_factory(lambda: client)

    page.price_max_button.click()
    _wait_limits(page, qapp)

    assert page.price_input.text() == "999"
    assert page.config.price == 999
    assert (
        page.validation_error_label.text()
        == STRINGS.LIMIT_PRICE_UNAVAILABLE
    )


def test_failed_loader_request_shows_unavailable_and_preserves_input(qapp):
    page, _instrument = _make_page()
    page.price_input.setText("999")
    page._on_price_changed()
    client = TSETMC()
    client.session = _FailingSession()
    page.set_price_limits_factory(lambda: client)

    page.price_max_button.click()
    _wait_limits(page, qapp)

    assert page.price_input.text() == "999"
    assert page.config.price == 999
    assert (
        page.validation_error_label.text()
        == STRINGS.LIMIT_PRICE_UNAVAILABLE
    )


def test_present_but_invalid_loader_values_show_invalid(qapp):
    page, _instrument = _make_page()
    page.price_input.setText("999")
    page._on_price_changed()
    client = TSETMC()
    client.session = _Session(
        "<script>var PSGelStaMin = '7630.5';"
        " var PSGelStaMax = '7900';</script>"
    )
    page.set_price_limits_factory(lambda: client)

    page.price_max_button.click()
    _wait_limits(page, qapp)

    assert page.price_input.text() == "999"
    assert page.config.price == 999
    assert page.validation_error_label.text() == STRINGS.LIMIT_PRICE_INVALID


# ---------------------------------------------------------------------------
# Quantity arrows
# ---------------------------------------------------------------------------

def test_quantity_arrows_use_active_account_provider_and_side(qapp):
    page, instrument = _make_page("INS-777")
    broker_instrument = BrokerInstrument(
        minimum_order_quantity=10,
        maximum_order_quantity_for_buy=100,
        maximum_order_quantity_for_sell=200,
    )
    providers = []

    def provider_factory(account_id, broker_name):
        provider = _Provider(broker_instrument)
        providers.append((account_id, broker_name, provider))
        return provider

    page.set_quantity_limits_factory(provider_factory)

    page.quantity_max_button.click()
    _wait_limits(page, qapp)
    assert page.quantity_input.text() == "100"
    assert page.config.quantity == 100
    assert providers[-1][0:2] == ("ACC-1", "آگاه")
    assert providers[-1][2].calls == [instrument.ins_code]

    page.side_buttons[SELL].click()
    page.quantity_max_button.click()
    _wait_limits(page, qapp)
    assert page.quantity_input.text() == "200"
    assert page.config.quantity == 200

    page.quantity_min_button.click()
    _wait_limits(page, qapp)
    assert page.quantity_input.text() == "10"
    assert page.config.quantity == 10


def test_invalid_quantity_limit_does_not_change_input(qapp):
    page, _instrument = _make_page()
    page.quantity_input.setText("33")
    page._on_quantity_changed()
    page.set_quantity_limits_factory(
        lambda _account, _broker: _Provider(
            BrokerInstrument(
                minimum_order_quantity=None,
                maximum_order_quantity_for_buy=None,
                maximum_order_quantity_for_sell=None,
            )
        )
    )

    page.quantity_max_button.click()
    _wait_limits(page, qapp)

    assert page.quantity_input.text() == "33"
    assert page.config.quantity == 33
    assert (
        page.validation_error_label.text()
        == STRINGS.LIMIT_QUANTITY_INVALID
    )


def test_quantity_without_active_account_keeps_input(qapp):
    page, _instrument = _make_page()
    page.quantity_input.setText("55")
    page._on_quantity_changed()
    page.store.delete("ACC-1")

    page.quantity_max_button.click()
    _wait_limits(page, qapp)

    assert page.quantity_input.text() == "55"
    assert page.config.quantity == 55
    assert (
        page.validation_error_label.text()
        == STRINGS.LIMIT_QUANTITY_NO_ACCOUNT
    )


# ---------------------------------------------------------------------------
# Stale-response rejection
# ---------------------------------------------------------------------------

class _GatedPriceClient:
    def __init__(self, limits):
        self.limits = limits
        self.started = threading.Event()
        self.release = threading.Event()

    def get_price_limits(self, ins_code):
        self.started.set()
        self.release.wait(2)
        return self.limits


class _GatedProvider:
    def __init__(self, broker_instrument):
        self.broker_instrument = broker_instrument
        self.started = threading.Event()
        self.release = threading.Event()

    def get_instrument(self, ins_code):
        self.started.set()
        self.release.wait(2)
        return (Instrument("آکو", "آکو", ins_code), self.broker_instrument)


def _wait_started(event):
    deadline = time.monotonic() + 2
    while not event.is_set() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert event.is_set()


def test_stale_price_response_after_symbol_change_is_discarded(qapp):
    page, _instrument = _make_page("INS-OLD")
    client = _GatedPriceClient(PriceLimits(price_min=1, price_max=9))

    try:
        page.set_price_limits_factory(lambda: client)
        page.price_max_button.click()
        _wait_started(client.started)

        page._on_symbol_edited("نماد جدید")
        page._debounce_timer.stop()
        client.release.set()
        _wait_limits(page, qapp)

        assert page.price_input.text() == ""
        assert page.config.price is None
    finally:
        client.release.set()


def test_stale_price_response_after_account_change_is_discarded(qapp):
    page, _instrument = _make_page("INS-ACC")
    client = _GatedPriceClient(PriceLimits(price_min=3, price_max=4))

    try:
        page.set_price_limits_factory(lambda: client)
        page.price_max_button.click()
        _wait_started(client.started)

        page.store.add("ACC-2", "آگاه", "حساب دو")
        page.store.set_active("ACC-2")
        client.release.set()
        _wait_limits(page, qapp)

        assert page.price_input.text() == ""
        assert page.config.price is None
    finally:
        client.release.set()


def test_stale_quantity_response_after_side_change_is_discarded(qapp):
    page, _instrument = _make_page("INS-SIDE")
    provider = _GatedProvider(
        BrokerInstrument(
            minimum_order_quantity=5,
            maximum_order_quantity_for_buy=111,
            maximum_order_quantity_for_sell=222,
        )
    )

    try:
        page.set_quantity_limits_factory(lambda _account, _broker: provider)
        page.quantity_max_button.click()
        _wait_started(provider.started)

        page.side_buttons[SELL].click()
        provider.release.set()
        _wait_limits(page, qapp)

        assert page.quantity_input.text() == ""
        assert page.config.quantity is None
    finally:
        provider.release.set()
