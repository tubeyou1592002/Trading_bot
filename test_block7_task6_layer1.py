"""
test_block7_task6_layer1.py — Task 7.6 Layer 1: N Account / N Broker Foundation Proof.

Proves that the current architecture:
- Supports N Brokers (not limited to 2).
- Supports N Accounts (not limited to 2).
- Preserves Account -> Broker binding via ExecutionPlan.
- Allows shared Brokers (multiple Accounts -> one Broker).
- Keeps Broker and Account identity independent.
- Fails closed for unknown broker, missing route, conflicting binding.

No production code is changed.
Only this file is created.

Run:
    python -m pytest test_block7_task6_layer1.py -q
    python -m pytest test_block7_task6_layer1.py test_block7_task5.py test_block7_task4.py test_broker_manager.py test_instrument_provider.py -q
"""

import pytest

from brokers.manager import BrokerManager
from core.dispatch_core import DispatchCore
from core.dispatch_contracts import BrokerDispatchRequest, DispatchResult, ExecutionPlan
from core.execution_planner import ExecutionPlanner, LogicalOrderInstruction, PlannedOrder
from core.order_engine import OrderExecutionResult
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, Order


# ============================================================
# Test Doubles (fully offline, deterministic, no network/API)
# ============================================================

class FakeBroker:
    """Offline fake broker — no network, no API, no credentials, no live trading."""

    def __init__(self, name: str):
        self.name = name
        self._instrument_cache = {}

    def login(self, username, password, **kwargs):
        return {"success": True, "username": username, "token": f"fake-token-{self.name}"}

    def get_account(self):
        return Account(account_id=f"ACC-default-{self.name}")

    def place_order(self, order, live=False):
        return {"mode": "DRY_RUN", "sent": False, "order_id": f"fake-order-{self.name}"}

    def cancel_order(self, order_id):
        return {"canceled": True, "order_id": order_id}


class FakeInstrumentProvider:
    """Offline provider for FakeBroker."""

    def __init__(self, broker: FakeBroker):
        self._broker = broker
        self._cache = {}

    def get_instrument(self, ins_code: str):
        if ins_code in self._cache:
            return self._cache[ins_code]
        instrument = Instrument(
            symbol=ins_code,
            name=f"{self._broker.name}-Instrument",
            ins_code=ins_code,
        )
        broker_instrument = BrokerInstrument(
            name=f"{self._broker.name}-Instrument",
            company_name=f"{self._broker.name} Co",
            nsc_id=ins_code,
            tse_id=ins_code,
        )
        result = (instrument, broker_instrument)
        self._cache[ins_code] = result
        return result


# ============================================================
# Helpers
# ============================================================

def make_order(nsc_id: str, side=BUY, price=150, quantity=10) -> Order:
    return Order(nsc_id=nsc_id, side=side, price=price, quantity=quantity)


def make_account(account_id: str, balance=1000000) -> Account:
    return Account(
        account_id=account_id,
        last_balance=balance,
        tradable_balance_t1=balance // 2,
        tradable_balance_t2=balance // 5,
    )


def make_spy():
    """Returns (spy function, spy_calls list)."""
    calls = []

    def spy(broker, provider, ins_code, order, account, live):
        calls.append({
            "broker": broker,
            "broker_name": getattr(broker, "name", None),
            "ins_code": ins_code,
            "order": order,
            "account": account,
            "live": live,
        })
        return OrderExecutionResult(
            success=True,
            sent=False,
            mode="READY",
            order=order,
            broker_name=getattr(broker, "name", None),
            message="READY",
        )

    return spy, calls


def build_plan_from_pairs(planner, pairs, plan_id="plan"):
    """
    Build an ExecutionPlan via real ExecutionPlanner.

    pairs: list of (order, account_id, broker_name)
    """
    planned_orders = [
        PlannedOrder(
            order=order,
            account_id=account_id,
            broker_name=broker_name,
            sequence=idx + 1,
        )
        for idx, (order, account_id, broker_name) in enumerate(pairs)
    ]
    plan = planner.build_plan(
        LogicalOrderInstruction(plan_id=plan_id, orders=planned_orders)
    )
    return plan


def attach_accounts(plan, accounts):
    """Attach Account objects to plan.accounts."""
    plan.accounts = list(accounts)
    return plan


def register_brokers(manager, broker_names, brokers):
    """Register brokers with FakeInstrumentProvider classes."""
    for name, broker in zip(broker_names, brokers):
        manager.register(name, broker, FakeInstrumentProvider)


# ============================================================
# Test — Foundation: Parameterized N Brokers / N Accounts
# ============================================================

@pytest.mark.parametrize("n", [1, 2, 10])
def test_foundation_n_brokers_n_accounts(n):
    """
    Foundation test for N Brokers and N Accounts.

    For N in [1, 2, 10]:
    - Create N Fake Brokers
    - Create N Account objects
    - Register brokers
    - Build plan: Account_i -> Broker_i
    - Verify account_routes and conditions["binding"]
    - Dispatch with spy and verify correct broker instance per order
    """
    broker_names = [f"Broker{i+1}" for i in range(n)]
    account_ids = [f"ACC-{i+1:03d}" for i in range(n)]

    brokers = [FakeBroker(name) for name in broker_names]
    accounts = [make_account(aid) for aid in account_ids]

    manager = BrokerManager()
    register_brokers(manager, broker_names, brokers)

    pairs = [
        (make_order(f"INS-{account_ids[i]}"), account_ids[i], broker_names[i])
        for i in range(n)
    ]
    planner = ExecutionPlanner()
    plan = build_plan_from_pairs(planner, pairs, plan_id="plan-foundation")
    attach_accounts(plan, accounts)

    # Verify account_routes: account_id -> broker_name
    for i in range(n):
        assert plan.account_routes[account_ids[i]] == broker_names[i], (
            f"account_routes[{account_ids[i]}] = {plan.account_routes.get(account_ids[i])}, "
            f"expected {broker_names[i]}"
        )

    # Verify conditions["binding"] matches account_routes
    for seq in plan.execution_order:
        binding = plan.conditions["binding"][seq]
        aid = binding["account_id"]
        bname = binding["broker_name"]
        assert plan.account_routes[aid] == bname, (
            f"binding[{seq}].broker_name={bname} != account_routes[{aid}]={plan.account_routes[aid]}"
        )

    # Dispatch and verify broker instances
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    result = core.dispatch(plan)

    assert result.success is True, f"dispatch failed: {result.message}"
    assert result.mode == "ALL_PROCESSED", f"mode={result.mode}"
    assert len(calls) == n, f"expected {n} calls, got {len(calls)}"

    # Each call must receive the correct broker INSTANCE
    for i, call in enumerate(calls):
        assert call["broker"] is brokers[i], (
            f"Order {i} expected Broker{i+1} instance, got {call['broker']}"
        )
        assert call["broker_name"] == broker_names[i]


# ============================================================
# Test — Main Scenario: 10 Brokers / 20 Accounts (Shared Brokers)
# ============================================================

def test_main_scenario_10_brokers_20_accounts():
    """
    Main scenario: 10 Brokers, 20 Accounts.

    Binding:
      Account1  -> Broker1
      Account2  -> Broker2
      ...
      Account10 -> Broker10
      Account11 -> Broker1
      Account12 -> Broker2
      ...
      Account20 -> Broker10
    """
    n_brokers = 10
    n_accounts = 20

    broker_names = [f"Broker{i+1}" for i in range(n_brokers)]
    account_ids = [f"ACC-{i+1:03d}" for i in range(n_accounts)]

    brokers = [FakeBroker(name) for name in broker_names]
    accounts = [make_account(aid) for aid in account_ids]

    manager = BrokerManager()
    register_brokers(manager, broker_names, brokers)

    pairs = []
    for i in range(n_accounts):
        account_id = account_ids[i]
        broker_name = broker_names[i % n_brokers]
        pairs.append((make_order(f"INS-{account_id}"), account_id, broker_name))

    planner = ExecutionPlanner()
    plan = build_plan_from_pairs(planner, pairs, plan_id="plan-main")
    attach_accounts(plan, accounts)

    # Verify all account_routes
    for i in range(n_accounts):
        expected_broker = broker_names[i % n_brokers]
        assert plan.account_routes[account_ids[i]] == expected_broker, (
            f"account_routes[{account_ids[i]}] = {plan.account_routes.get(account_ids[i])}, "
            f"expected {expected_broker}"
        )

    # Verify binding consistency
    for seq in plan.execution_order:
        binding = plan.conditions["binding"][seq]
        aid = binding["account_id"]
        bname = binding["broker_name"]
        assert plan.account_routes[aid] == bname

    # Dispatch with spy
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    result = core.dispatch(plan)

    assert result.success is True, f"dispatch failed: {result.message}"
    assert result.mode == "ALL_PROCESSED", f"mode={result.mode}"
    assert len(calls) == n_accounts, f"expected {n_accounts} calls, got {len(calls)}"

    # Verify each call went to correct broker instance
    for i, call in enumerate(calls):
        expected_broker = brokers[i % n_brokers]
        assert call["broker"] is expected_broker, (
            f"Order {i} expected {expected_broker.name} instance, got {call['broker']}"
        )
        assert call["broker_name"] == broker_names[i % n_brokers]


# ============================================================
# Test — Shared Broker: Multiple Accounts -> One Broker
# ============================================================

def test_shared_broker():
    """Multiple Accounts can share one Broker; Account identity remains independent."""
    broker = FakeBroker("Broker1")

    manager = BrokerManager()
    register_brokers(manager, ["Broker1"], [broker])

    account1 = make_account("ACC-001")
    account2 = make_account("ACC-002")
    account3 = make_account("ACC-003")

    pairs = [
        (make_order("INS-1"), "ACC-001", "Broker1"),
        (make_order("INS-2"), "ACC-002", "Broker1"),
        (make_order("INS-3"), "ACC-003", "Broker1"),
    ]

    planner = ExecutionPlanner()
    plan = build_plan_from_pairs(planner, pairs, plan_id="plan-shared")
    attach_accounts(plan, [account1, account2, account3])

    # All routes point to Broker1
    for aid in ["ACC-001", "ACC-002", "ACC-003"]:
        assert plan.account_routes[aid] == "Broker1"

    # Accounts are INDEPENDENT objects
    assert account1 is not account2
    assert account1 is not account3
    assert account2 is not account3
    assert account1.account_id != account2.account_id
    assert account1.account_id != account3.account_id
    assert account2.account_id != account3.account_id

    # Dispatch and verify all calls go to the SAME broker instance
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    result = core.dispatch(plan)

    assert result.success is True
    assert len(calls) == 3
    for call in calls:
        assert call["broker"] is broker, f"All orders must go to Broker1 instance, got {call['broker']}"


# ============================================================
# Test — Broker Instance Independence
# ============================================================

def test_broker_instance_independence():
    """Broker instances are independent; manager.get returns the registered instance."""
    brokers = [FakeBroker(f"Broker{i+1}") for i in range(3)]
    broker_names = [f"Broker{i+1}" for i in range(3)]

    manager = BrokerManager()
    register_brokers(manager, broker_names, brokers)

    # Broker instances are distinct
    assert brokers[0] is not brokers[1]
    assert brokers[1] is not brokers[2]
    assert brokers[0] is not brokers[2]

    # manager.get returns the SAME instance
    assert manager.get("Broker1") is brokers[0]
    assert manager.get("Broker2") is brokers[1]
    assert manager.get("Broker3") is brokers[2]

    # Build plan and dispatch
    accounts = [make_account(f"ACC-{i+1:03d}") for i in range(3)]
    pairs = [
        (make_order("INS-1"), "ACC-001", "Broker1"),
        (make_order("INS-2"), "ACC-002", "Broker2"),
        (make_order("INS-3"), "ACC-003", "Broker3"),
    ]

    planner = ExecutionPlanner()
    plan = build_plan_from_pairs(planner, pairs, plan_id="plan-independence")
    attach_accounts(plan, accounts)

    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    core.dispatch(plan)

    # Each order received the correct broker INSTANCE by identity
    assert calls[0]["broker"] is brokers[0]
    assert calls[1]["broker"] is brokers[1]
    assert calls[2]["broker"] is brokers[2]


# ============================================================
# Test — Account Identity
# ============================================================

def test_account_identity():
    """Account instances are independent; account_ids are unique."""
    n = 5
    accounts = [make_account(f"ACC-{i+1:03d}") for i in range(n)]

    # All account_ids unique
    ids = [a.account_id for a in accounts]
    assert len(ids) == len(set(ids)), f"Duplicate account_ids: {ids}"

    # All are distinct instances
    for i in range(n):
        for j in range(n):
            if i != j:
                assert accounts[i] is not accounts[j], f"Account {i} and {j} are same instance"
                assert accounts[i].account_id != accounts[j].account_id


# ============================================================
# Test — Fail-Closed: Unknown Broker
# ============================================================

def test_fail_closed_unknown_broker():
    """Unknown broker in account_routes -> BLOCKED, no fallback, no dispatch calls."""
    broker = FakeBroker("Broker1")
    manager = BrokerManager()
    register_brokers(manager, ["Broker1"], [broker])

    account1 = make_account("ACC-001")
    account2 = make_account("ACC-002")
    account3 = make_account("ACC-003")

    # Account3 -> UnknownBroker
    pairs = [
        (make_order("INS-1"), "ACC-001", "Broker1"),
        (make_order("INS-2"), "ACC-002", "Broker1"),
        (make_order("INS-3"), "ACC-003", "UnknownBroker"),
    ]

    planner = ExecutionPlanner()
    plan = build_plan_from_pairs(planner, pairs, plan_id="plan-unknown")
    attach_accounts(plan, [account1, account2, account3])

    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    result = core.dispatch(plan)

    assert result.success is False, "Unknown broker should fail"
    assert result.mode == "BLOCKED", f"mode={result.mode}"
    assert len(calls) == 0, f"No dispatch calls allowed, got {len(calls)}"

    # No fallback to Broker1, no default broker, no previous broker


# ============================================================
# Test — Fail-Closed: Missing Account Route
# ============================================================

def test_fail_closed_missing_account_route():
    """Missing account_routes entry -> BLOCKED, no other broker selected."""
    broker = FakeBroker("Broker1")
    manager = BrokerManager()
    register_brokers(manager, ["Broker1"], [broker])

    account1 = make_account("ACC-001")

    pairs = [
        (make_order("INS-1"), "ACC-001", "Broker1"),
    ]

    planner = ExecutionPlanner()
    plan = build_plan_from_pairs(planner, pairs, plan_id="plan-missing")
    attach_accounts(plan, [account1])

    # Remove the account route
    plan.account_routes = {}

    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    result = core.dispatch(plan)

    assert result.success is False, "Missing route should fail"
    assert result.mode == "BLOCKED", f"mode={result.mode}"
    assert len(calls) == 0, f"No dispatch calls allowed, got {len(calls)}"


# ============================================================
# Test — Fail-Closed: Conflicting Account Binding
# ============================================================

def test_fail_closed_conflicting_binding():
    """Same account bound to two different brokers -> BLOCKED (per Planner/DispatchCore contract)."""
    broker1 = FakeBroker("Broker1")
    broker2 = FakeBroker("Broker2")

    manager = BrokerManager()
    register_brokers(manager, ["Broker1", "Broker2"], [broker1, broker2])

    account1 = make_account("ACC-001")

    pairs = [
        (make_order("INS-1"), "ACC-001", "Broker1"),
    ]

    planner = ExecutionPlanner()
    plan = build_plan_from_pairs(planner, pairs, plan_id="plan-conflict")
    attach_accounts(plan, [account1])

    # Inject conflict: account_routes says Broker2, binding says Broker1
    plan.account_routes["ACC-001"] = "Broker2"

    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy()
    core.order_engine.execute_by_ins_code = spy

    result = core.dispatch(plan)

    assert result.success is False, "Conflicting binding should fail"
    assert result.mode == "BLOCKED", f"mode={result.mode}"
    assert len(calls) == 0, f"No dispatch calls allowed, got {len(calls)}"


# ============================================================
# Runner (for direct execution without pytest)
# ============================================================

if __name__ == "__main__":
    import sys
    import traceback

    TEST_RESULTS = []

    def run(name, fn):
        try:
            fn()
            TEST_RESULTS.append((name, "PASS", None))
        except Exception as exc:
            TEST_RESULTS.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))
            traceback.print_exc()

    # Run all tests manually for direct execution
    run("test_foundation_n_brokers_n_accounts[1]", lambda: test_foundation_n_brokers_n_accounts(1))
    run("test_foundation_n_brokers_n_accounts[2]", lambda: test_foundation_n_brokers_n_accounts(2))
    run("test_foundation_n_brokers_n_accounts[10]", lambda: test_foundation_n_brokers_n_accounts(10))
    run("test_main_scenario_10_brokers_20_accounts", test_main_scenario_10_brokers_20_accounts)
    run("test_shared_broker", test_shared_broker)
    run("test_broker_instance_independence", test_broker_instance_independence)
    run("test_account_identity", test_account_identity)
    run("test_fail_closed_unknown_broker", test_fail_closed_unknown_broker)
    run("test_fail_closed_missing_account_route", test_fail_closed_missing_account_route)
    run("test_fail_closed_conflicting_binding", test_fail_closed_conflicting_binding)

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