"""Offline regression tests for TSETMC ins_code / Agah nsc_id separation.

Verifies that:
  * Order carries both numeric TSETMC ins_code and non-numeric Agah nsc_id.
  * dispatch_core passes order.ins_code (numeric) to execute_by_ins_code,
    not order.nsc_id (non-numeric Agah identifier).
  * A failing instrument lookup blocks the order; no place_order is called.
No network, login, real order, Dry Run, Live, or schedule is exercised.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from brokers.base import InstrumentLookupError
from core.dispatch_core import DispatchCore, BrokerDispatchRequest
from core.order_engine import OrderEngine
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, Order
from models.trading_state import VERIFIED_TRADABLE


class _FakeProvider:
    """Provider that returns a matching BrokerInstrument for a numeric ins_code."""

    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.calls = []

    def get_instrument(self, ins_code):
        self.calls.append(ins_code)
        if self.should_fail:
            raise InstrumentLookupError("no match")
        return (
            Instrument(ins_code=ins_code, symbol="SYM", name="Sym", market="TSE"),
            BrokerInstrument(
                nsc_id="IRO3FSTZ0001",
                tse_id=ins_code,
                name="Sym",
                company_name="Sym Co",
            ),
        )

    def get_nsc_id(self, ins_code):
        return "IRO3FSTZ0001"


class _FakeBroker:
    name = "آگاه"

    def __init__(self):
        self.place_order_calls = []

    def place_order(self, order):
        self.place_order_calls.append(order)
        return {"isSuccess": True}

    def get_trading_state(self, nsc_id):
        return VERIFIED_TRADABLE


def _make_engine():
    return OrderEngine()


def _make_account():
    return Account(account_id="ACC-A")


def _make_dispatch_request(order, broker, account):
    return BrokerDispatchRequest(
        order=order,
        account=account,
        broker_name="آگاه",
        instrument=BrokerInstrument(
            nsc_id="IRO3FSTZ0001",
            tse_id="40467386864240950",
            name="Sym",
            company_name="Sym Co",
        ),
        live=False,
    )


def test_order_carries_both_ins_code_and_nsc_id():
    """Order must hold numeric TSETMC ins_code separately from Agah nsc_id."""
    order = Order(
        nsc_id="IRO3FSTZ0001",
        ins_code="40467386864240950",
        side=BUY,
        price=100,
        quantity=1,
    )
    assert order.nsc_id == "IRO3FSTZ0001"
    assert order.ins_code == "40467386864240950"
    assert order.nsc_id != order.ins_code


def test_execute_receives_numeric_ins_code_not_nsc_id():
    """execute_by_ins_code must receive order.ins_code, not order.nsc_id."""
    engine = _make_engine()
    provider = _FakeProvider()
    broker = _FakeBroker()
    account = _make_account()

    order = Order(
        nsc_id="IRO3FSTZ0001",
        ins_code="40467386864240950",
        side=BUY,
        price=100,
        quantity=1,
    )

    result = engine.execute_by_ins_code(
        broker=broker,
        provider=provider,
        ins_code=order.ins_code,
        order=order,
        account=account,
        live=False,
    )

    # Provider was called with the numeric TSETMC ins_code, not the Agah nscId.
    assert provider.calls == ["40467386864240950"]
    assert provider.calls[0] != "IRO3FSTZ0001"
    assert result.mode == "BLOCKED"


def test_failed_lookup_blocks_order_no_place_order():
    """If instrument lookup fails, place_order must NOT be called."""
    engine = _make_engine()
    provider = _FakeProvider(should_fail=True)
    broker = _FakeBroker()
    account = _make_account()

    order = Order(
        nsc_id="IRO3FSTZ0001",
        ins_code="40467386864240950",
        side=BUY,
        price=100,
        quantity=1,
    )

    result = engine.execute_by_ins_code(
        broker=broker,
        provider=provider,
        ins_code=order.ins_code,
        order=order,
        account=account,
        live=False,
    )

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    # provider was attempted with the numeric ins_code (not the nscId).
    assert provider.calls == ["40467386864240950"]
    # No place_order was invoked.
    assert broker.place_order_calls == []


def test_dispatch_core_passes_order_ins_code():
    """DispatchCore._execute_single_order passes order.ins_code as ins_code."""
    core = DispatchCore()
    engine = _make_engine()
    provider = _FakeProvider()
    broker = _FakeBroker()
    account = _make_account()

    order = Order(
        nsc_id="IRO3FSTZ0001",
        ins_code="40467386864240950",
        side=BUY,
        price=100,
        quantity=1,
    )
    request = _make_dispatch_request(order, broker, account)

    # Monkey-patch engine.execute_by_ins_code to record what ins_code it receives.
    captured = {}

    def fake_execute(broker, provider, ins_code, order, account, live):
        captured["ins_code"] = ins_code
        captured["order_nsc_id"] = order.nsc_id
        return SimpleNamespace(success=True, sent=True, mode="LIVE")

    engine.execute_by_ins_code = fake_execute
    core.order_engine = engine  # type: ignore[assignment]

    result = core._execute_single_order(
        broker=broker,
        provider=provider,
        dispatch_request=request,
    )

    # ins_code passed to engine is the numeric TSETMC ins_code, not nscId.
    assert captured["ins_code"] == "40467386864240950"
    assert captured["ins_code"] != "IRO3FSTZ0001"
    assert captured["order_nsc_id"] == "IRO3FSTZ0001"
