"""
M6-C — Account Cash + BUY Capacity Preflight tests.

Account Cash tests (unchanged):
- valid sufficient cash + valid capacity → pass
- insufficient cash → BLOCKED
- missing tradableBalanceT1 → BLOCKED
- invalid/malformed balance → BLOCKED
- negative balance → BLOCKED
- bool balance → BLOCKED

BUY Capacity tests (M6-C BUY Capacity gate):
- valid sufficient capacity → order can continue
- capacity smaller than requested quantity → BLOCKED
- data == None → BLOCKED
- missing data → BLOCKED
- isSuccess == false → BLOCKED
- malformed/non-numeric data → BLOCKED
- API/HTTP failure → BLOCKED
- timeout/network failure → BLOCKED

No real orders. All collaborators are fakes/mocks.
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
from models.order import BUY, Order
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
    def __init__(
        self,
        state=VERIFIED_TRADABLE,
        buy_capacity=1_000_000_000,
        capacity_exception=None,
    ):
        self._state = state
        self._buy_capacity = buy_capacity
        self._capacity_exception = capacity_exception
        self.placed_calls = []
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
        if self._capacity_exception is not None:
            raise self._capacity_exception
        return self._buy_capacity


def _prepare(broker, order, instrument, account):
    engine = OrderEngine()
    return engine.prepare(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
    )


# =================================================
# Account Cash checks (M6-C)
# =================================================


def test_valid_sufficient_cash_continues():
    broker = FakeBroker()
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=100, quantity=100)

    result = _prepare(broker, order, instrument, account)

    assert result.success is True
    assert result.sent is False
    assert result.mode == "READY"
    assert broker.placed_calls == []


def test_insufficient_cash_blocks():
    broker = FakeBroker()
    instrument = make_instrument()
    account = make_account(balance=500)
    order = make_order(price=100, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "کافی نیست" in result.message
    assert broker.placed_calls == []


def test_missing_tradable_balance_t1_blocks():
    broker = FakeBroker()
    instrument = make_instrument()
    account = Account(tradable_balance_t1=None)
    order = make_order(price=100, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "موجودی قابل معامله T1 مشخص نیست" in result.message
    assert broker.placed_calls == []


def test_invalid_malformed_balance_blocks():
    broker = FakeBroker()
    instrument = make_instrument()
    account = Account(tradable_balance_t1="invalid")
    order = make_order(price=100, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "معتبر نیست" in result.message
    assert broker.placed_calls == []


def test_negative_balance_blocks():
    broker = FakeBroker()
    instrument = make_instrument()
    account = Account(tradable_balance_t1=-1000)
    order = make_order(price=100, quantity=1)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "منفی است" in result.message
    assert broker.placed_calls == []


def test_bool_balance_blocks():
    """bool must not be accepted as a valid numeric balance."""
    broker = FakeBroker()
    instrument = make_instrument()
    account = Account(tradable_balance_t1=True)
    order = make_order(price=100, quantity=1)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "معتبر نیست" in result.message
    assert broker.placed_calls == []


# =================================================
# BUY Capacity via Agah calculatedquantity
# =================================================


def test_buy_capacity_sufficient_continues():
    """
    Agah returns valid data (45789) >= requested quantity
    (10) -> order can continue (READY).
    """
    broker = FakeBroker(buy_capacity=45789)
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is True
    assert result.sent is False
    assert result.mode == "READY"
    assert broker.placed_calls == []
    assert len(broker.buy_capacity_calls) == 1
    assert broker.buy_capacity_calls[0]["nsc_id"] == (
        order.nsc_id
    )
    assert broker.buy_capacity_calls[0]["side_code"] == (
        order.side
    )
    assert broker.buy_capacity_calls[0]["fund"] == (
        account.tradable_balance_t1
    )
    assert broker.buy_capacity_calls[0]["price"] == (
        order.price
    )


def test_buy_capacity_insufficient_blocks():
    """
    Agah returns data (5) smaller than requested quantity
    (100) -> BLOCKED.
    """
    broker = FakeBroker(buy_capacity=5)
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(price=150, quantity=100)

    result = _prepare(broker, order, instrument, account)

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert "ظرفیت" in result.message
    assert broker.placed_calls == []


def test_buy_capacity_none_data_blocks():
    """
    Agah returns data == None -> BLOCKED.
    """
    broker = FakeBroker(
        capacity_exception=RuntimeError(
            "پاسخ ظرفیت خرید فاقد data است."
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


def test_buy_capacity_missing_data_blocks():
    """
    Agah response missing 'data' key -> BLOCKED.
    """
    broker = FakeBroker(
        capacity_exception=RuntimeError(
            "پاسخ ظرفیت خرید فاقد data است."
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


def test_buy_capacity_isSuccess_false_blocks():
    """
    Agah returns isSuccess == false -> BLOCKED.
    """
    broker = FakeBroker(
        capacity_exception=RuntimeError(
            "درخواست ظرفیت خرید ناموفق بود."
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


def test_buy_capacity_non_numeric_blocks():
    """
    Agah returns non-numeric data -> BLOCKED.
    """
    broker = FakeBroker(
        capacity_exception=RuntimeError(
            "data پاسخ ظرفیت خرید عددی نیست."
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


def test_buy_capacity_api_failure_blocks():
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


def test_buy_capacity_timeout_network_blocks():
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


def test_buy_capacity_connection_error_blocks():
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


def test_sell_order_skips_buy_capacity():
    """
    SELL orders must NOT call get_buy_capacity; the gate
    is BUY-only. (Scope: M6-C BUY Capacity only.)
    """
    from models.order import SELL

    broker = FakeBroker(buy_capacity=0)
    instrument = make_instrument()
    account = make_account(balance=1_000_000)
    order = make_order(side=SELL, price=150, quantity=10)

    result = _prepare(broker, order, instrument, account)

    assert result.success is True
    assert result.mode == "READY"
    assert len(broker.buy_capacity_calls) == 0
    assert broker.placed_calls == []


# =================================================
# Runner
# =================================================


def main():
    tests = [
        # M6-C Account Cash (unchanged)
        test_valid_sufficient_cash_continues,
        test_insufficient_cash_blocks,
        test_missing_tradable_balance_t1_blocks,
        test_invalid_malformed_balance_blocks,
        test_negative_balance_blocks,
        test_bool_balance_blocks,
        # M6-C BUY Capacity (new)
        test_buy_capacity_sufficient_continues,
        test_buy_capacity_insufficient_blocks,
        test_buy_capacity_none_data_blocks,
        test_buy_capacity_missing_data_blocks,
        test_buy_capacity_isSuccess_false_blocks,
        test_buy_capacity_non_numeric_blocks,
        test_buy_capacity_api_failure_blocks,
        test_buy_capacity_timeout_network_blocks,
        test_buy_capacity_connection_error_blocks,
        test_sell_order_skips_buy_capacity,
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
        f"\nM6-C Account Cash + BUY Capacity tests "
        f"passed. ({len(tests)} tests)"
    )


if __name__ == "__main__":
    main()
