"""
test_block7_task5.py — Task 7.5 Multi-Broker Dispatch Routing Proof.

Proves that DispatchCore routes every order to the correct Broker
via the path:

    ExecutionPlan
        → conditions["binding"]
        → account_routes
        → DispatchCore.dispatch()
        → BrokerManager.get(broker_name)
        → correct Broker instance
        → OrderEngine.execute_by_ins_code(...)

No production code is changed.
Only this file is created/modified.

Run:
    python -m pytest test_block7_task5.py test_block7_task4.py test_broker_manager.py test_instrument_provider.py -q
"""

import sys
import traceback

from unittest.mock import Mock

from brokers.base import InstrumentLookupError
from brokers.manager import BrokerManager
from core.dispatch_core import DispatchCore
from core.dispatch_contracts import (
    BrokerDispatchRequest,
    DispatchResult,
    ExecutionPlan,
)
from core.order_engine import OrderExecutionResult
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, SELL, Order


# ============================================================
# Test Doubles (fully offline)
# ============================================================


class FakeBrokerA:
    """Fake Broker A — fully offline, no network/API/login."""

    def __init__(self):
        self.name = "BrokerA"
        self._instrument_cache = {}

    def login(self, username, password, **kwargs):
        return {"success": True, "username": username, "token": "fake-token-a"}

    def get_account(self):
        return Account(
            account_id="ACC-001",
            last_balance=1000000,
            tradable_balance_t1=500000,
            tradable_balance_t2=200000,
        )

    def place_order(self, order, live=False):
        return {"mode": "DRY_RUN", "sent": False, "order_id": "fake-order-a"}

    def cancel_order(self, order_id):
        return {"canceled": True, "order_id": order_id}

    def get_trading_state(self, nsc_id):
        return UNVERIFIED_STATE

    def get_buy_capacity(self, nsc_id, side_code, fund, price):
        raise NotImplementedError

    def get_sell_capacity(self, nsc_id, side_code, fund, price):
        raise NotImplementedError

    def get_instrument(self, nsc_id):
        if nsc_id in self._instrument_cache:
            return self._instrument_cache[nsc_id]
        result = (
            Instrument(symbol="A", name="BrokerA-Instrument", ins_code=nsc_id),
            BrokerInstrument(
                name="BrokerA-Instrument",
                company_name="BrokerA Co",
                nsc_id=nsc_id,
                tse_id=nsc_id,
            ),
        )
        self._instrument_cache[nsc_id] = result
        return result


class FakeBrokerB:
    """Fake Broker B — fully offline, no network/API/login."""

    def __init__(self):
        self.name = "BrokerB"
        self._instrument_cache = {}

    def login(self, username, password, **kwargs):
        return {"success": True, "username": username, "token": "fake-token-b"}

    def get_account(self):
        return Account(
            account_id="ACC-002",
            last_balance=2000000,
            tradable_balance_t1=1000000,
            tradable_balance_t2=400000,
        )

    def place_order(self, order, live=False):
        return {"mode": "DRY_RUN", "sent": False, "order_id": "fake-order-b"}

    def cancel_order(self, order_id):
        return {"canceled": True, "order_id": order_id}

    def get_trading_state(self, nsc_id):
        return UNVERIFIED_STATE

    def get_buy_capacity(self, nsc_id, side_code, fund, price):
        raise NotImplementedError

    def get_sell_capacity(self, nsc_id, side_code, fund, price):
        raise NotImplementedError

    def get_instrument(self, nsc_id):
        if nsc_id in self._instrument_cache:
            return self._instrument_cache[nsc_id]
        result = (
            Instrument(symbol="B", name="BrokerB-Instrument", ins_code=nsc_id),
            BrokerInstrument(
                name="BrokerB-Instrument",
                company_name="BrokerB Co",
                nsc_id=nsc_id,
                tse_id=nsc_id,
            ),
        )
        self._instrument_cache[nsc_id] = result
        return result


class FakeInstrumentProviderA:
    """Offline provider for BrokerA."""

    def __init__(self, broker):
        self._broker = broker
        self._cache = {}
        self._nsc_cache = {}

    def get_instrument(self, ins_code):
        if ins_code in self._cache:
            return self._cache[ins_code]
        instrument = Instrument(
            symbol="A", name="BrokerA-Instrument", ins_code=ins_code,
        )
        broker_instrument = BrokerInstrument(
            name="BrokerA-Instrument",
            company_name="BrokerA Co",
            nsc_id=ins_code,
            tse_id=ins_code,
        )
        result = (instrument, broker_instrument)
        self._cache[ins_code] = result
        return result

    def get_nsc_id(self, ins_code):
        if ins_code in self._nsc_cache:
            return self._nsc_cache[ins_code]
        self._nsc_cache[ins_code] = ins_code
        return ins_code

    def refresh_cache(self):
        self._cache.clear()
        self._nsc_cache.clear()


class FakeInstrumentProviderB:
    """Offline provider for BrokerB."""

    def __init__(self, broker):
        self._broker = broker
        self._cache = {}
        self._nsc_cache = {}

    def get_instrument(self, ins_code):
        if ins_code in self._cache:
            return self._cache[ins_code]
        instrument = Instrument(
            symbol="B", name="BrokerB-Instrument", ins_code=ins_code,
        )
        broker_instrument = BrokerInstrument(
            name="BrokerB-Instrument",
            company_name="BrokerB Co",
            nsc_id=ins_code,
            tse_id=ins_code,
        )
        result = (instrument, broker_instrument)
        self._cache[ins_code] = result
        return result

    def get_nsc_id(self, ins_code):
        if ins_code in self._nsc_cache:
            return self._nsc_cache[ins_code]
        self._nsc_cache[ins_code] = ins_code
        return ins_code

    def refresh_cache(self):
        self._cache.clear()
        self._nsc_cache.clear()


UNVERIFIED_STATE = Mock()
UNVERIFIED_STATE.is_verified = False
UNVERIFIED_STATE.is_order_entry_allowed = True


# ============================================================
# Test infrastructure
# ============================================================

TEST_RESULTS = []


def _run(name, fn):
    try:
        fn()
        TEST_RESULTS.append((name, "PASS", None))
    except Exception as exc:
        TEST_RESULTS.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))
        traceback.print_exc()


def make_order(nsc_id, side=BUY, price=150, quantity=10):
    return Order(nsc_id=nsc_id, side=side, price=price, quantity=quantity)


def make_account(account_id, balance=1000000):
    acc = Account(
        account_id=account_id,
        last_balance=balance,
        tradable_balance_t1=balance // 2,
        tradable_balance_t2=balance // 5,
    )
    return acc


def build_plan_real(planner, orders_info, execution_order=None, plan_id="plan-75"):
    """
    Build an ExecutionPlan through the REAL Block 1 planner.

    orders_info: list of (order, account_id, broker_name)
    Returns (plan, accounts_dict) — accounts_dict maps account_id → Account object.
    """
    planned_orders = [
        PlannedOrder(
            order=order,
            account_id=aid,
            broker_name=bname,
            sequence=seq,
        )
        for seq, (order, aid, bname) in enumerate(orders_info, start=1)
    ]
    plan = planner.build_plan(
        LogicalOrderInstruction(plan_id=plan_id, orders=planned_orders)
    )
    accounts = {}
    for _, aid, _ in orders_info:
        if aid not in accounts:
            accounts[aid] = make_account(aid)
    return plan, accounts


def attach_accounts(plan, accounts):
    seen = []
    for seq in plan.execution_order:
        acc_id = plan.conditions["binding"][seq]["account_id"]
        if acc_id not in seen:
            seen.append(acc_id)
    plan.accounts = [accounts[a] for a in seen]
    return plan


def make_spy():
    """Returns (spy function, spy_calls list)."""
    calls = []

    def spy(broker, provider, ins_code, order, account, live):
        calls.append(
            {
                "broker": broker,
                "broker_name": getattr(broker, "name", None),
                "ins_code": ins_code,
                "order": order,
                "account": account,
                "live": live,
            }
        )
        return OrderExecutionResult(
            success=True,
            sent=False,
            mode="READY",
            order=order,
            broker_name=getattr(broker, "name", None),
            message="READY",
        )

    return spy, calls


def ok_result():
    return OrderExecutionResult(
        success=True,
        sent=False,
        mode="READY",
        order=None,
        broker_name=None,
        message="READY",
    )


# ============================================================
# Test — A/B/A Main Scenario
# ============================================================


def test_aba_main_scenario():
    """
    Sequence 1 → BrokerA
    Sequence 2 → BrokerB
    Sequence 3 → BrokerA

    Verify execute_by_ins_code receives the correct broker instance
    for each order (by INSTANCE IDENTITY, not just name).
    """
    planner = ExecutionPlanner()
    broker_manager = BrokerManager()

    fake_a = FakeBrokerA()
    fake_b = FakeBrokerB()
    provider_a = FakeInstrumentProviderA(fake_a)
    provider_b = FakeInstrumentProviderB(fake_b)

    broker_manager.register("BrokerA", fake_a, FakeInstrumentProviderA)
    broker_manager.register("BrokerB", fake_b, FakeInstrumentProviderB)

    order1 = make_order("TEST-A")
    order2 = make_order("TEST-B")
    order3 = make_order("TEST-C")

    plan, accounts = build_plan_real(
        planner,
        [
            (order1, "ACC-001", "BrokerA"),
            (order2, "ACC-002", "BrokerB"),
            (order3, "ACC-001", "BrokerA"),
        ],
    )
    attach_accounts(plan, accounts)

    core = DispatchCore(broker_manager=broker_manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    result = core.dispatch(plan)

    assert isinstance(result, DispatchResult), "dispatch returns DispatchResult"
    assert result.success is True, f"all orders processed: {result.mode}"
    assert result.mode == "ALL_PROCESSED", f"mode={result.mode}"

    assert len(calls) == 3, f"3 orders dispatched, got {len(calls)}"

    assert calls[0]["broker"] is fake_a, (
        f"Order 1 → FakeBrokerA instance, got {calls[0]['broker']}"
    )
    assert calls[0]["broker_name"] == "BrokerA", (
        f"Order 1 broker name BrokerA, got {calls[0]['broker_name']}"
    )
    assert calls[0]["ins_code"] == "TEST-A", (
        f"Order 1 ins_code TEST-A, got {calls[0]['ins_code']}"
    )

    assert calls[1]["broker"] is fake_b, (
        f"Order 2 → FakeBrokerB instance, got {calls[1]['broker']}"
    )
    assert calls[1]["broker_name"] == "BrokerB", (
        f"Order 2 broker name BrokerB, got {calls[1]['broker_name']}"
    )
    assert calls[1]["ins_code"] == "TEST-B", (
        f"Order 2 ins_code TEST-B, got {calls[1]['ins_code']}"
    )

    assert calls[2]["broker"] is fake_a, (
        f"Order 3 → FakeBrokerA instance, got {calls[2]['broker']}"
    )
    assert calls[2]["broker_name"] == "BrokerA", (
        f"Order 3 broker name BrokerA, got {calls[2]['broker_name']}"
    )
    assert calls[2]["ins_code"] == "TEST-C", (
        f"Order 3 ins_code TEST-C, got {calls[2]['ins_code']}"
    )


# ============================================================
# Test — Order Independence
# ============================================================


def test_order_independence():
    """
    Each order's broker selection is independent.
    Order 1 → A, Order 2 → B, Order 3 → A
    Must NOT produce A → A → A or A → B → B.
    """
    planner = ExecutionPlanner()
    broker_manager = BrokerManager()

    fake_a = FakeBrokerA()
    fake_b = FakeBrokerB()
    provider_a = FakeInstrumentProviderA(fake_a)
    provider_b = FakeInstrumentProviderB(fake_b)

    broker_manager.register("BrokerA", fake_a, FakeInstrumentProviderA)
    broker_manager.register("BrokerB", fake_b, FakeInstrumentProviderB)

    o1 = make_order("X1")
    o2 = make_order("X2")
    o3 = make_order("X3")

    plan, accounts = build_plan_real(
        planner,
        [
            (o1, "C1", "BrokerA"),
            (o2, "C2", "BrokerB"),
            (o3, "C1", "BrokerA"),
        ],
    )
    attach_accounts(plan, accounts)

    core = DispatchCore(broker_manager=broker_manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    core.dispatch(plan)

    broker_names = [c["broker_name"] for c in calls]
    assert broker_names == ["BrokerA", "BrokerB", "BrokerA"], (
        f"Expected A,B,A but got {broker_names}"
    )

    broker_instances = [c["broker"] for c in calls]
    assert broker_instances[0] is fake_a
    assert broker_instances[1] is fake_b
    assert broker_instances[2] is fake_a


# ============================================================
# Test — Unknown Broker → BLOCKED
# ============================================================


def test_unknown_broker_blocked():
    """
    A plan with an order routed to an unknown broker.
    execute_by_ins_code must NOT be called for that order.
    No fallback to BrokerA or BrokerB.
    """
    planner = ExecutionPlanner()
    broker_manager = BrokerManager()

    fake_a = FakeBrokerA()
    fake_b = FakeBrokerB()
    provider_a = FakeInstrumentProviderA(fake_a)
    provider_b = FakeInstrumentProviderB(fake_b)

    broker_manager.register("BrokerA", fake_a, FakeInstrumentProviderA)
    broker_manager.register("BrokerB", fake_b, FakeInstrumentProviderB)

    o1 = make_order("TEST-A")
    o2 = make_order("TEST-X")
    o3 = make_order("TEST-C")

    plan, accounts = build_plan_real(
        planner,
        [
            (o1, "ACC-001", "BrokerA"),
            (o2, "ACC-002", "UnknownBroker"),
            (o3, "ACC-001", "BrokerA"),
        ],
    )
    attach_accounts(plan, accounts)

    core = DispatchCore(broker_manager=broker_manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    result = core.dispatch(plan)

    assert result.success is False, "unknown broker → fail"
    assert result.mode == "BLOCKED", f"mode={result.mode}"

    assert len(calls) == 0, (
        f"execute_by_ins_code must NOT be called for unknown broker, got {len(calls)} calls"
    )


# ============================================================
# Test — Route Mismatch → BLOCKED
# ============================================================


def test_route_mismatch_blocked():
    """
    binding says BrokerA but account_routes says BrokerB for same account.
    execute_by_ins_code must NOT be called.
    No other broker selected.
    """
    planner = ExecutionPlanner()
    broker_manager = BrokerManager()

    fake_a = FakeBrokerA()
    fake_b = FakeBrokerB()

    broker_manager.register("BrokerA", fake_a, FakeInstrumentProviderA)
    broker_manager.register("BrokerB", fake_b, FakeInstrumentProviderB)

    o1 = make_order("TEST-001")

    plan, accounts = build_plan_real(
        planner,
        [
            (o1, "ACC-001", "BrokerA"),
        ],
    )
    attach_accounts(plan, accounts)

    # Inject route mismatch: account_routes says BrokerB, binding says BrokerA
    plan.account_routes["ACC-001"] = "BrokerB"

    core = DispatchCore(broker_manager=broker_manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    result = core.dispatch(plan)

    assert result.success is False, "route mismatch → fail"
    assert result.mode == "BLOCKED", f"mode={result.mode}"
    assert len(calls) == 0, (
        f"execute_by_ins_code must NOT be called on route mismatch, got {len(calls)}"
    )


# ============================================================
# Test — Missing Account Route → BLOCKED
# ============================================================


def test_missing_account_route_blocked():
    """
    Valid account but no entry in account_routes.
    execute_by_ins_code must NOT be called.
    """
    planner = ExecutionPlanner()
    broker_manager = BrokerManager()

    fake_a = FakeBrokerA()
    fake_b = FakeBrokerB()

    broker_manager.register("BrokerA", fake_a, FakeInstrumentProviderA)
    broker_manager.register("BrokerB", fake_b, FakeInstrumentProviderB)

    o1 = make_order("TEST-001")

    plan, accounts = build_plan_real(
        planner,
        [
            (o1, "ACC-001", "BrokerA"),
        ],
    )
    attach_accounts(plan, accounts)

    # Remove the account route
    plan.account_routes = {}

    core = DispatchCore(broker_manager=broker_manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    result = core.dispatch(plan)

    assert result.success is False, "missing route → fail"
    assert result.mode == "BLOCKED", f"mode={result.mode}"
    assert len(calls) == 0, (
        f"execute_by_ins_code must NOT be called on missing route, got {len(calls)}"
    )


# ============================================================
# Test — Broker Instance Independence
# ============================================================


def test_broker_instance_independence():
    """
    FakeBrokerA and FakeBrokerB must be DISTINCT instances.
    Order 1 must receive the FakeBrokerA instance by identity,
    Order 2 must receive the FakeBrokerB instance by identity.
    """
    planner = ExecutionPlanner()
    broker_manager = BrokerManager()

    fake_a = FakeBrokerA()
    fake_b = FakeBrokerB()

    broker_manager.register("BrokerA", fake_a, FakeInstrumentProviderA)
    broker_manager.register("BrokerB", fake_b, FakeInstrumentProviderB)

    assert fake_a is not fake_b, "FakeBrokerA and FakeBrokerB must be different instances"

    o1 = make_order("TEST-A")
    o2 = make_order("TEST-B")

    plan, accounts = build_plan_real(
        planner,
        [
            (o1, "ACC-001", "BrokerA"),
            (o2, "ACC-002", "BrokerB"),
        ],
    )
    attach_accounts(plan, accounts)

    core = DispatchCore(broker_manager=broker_manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    core.dispatch(plan)

    assert len(calls) == 2
    assert calls[0]["broker"] is fake_a, (
        f"Order 1 must receive FakeBrokerA instance by identity, got {calls[0]['broker']}"
    )
    assert calls[1]["broker"] is fake_b, (
        f"Order 2 must receive FakeBrokerB instance by identity, got {calls[1]['broker']}"
    )


# ============================================================
# Test — Order-Specific Broker (same symbol, different brokers)
# ============================================================


def test_order_specific_broker():
    """
    Two orders with the SAME nsc_id but bound to DIFFERENT brokers.
    Each must go to its own broker — not determined by symbol similarity.
    """
    planner = ExecutionPlanner()
    broker_manager = BrokerManager()

    fake_a = FakeBrokerA()
    fake_b = FakeBrokerB()

    broker_manager.register("BrokerA", fake_a, FakeInstrumentProviderA)
    broker_manager.register("BrokerB", fake_b, FakeInstrumentProviderB)

    o1 = make_order("TEST-001")
    o2 = make_order("TEST-001")

    plan, accounts = build_plan_real(
        planner,
        [
            (o1, "ACC-001", "BrokerA"),
            (o2, "ACC-002", "BrokerB"),
        ],
    )
    attach_accounts(plan, accounts)

    core = DispatchCore(broker_manager=broker_manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    core.dispatch(plan)

    assert len(calls) == 2
    assert calls[0]["broker"] is fake_a
    assert calls[0]["broker_name"] == "BrokerA"
    assert calls[0]["ins_code"] == "TEST-001"

    assert calls[1]["broker"] is fake_b
    assert calls[1]["broker_name"] == "BrokerB"
    assert calls[1]["ins_code"] == "TEST-001"


# ============================================================
# Test — No Fallback (fail-closed)
# ============================================================


def test_no_fallback():
    """
    For every failure scenario, execute_by_ins_code must NOT be called.
    Fail-closed: no unknown broker → BrokerA fallback, no previous broker fallback.
    """
    broker_manager = BrokerManager()

    fake_a = FakeBrokerA()
    fake_b = FakeBrokerB()

    broker_manager.register("BrokerA", fake_a, FakeInstrumentProviderA)
    broker_manager.register("BrokerB", fake_b, FakeInstrumentProviderB)

    o1 = make_order("TEST-001")

    # --- Scenario 1: Unknown broker ---
    planner = ExecutionPlanner()
    plan1, accounts1 = build_plan_real(
        planner,
        [(o1, "ACC-001", "NoSuchBroker")],
    )
    attach_accounts(plan1, accounts1)

    core1 = DispatchCore(broker_manager=broker_manager)
    spy1, calls1 = make_spy()
    core1.order_engine.execute_by_ins_code = spy1
    core1.dispatch(plan1)

    assert len(calls1) == 0, (
        f"Unknown broker: execute_by_ins_code called {len(calls1)} times, expected 0"
    )

    # --- Scenario 2: Route mismatch ---
    planner2 = ExecutionPlanner()
    plan2, accounts2 = build_plan_real(
        planner2,
        [(o1, "ACC-001", "BrokerA")],
    )
    attach_accounts(plan2, accounts2)
    plan2.account_routes["ACC-001"] = "BrokerB"

    core2 = DispatchCore(broker_manager=broker_manager)
    spy2, calls2 = make_spy()
    core2.order_engine.execute_by_ins_code = spy2
    core2.dispatch(plan2)

    assert len(calls2) == 0, (
        f"Route mismatch: execute_by_ins_code called {len(calls2)} times, expected 0"
    )

    # --- Scenario 3: Missing route ---
    planner3 = ExecutionPlanner()
    plan3, accounts3 = build_plan_real(
        planner3,
        [(o1, "ACC-001", "BrokerA")],
    )
    attach_accounts(plan3, accounts3)
    plan3.account_routes = {}

    core3 = DispatchCore(broker_manager=broker_manager)
    spy3, calls3 = make_spy()
    core3.order_engine.execute_by_ins_code = spy3
    core3.dispatch(plan3)

    assert len(calls3) == 0, (
        f"Missing route: execute_by_ins_code called {len(calls3)} times, expected 0"
    )


# ============================================================
# Test — Spy Records: sequence, broker instance, broker name, ins_code
# ============================================================


def test_spy_records_all_fields():
    """
    Verify spy records broker, broker_name, ins_code, and live
    for every order in A/B/A plan.

    Note: execute_by_ins_code() does not receive a sequence parameter,
    so the spy does NOT record sequence. Instead, call order follows
    plan.execution_order, and broker/broker_name/ins_code/live are
    recorded for each call.

    This test verifies that call order matches the A/B/A dispatch
    sequence and that ins_code values follow the same execution order.
    """
    planner = ExecutionPlanner()
    broker_manager = BrokerManager()

    fake_a = FakeBrokerA()
    fake_b = FakeBrokerB()

    broker_manager.register("BrokerA", fake_a, FakeInstrumentProviderA)
    broker_manager.register("BrokerB", fake_b, FakeInstrumentProviderB)

    o1 = make_order("TEST-A")
    o2 = make_order("TEST-B")
    o3 = make_order("TEST-C")

    plan, accounts = build_plan_real(
        planner,
        [
            (o1, "ACC-001", "BrokerA"),
            (o2, "ACC-002", "BrokerB"),
            (o3, "ACC-001", "BrokerA"),
        ],
    )
    attach_accounts(plan, accounts)

    core = DispatchCore(broker_manager=broker_manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    core.dispatch(plan)

    assert len(calls) == 3

    broker_names = [c["broker_name"] for c in calls]
    assert broker_names == ["BrokerA", "BrokerB", "BrokerA"], (
        f"Call order must match A/B/A dispatch, got {broker_names}"
    )

    ins_codes = [c["ins_code"] for c in calls]
    assert ins_codes == ["TEST-A", "TEST-B", "TEST-C"], (
        f"ins_code order must follow execution_order, got {ins_codes}"
    )

    for i, call in enumerate(calls):
        assert "broker" in call, f"call {i} missing broker"
        assert "broker_name" in call, f"call {i} missing broker_name"
        assert "ins_code" in call, f"call {i} missing ins_code"
        assert call["broker"] is not None, f"call {i} broker is None"
        assert call["broker_name"] is not None, f"call {i} broker_name is None"
        assert call["ins_code"] is not None, f"call {i} ins_code is None"
        assert call["live"] is False, f"call {i} live should be False"


# ============================================================
# Runner
# ============================================================


def main():
    tests = [
        ("test_aba_main_scenario", test_aba_main_scenario),
        ("test_order_independence", test_order_independence),
        ("test_unknown_broker_blocked", test_unknown_broker_blocked),
        ("test_route_mismatch_blocked", test_route_mismatch_blocked),
        ("test_missing_account_route_blocked", test_missing_account_route_blocked),
        ("test_broker_instance_independence", test_broker_instance_independence),
        ("test_order_specific_broker", test_order_specific_broker),
        ("test_no_fallback", test_no_fallback),
        ("test_spy_records_all_fields", test_spy_records_all_fields),
    ]

    for name, fn in tests:
        _run(name, fn)

    print()
    print("=" * 60)
    passed = sum(1 for _, s, _ in TEST_RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in TEST_RESULTS if s == "FAIL")
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    for name, status, msg in TEST_RESULTS:
        line = f"  [{status}] {name}"
        if msg:
            line += f"  -- {msg}"
        print(line)

    if failed:
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
