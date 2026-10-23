"""Offline timeout coverage for the HTTP submission boundary; no socket used."""

from types import SimpleNamespace

import requests

from core.order_engine import OrderEngine
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order
from models.trading_state import TradingState


class FakeProvider:
    def get_instrument(self, _):
        return SimpleNamespace(), BrokerInstrument(
            name="sim", company_name="sim", nsc_id="N1", tse_id="T1",
            last_trade_price=100, final_price=100, previous_day_price=100,
            upper_price_threshold=200, lower_price_threshold=1,
            minimum_order_quantity=1, lot_size=1, fixed_price_tick=1,
            maximum_order_quantity_for_buy=100, maximum_order_quantity_for_sell=100,
        )


class FakeBroker:
    name = "sim"
    live_trading_enabled = False

    def get_trading_state(self, _):
        return TradingState(
            is_order_entry_allowed=True, is_verified=True,
            source="mock", reason="mock",
        )

    def get_buy_capacity(self, **_):
        return 100

    def place_order(self, order, live=False):
        # Simulate the one network attempt at the broker adapter boundary.
        self.calls += 1
        raise requests.Timeout("mock timeout")

    calls = 0


def test_submission_timeout_is_recorded_once_and_never_retried():
    broker = FakeBroker()
    result = OrderEngine().execute_by_ins_code(
        broker=broker, provider=FakeProvider(), ins_code="T1",
        order=Order("N1", BUY, 100, 1),
        account=Account(account_id="A", tradable_balance_t1=1000),
        live=False,
    )
    assert result.mode == "ERROR"
    assert result.sent is False
    assert broker.calls == 1
