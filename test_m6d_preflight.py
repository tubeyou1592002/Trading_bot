"""
M6-D — Portfolio Quantity / SELL Gate tests.

M6-D contract (Architect-approved):
- Endpoint: GET /api/v1/portfolio
- Quantity field: portfolio.numberOfShares
- SELL rule: requested quantity <= numberOfShares -> allowed
- missing/invalid/portfolio API failure -> BLOCKED (fail-closed)
- BUY orders must NOT call get_sell_capacity; BUY gate must
  not be affected by SELL gate.

Scope: SELL capacity gate only.
Out-of-scope: Unified BUY/SELL Preflight, Order Splitting.
"""

import sys
import os

from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    Timeout as RequestsTimeout,
)

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


def make_order(
    nsc_id="IRO1TEST0001",
    side=SELL,
    price=150,
    quantity=10,
):
    return Order(
        nsc_id=nsc_id,
        side=side,
        price=price,
        quantity=quantity,
        bank_account_id=0,
    )


class FakeBroker(Broker):
    def __init__(
        self,
        state=VERIFIED_TRADABLE,
        sell_capacity=1_000_000_000,
        capacity_exception=None,
    ):
        self._state = state
        self._sell_capacity = sell_capacity
        self._capacity_exception = capacity_exception
        self.placed_calls = []
        self.sell_capacity_calls = []
        self.buy_capacity_calls = []
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
        self.buy_capacity_calls.append(
            {
                "nsc_id": nsc_id,
                "side_code": side_code,
                "fund": fund,
                "price": price,
            }
        )
        return 1_000_000_000

    def get_sell_capacity(
        self,
        nsc_id,
        side_code,
        fund,
        price,
    ):
        self.sell_capacity_calls.append(
            {
                "nsc_id": nsc_id,
                "side_code": side_code,
                "fund": fund,
                "price": price,
            }
        )
        if self._capacity_exception is not None:
            raise self._capacity_exception
        return self._sell_capacity


def _prepare(broker, order, instrument, account):
    engine = OrderEngine()
    return engine.prepare(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
    )


# =================================================
# SELL Capacity tests (M6-D)
# =================================================


def test_sell_capacity_sufficient_continues():
    """
    portfolio.numberOfShares (45789) >= requested quantity
    (10) -> order can continue (READY).
    """
    broker = FakeBroker(sell_capacity=45789)
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is True
    assert result.sent is False
    assert result.mode == "READY"
    assert broker.placed_calls == []
    assert len(broker.sell_capacity_calls) == 1
    assert broker.sell_capacity_calls[0]["nsc_id"] == (
        order.nsc_id
    )
    assert broker.sell_capacity_calls[0]["side_code"] == (
        order.side
    )
    assert broker.sell_capacity_calls[0]["price"] == (
        order.price
    )


def test_sell_capacity_exact_quantity_continues():
    """
    portfolio.numberOfShares == requested quantity
    -> order can continue (READY).
    """
    broker = FakeBroker(sell_capacity=10)
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is True
    assert result.mode == "READY"
    assert broker.placed_calls == []
    assert len(broker.sell_capacity_calls) == 1


def test_sell_capacity_insufficient_blocks():
    """
    portfolio.numberOfShares (5) < requested quantity
    (100) -> BLOCKED.
    """
    broker = FakeBroker(sell_capacity=5)
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=100)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "ظرفیت فروش" in result.message
    assert broker.placed_calls == []


def test_sell_capacity_zero_quantity_blocks():
    """
    order.quantity == 0 -> BLOCKED by existing
    OrderValidator (zero quantity check).
    """
    broker = FakeBroker(sell_capacity=45789)
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=0)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.sell_capacity_calls == []


def test_sell_capacity_api_failure_blocks():
    """
    HTTP/API error -> BLOCKED.
    """
    broker = FakeBroker(
        capacity_exception=RuntimeError(
            "HTTP 500: Internal Server Error"
        )
    )
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_sell_capacity_none_data_blocks():
    """
    portfolio.numberOfShares is None (missing in
    response) -> BLOCKED.
    """
    broker = FakeBroker(
        capacity_exception=RuntimeError(
            "portfolio فاقد numberOfShares است."
        )
    )
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_sell_capacity_missing_portfolio_blocks():
    """
    portfolio itself is None/missing -> BLOCKED.
    """
    broker = FakeBroker(
        capacity_exception=RuntimeError(
            "پاسخ ظرفیت فروش فاقد portfolio است."
        )
    )
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_sell_capacity_non_numeric_blocks():
    """
    portfolio.numberOfShares is non-numeric -> BLOCKED.
    """
    broker = FakeBroker(
        capacity_exception=RuntimeError(
            "numberOfShares پاسخ ظرفیت فروش "
            "عددی نیست."
        )
    )
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_sell_capacity_timeout_blocks():
    """
    Timeout / network error -> BLOCKED.
    """
    broker = FakeBroker(
        capacity_exception=RequestsTimeout(
            "connection timed out"
        )
    )
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_sell_capacity_connection_error_blocks():
    """
    Network connection error -> BLOCKED.
    """
    broker = FakeBroker(
        capacity_exception=RequestsConnectionError(
            "network unreachable"
        )
    )
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_sell_capacity_negative_blocks():
    """
    portfolio.numberOfShares is negative -> BLOCKED.
    """
    broker = FakeBroker(
        capacity_exception=RuntimeError(
            "ظرفیت فروش منفی است."
        )
    )
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_buy_skips_sell_capacity():
    """
    BUY orders must NOT call get_sell_capacity.
    BUY gate (get_buy_capacity) is unaffected by SELL gate.
    """
    broker = FakeBroker(sell_capacity=0)
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(
        side=BUY, price=150, quantity=10
    )

    result = _prepare(broker, order, instrument, account)

    assert result.success is True
    assert result.mode == "READY"
    assert len(broker.sell_capacity_calls) == 0
    assert len(broker.buy_capacity_calls) == 1
    assert broker.placed_calls == []


def test_sell_does_not_break_buy_gate():
    """
    SELL gate must not break BUY path: a BUY order
    with valid cash+capacity -> READY, even when
    sell_capacity is 0.
    """
    broker = FakeBroker(sell_capacity=0)
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(
        side=BUY, price=150, quantity=10
    )

    result = _prepare(broker, order, instrument, account)

    assert result.mode == "READY"
    assert result.success is True
    assert broker.sell_capacity_calls == []


def test_sell_capacity_is_called_with_correct_args():
    """
    Verify get_sell_capacity receives correct args:
    nsc_id = order.nsc_id, side_code = SELL (2),
    price = order.price. fund is not relevant for
    SELL but is passed as None per signature.
    """
    broker = FakeBroker(sell_capacity=1000)
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=10)

    _prepare(broker, order, instrument, account)

    assert len(broker.sell_capacity_calls) == 1
    call = broker.sell_capacity_calls[0]
    assert call["nsc_id"] == order.nsc_id
    assert call["side_code"] == SELL
    assert call["price"] == order.price


def test_sell_quantity_above_max_sell_blocks():
    """
    The existing M6-B maximum_order_quantity_for_sell
    check must still fire BEFORE the SELL capacity gate.
    If quantity > max_sell, BLOCKED with the
    OrderValidator message (not the SELL capacity
    message).
    """
    broker = FakeBroker(sell_capacity=1_000_000)
    instrument = make_instrument(max_sell=100)
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=150)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.mode == "BLOCKED"
    assert "حداکثر حجم" in result.message
    assert len(broker.sell_capacity_calls) == 0


# =================================================
# Runner
# =================================================


def main():
    tests = [
        test_sell_capacity_sufficient_continues,
        test_sell_capacity_exact_quantity_continues,
        test_sell_capacity_insufficient_blocks,
        test_sell_capacity_zero_quantity_blocks,
        test_sell_capacity_api_failure_blocks,
        test_sell_capacity_none_data_blocks,
        test_sell_capacity_missing_portfolio_blocks,
        test_sell_capacity_non_numeric_blocks,
        test_sell_capacity_timeout_blocks,
        test_sell_capacity_connection_error_blocks,
        test_sell_capacity_negative_blocks,
        test_buy_skips_sell_capacity,
        test_sell_does_not_break_buy_gate,
        test_sell_capacity_is_called_with_correct_args,
        test_sell_quantity_above_max_sell_blocks,
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
        f"\nAll M6-D preflight tests passed. "
        f"({len(tests)} tests)"
    )


if __name__ == "__main__":
    main()
