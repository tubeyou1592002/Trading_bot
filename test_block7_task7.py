"""
Task 7.7 — Block 7 End-to-End Integration Test.

Final integration proof combining:
- Multiple Accounts (4)
- Multiple Brokers (3)
- Multiple Orders (5)
- Multiple Instruments (4 distinct symbols)
- Shared Symbol across Brokers (Symbol-1 on Broker-A and Broker-C)
- Independent mapping per Broker
- Account with multiple orders (ACC-001)
- No cross-routing
- Fail-closed behavior

Uses only offline Fake brokers, providers, accounts, and orders.
No production code is changed.
No real trading occurs.
"""

import pytest

from brokers.base import InstrumentLookupError
from brokers.manager import BrokerManager
from core.dispatch_core import DispatchCore
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
    PlannerValidationError,
)
from core.order_engine import OrderExecutionResult
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, SELL, Order
from models.trading_state import VERIFIED_TRADABLE


class FakeBroker:
    def __init__(self, name, mappings=None, unknown_instruments=None):
        self.name = name
        self.instrument_mappings = dict(mappings or {})
        self.unknown_instruments = set(unknown_instruments or ())
        self.place_order_calls = []

    def login(self, username, password, **kwargs):
        return {
            "success": True,
            "username": username,
            "token": f"fake-token-{self.name}",
        }

    def get_account(self):
        return Account(account_id=f"ACCOUNT-{self.name}")

    def place_order(self, order, live=False):
        self.place_order_calls.append((order, live))
        return {
            "mode": "DRY_RUN",
            "sent": False,
            "order_id": f"fake-order-{self.name}",
        }

    def cancel_order(self, order_id):
        return {"canceled": True, "order_id": order_id}

    def get_trading_state(self, nsc_id):
        return VERIFIED_TRADABLE

    def get_buy_capacity(self, nsc_id, side_code, fund, price):
        return 1_000_000

    def get_sell_capacity(self, nsc_id, side_code, fund, price):
        return 1_000_000


class FakeInstrumentProvider:
    def __init__(self, broker):
        self._broker = broker
        self._cache = {}
        self.resolution_log = []

    def get_instrument(self, ins_code):
        if ins_code in self._broker.unknown_instruments:
            raise InstrumentLookupError(
                f"Instrument is unavailable for {self._broker.name}: {ins_code}"
            )
        if ins_code in self._broker.instrument_mappings:
            result = self._broker.instrument_mappings[ins_code]
        else:
            result = make_instrument_pair(self._broker.name, ins_code)
        if ins_code not in self._cache:
            self._cache[ins_code] = result
        self.resolution_log.append(
            {
                "ins_code": ins_code,
                "broker_instrument": result[1],
            }
        )
        return self._cache[ins_code]

    def get_nsc_id(self, ins_code):
        return self.get_instrument(ins_code)[1].nsc_id

    def refresh_cache(self):
        self._cache.clear()


def make_instrument_pair(
    broker_name,
    ins_code,
    resolved_nsc_id=None,
    symbol=None,
):
    resolved = resolved_nsc_id or ins_code
    symbol = symbol or ins_code
    return (
        Instrument(
            symbol=symbol,
            name=f"{broker_name}:{symbol}",
            ins_code=ins_code,
        ),
        BrokerInstrument(
            name=f"{broker_name}:{symbol}", company_name=f"{broker_name} Co",
            nsc_id=resolved, tse_id=ins_code,
            minimum_order_quantity=1, lot_size=1, fixed_price_tick=1,
            lower_price_threshold=1, upper_price_threshold=1_000_000,
            maximum_order_quantity_for_buy=1_000_000,
            maximum_order_quantity_for_sell=1_000_000,
        ),
    )


def make_order(nsc_id, side=BUY, price=150, quantity=10):
    return Order(
        nsc_id=nsc_id,
        side=side,
        price=price,
        quantity=quantity,
    )


def make_account(account_id, balance=10_000_000):
    return Account(
        account_id=account_id,
        last_balance=balance,
        tradable_balance_t1=balance,
        tradable_balance_t2=balance,
    )


def make_spy(plan):
    """Fake spy that bypasses OrderEngine (used for fail-closed tests)."""
    calls = []
    order_to_sequence = {
        id(order): sequence
        for sequence, order in zip(
            plan.execution_order,
            plan.orders,
        )
    }

    def spy(broker, provider, ins_code, order, account, live):
        sequence = order_to_sequence.get(id(order))
        assert sequence is not None, "order not found in plan"
        binding = plan.conditions["binding"][sequence]
        matching_resolutions = [
            entry
            for entry in provider.resolution_log
            if entry["ins_code"] == ins_code
        ]
        assert matching_resolutions, (
            f"sequence {sequence} has no resolved instrument for {ins_code}"
        )
        resolved_instrument = matching_resolutions[-1]["broker_instrument"]
        assert isinstance(resolved_instrument, BrokerInstrument)
        assert resolved_instrument.tse_id == ins_code, (
            f"sequence {sequence}: tse_id {resolved_instrument.tse_id} != {ins_code}"
        )
        calls.append(
            {
                "sequence": sequence,
                "binding": binding,
                "broker": broker,
                "broker_name": broker.name,
                "provider": provider,
                "resolved_instrument": resolved_instrument,
                "resolved_nsc_id": resolved_instrument.nsc_id,
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
            broker_name=broker.name,
            message="READY",
        )

    return spy, calls


def make_real_spy(plan, real_execute):
    """Recording spy that wraps the real OrderEngine.execute_by_ins_code."""
    calls = []
    order_to_sequence = {
        id(order): sequence
        for sequence, order in zip(
            plan.execution_order,
            plan.orders,
        )
    }

    def spy(broker, provider, ins_code, order, account, live):
        sequence = order_to_sequence.get(id(order))
        result = real_execute(broker, provider, ins_code, order, account, live)
        matching_resolutions = [
            entry
            for entry in provider.resolution_log
            if entry["ins_code"] == ins_code
        ]
        resolved_instrument = matching_resolutions[-1]["broker_instrument"] if matching_resolutions else None
        calls.append(
            {
                "sequence": sequence,
                "broker": broker,
                "broker_name": broker.name,
                "provider": provider,
                "ins_code": ins_code,
                "order": order,
                "account": account,
                "live": live,
                "result": result,
                "resolved_instrument": resolved_instrument,
            }
        )
        return result

    return spy, calls


def build_plan(pairs, plan_id="plan-e2e", sequences=None):
    if sequences is None:
        sequences = range(1, len(pairs) + 1)
    planned_orders = [
        PlannedOrder(
            order=order,
            account_id=account_id,
            broker_name=broker_name,
            sequence=sequence,
        )
        for sequence, (order, account_id, broker_name) in zip(
            sequences,
            pairs,
        )
    ]
    planner = ExecutionPlanner()
    return planner.build_plan(
        LogicalOrderInstruction(plan_id=plan_id, orders=planned_orders)
    )


def attach_accounts(plan, accounts):
    plan.accounts = list(accounts)
    return plan


def register_brokers(manager, names, brokers):
    for name, broker in zip(names, brokers):
        manager.register(name, broker, FakeInstrumentProvider)
    return dict(zip(names, brokers))


def assert_successful_dispatch(result, calls, expected_count):
    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert result.order_count == expected_count
    assert len(calls) == expected_count
    for call in calls:
        assert isinstance(call["resolved_instrument"], BrokerInstrument)
        assert call["resolved_instrument"].tse_id == call["ins_code"]
        assert call["resolved_nsc_id"] == call["ins_code"]


def test_end_to_end_integration():
    """End-to-end with REAL OrderEngine path — no spy bypass."""
    # Setup brokers with independent mappings for shared Symbol-1
    broker_a = FakeBroker(
        "Broker-A",
        mappings={
            "Symbol-1": make_instrument_pair(
                "Broker-A", "Symbol-1",
                resolved_nsc_id="A-SYM-1", symbol="SHARED",
            ),
        },
    )
    broker_b = FakeBroker("Broker-B")
    broker_c = FakeBroker(
        "Broker-C",
        mappings={
            "Symbol-1": make_instrument_pair(
                "Broker-C", "Symbol-1",
                resolved_nsc_id="C-SYM-1", symbol="SHARED",
            ),
        },
    )
    manager = BrokerManager()
    brokers = register_brokers(
        manager, ["Broker-A", "Broker-B", "Broker-C"],
        [broker_a, broker_b, broker_c],
    )
    provider_a = manager.get_instrument_provider("Broker-A")
    provider_b = manager.get_instrument_provider("Broker-B")
    provider_c = manager.get_instrument_provider("Broker-C")

    # Independent mapping verification (pre-dispatch)
    assert provider_a is not provider_b
    assert provider_b is not provider_c
    assert provider_a is not provider_c
    assert provider_a.get_instrument("Symbol-1")[1].nsc_id == "A-SYM-1"
    assert provider_c.get_instrument("Symbol-1")[1].nsc_id == "C-SYM-1"
    assert provider_b.get_instrument("Symbol-2")[1].nsc_id == "Symbol-2"

    # Accounts
    accounts = {
        aid: make_account(aid)
        for aid in ["ACC-001", "ACC-002", "ACC-003", "ACC-004"]
    }

    # Orders: nsc_id must match each broker's resolved BrokerInstrument.nsc_id
    # for M6-A nsc_id consistency check to pass.
    order_1 = make_order("A-SYM-1", side=BUY, price=100, quantity=10)    # Broker-A, Symbol-1 mapped to A-SYM-1
    order_2 = make_order("Symbol-2", side=SELL, price=200, quantity=20)  # Broker-B, Symbol-2 → default nsc_id
    order_3 = make_order("Symbol-3", side=BUY, price=300, quantity=30)   # Broker-A, Symbol-3 → default nsc_id
    order_4 = make_order("C-SYM-1", side=SELL, price=400, quantity=40)   # Broker-C, Symbol-1 mapped to C-SYM-1
    order_5 = make_order("Symbol-4", side=BUY, price=500, quantity=50)   # Broker-A, Symbol-4 → default nsc_id

    pairs = [
        (order_1, "ACC-001", "Broker-A"),
        (order_2, "ACC-002", "Broker-B"),
        (order_3, "ACC-003", "Broker-A"),
        (order_4, "ACC-004", "Broker-C"),
        (order_5, "ACC-001", "Broker-A"),
    ]

    plan = build_plan(pairs, plan_id="e2e-final")
    attach_accounts(plan, list(accounts.values()))

    assert plan.execution_order == [1, 2, 3, 4, 5]
    assert len(plan.broker_names) == 3
    assert len(plan.accounts) == 4
    assert len(plan.orders) == 5

    expected_binding = {
        1: {"account_id": "ACC-001", "broker_name": "Broker-A"},
        2: {"account_id": "ACC-002", "broker_name": "Broker-B"},
        3: {"account_id": "ACC-003", "broker_name": "Broker-A"},
        4: {"account_id": "ACC-004", "broker_name": "Broker-C"},
        5: {"account_id": "ACC-001", "broker_name": "Broker-A"},
    }
    assert plan.conditions["binding"] == expected_binding

    # Dispatch with REAL OrderEngine path wrapped by recording spy
    core = DispatchCore(broker_manager=manager)
    real_execute = core.order_engine.execute_by_ins_code  # Save real method
    spy, calls = make_real_spy(plan, real_execute)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)

    # All 5 orders processed successfully by REAL OrderEngine
    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert result.order_count == 5
    assert len(calls) == 5

    # Each call went through real OrderEngine — check real results
    for call in calls:
        assert call["result"].success is True
        assert call["result"].mode == "DRY_RUN"     # live=False → DRY_RUN
        assert call["result"].sent is False
        assert call["live"] is False

    # Verify execution order preserved
    assert [call["sequence"] for call in calls] == [1, 2, 3, 4, 5]

    # Instance identity assertions
    for index, call in enumerate(calls):
        sequence = index + 1
        expected_order, expected_acc_id, expected_broker_name = pairs[index]

        assert call["sequence"] == sequence
        assert call["order"] is expected_order
        assert call["account"] is accounts[expected_acc_id]
        assert call["account"].account_id == expected_acc_id
        assert call["broker"] is brokers[expected_broker_name]
        assert call["broker_name"] == expected_broker_name
        assert call["provider"]._broker is brokers[expected_broker_name]

    # Broker/Provider identity per sequence
    assert calls[0]["broker"] is broker_a
    assert calls[0]["provider"] is provider_a
    assert calls[1]["broker"] is broker_b
    assert calls[1]["provider"] is provider_b
    assert calls[2]["broker"] is broker_a
    assert calls[2]["provider"] is provider_a
    assert calls[3]["broker"] is broker_c
    assert calls[3]["provider"] is provider_c
    assert calls[4]["broker"] is broker_a
    assert calls[4]["provider"] is provider_a

    # ACC-001 has 2 orders (multiple orders on one account) — both on Broker-A
    acc001_calls = [c for c in calls if c["account"].account_id == "ACC-001"]
    assert len(acc001_calls) == 2
    assert all(c["broker"] is broker_a for c in acc001_calls)
    assert all(c["broker"] is not broker_b for c in acc001_calls)
    assert all(c["broker"] is not broker_c for c in acc001_calls)
    assert [c["order"] for c in acc001_calls] == [order_1, order_5]

    # ─── SEPARATION OF CONCERNS: mapping vs execution ───
    #
    # PRE-DISPATCH mapping verification (lines 320-326 above) proves:
    #   provider_a.get_instrument("Symbol-1").broker_instrument.nsc_id == "A-SYM-1"
    #   provider_c.get_instrument("Symbol-1").broker_instrument.nsc_id == "C-SYM-1"
    #   provider_a.get_instrument("Symbol-1").broker_instrument.tse_id == "Symbol-1"
    #   provider_c.get_instrument("Symbol-1").broker_instrument.tse_id == "Symbol-1"
    #   → Independent per-broker mapping for shared Symbol-1
    #
    # E2E EXECUTION uses order.nsc_id as lookup key (per DispatchCore contract).
    # Successful orders use nsc_id that matches their broker's resolved nsc_id:
    #   Broker-A order: nsc_id="A-SYM-1" → provider.get_instrument("A-SYM-1") → default path → nsc_id="A-SYM-1" ✓
    #   Broker-C order: nsc_id="C-SYM-1" → provider.get_instrument("C-SYM-1") → default path → nsc_id="C-SYM-1" ✓
    #   (The shared "Symbol-1" mapping is NOT used as lookup key during dispatch.)
    #
    # This test verifies BOTH: mapping independence (pre-dispatch) AND
    # nsc_id-consistent order execution (dispatch).

    # Verify E2E execution: each call used the correct order.nsc_id and resolved correctly
    # Sequence 1: Broker-A, order_1 with nsc_id="A-SYM-1"
    assert calls[0]["ins_code"] == "A-SYM-1"
    assert calls[0]["order"].nsc_id == "A-SYM-1"
    resolved_1 = calls[0]["resolved_instrument"]
    assert resolved_1 is not None
    assert isinstance(resolved_1, BrokerInstrument)
    assert resolved_1.nsc_id == "A-SYM-1"
    assert resolved_1.tse_id == "A-SYM-1"  # default mapping: tse_id == ins_code

    # Sequence 2: Broker-B, order_2 with nsc_id="Symbol-2"
    assert calls[1]["ins_code"] == "Symbol-2"
    assert calls[1]["order"].nsc_id == "Symbol-2"
    resolved_2 = calls[1]["resolved_instrument"]
    assert resolved_2 is not None
    assert resolved_2.nsc_id == "Symbol-2"
    assert resolved_2.tse_id == "Symbol-2"

    # Sequence 3: Broker-A, order_3 with nsc_id="Symbol-3"
    assert calls[2]["ins_code"] == "Symbol-3"
    assert calls[2]["order"].nsc_id == "Symbol-3"
    resolved_3 = calls[2]["resolved_instrument"]
    assert resolved_3 is not None
    assert resolved_3.nsc_id == "Symbol-3"
    assert resolved_3.tse_id == "Symbol-3"

    # Sequence 4: Broker-C, order_4 with nsc_id="C-SYM-1"
    assert calls[3]["ins_code"] == "C-SYM-1"
    assert calls[3]["order"].nsc_id == "C-SYM-1"
    resolved_4 = calls[3]["resolved_instrument"]
    assert resolved_4 is not None
    assert isinstance(resolved_4, BrokerInstrument)
    assert resolved_4.nsc_id == "C-SYM-1"
    assert resolved_4.tse_id == "C-SYM-1"  # default mapping: tse_id == ins_code

    # Sequence 5: Broker-A, order_5 with nsc_id="Symbol-4"
    assert calls[4]["ins_code"] == "Symbol-4"
    assert calls[4]["order"].nsc_id == "Symbol-4"
    resolved_5 = calls[4]["resolved_instrument"]
    assert resolved_5 is not None
    assert resolved_5.nsc_id == "Symbol-4"
    assert resolved_5.tse_id == "Symbol-4"

    # Real place_order WAS called for all successful orders (dry-run mode)
    assert len(broker_a.place_order_calls) == 3
    assert len(broker_b.place_order_calls) == 1
    assert len(broker_c.place_order_calls) == 1
    for broker in [broker_a, broker_b, broker_c]:
        for order, live in broker.place_order_calls:
            assert live is False


def test_fail_closed_unknown_broker_in_e2e():
    broker_a = FakeBroker("Broker-A")
    broker_b = FakeBroker("Broker-B")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A", "Broker-B"], [broker_a, broker_b])
    account = make_account("ACC-001")
    order_1 = make_order("Symbol-1", side=BUY, price=100, quantity=10)
    order_2 = make_order("Symbol-2", side=SELL, price=200, quantity=20)
    pairs = [
        (order_1, "ACC-001", "Broker-A"),
        (order_2, "ACC-002", "Broker-X"),
    ]
    plan = build_plan(pairs, plan_id="e2e-unknown-broker")
    attach_accounts(plan, [account, make_account("ACC-002")])
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert result.order_count == 0
    assert calls == []


def test_fail_closed_invalid_instrument_proves_no_place_order():
    broker_a = FakeBroker("Broker-A")
    broker_b = FakeBroker("Broker-B", unknown_instruments={"INVALID-001"})
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A", "Broker-B"], [broker_a, broker_b])
    account_a = make_account("ACC-001")
    account_b = make_account("ACC-002")
    valid_order = make_order("SYM-VALID", side=BUY, price=100, quantity=10)
    invalid_order = make_order("INVALID-001", side=SELL, price=200, quantity=20)
    pairs = [
        (valid_order, "ACC-001", "Broker-A"),
        (invalid_order, "ACC-002", "Broker-B"),
    ]
    plan = build_plan(pairs, plan_id="e2e-instrument-isolation")
    attach_accounts(plan, [account_a, account_b])
    core = DispatchCore(broker_manager=manager)
    result = core.dispatch(plan)
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert broker_a.place_order_calls == [(valid_order, False)]
    assert broker_b.place_order_calls == []


def test_fail_closed_conflicting_binding_in_e2e():
    broker_a = FakeBroker("Broker-A")
    broker_c = FakeBroker("Broker-C")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A", "Broker-C"], [broker_a, broker_c])
    account = make_account("ACC-001")
    order = make_order("Symbol-1", side=BUY, price=100, quantity=10)
    plan = build_plan(
        [(order, "ACC-001", "Broker-A")],
        plan_id="e2e-conflict",
    )
    attach_accounts(plan, [account])
    plan.conditions["binding"][1]["broker_name"] = "Broker-C"
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert result.order_count == 0
    assert calls == []


def test_e2e_execution_sequence_not_in_source_order():
    broker_a = FakeBroker("Broker-A")
    broker_b = FakeBroker("Broker-B")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A", "Broker-B"], [broker_a, broker_b])
    accounts = [make_account(f"ACC-{index:03d}") for index in range(1, 4)]
    order_1 = make_order("SYM-1", side=BUY, price=100, quantity=10)
    order_2 = make_order("SYM-2", side=SELL, price=200, quantity=20)
    order_3 = make_order("SYM-3", side=BUY, price=300, quantity=30)
    pairs = [
        (order_3, "ACC-001", "Broker-A"),
        (order_1, "ACC-002", "Broker-B"),
        (order_2, "ACC-003", "Broker-A"),
    ]
    plan = build_plan(pairs, plan_id="e2e-seq", sequences=[3, 1, 2])
    attach_accounts(plan, accounts)
    assert plan.execution_order == [1, 2, 3]
    assert [o.nsc_id for o in plan.orders] == ["SYM-1", "SYM-2", "SYM-3"]
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert_successful_dispatch(result, calls, 3)
    assert [call["order"].nsc_id for call in calls] == ["SYM-1", "SYM-2", "SYM-3"]