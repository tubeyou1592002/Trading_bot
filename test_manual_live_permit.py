"""Offline-only contracts for scoped manual Live permits."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.live_order_authorization import (
    LiveAuthorizationError, ManualLivePermit, _MANUAL_PERMIT_ISSUER,
)
from core.safety_gate import SafetyGate
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order
from core.order_engine import OrderEngine
from ui.live_order_gate import check_manual_live_preflight
from ui.session_manager import SessionManager


class FakeBroker:
    name = "SIM"
    live_trading_enabled = False

    def __init__(self):
        self.payloads = []

    def get_trading_state(self, _):
        from models.trading_state import TradingState
        return TradingState(True, True, "SIM", "ok")

    def get_buy_capacity(self, **_):
        return 100000

    def get_sell_capacity(self, **_):
        return 100000

    def build_order_payload(self, order):
        return order.to_payload()

    def submit_manual_prepared_order(self, payload, *, permit, prepared,
                                     account_id, broker_name,
                                     queue_fingerprint, index):
        assert self.live_trading_enabled is False
        assert permit.claim(
            execution_id=prepared.execution_id, account_id=account_id,
            broker_name=broker_name, broker=self,
            queue_fingerprint=queue_fingerprint,
            prepared_fingerprint=__import__("core.live_order_authorization",
                fromlist=["prepared_fingerprint"]).prepared_fingerprint(prepared),
            index=index,
        )
        self.payloads.append(payload)
        return {"isSuccess": True}


class FakeProvider:
    def get_instrument(self, code):
        return None, BrokerInstrument(
            nsc_id=code, tse_id=code, minimum_order_quantity=1,
            lot_size=1, maximum_order_quantity_for_buy=1000,
            maximum_order_quantity_for_sell=1000, fixed_price_tick=1,
            lower_price_threshold=1, upper_price_threshold=1000,
        )


class FakeAuth:
    def __init__(self):
        self.adapter = SimpleNamespace(
            broker_name="SIM", is_authenticated=lambda: True,
            get_authenticated_session=lambda: SimpleNamespace(access_token="tok"),
        )

    def is_logged_in(self, _): return True
    def get_adapter(self, _): return self.adapter


def prepared_case(count=1):
    account = Account("A1", tradable_balance_t1=100000)
    broker = FakeBroker()
    manager = SimpleNamespace(
        get_for_account=lambda *_: broker,
        get_instrument_provider_for_account=lambda *_: FakeProvider(),
    )
    store = SimpleNamespace(
        get=lambda _: SimpleNamespace(account=account, account_id="A1", broker_name="SIM"),
        active_account_id=lambda: "A1",
    )
    sessions = SessionManager()
    sessions.register("A1", "SIM")
    sessions.begin_login("A1")
    sessions.mark_logged_in("A1", "tok")
    orders = [Order(f"N{i}", BUY, 10, 2) for i in range(count)]
    entries = [SimpleNamespace(order=o, account_id="A1", broker_name="SIM") for o in orders]
    engine = OrderEngine()
    execution_id = f"manual-{id(engine)}"
    batch = engine.prepare_batch([
        dict(broker=broker, provider=FakeProvider(), ins_code=o.nsc_id,
             order=o, account=account, account_id="A1", broker_name="SIM")
        for o in orders
    ], execution_id=execution_id)
    return account, broker, manager, store, sessions, entries, engine, execution_id, batch


def test_preflight_requires_confirmation_and_allows_only_single_destination():
    account, broker, manager, store, sessions, entries, engine, execution, batch = prepared_case(2)
    check = check_manual_live_preflight(
        account_store=store, authentication_service=FakeAuth(), session_manager=sessions,
        broker_manager=manager, account_id="A1", broker_name="SIM",
        execution_id=execution, entries=entries, prepared_batch=batch, engine=engine,
        live_selected=False, human_approval=True, include_missing_broker_ack=True,
    )
    assert not check.allowed
    assert broker.payloads == []


def test_scoped_permit_each_ticket_once_global_lock_stays_closed():
    account, broker, manager, store, sessions, entries, engine, execution, batch = prepared_case(2)
    check = check_manual_live_preflight(
        account_store=store, authentication_service=FakeAuth(), session_manager=sessions,
        broker_manager=manager, account_id="A1", broker_name="SIM",
        execution_id=execution, entries=entries, prepared_batch=batch, engine=engine,
        live_selected=True, human_approval=True, include_missing_broker_ack=True,
        confirmation_acknowledged=True,
    )
    assert check.allowed and broker.live_trading_enabled is False
    from ui.live_order_gate import issue_manual_live_permit
    permit, queue_fp = issue_manual_live_permit(
        execution_id=execution, account_id="A1", broker_name="SIM", broker=broker,
        entries=entries, prepared_batch=batch, gate_decision=check.gate.evaluate(
            manual_broker_acknowledged=True), confirmation_acknowledged=True,
        include_missing_broker_ack=True,
    )
    results = [engine.submit_manual_prepared_order(
        prepared, permit=permit, broker=broker, account=account,
        account_id="A1", broker_name="SIM", queue_fingerprint=queue_fp,
        index=index, acknowledge_missing_broker_readiness=True,
    ) for index, prepared in enumerate(batch.orders)]
    assert all(result.success and result.sent for result in results), [r.message for r in results]
    assert len(broker.payloads) == 2
    again = engine.submit_manual_prepared_order(
        batch.orders[0], permit=permit, broker=broker, account=account,
        account_id="A1", broker_name="SIM", queue_fingerprint=queue_fp,
        index=0, acknowledge_missing_broker_readiness=True,
    )
    assert not again.success
    permit.close()
    assert broker.live_trading_enabled is False


def test_permit_cannot_be_constructed_with_fabricated_gate():
    with pytest.raises(LiveAuthorizationError):
        ManualLivePermit(
            execution_id="x", account_id="A", broker_name="SIM",
            broker=FakeBroker(), queue_fingerprint="q",
            prepared_fingerprints=("p",),
            gate_decision=SafetyGate().evaluate(), _issuer=_MANUAL_PERMIT_ISSUER,
        )
