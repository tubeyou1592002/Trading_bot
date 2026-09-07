"""
test_main_order_workflow.py

Tests for M4-B: main.py order workflow integration.

Tests that main.py correctly:
  1. wires InstrumentProvider alongside Broker in on_broker_changed
  2. stores selected_instrument in select_symbol
  3. calls OrderEngine.execute_by_ins_code via send_order
  4. handles all error paths gracefully without crashing
  5. never sends a real order (live=False)

These tests are fully offline:
  - no network
  - no login
  - no captcha
  - no real order
  - no TSETMC call (uses fakes)

Run:
    python test_main_order_workflow.py
"""

import sys
import traceback


from PySide6.QtWidgets import QApplication

from brokers.agaah import (
    AgaahBroker,
    AgaahInstrumentProvider,
)
from brokers.base import Broker, InstrumentProvider
from core.order_engine import OrderEngine
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, Order, SELL
from models.trading_state import (
    UNVERIFIED,
    VERIFIED_TRADABLE,
    TradingState,
)

from main import SymbolSearchWindow


app = QApplication([])

TEST_RESULTS = []


def _run(name, fn):
    try:
        fn()
        TEST_RESULTS.append((name, "PASS", None))
    except Exception as exc:
        TEST_RESULTS.append((
            name,
            "FAIL",
            f"{type(exc).__name__}: {exc}",
        ))
        traceback.print_exc()


# ============================================================
# Fakes
# ============================================================


class _StubBroker(Broker):
    """
    Minimal fake broker for testing main.py wiring.
    Subclasses Broker ABC so OrderEngine accepts it.
    """

    def __init__(
        self,
        state=UNVERIFIED,
        account=None,
        placed_calls=None,
    ):
        self._state = state
        self._account = account or Account(
            tradable_balance_t1=10_000_000
        )
        self.placed_calls = (
            placed_calls
            if placed_calls is not None
            else []
        )
        self.get_account_calls = []
        self.get_trading_state_calls = []
        self.live_trading_enabled = False

    @property
    def name(self):
        return "آگاه"

    def login(self, username, password, **kwargs):
        return {"userName": username}

    def get_account(self):
        self.get_account_calls.append(True)
        return self._account

    def get_trading_state(self, nsc_id):
        self.get_trading_state_calls.append(nsc_id)
        return self._state

    def get_instrument(self, nsc_id):
        raise NotImplementedError(
            "not used in this test"
        )

    def place_order(self, order, live=False):
        self.placed_calls.append({
            "order": order,
            "live": live,
        })
        if not live:
            return {
                "mode": "DRY_RUN",
                "sent": False,
                "payload": order.to_payload(),
            }
        raise RuntimeError(
            "live trading disabled"
        )

    def cancel_order(self, order_id):
        raise NotImplementedError


class _StubProvider(InstrumentProvider):
    """
    Minimal stub provider for testing main.py wiring.
    Does NOT use AgaahInstrumentProvider — just returns
    canned data so the test has no network dependency.
    """

    def __init__(self, nsc_id, broker_instrument, instrument):
        self._nsc_id = nsc_id
        self._broker_instrument = broker_instrument
        self._instrument = instrument
        self.get_instrument_calls = []
        self.get_nsc_id_calls = []

    def get_instrument(self, ins_code):
        self.get_instrument_calls.append(ins_code)
        return (self._instrument, self._broker_instrument)

    def get_nsc_id(self, ins_code):
        self.get_nsc_id_calls.append(ins_code)
        return self._nsc_id

    def refresh_cache(self):
        pass


# ============================================================
# Fixtures
# ============================================================


def _make_instrument(ins_code="35366681030756042"):
    return Instrument(
        symbol="شبندر",
        name="پالایش نفت بندرعباس",
        ins_code=ins_code,
        instrument_id="IRO1ACCO0001",
        isin="IRO1ACCO0001",
        market="بورس",
        flow=1,
    )


def _make_broker_instrument(
    nsc_id="IRO1PNBA0001",
    ins_code="35366681030756042",
):
    return BrokerInstrument(
        name="شبندر",
        company_name="پالایش نفت بندرعباس",
        nsc_id=nsc_id,
        tse_id=ins_code,
        market_title="بورس",
        state_code="A",
        group_state_code="B",
        last_trade_price=716,
        final_price=715,
        previous_day_price=696,
        upper_price_threshold=716,
        lower_price_threshold=676,
        minimum_order_quantity=1,
        lot_size=1,
        fixed_price_tick=1.0,
        maximum_order_quantity_for_buy=3_000_000,
        maximum_order_quantity_for_sell=3_000_000,
        bid_ask_list=[],
        is_fund=False,
    )


def _make_order(nsc_id="IRO1PNBA0001", price=716, quantity=100):
    return Order(
        nsc_id=nsc_id,
        side=BUY,
        price=price,
        quantity=quantity,
        bank_account_id=0,
    )


# ============================================================
# Tests
# ============================================================


def test_smoke_import():
    """
    Test 1: main.py imports without error.
    """
    import main
    assert hasattr(main, "SymbolSearchWindow")
    assert hasattr(main, "main")
    assert hasattr(main, "OrderEngine")
    assert hasattr(main.SymbolSearchWindow, "send_order")


def test_broker_and_provider_wired():
    """
    Test 2: on_broker_changed sets BOTH current_broker
    and current_provider when a valid broker name is given.
    """
    window = SymbolSearchWindow(None)

    assert window.current_broker is not None
    assert window.current_provider is not None

    assert isinstance(window.current_broker, AgaahBroker)
    assert isinstance(
        window.current_provider, AgaahInstrumentProvider
    )


def test_provider_uses_same_broker_instance():
    """
    Test 3: The provider's internal broker is the exact
    same AgaahBroker instance as current_broker (no
    new AgaahBroker constructed by the manager).
    """
    window = SymbolSearchWindow(None)

    assert window.current_provider._broker is (
        window.current_broker
    )


def test_send_order_without_broker_graceful():
    """
    Test 4: send_order with no broker/provider set
    must not crash — must display a status message.
    """
    window = SymbolSearchWindow(None)
    window.current_broker = None
    window.current_provider = None

    original_label = window.status_label.text()

    window.send_order()

    assert window.status_label.text() != original_label


def test_send_order_without_instrument_graceful():
    """
    Test 5: send_order with no selected_instrument
    must not crash — must display a status message.
    """
    window = SymbolSearchWindow(None)
    window.selected_instrument = None

    original_label = window.status_label.text()

    window.send_order()

    assert window.status_label.text() != original_label


def test_send_order_dry_run_success():
    """
    Test 6: Full dry-run flow with a stub broker that
    returns VERIFIED_TRADABLE.

    Verify:
      - OrderEngine.execute_by_ins_code is called
      - broker.place_order is called exactly once with live=False
      - result mode is DRY_RUN
      - no real order is sent (sent=False)
      - provider.get_nsc_id is called
      - provider.get_instrument is called (inside execute_by_ins_code)
    """
    ins_code = "35366681030756042"
    nsc_id = "IRO1PNBA0001"

    instrument = _make_instrument(ins_code)
    broker_instrument = _make_broker_instrument(
        nsc_id=nsc_id, ins_code=ins_code
    )

    stub_broker = _StubBroker(
        state=VERIFIED_TRADABLE
    )
    stub_provider = _StubProvider(
        nsc_id=nsc_id,
        broker_instrument=broker_instrument,
        instrument=instrument,
    )

    window = SymbolSearchWindow(None)
    window.current_broker = stub_broker
    window.current_provider = stub_provider
    window.selected_instrument = instrument
    window.side_combo.setCurrentIndex(0)
    window.price_edit.setText("716")
    window.quantity_edit.setText("100")

    window.send_order()

    assert "DRY_RUN" in window.status_label.text(), (
        f"expected DRY_RUN in status, got: "
        f"{window.status_label.text()!r}"
    )
    assert len(stub_broker.placed_calls) == 1, (
        "broker.place_order must be called exactly once"
    )
    assert stub_broker.placed_calls[0]["live"] is False, (
        "order must be dry-run (live=False)"
    )
    assert len(stub_provider.get_nsc_id_calls) == 1, (
        "provider.get_nsc_id must be called once"
    )
    assert len(stub_provider.get_instrument_calls) == 1, (
        "provider.get_instrument must be called "
        "once (inside execute_by_ins_code)"
    )


def test_send_order_blocked_when_unverified():
    """
    Test 7: With a stub broker that returns UNVERIFIED,
    send_order must block the order per M6-A fail-closed
    policy. No real order is sent, no crash occurs.
    """
    ins_code = "35366681030756042"
    nsc_id = "IRO1PNBA0001"

    instrument = _make_instrument(ins_code)
    broker_instrument = _make_broker_instrument(
        nsc_id=nsc_id, ins_code=ins_code
    )

    stub_broker = _StubBroker(
        state=UNVERIFIED
    )
    stub_provider = _StubProvider(
        nsc_id=nsc_id,
        broker_instrument=broker_instrument,
        instrument=instrument,
    )

    window = SymbolSearchWindow(None)
    window.current_broker = stub_broker
    window.current_provider = stub_provider
    window.selected_instrument = instrument
    window.side_combo.setCurrentIndex(0)
    window.price_edit.setText("716")
    window.quantity_edit.setText("100")

    window.send_order()

    assert "BLOCKED" in window.status_label.text(), (
        f"expected BLOCKED in status, got: "
        f"{window.status_label.text()!r}"
    )
    assert len(stub_broker.placed_calls) == 0, (
        "broker.place_order must NOT be called "
        "when trading state is UNVERIFIED"
    )


# ============================================================
# Runner
# ============================================================


def main():
    _run("test_smoke_import", test_smoke_import)
    _run(
        "test_broker_and_provider_wired",
        test_broker_and_provider_wired,
    )
    _run(
        "test_provider_uses_same_broker_instance",
        test_provider_uses_same_broker_instance,
    )
    _run(
        "test_send_order_without_broker_graceful",
        test_send_order_without_broker_graceful,
    )
    _run(
        "test_send_order_without_instrument_graceful",
        test_send_order_without_instrument_graceful,
    )
    _run(
        "test_send_order_dry_run_success",
        test_send_order_dry_run_success,
    )
    _run(
        "test_send_order_blocked_when_unverified",
        test_send_order_blocked_when_unverified,
    )

    print()
    print("=" * 60)
    passed = sum(
        1 for _, s, _ in TEST_RESULTS if s == "PASS"
    )
    failed = sum(
        1 for _, s, _ in TEST_RESULTS if s == "FAIL"
    )
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    for name, status, msg in TEST_RESULTS:
        line = f"  [{status}] {name}"
        if msg:
            line += f"  -- {msg}"
        print(line)

    if failed:
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
