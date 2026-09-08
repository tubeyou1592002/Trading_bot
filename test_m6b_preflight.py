"""
M6-B — Instrument Price / Quantity Preflight Constraints tests.

Tests the deterministic price/quantity gate added in M6-B:
- price > 0
- lowerPriceThreshold <= price <= upperPriceThreshold
- price compatible with fixedPriceTick
- quantity > 0
- quantity >= minimumOrderQuantity
- quantity is multiple of lotSize
- quantity <= maximumOrderQuantityForBuy (BUY)
- quantity <= maximumOrderQuantityForSell (SELL)
- missing/invalid/unknown → BLOCKED

No real orders. All collaborators are fakes/mocks.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from brokers.base import Broker
from core.order_engine import OrderEngine
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, SELL, Order
from models.trading_state import VERIFIED_TRADABLE


def make_instrument(
    nsc_id="IRO1TEST0001",
    lower=100,
    upper=200,
    tick=1,
    min_qty=1,
    max_buy=3_000_000,
    max_sell=3_000_000,
    lot=1,
):
    return BrokerInstrument(
        name="TEST",
        nsc_id=nsc_id,
        tse_id="60235881999727383",
        market_title="بورس",
        state_code="A",
        group_state_code="B",
        last_trade_price=150,
        final_price=150,
        previous_day_price=150,
        upper_price_threshold=upper,
        lower_price_threshold=lower,
        minimum_order_quantity=min_qty,
        lot_size=lot,
        fixed_price_tick=tick,
        maximum_order_quantity_for_buy=max_buy,
        maximum_order_quantity_for_sell=max_sell,
        bid_ask_list=[],
        is_fund=False,
    )


def make_account(balance=10_000_000):
    return Account(tradable_balance_t1=balance)


def make_order(nsc_id="IRO1TEST0001", side=BUY, price=150, quantity=10):
    return Order(
        nsc_id=nsc_id,
        side=side,
        price=price,
        quantity=quantity,
        bank_account_id=0,
    )


class FakeBroker(Broker):
    def __init__(self, state=VERIFIED_TRADABLE):
        self._state = state
        self.placed_calls = []
        self.live_trading_enabled = False

    @property
    def name(self):
        return "FakeBroker"

    def login(self, username, password, **kwargs):
        return {"userName": username}

    def get_account(self):
        return Account(tradable_balance_t1=10_000_000)

    def get_trading_state(self, nsc_id):
        return self._state

    def place_order(self, order, live=False):
        self.placed_calls.append(
            {"order": order, "live": live}
        )
        return {
            "mode": "DRY_RUN" if not live else "LIVE",
            "sent": live,
            "payload": order.to_payload(),
        }

    def cancel_order(self, order_id):
        raise NotImplementedError

    def get_buy_capacity(
        self,
        nsc_id,
        side_code,
        fund,
        price,
    ):
        return 1_000_000_000


def _prepare(broker, order, instrument, account):
    engine = OrderEngine()
    return engine.prepare(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
    )


# =================================================
# Price checks
# =================================================


def test_price_below_lower_threshold_blocks():
    broker = FakeBroker()
    instrument = make_instrument(lower=100, upper=200, tick=1)
    order = make_order(price=50, quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "حداقل" in result.message or "پایین" in result.message
    assert broker.placed_calls == []


def test_price_above_upper_threshold_blocks():
    broker = FakeBroker()
    instrument = make_instrument(lower=100, upper=200, tick=1)
    order = make_order(price=250, quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "حداکثر" in result.message or "بالا" in result.message
    assert broker.placed_calls == []


def test_valid_price_continues():
    broker = FakeBroker()
    instrument = make_instrument(lower=100, upper=200, tick=1)
    order = make_order(price=150, quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is True
    assert result.sent is False
    assert result.mode == "READY"
    assert broker.placed_calls == []


def test_invalid_tick_blocks():
    broker = FakeBroker()
    instrument = make_instrument(lower=100, upper=200, tick=10)
    order = make_order(price=155, quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "Tick" in result.message
    assert broker.placed_calls == []


# =================================================
# Quantity checks
# =================================================


def test_zero_quantity_blocks():
    broker = FakeBroker()
    instrument = make_instrument()
    order = make_order(quantity=0)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_negative_quantity_blocks():
    broker = FakeBroker()
    instrument = make_instrument()
    order = make_order(quantity=-10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_below_minimum_quantity_blocks():
    broker = FakeBroker()
    instrument = make_instrument(min_qty=100)
    order = make_order(quantity=50)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "حداقل حجم" in result.message
    assert broker.placed_calls == []


def test_invalid_lot_size_blocks():
    broker = FakeBroker()
    instrument = make_instrument(lot=10)
    order = make_order(quantity=15)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "مضرب" in result.message
    assert broker.placed_calls == []


def test_buy_above_max_buy_blocks():
    broker = FakeBroker()
    instrument = make_instrument(max_buy=100)
    order = make_order(side=BUY, quantity=150)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "حداکثر حجم" in result.message
    assert broker.placed_calls == []


def test_sell_above_max_sell_blocks():
    broker = FakeBroker()
    instrument = make_instrument(max_sell=100)
    order = make_order(side=SELL, quantity=150)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "حداکثر حجم" in result.message
    assert broker.placed_calls == []


def test_valid_buy_quantity_continues():
    broker = FakeBroker()
    instrument = make_instrument(
        min_qty=1, max_buy=1000, lot=1
    )
    order = make_order(side=BUY, quantity=100)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is True
    assert result.sent is False
    assert result.mode == "READY"
    assert broker.placed_calls == []


def test_valid_sell_quantity_continues():
    broker = FakeBroker()
    instrument = make_instrument(
        min_qty=1, max_sell=1000, lot=1
    )
    order = make_order(side=SELL, quantity=100)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is True
    assert result.sent is False
    assert result.mode == "READY"
    assert broker.placed_calls == []


def test_missing_price_blocks():
    """Order with price=0 (missing/invalid price value) → BLOCKED."""
    broker = FakeBroker()
    instrument = make_instrument()
    order = make_order(price=0, quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_missing_quantity_blocks():
    """Order with quantity=0 (missing/invalid quantity value) → BLOCKED."""
    broker = FakeBroker()
    instrument = make_instrument()
    order = make_order(quantity=0)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_missing_lower_threshold_blocks():
    """missing lower_price_threshold → BLOCKED."""
    broker = FakeBroker()
    instrument = make_instrument(lower=None, upper=200, tick=1)
    order = make_order(price=150, quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "حد پایین" in result.message
    assert broker.placed_calls == []


def test_missing_upper_threshold_blocks():
    """missing upper_price_threshold → BLOCKED."""
    broker = FakeBroker()
    instrument = make_instrument(lower=100, upper=None, tick=1)
    order = make_order(price=150, quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "حد بالای" in result.message
    assert broker.placed_calls == []


def test_missing_tick_blocks():
    """missing fixed_price_tick → BLOCKED."""
    broker = FakeBroker()
    instrument = make_instrument(lower=100, upper=200, tick=None)
    order = make_order(price=150, quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "Tick" in result.message
    assert broker.placed_calls == []


def test_missing_minimum_quantity_blocks():
    """missing minimum_order_quantity → BLOCKED."""
    broker = FakeBroker()
    instrument = make_instrument(min_qty=None)
    order = make_order(quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "حداقل حجم" in result.message
    assert broker.placed_calls == []


def test_missing_lot_size_blocks():
    """missing lot_size → BLOCKED."""
    broker = FakeBroker()
    instrument = make_instrument(lot=None)
    order = make_order(quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "lot size" in result.message
    assert broker.placed_calls == []


def test_missing_max_buy_blocks():
    """missing maximum_order_quantity_for_buy → BLOCKED."""
    broker = FakeBroker()
    instrument = make_instrument(max_buy=None)
    order = make_order(side=BUY, quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "حداکثر حجم" in result.message
    assert broker.placed_calls == []


def test_missing_max_sell_blocks():
    """missing maximum_order_quantity_for_sell → BLOCKED."""
    broker = FakeBroker()
    instrument = make_instrument(max_sell=None)
    order = make_order(side=SELL, quantity=10)
    account = make_account()

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "حداکثر حجم" in result.message
    assert broker.placed_calls == []


# =================================================
# Runner
# =================================================


def main():
    tests = [
        test_price_below_lower_threshold_blocks,
        test_price_above_upper_threshold_blocks,
        test_valid_price_continues,
        test_invalid_tick_blocks,
        test_zero_quantity_blocks,
        test_negative_quantity_blocks,
        test_below_minimum_quantity_blocks,
        test_invalid_lot_size_blocks,
        test_buy_above_max_buy_blocks,
        test_sell_above_max_sell_blocks,
        test_valid_buy_quantity_continues,
        test_valid_sell_quantity_continues,
        test_missing_price_blocks,
        test_missing_quantity_blocks,
        test_missing_lower_threshold_blocks,
        test_missing_upper_threshold_blocks,
        test_missing_tick_blocks,
        test_missing_minimum_quantity_blocks,
        test_missing_lot_size_blocks,
        test_missing_max_buy_blocks,
        test_missing_max_sell_blocks,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print("  PASS  " + test.__name__)
        except AssertionError as exc:
            failed += 1
            print(
                "  FAIL  "
                + test.__name__
                + ": "
                + str(exc)
            )
        except Exception:
            failed += 1
            import traceback
            traceback.print_exc()

    print()
    print("=" * 50)
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    print("=" * 50)

    if failed:
        sys.exit(1)

    print(
        f"\nAll M6-B preflight tests passed. "
        f"({len(tests)} tests)"
    )


if __name__ == "__main__":
    main()
