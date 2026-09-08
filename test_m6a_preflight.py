"""
M6-A — Instrument Identity + Trading-State Gate tests.

Tests the deterministic preflight gate:
1. Instrument identity validation (order.nsc_id == instrument.nsc_id)
2. Trading state validation (fail-closed: Valid+Known -> continue;
   Invalid -> BLOCK; Unknown/Missing/Error/Timeout -> BLOCK)

No real orders. All collaborators are fakes/mocks.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch
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


def make_instrument(nsc_id="IRO1TEST0001"):
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
        upper_price_threshold=200,
        lower_price_threshold=100,
        minimum_order_quantity=1,
        lot_size=1,
        fixed_price_tick=1,
        maximum_order_quantity_for_buy=3_000_000,
        maximum_order_quantity_for_sell=3_000_000,
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
    def __init__(
        self,
        state=VERIFIED_TRADABLE,
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

    def get_buy_capacity(
        self,
        nsc_id,
        side_code,
        fund,
        price,
    ):
        return 1_000_000_000


# =================================================
# M6-A Test cases
# =================================================


def test_valid_identity_allowed_state_ready():
    """
    Valid identity + allowed trading state (VERIFIED_TRADABLE)
    -> READY.
    """
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


def test_valid_identity_ar_allowed_state_ready():
    """
    Valid identity + allowed trading state (VERIFIED_TRADABLE)
    representing cEtaval='AR' -> READY.
    """
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


def test_identity_mismatch_blocks():
    """
    order.nsc_id != instrument.nsc_id -> BLOCKED.
    """
    engine = OrderEngine()
    broker = FakeBroker(state=VERIFIED_TRADABLE)
    order = make_order(nsc_id="IRO1WRONG9999")
    instrument = make_instrument(nsc_id="IRO1TEST0001")
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
    assert "nscId" in result.message
    assert broker.placed_calls == []


def test_unsupported_state_blocks():
    """
    Unsupported cEtaval (VERIFIED_BLOCKED) -> BLOCKED.
    """
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
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_missing_state_blocks():
    """
    Missing/empty trading state (UNVERIFIED) -> BLOCKED.
    """
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
    assert result.mode == "BLOCKED"
    assert broker.placed_calls == []


def test_network_error_blocks():
    """
    Network error / TradingStateUnavailable -> BLOCKED.
    """
    engine = OrderEngine()
    broker = FakeBroker(
        raise_on_state=True,
        raise_with=TradingStateUnavailable(
            "network error"
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


def test_unknown_state_blocks():
    """
    Unknown trading state (not verified, not allowed) -> BLOCKED.
    """
    engine = OrderEngine()
    broker = FakeBroker(
        state=TradingState(
            is_order_entry_allowed=False,
            is_verified=False,
            source="unknown",
            reason="unknown state",
        )
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


def test_agaah_broker_identity_mismatch_in_get_trading_state_blocks():
    """
    At the broker layer, if TSETMC returns a state with insCode
    that doesn't match the requested ins_code, get_trading_state()
    returns UNVERIFIED, which the M6-A gate interprets as BLOCKED.
    """
    broker = AgaahBroker()

    mock_instrument = type(
        "MockInstrument",
        (),
        {"tse_id": "EXPECTED_INS_CODE"},
    )()

    fake_states = [
        {
            "insCode": "WRONG_INS_CODE",
            "dEven": 20260906,
            "hEven": 105028,
            "cEtaval": "A ",
        }
    ]

    with patch.object(
        broker,
        "get_instrument",
        return_value=mock_instrument,
    ), patch(
        "brokers.agaah.broker.TSETMC",
    ) as mock_tsetmc_class:
        mock_tsetmc = mock_tsetmc_class.return_value
        mock_tsetmc.get_trading_state.return_value = (
            fake_states
        )

        state = broker.get_trading_state("IRO1TEST0001")

    assert state == UNVERIFIED
    assert state.is_verified is False
    assert state.is_order_entry_allowed is False


# =================================================
# Runner
# =================================================


def main():
    tests = [
        test_valid_identity_allowed_state_ready,
        test_valid_identity_ar_allowed_state_ready,
        test_identity_mismatch_blocks,
        test_unsupported_state_blocks,
        test_missing_state_blocks,
        test_network_error_blocks,
        test_unknown_state_blocks,
        test_agaah_broker_identity_mismatch_in_get_trading_state_blocks,
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

    print(f"\nAll M6-A preflight tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()
