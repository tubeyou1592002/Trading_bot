"""
Unit tests for the broker/order-engine interface stabilization.

این تست‌ها کاملاً آفلاین هستند:
- بدون شبکه
- بدون ورودی تعاملی
- بدون credentials واقعی
- بدون ارسال سفارش واقعی

اجرا:
    python test_engine_interface.py
"""

import sys
import traceback

from brokers.agaah import AgaahBroker
from brokers.base import Broker
from core.order_engine import OrderEngine
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order
from models.trading_state import (
    UNVERIFIED,
    VERIFIED_BLOCKED,
    VERIFIED_TRADABLE,
    TradingState,
    TradingStateUnavailable,
)


PASSED = 0
FAILED = 0


def make_instrument(
    nsc_id="IRO1TEST0001",
    min_qty=1,
    max_buy=3_000_000,
    max_sell=3_000_000,
    lower=100,
    upper=200,
    tick=1,
):
    return BrokerInstrument(
        name="TEST",
        company_name="Test Co",
        nsc_id=nsc_id,
        tse_id="0",
        market_title="بورس",
        state_code="A",
        group_state_code="B",
        last_trade_price=150,
        final_price=150,
        previous_day_price=150,
        upper_price_threshold=upper,
        lower_price_threshold=lower,
        minimum_order_quantity=min_qty,
        lot_size=1,
        fixed_price_tick=tick,
        maximum_order_quantity_for_buy=max_buy,
        maximum_order_quantity_for_sell=max_sell,
        bid_ask_list=[],
        is_fund=False,
    )


def make_account(balance=10_000_000):
    return Account(tradable_balance_t1=balance)


def make_order(nsc_id="IRO1TEST0001", price=150, quantity=10):
    return Order(
        nsc_id=nsc_id,
        side=BUY,
        price=price,
        quantity=quantity,
        bank_account_id=0,
    )


class FakeBroker(Broker):
    """
    یک broker ساختگی برای تست‌های واحد.
    """

    def __init__(
        self,
        state=UNVERIFIED,
        raise_on_state=False,
        raise_with=None,
    ):
        self._state = state
        self._raise_on_state = raise_on_state
        self._raise_with = raise_with
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
        if self._raise_on_state:
            exc = self._raise_with or RuntimeError(
                "state source failed"
            )
            raise exc
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


# --------------------------------------------------------------------
# Test cases
# --------------------------------------------------------------------


def test_abstract_broker_defines_interface():
    """ABC باید متدهای مورد انتظار را تعریف کند."""

    expected = {
        "name",
        "login",
        "get_account",
        "place_order",
        "cancel_order",
        "get_trading_state",
    }
    for attr in expected:
        assert hasattr(Broker, attr), (
            f"Broker باید {attr} داشته باشد."
        )


def test_agaah_broker_is_broker():
    """AgaahBroker باید زیرکلاس Broker باشد."""

    assert issubclass(AgaahBroker, Broker)


def test_agaah_live_trading_disabled_by_default():
    """live_trading_enabled باید به‌صورت پیش‌فرض False باشد."""

    broker = AgaahBroker()
    assert broker.live_trading_enabled is False


def test_agaah_get_trading_state_returns_unverified():
    """تا زمان تأیید منبع، وضعیت باید UNVERIFIED باشد."""

    broker = AgaahBroker()
    state = broker.get_trading_state("IRO1TEST0001")
    assert isinstance(state, TradingState)
    assert state.is_verified is False
    assert state.is_order_entry_allowed is False


def test_agaah_get_trading_state_requires_nsc_id():
    """nsc_id خالی نباید پذیرفته شود."""

    broker = AgaahBroker()
    try:
        broker.get_trading_state("")
    except ValueError:
        return
    raise AssertionError(
        "broker.get_trading_state('') باید ValueError بدهد."
    )


def test_engine_blocks_unverified_state():
    """وقتی وضعیت معاملاتی تأیید نشده، سفارش بلاک می‌شود."""

    engine = OrderEngine()
    broker = FakeBroker(state=UNVERIFIED)
    order = make_order()
    instrument = make_instrument()
    account = make_account()

    result = engine.prepare(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
    )

    assert result.success is False
    assert result.sent is False
    assert result.mode == "UNVERIFIED"
    assert broker.placed_calls == []


def test_engine_blocks_verified_blocked_state():
    """وقتی وضعیت verified-blocked است، سفارش بلاک می‌شود."""

    engine = OrderEngine()
    broker = FakeBroker(state=VERIFIED_BLOCKED)
    order = make_order()
    instrument = make_instrument()
    account = make_account()

    result = engine.prepare(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
    )

    assert result.success is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_engine_blocks_on_trading_state_unavailable():
    """
    وقتی broker صریحاً اعلام می‌کند منبع در دسترس
    نیست، موتور باید به‌صورت ایمن بلاک کند.
    """

    engine = OrderEngine()
    broker = FakeBroker(
        raise_on_state=True,
        raise_with=TradingStateUnavailable(
            "remote offline"
        ),
    )
    order = make_order()
    instrument = make_instrument()
    account = make_account()

    result = engine.prepare(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
    )

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_engine_does_not_swallow_programming_errors():
    """
    خطاهای برنامه‌نویسی (RuntimeError، TypeError،
    AttributeError) نباید توسط موتور خورده شوند؛
    این خطاها نشان‌دهنده باگ هستند.
    """

    engine = OrderEngine()
    order = make_order()
    instrument = make_instrument()
    account = make_account()

    for exc in (
        RuntimeError("boom"),
        TypeError("bad arg"),
        AttributeError("missing"),
    ):
        broker = FakeBroker(
            raise_on_state=True,
            raise_with=exc,
        )
        try:
            engine.prepare(
                broker=broker,
                order=order,
                instrument=instrument,
                account=account,
            )
        except type(exc) as raised:
            assert raised is exc
        else:
            raise AssertionError(
                f"خطای {type(exc).__name__} باید "
                "منتشر شود، نه بلاک."
            )


def test_engine_rejects_non_trading_state():
    """اگر broker چیزی غیر از TradingState برگرداند، موتور بلاک کند."""

    engine = OrderEngine()
    broker = FakeBroker()
    broker._state = {"is_order_entry_allowed": True}
    order = make_order()
    instrument = make_instrument()
    account = make_account()

    result = engine.prepare(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
    )

    assert result.success is False
    assert result.mode == "BLOCKED"


def test_engine_validates_invalid_order_even_when_tradable():
    """اگر نماد tradable باشد ولی سفارش نامعتبر باشد، INVALID برگردد."""

    engine = OrderEngine()
    broker = FakeBroker(state=VERIFIED_TRADABLE)
    order = make_order(price=10)
    instrument = make_instrument(lower=100, upper=200)
    account = make_account()

    result = engine.prepare(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
    )

    assert result.success is False
    assert result.mode == "INVALID"
    assert broker.placed_calls == []


def test_engine_prepare_returns_ready_for_valid_order():
    """سفارش معتبر در حالت tradable باید READY شود."""

    engine = OrderEngine()
    broker = FakeBroker(state=VERIFIED_TRADABLE)
    order = make_order()
    instrument = make_instrument()
    account = make_account()

    result = engine.prepare(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
    )

    assert result.success is True
    assert result.sent is False
    assert result.mode == "READY"
    assert broker.placed_calls == []


def test_engine_execute_dry_run_does_not_send():
    """execute(live=False) نباید هیچ درخواست واقعی بفرستد."""

    engine = OrderEngine()
    broker = FakeBroker(state=VERIFIED_TRADABLE)
    order = make_order()
    instrument = make_instrument()
    account = make_account()

    result = engine.execute(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
        live=False,
    )

    assert result.success is True
    assert result.sent is False
    assert result.mode == "DRY_RUN"
    assert len(broker.placed_calls) == 1
    assert broker.placed_calls[0]["live"] is False


def test_engine_blocks_live_when_broker_disabled():
    """حتی اگر broker قفل داخلی داشته باشد، موتور نیز بلاک کند."""

    engine = OrderEngine()
    broker = FakeBroker(state=VERIFIED_TRADABLE)
    broker.live_trading_enabled = False
    order = make_order()
    instrument = make_instrument()
    account = make_account()

    result = engine.execute(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
        live=True,
    )

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_engine_live_path_uses_broker_place_order():
    """اگر live_trading_enabled=True باشد، موتور broker را صدا بزند."""

    engine = OrderEngine()
    broker = FakeBroker(state=VERIFIED_TRADABLE)
    broker.live_trading_enabled = True
    order = make_order()
    instrument = make_instrument()
    account = make_account()

    result = engine.execute(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
        live=True,
    )

    assert result.success is True
    assert result.sent is True
    assert result.mode == "LIVE"
    assert len(broker.placed_calls) == 1
    assert broker.placed_calls[0]["live"] is True


def test_engine_execute_does_not_call_broker_when_blocked():
    """اگر prepare بلاک شود، broker.place_order فراخوانی نشود."""

    engine = OrderEngine()
    broker = FakeBroker(state=UNVERIFIED)
    order = make_order()
    instrument = make_instrument()
    account = make_account()

    result = engine.execute(
        broker=broker,
        order=order,
        instrument=instrument,
        account=account,
        live=False,
    )

    assert result.success is False
    assert result.mode == "UNVERIFIED"
    assert broker.placed_calls == []


def test_broker_place_order_signature_accepts_live_kwarg():
    """Broker.place_order باید live=False را بپذیرد."""

    broker = FakeBroker(state=VERIFIED_TRADABLE)
    order = make_order()
    out = broker.place_order(order, live=False)
    assert out["sent"] is False


# --------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------


def main():
    global PASSED, FAILED
    tests = [
        test_abstract_broker_defines_interface,
        test_agaah_broker_is_broker,
        test_agaah_live_trading_disabled_by_default,
        test_agaah_get_trading_state_returns_unverified,
        test_agaah_get_trading_state_requires_nsc_id,
        test_engine_blocks_unverified_state,
        test_engine_blocks_verified_blocked_state,
        test_engine_blocks_on_trading_state_unavailable,
        test_engine_does_not_swallow_programming_errors,
        test_engine_rejects_non_trading_state,
        test_engine_validates_invalid_order_even_when_tradable,
        test_engine_prepare_returns_ready_for_valid_order,
        test_engine_execute_dry_run_does_not_send,
        test_engine_blocks_live_when_broker_disabled,
        test_engine_live_path_uses_broker_place_order,
        test_engine_execute_does_not_call_broker_when_blocked,
        test_broker_place_order_signature_accepts_live_kwarg,
    ]

    for test in tests:
        try:
            test()
            PASSED += 1
            print(f"  PASS  {test.__name__}")
        except AssertionError as exc:
            FAILED += 1
            print(f"  FAIL  {test.__name__}: {exc}")
        except Exception:
            FAILED += 1
            print(f"  ERROR {test.__name__}")
            traceback.print_exc()

    print()
    print("=" * 50)
    print(f"PASSED: {PASSED}")
    print(f"FAILED: {FAILED}")
    print("=" * 50)

    if FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
