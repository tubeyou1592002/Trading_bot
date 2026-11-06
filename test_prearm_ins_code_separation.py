"""Offline regression tests for LivePrearmService ins_code / Agah nsc_id separation.

Verifies:
  * prepare() passes order.ins_code (numeric TSETMC), NOT order.nsc_id (Agah), to
    the engine request payload.
  * prepare() fails closed when ins_code is empty/missing — never falls back
    to nscId, and no submission/lookup happens.
No network, login, real order, Dry Run, Live, or schedule is exercised.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ui.prearm_service import LivePrearmService
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order


class _FakeProvider:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.calls = []

    def get_instrument(self, ins_code):
        self.calls.append(ins_code)
        if self.should_fail:
            raise RuntimeError("no match")
        return (
            SimpleNamespace(symbol="SYM", name="Sym"),
            BrokerInstrument(
                nsc_id="IRO3FSTZ0001",
                tse_id=ins_code,
                name="Sym",
                company_name="Sym Co",
                minimum_order_quantity=1,
                lot_size=1,
                fixed_price_tick=1,
                lower_price_threshold=1,
                upper_price_threshold=1000,
                maximum_order_quantity_for_buy=1000,
                maximum_order_quantity_for_sell=1000,
            ),
        )

    def get_nsc_id(self, ins_code):
        return "IRO3FSTZ0001"


class _FakeBroker:
    name = "آگاه"

    def __init__(self, account_id):
        self.account_id = account_id
        self.place_order_calls = []

    def place_order(self, order):
        self.place_order_calls.append(order)
        return {"isSuccess": True}

    def build_order_payload(self, order):
        return {"nscId": order.nsc_id}

    def get_account(self):
        return SimpleNamespace(account_id=self.account_id)

    def get_trading_state(self, _):
        from models.trading_state import TradingState
        return TradingState(True, True, "SIM", "ok")

    def get_buy_capacity(self, **_):
        return 100000


class _FakeBrokerManager:
    def __init__(self):
        self.brokers = {}
        self.providers = {}

    def register(self, account_id, broker_name, broker, provider):
        self.brokers[(account_id, broker_name)] = broker
        self.providers[(account_id, broker_name)] = provider

    def get_for_account(self, account_id, broker_name):
        return self.brokers[(account_id, broker_name)]

    def get_instrument_provider_for_account(self, account_id, broker_name):
        return self.providers[(account_id, broker_name)]


class _FakeSessionManager:
    def __init__(self):
        self.sessions = {}

    def register(self, account_id, session):
        self.sessions[account_id] = session

    def get(self, account_id):
        return self.sessions.get(account_id)


class _FakeTarget:
    def __init__(self, entry, account, account_id, broker_name):
        self.entry = entry
        self.account = account
        self.account_id = account_id
        self.broker_name = broker_name


def _make_provider(should_fail=False):
    return _FakeProvider(should_fail=should_fail)


def _make_broker(account_id):
    return _FakeBroker(account_id=account_id)


def _make_order(ins_code, nsc_id="IRO3FSTZ0001", side=BUY, price=100, quantity=1):
    return Order(
        nsc_id=nsc_id,
        ins_code=ins_code,
        side=side,
        price=price,
        quantity=quantity,
    )


def test_prearm_passes_numeric_ins_code_not_nsc_id():
    """prepare() must pass order.ins_code (numeric), not order.nsc_id (Agah)."""
    manager = _FakeBrokerManager()
    session_manager = _FakeSessionManager()
    provider = _make_provider()
    broker = _make_broker("ACC-A")
    manager.register("ACC-A", "آگاه", broker, provider)

    service = LivePrearmService(
        account_store=SimpleNamespace(),
        session_manager=session_manager,
        broker_manager=manager,
    )

    account = SimpleNamespace(account_id="ACC-A")
    order = _make_order(ins_code="40467386864240950", nsc_id="IRO3FSTZ0001")
    target = _FakeTarget(entry=SimpleNamespace(order=order), account=account,
                         account_id="ACC-A", broker_name="آگاه")

    execution_id, batch = service.prepare([target])

    # Provider must be invoked with numeric ins_code, not Agah nscId.
    assert provider.calls == ["40467386864240950"]
    assert provider.calls[0] != "IRO3FSTZ0001"
    # No place_order invoked — prepare only builds the batch.
    assert broker.place_order_calls == []


def test_prearm_fails_closed_when_ins_code_empty():
    """Missing ins_code must block prearm; never fall back to nscId."""
    manager = _FakeBrokerManager()
    session_manager = _FakeSessionManager()
    provider = _make_provider()
    broker = _make_broker("ACC-A")
    manager.register("ACC-A", "آگاه", broker, provider)

    service = LivePrearmService(
        account_store=SimpleNamespace(),
        session_manager=session_manager,
        broker_manager=manager,
    )

    account = SimpleNamespace(account_id="ACC-A")
    # Order with empty ins_code but valid Agah nscId — must not fall back.
    order = _make_order(ins_code="", nsc_id="IRO3FSTZ0001")
    target = _FakeTarget(entry=SimpleNamespace(order=order), account=account,
                         account_id="ACC-A", broker_name="آگاه")

    execution_id, batch = service.prepare([target])

    # Provider never invoked (fail-closed before lookup).
    assert provider.calls == []
    # Batch should be blocked / empty due to missing ins_code.
    assert batch.valid is False or len(batch.orders) == 0


def test_prearm_prepares_with_fresh_valid_t1_balance():
    """prepare() succeeds when account has fresh valid tradable_balance_t1."""
    manager = _FakeBrokerManager()
    session_manager = _FakeSessionManager()
    provider = _make_provider()
    broker = _make_broker("ACC-A")
    manager.register("ACC-A", "آگاه", broker, provider)

    service = LivePrearmService(
        account_store=SimpleNamespace(),
        session_manager=session_manager,
        broker_manager=manager,
    )

    # Cached balance is None; fresh valid balance is provided on the account.
    account = Account("ACC-A", tradable_balance_t1=50000)
    order = _make_order(ins_code="40467386864240950", nsc_id="IRO3FSTZ0001")
    target = _FakeTarget(entry=SimpleNamespace(order=order), account=account,
                         account_id="ACC-A", broker_name="آگاه")

    execution_id, batch = service.prepare([target])

    assert batch.valid is True
    assert batch.checks_succeeded is True
    # Provider invoked with numeric ins_code, not Agah nscId.
    assert provider.calls == ["40467386864240950"]
    assert provider.calls[0] != "IRO3FSTZ0001"
    # No place_order — prepare only builds the batch.
    assert broker.place_order_calls == []


def test_prearm_blocks_when_t1_balance_none():
    """prepare() fails closed when tradable_balance_t1 is None on account."""
    manager = _FakeBrokerManager()
    session_manager = _FakeSessionManager()
    provider = _make_provider()
    broker = _make_broker("ACC-A")
    manager.register("ACC-A", "آگاه", broker, provider)

    service = LivePrearmService(
        account_store=SimpleNamespace(),
        session_manager=session_manager,
        broker_manager=manager,
    )

    account = Account("ACC-A", tradable_balance_t1=None)
    order = _make_order(ins_code="40467386864240950", nsc_id="IRO3FSTZ0001")
    target = _FakeTarget(entry=SimpleNamespace(order=order), account=account,
                         account_id="ACC-A", broker_name="آگاه")

    execution_id, batch = service.prepare([target])

    assert batch.valid is False
    assert provider.calls == ["40467386864240950"]  # lookup attempted
    assert broker.place_order_calls == []  # but no submission


def test_prearm_blocks_when_t1_balance_invalid():
    """prepare() fails closed when tradable_balance_t1 is non-numeric/negative."""
    for bad in ("not-a-number", -100):
        manager = _FakeBrokerManager()
        session_manager = _FakeSessionManager()
        provider = _make_provider()
        broker = _make_broker("ACC-A")
        manager.register("ACC-A", "آگاه", broker, provider)

        service = LivePrearmService(
            account_store=SimpleNamespace(),
            session_manager=session_manager,
            broker_manager=manager,
        )

        account = Account("ACC-A", tradable_balance_t1=bad)
        order = _make_order(ins_code="40467386864240950", nsc_id="IRO3FSTZ0001")
        target = _FakeTarget(entry=SimpleNamespace(order=order), account=account,
                             account_id="ACC-A", broker_name="آگاه")

        execution_id, batch = service.prepare([target])

        assert batch.valid is False, f"{bad!r}: batch should be invalid"
        assert broker.place_order_calls == [], f"{bad!r}: no place_order"
