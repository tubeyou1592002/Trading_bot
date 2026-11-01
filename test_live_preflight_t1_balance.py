"""Offline regression tests for Live preflight T1 balance synchronization.

Verifies:
  * Fresh tradable_balance_t1 from the authenticated session of the active
    account reaches preflight before purchase validation.
  * Another account's session/balance is never used.
  * Missing / None / invalid fresh balance blocks preflight; place_order is
    never called.
  * Fresh balance is used only in the preflight snapshot; the persistent
    account object is never mutated.
No network, login, real order, Dry Run, Live, or schedule is exercised.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.order_engine import OrderEngine
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order
from ui.live_order_gate import check_manual_live_preflight
from ui.session_manager import SessionManager


class _FakeBroker:
    name = "SIM"
    live_trading_enabled = False

    def __init__(self):
        self.place_order_calls = []

    def get_trading_state(self, _):
        from models.trading_state import TradingState
        return TradingState(True, True, "SIM", "ok")

    def get_buy_capacity(self, **_):
        return 100000

    def build_order_payload(self, order):
        return order.to_payload()

    def submit_manual_prepared_order(self, payload, *, permit, prepared,
                                     account_id, broker_name,
                                     queue_fingerprint, index, trace_id=None):
        self.place_order_calls.append(payload)
        return {"isSuccess": True}


class _FakeProvider:
    def get_instrument(self, code):
        return None, BrokerInstrument(
            nsc_id=code, tse_id=code, minimum_order_quantity=1,
            lot_size=1, maximum_order_quantity_for_buy=1000,
            maximum_order_quantity_for_sell=1000, fixed_price_tick=1,
            lower_price_threshold=1, upper_price_threshold=1000,
        )


class _FakeAuth:
    """Auth service exposing get_purchase_power for the active session."""

    def __init__(self, balances=None):
        self.balances = balances or {}
        self.adapter = SimpleNamespace(
            broker_name="SIM", is_authenticated=lambda: True,
            get_authenticated_session=lambda: SimpleNamespace(access_token="tok"),
        )

    def is_logged_in(self, account_id):
        return account_id in self.balances

    def get_adapter(self, account_id):
        return self.adapter

    def get_purchase_power(self, account_id):
        if account_id not in self.balances:
            raise KeyError(account_id)
        return self.balances[account_id]


def _make_case(account_id="A", ins_code="N1", price=10, quantity=2):
    # Cached account has a SUFFICIENT stale balance so prepare_batch builds a
    # valid batch; the FRESH balance comes from the auth session in preflight.
    account = Account(account_id, tradable_balance_t1=100000)
    broker = _FakeBroker()
    manager = SimpleNamespace(
        get_for_account=lambda *_: broker,
        get_instrument_provider_for_account=lambda *_: _FakeProvider(),
    )
    store = SimpleNamespace(
        get=lambda aid: SimpleNamespace(
            account=account, account_id=aid, broker_name="SIM",
        ),
        active_account_id=lambda: account_id,
    )
    sessions = SessionManager()
    sessions.register(account_id, "SIM")
    sessions.begin_login(account_id)
    sessions.mark_logged_in(account_id, "tok")
    order = Order(ins_code, BUY, price, quantity)
    entries = [SimpleNamespace(order=order, account_id=account_id,
                               broker_name="SIM")]
    engine = OrderEngine()
    execution_id = "manual-preflight-test"
    batch = engine.prepare_batch([
        dict(broker=broker, provider=_FakeProvider(), ins_code=order.nsc_id,
             order=order, account=account, account_id=account_id,
             broker_name="SIM")
    ], execution_id=execution_id)
    return account, broker, manager, store, sessions, entries, engine, \
        execution_id, batch


def _run_preflight(fresh_balance, account_id="A"):
    account, broker, manager, store, sessions, entries, engine, \
        execution_id, batch = _make_case(account_id=account_id)
    if fresh_balance is not None and isinstance(fresh_balance, (int, float)):
        from dataclasses import replace
        fresh_account = replace(account, tradable_balance_t1=fresh_balance)
        batch = engine.prepare_batch([dict(
            broker=manager.get_for_account(account_id, "SIM"),
            provider=_FakeProvider(), ins_code=entries[0].order.nsc_id,
            order=entries[0].order, account=fresh_account,
            account_id=account_id, broker_name="SIM",
        )], execution_id=execution_id + "-fresh")
        execution_id += "-fresh"
    auth = _FakeAuth(balances={account_id: fresh_balance}
                     if fresh_balance is not None else {})
    check = check_manual_live_preflight(
        account_store=store, authentication_service=auth,
        session_manager=sessions, broker_manager=manager,
        account_id=account_id, broker_name="SIM",
        execution_id=execution_id, entries=entries,
        prepared_batch=batch, engine=engine,
        live_selected=True, human_approval=True,
        include_missing_broker_ack=True,
        confirmation_acknowledged=True,
    )
    return account, broker, check


def test_fresh_balance_reaches_preflight_for_active_account(tmp_path, monkeypatch):
    """Fresh T1 balance from session reaches preflight; order passes."""
    account, broker, check = _run_preflight(fresh_balance=50000)
    assert check.allowed is True, check.reason
    # Stored account object is NOT mutated by preflight.
    assert account.tradable_balance_t1 == 100000
    assert broker.place_order_calls == []


def test_different_initial_and_fresh_balance_reaches_engine_and_fake_post(monkeypatch, tmp_path):
    """Pre-fix reproduction: stale submit snapshot failed real validation."""
    from core.live_order_authorization import prepared_fingerprint
    from core.live_order_authorization import ManualLivePermit, _MANUAL_PERMIT_ISSUER
    from core.safety_gate import SafetyGateDecision
    from ui import manual_live_trace

    monkeypatch.setattr(manual_live_trace, "_TRACE_DIR", tmp_path / "trace")
    monkeypatch.setattr(manual_live_trace, "_TRACE_FILE", tmp_path / "trace" / "events.jsonl")

    from dataclasses import replace
    account, broker, manager, store, sessions, entries, engine, execution_id, batch = _make_case()
    auth = _FakeAuth({"A": 50000})
    check = check_manual_live_preflight(
        account_store=store, authentication_service=auth,
        session_manager=sessions, broker_manager=manager,
        account_id="A", broker_name="SIM", execution_id=execution_id,
        entries=entries, prepared_batch=batch, engine=engine,
        live_selected=True, human_approval=True,
        include_missing_broker_ack=True, confirmation_acknowledged=True,
    )
    assert check.allowed is False
    assert "Prepared account changed" in check.reason

    account, broker, manager, store, sessions, entries, engine, execution_id, _cached_batch = _make_case()
    fresh_account = replace(account, tradable_balance_t1=50000)
    batch = engine.prepare_batch([dict(
        broker=broker, provider=_FakeProvider(), ins_code="N1",
        order=entries[0].order, account=fresh_account, account_id="A",
        broker_name="SIM",
    )], execution_id=execution_id + "-fresh")
    execution_id += "-fresh"
    check = check_manual_live_preflight(
        account_store=store, authentication_service=auth,
        session_manager=sessions, broker_manager=manager,
        account_id="A", broker_name="SIM", execution_id=execution_id,
        entries=entries, prepared_batch=batch, engine=engine,
        live_selected=True, human_approval=True,
        include_missing_broker_ack=True, confirmation_acknowledged=True,
    )
    assert check.allowed is True, check.reason

    prepared = batch.orders[0]
    permit = ManualLivePermit(
        execution_id=execution_id, account_id="A", broker_name="SIM",
        broker=broker, queue_fingerprint="queue-fp",
        prepared_fingerprints=(prepared_fingerprint(prepared),),
        gate_decision=SafetyGateDecision(True, "ALLOWED", None, "ok"),
        missing_broker_acknowledged=True, _issuer=_MANUAL_PERMIT_ISSUER,
    )
    result = engine.submit_manual_prepared_order(
        prepared, permit=permit, broker=broker, account=fresh_account,
        account_id="A", broker_name="SIM", queue_fingerprint="queue-fp",
        index=0, acknowledge_missing_broker_readiness=True,
    )
    assert result.mode == "LIVE", result.message
    assert len(broker.place_order_calls) == 1


def test_changed_account_snapshot_still_blocks_engine_and_fake_post(monkeypatch, tmp_path):
    """A real post-approval account change is not normalized away."""
    from core.live_order_authorization import prepared_fingerprint
    from core.live_order_authorization import ManualLivePermit, _MANUAL_PERMIT_ISSUER
    from core.safety_gate import SafetyGateDecision
    from ui import manual_live_trace
    from dataclasses import replace

    monkeypatch.setattr(manual_live_trace, "_TRACE_DIR", tmp_path / "trace")
    monkeypatch.setattr(manual_live_trace, "_TRACE_FILE", tmp_path / "trace" / "events.jsonl")
    account, _broker, _manager, _store, _sessions, _entries, engine, execution_id, batch = _make_case()
    broker = _FakeBroker()
    prepared = batch.orders[0]
    # Reprepare against this test's broker to keep destination identity valid.
    batch = engine.prepare_batch([dict(
        broker=broker, provider=_FakeProvider(), ins_code="N1",
        order=prepared.order, account=account, account_id="A", broker_name="SIM",
    )], execution_id=execution_id + "-changed")
    execution_id += "-changed"
    prepared = batch.orders[0]
    permit = ManualLivePermit(
        execution_id=execution_id, account_id="A", broker_name="SIM",
        broker=broker, queue_fingerprint="queue-fp",
        prepared_fingerprints=(prepared_fingerprint(prepared),),
        gate_decision=SafetyGateDecision(True, "ALLOWED", None, "ok"),
        missing_broker_acknowledged=True, _issuer=_MANUAL_PERMIT_ISSUER,
    )
    changed = replace(account, tradable_balance_t1=49999)
    result = engine.submit_manual_prepared_order(
        prepared, permit=permit, broker=broker, account=changed,
        account_id="A", broker_name="SIM", queue_fingerprint="queue-fp",
        index=0, acknowledge_missing_broker_readiness=True,
    )
    assert result.mode == "BLOCKED"
    assert result.message == "Prepared account changed"
    assert broker.place_order_calls == []


def test_other_account_balance_not_used(tmp_path, monkeypatch):
    """Account B's balance is not read for account A's preflight."""
    account, broker, manager, store, sessions, entries, engine, \
        execution_id, batch = _make_case(account_id="A")
    # Auth only knows B's balance; A's is missing.
    auth = _FakeAuth(balances={"B": 999999})
    check = check_manual_live_preflight(
        account_store=store, authentication_service=auth,
        session_manager=sessions, broker_manager=manager,
        account_id="A", broker_name="SIM",
        execution_id=execution_id, entries=entries,
        prepared_batch=batch, engine=engine,
        live_selected=True, human_approval=True,
        include_missing_broker_ack=True,
        confirmation_acknowledged=True,
    )
    assert check.allowed is False, check.reason
    assert broker.place_order_calls == []


def test_missing_balance_blocks_preflight_no_place_order(tmp_path, monkeypatch):
    """No fresh balance → fail-closed, no place_order."""
    account, broker, check = _run_preflight(fresh_balance=None)
    assert check.allowed is False, check.reason
    assert broker.place_order_calls == []


def test_invalid_balance_blocks_preflight_no_place_order(tmp_path, monkeypatch):
    """Non-numeric / negative fresh balance → fail-closed, no place_order."""
    for bad in ("not-a-number", -100, float("nan"), float("inf")):
        account, broker, check = _run_preflight(fresh_balance=bad)
        assert check.allowed is False, f"{bad!r}: {check.reason}"
        assert broker.place_order_calls == []


def test_balance_none_blocks_preflight_no_place_order(tmp_path, monkeypatch):
    """Fresh balance explicitly None → fail-closed, no place_order."""
    account, broker, check = _run_preflight(fresh_balance=None)
    assert check.allowed is False, check.reason
    assert broker.place_order_calls == []


def test_persistent_account_not_mutated(tmp_path, monkeypatch):
    """Preflight uses a copy; stored account keeps its stale balance."""
    account, broker, check = _run_preflight(fresh_balance=50000)
    assert check.allowed is True
    assert account.tradable_balance_t1 == 100000  # unchanged
    assert broker.place_order_calls == []


def test_no_get_purchase_power_blocks_preflight(tmp_path, monkeypatch):
    """Auth service without get_purchase_power blocks preflight even with
    valid cached T1; place_order never called."""
    account, broker, manager, store, sessions, entries, engine, \
        execution_id, batch = _make_case(account_id="A")
    # Auth service has no get_purchase_power / get_tradable_balance at all.
    auth = SimpleNamespace(
        is_logged_in=lambda aid: True,
        get_adapter=lambda aid: SimpleNamespace(
            broker_name="SIM", is_authenticated=lambda: True,
            get_authenticated_session=lambda: SimpleNamespace(access_token="tok"),
        ),
    )
    check = check_manual_live_preflight(
        account_store=store, authentication_service=auth,
        session_manager=sessions, broker_manager=manager,
        account_id="A", broker_name="SIM",
        execution_id=execution_id, entries=entries,
        prepared_batch=batch, engine=engine,
        live_selected=True, human_approval=True,
        include_missing_broker_ack=True,
        confirmation_acknowledged=True,
    )
    assert check.allowed is False, check.reason
    assert broker.place_order_calls == []


def test_no_adapter_blocks_preflight(tmp_path, monkeypatch):
    """Auth service without adapter blocks preflight even with valid cached
    T1; place_order never called."""
    account, broker, manager, store, sessions, entries, engine, \
        execution_id, batch = _make_case(account_id="A")
    auth = SimpleNamespace(
        is_logged_in=lambda aid: True,
        get_purchase_power=lambda aid: 50000,
        get_adapter=lambda aid: None,
    )
    check = check_manual_live_preflight(
        account_store=store, authentication_service=auth,
        session_manager=sessions, broker_manager=manager,
        account_id="A", broker_name="SIM",
        execution_id=execution_id, entries=entries,
        prepared_batch=batch, engine=engine,
        live_selected=True, human_approval=True,
        include_missing_broker_ack=True,
        confirmation_acknowledged=True,
    )
    assert check.allowed is False, check.reason
    assert broker.place_order_calls == []


def test_fresh_account_fingerprint_integrity():
    """The temporary snapshot fingerprint covers the fresh account; changed
    account/order/permission checks are NOT weakened."""
    account, broker, manager, store, sessions, entries, engine, \
        execution_id, batch = _make_case(account_id="A")
    auth = _FakeAuth(balances={"A": 50000})
    # Change order price AFTER batch preparation so prepared order fingerprint
    # no longer matches the entry order.
    entries[0].order.price = 999999
    check = check_manual_live_preflight(
        account_store=store, authentication_service=auth,
        session_manager=sessions, broker_manager=manager,
        account_id="A", broker_name="SIM",
        execution_id=execution_id, entries=entries,
        prepared_batch=batch, engine=engine,
        live_selected=True, human_approval=True,
        include_missing_broker_ack=True,
        confirmation_acknowledged=True,
    )
    assert check.allowed is False, check.reason
    assert broker.place_order_calls == []


def test_fresh_balance_insufficient_blocks_preflight():
    """Fresh balance below order cost blocks preflight; place_order never called."""
    account, broker, check = _run_preflight(fresh_balance=1)
    assert check.allowed is False, check.reason
    assert broker.place_order_calls == []
