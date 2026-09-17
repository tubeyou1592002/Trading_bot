"""
Task 7.6 Layer 2 integration proof.

The tests use only offline Fake brokers, providers, accounts, and orders.
No production code is changed.
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
            name=f"{broker_name}:{symbol}",
            company_name=f"{broker_name} Co",
            nsc_id=resolved,
            tse_id=ins_code,
            minimum_order_quantity=1,
            lot_size=1,
            fixed_price_tick=1,
            lower_price_threshold=1,
            upper_price_threshold=1_000_000,
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


def build_plan(pairs, plan_id="plan-layer2", sequences=None):
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


@pytest.mark.parametrize("n", [1, 2, 10])
def test_foundation_n_brokers_n_accounts_n_orders(n):
    broker_names = [f"Broker-{index + 1}" for index in range(n)]
    account_ids = [f"ACC-{index + 1:03d}" for index in range(n)]
    brokers = [FakeBroker(name) for name in broker_names]
    manager = BrokerManager()
    broker_by_name = register_brokers(manager, broker_names, brokers)
    pairs = [
        (
            make_order(
                f"INS-{index + 1:03d}",
                side=BUY if index % 2 == 0 else SELL,
                price=100 + index * 10,
                quantity=10 + index,
            ),
            account_ids[index],
            broker_names[index],
        )
        for index in range(n)
    ]
    plan = build_plan(pairs, plan_id=f"foundation-{n}")
    accounts = [make_account(account_id) for account_id in account_ids]
    assert plan.accounts == account_ids
    attach_accounts(plan, accounts)
    expected_binding = {
        sequence: {
            "account_id": account_ids[index],
            "broker_name": broker_names[index],
        }
        for sequence, index in enumerate(range(n), start=1)
    }
    assert plan.conditions["binding"] == expected_binding

    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)

    assert_successful_dispatch(result, calls, n)
    for index, call in enumerate(calls):
        order, account_id, broker_name = pairs[index]
        assert call["sequence"] == index + 1
        assert call["binding"] == expected_binding[index + 1]
        assert call["broker"].name == broker_name
        assert call["provider"]._broker.name == broker_name
        assert call["account"].account_id == account_id
        assert call["order"] is order
        assert call["ins_code"] == order.nsc_id
        assert call["resolved_nsc_id"] == order.nsc_id
        assert call["live"] is False


def test_combined_10_brokers_20_accounts():
    broker_count = 10
    account_count = 20
    broker_names = [f"Broker-{index + 1}" for index in range(broker_count)]
    account_ids = [f"ACC-{index + 1:03d}" for index in range(account_count)]
    brokers = []
    for index, broker_name in enumerate(broker_names):
        mappings = {}
        if broker_name in {"Broker-1", "Broker-2"}:
            mappings["SHARED-001"] = make_instrument_pair(
                broker_name,
                "SHARED-001",
                resolved_nsc_id="SHARED-001",
                symbol="SHARED",
            )
        brokers.append(FakeBroker(broker_name, mappings=mappings))
    manager = BrokerManager()
    broker_by_name = register_brokers(manager, broker_names, brokers)
    accounts_by_id = {
        account_id: make_account(account_id) for account_id in account_ids
    }

    pairs = []
    for index, account_id in enumerate(account_ids):
        broker_name = broker_names[index % broker_count]
        if index == 0:
            symbols = ["SHARED-001", "SYM-21", "SYM-22"]
        elif index == 1:
            symbols = ["SHARED-001"]
        else:
            symbols = [f"SYM-{index + 1:02d}"]
        for symbol in symbols:
            pairs.append(
                (
                    make_order(
                        symbol,
                        side=BUY if index % 2 == 0 else SELL,
                        price=100 + index * 10 + len(pairs),
                        quantity=10 + index + len(pairs),
                    ),
                    account_id,
                    broker_name,
                )
            )

    plan = build_plan(pairs, plan_id="combined-10-20")
    attach_accounts(plan, accounts_by_id.values())
    expected_binding = {
        sequence: {
            "account_id": account_id,
            "broker_name": broker_name,
        }
        for sequence, (_, account_id, broker_name) in enumerate(
            pairs,
            start=1,
        )
    }
    assert len(plan.broker_names) == broker_count
    assert len(plan.accounts) == account_count
    assert len(plan.orders) == len(pairs)
    assert len(plan.execution_order) == len(pairs)
    assert plan.conditions["binding"] == expected_binding
    for sequence in plan.execution_order:
        binding = plan.conditions["binding"][sequence]
        assert binding["account_id"] in accounts_by_id
        assert binding["broker_name"] in broker_by_name

    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)

    assert_successful_dispatch(result, calls, len(pairs))
    for index, call in enumerate(calls):
        order, account_id, broker_name = pairs[index]
        assert call["sequence"] == index + 1
        assert call["binding"] == expected_binding[index + 1]
        assert call["broker"] is broker_by_name[broker_name]
        assert call["provider"] is manager.get_instrument_provider(broker_name)
        assert call["provider"]._broker is broker_by_name[broker_name]
        assert call["account"] is accounts_by_id[account_id]
        assert call["order"] is order
        assert call["ins_code"] == order.nsc_id
        expected_resolved_nsc_id = (
            "SHARED-001"
            if order.nsc_id == "SHARED-001"
            else order.nsc_id
        )
        assert call["resolved_nsc_id"] == expected_resolved_nsc_id
        assert call["live"] is False


def test_multiple_accounts_on_one_broker():
    broker = FakeBroker("Broker-A")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    accounts = [
        make_account("ACC-001"),
        make_account("ACC-002"),
        make_account("ACC-003"),
    ]
    orders = [
        make_order("SYM-A", side=BUY, price=100, quantity=10),
        make_order("SYM-B", side=SELL, price=200, quantity=20),
        make_order("SYM-C", side=BUY, price=300, quantity=30),
    ]
    pairs = [
        (orders[0], accounts[0].account_id, "Broker-A"),
        (orders[1], accounts[1].account_id, "Broker-A"),
        (orders[2], accounts[2].account_id, "Broker-A"),
    ]
    plan = build_plan(pairs, plan_id="shared-broker")
    attach_accounts(plan, accounts)
    provider = manager.get_instrument_provider("Broker-A")

    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)

    assert_successful_dispatch(result, calls, 3)
    for index, call in enumerate(calls):
        assert call["broker"] is broker
        assert call["provider"] is provider
        assert call["account"] is accounts[index]
        assert call["order"] is orders[index]


def test_one_account_multiple_orders():
    broker = FakeBroker("Broker-A")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    account = make_account("ACC-001")
    orders = [
        make_order("SYM-A", side=BUY, price=100, quantity=10),
        make_order("SYM-B", side=SELL, price=200, quantity=20),
        make_order("SYM-C", side=BUY, price=300, quantity=30),
    ]
    pairs = [(order, account.account_id, "Broker-A") for order in orders]
    plan = build_plan(pairs, plan_id="one-account")
    attach_accounts(plan, [account])

    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)

    assert_successful_dispatch(result, calls, len(orders))
    assert all(call["account"] is account for call in calls)
    assert [call["order"] for call in calls] == orders
    assert [call["ins_code"] for call in calls] == [
        order.nsc_id for order in orders
    ]


def test_same_symbol_multiple_brokers_mapping_isolation():
    broker_a = FakeBroker(
        "Broker-A",
        mappings={
            "TEST-001": make_instrument_pair(
                "Broker-A",
                "TEST-001",
                resolved_nsc_id="A-TEST-001",
                symbol="TEST",
            )
        },
    )
    broker_b = FakeBroker(
        "Broker-B",
        mappings={
            "TEST-001": make_instrument_pair(
                "Broker-B",
                "TEST-001",
                resolved_nsc_id="B-TEST-001",
                symbol="TEST",
            )
        },
    )
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A", "Broker-B"], [broker_a, broker_b])
    provider_a = manager.get_instrument_provider("Broker-A")
    provider_b = manager.get_instrument_provider("Broker-B")

    assert provider_a is not provider_b
    assert provider_a.get_instrument("TEST-001")[1].nsc_id == "A-TEST-001"
    assert provider_a.get_instrument("TEST-001")[1].tse_id == "TEST-001"
    assert provider_b.get_instrument("TEST-001")[1].nsc_id == "B-TEST-001"
    assert provider_b.get_instrument("TEST-001")[1].tse_id == "TEST-001"
    assert broker_a.instrument_mappings["TEST-001"][1].nsc_id == "A-TEST-001"
    assert broker_b.instrument_mappings["TEST-001"][1].nsc_id == "B-TEST-001"

    account_a = make_account("ACC-001")
    account_b = make_account("ACC-002")
    order_a = make_order("TEST-001", side=BUY, price=100, quantity=10)
    order_b = make_order("TEST-001", side=SELL, price=200, quantity=20)
    pairs = [
        (order_a, account_a.account_id, "Broker-A"),
        (order_b, account_b.account_id, "Broker-B"),
    ]
    plan = build_plan(pairs, plan_id="same-symbol")
    attach_accounts(plan, [account_a, account_b])

    core = DispatchCore(broker_manager=manager)
    result = core.dispatch(plan)

    assert result.success is False
    assert result.mode == "BLOCKED"
    assert broker_a.place_order_calls == []
    assert broker_b.place_order_calls == []


def test_broker_instance_identity_isolation():
    brokers = [FakeBroker(f"Broker-{index}") for index in range(3)]
    manager = BrokerManager()
    register_brokers(
        manager,
        ["Broker-1", "Broker-2", "Broker-3"],
        brokers,
    )
    assert brokers[0] is not brokers[1]
    assert brokers[1] is not brokers[2]
    assert brokers[0] is not brokers[2]
    assert manager.get("Broker-1") is brokers[0]
    assert manager.get("Broker-2") is brokers[1]
    assert manager.get("Broker-3") is brokers[2]


def test_account_instance_identity_isolation():
    accounts = [
        make_account("ACC-001"),
        make_account("ACC-002"),
        make_account("ACC-003"),
    ]
    assert len({account.account_id for account in accounts}) == len(accounts)
    assert accounts[0] is not accounts[1]
    assert accounts[1] is not accounts[2]
    assert accounts[0] is not accounts[2]


def test_order_instance_identity_isolation():
    broker = FakeBroker("Broker-A")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    account = make_account("ACC-001")
    orders = [
        make_order("SYM-A", side=BUY, price=100, quantity=10),
        make_order("SYM-B", side=SELL, price=200, quantity=20),
        make_order("SYM-C", side=BUY, price=300, quantity=30),
    ]
    assert orders[0] is not orders[1]
    assert orders[1] is not orders[2]
    assert orders[0] is not orders[2]
    plan = build_plan(
        [(order, account.account_id, "Broker-A") for order in orders],
        plan_id="order-identity",
    )
    attach_accounts(plan, [account])

    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)

    assert_successful_dispatch(result, calls, len(orders))
    assert [call["order"] for call in calls] == orders


def test_instrument_provider_instance_isolation():
    broker_a = FakeBroker(
        "Broker-A",
        mappings={
            "TEST-001": make_instrument_pair(
                "Broker-A",
                "TEST-001",
                resolved_nsc_id="A-TEST-001",
                symbol="TEST",
            )
        },
    )
    broker_b = FakeBroker(
        "Broker-B",
        mappings={
            "TEST-001": make_instrument_pair(
                "Broker-B",
                "TEST-001",
                resolved_nsc_id="B-TEST-001",
                symbol="TEST",
            )
        },
    )
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A", "Broker-B"], [broker_a, broker_b])
    provider_a = manager.get_instrument_provider("Broker-A")
    provider_b = manager.get_instrument_provider("Broker-B")
    assert provider_a is not provider_b
    assert manager.get_instrument_provider("Broker-A") is provider_a
    assert manager.get_instrument_provider("Broker-B") is provider_b
    assert provider_a.get_instrument("TEST-001")[1].nsc_id == "A-TEST-001"
    assert provider_b.get_instrument("TEST-001")[1].nsc_id == "B-TEST-001"


def test_quantity_isolation():
    broker = FakeBroker("Broker-A")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    account = make_account("ACC-001")
    orders = [
        make_order("SYM-A", side=BUY, price=100, quantity=10),
        make_order("SYM-B", side=BUY, price=100, quantity=20),
        make_order("SYM-C", side=BUY, price=100, quantity=30),
    ]
    plan = build_plan(
        [(order, account.account_id, "Broker-A") for order in orders],
        plan_id="quantity",
    )
    attach_accounts(plan, [account])
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert_successful_dispatch(result, calls, len(orders))
    assert [call["order"].quantity for call in calls] == [
        order.quantity for order in orders
    ]


def test_price_isolation():
    broker = FakeBroker("Broker-A")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    account = make_account("ACC-001")
    orders = [
        make_order("SYM-A", side=BUY, price=100, quantity=10),
        make_order("SYM-B", side=BUY, price=200, quantity=10),
        make_order("SYM-C", side=BUY, price=300, quantity=10),
    ]
    plan = build_plan(
        [(order, account.account_id, "Broker-A") for order in orders],
        plan_id="price",
    )
    attach_accounts(plan, [account])
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert_successful_dispatch(result, calls, len(orders))
    assert [call["order"].price for call in calls] == [
        order.price for order in orders
    ]


def test_side_isolation():
    broker = FakeBroker("Broker-A")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    account = make_account("ACC-001")
    orders = [
        make_order("SYM-A", side=BUY, price=100, quantity=10),
        make_order("SYM-B", side=SELL, price=200, quantity=10),
        make_order("SYM-C", side=BUY, price=300, quantity=10),
    ]
    plan = build_plan(
        [(order, account.account_id, "Broker-A") for order in orders],
        plan_id="side",
    )
    attach_accounts(plan, [account])
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert_successful_dispatch(result, calls, len(orders))
    assert [call["order"].side for call in calls] == [
        order.side for order in orders
    ]


def test_execution_sequence_preservation():
    broker = FakeBroker("Broker-A")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    account = make_account("ACC-001")
    order_1 = make_order("SEQ-1", side=BUY, price=100, quantity=10)
    order_2 = make_order("SEQ-2", side=SELL, price=200, quantity=20)
    order_3 = make_order("SEQ-3", side=BUY, price=300, quantity=30)
    pairs = [
        (order_3, account.account_id, "Broker-A"),
        (order_1, account.account_id, "Broker-A"),
        (order_2, account.account_id, "Broker-A"),
    ]
    plan = build_plan(
        pairs,
        plan_id="sequence",
        sequences=[3, 1, 2],
    )
    attach_accounts(plan, [account])
    assert plan.execution_order == [1, 2, 3]
    assert [order.nsc_id for order in plan.orders] == ["SEQ-1", "SEQ-2", "SEQ-3"]
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert_successful_dispatch(result, calls, 3)
    assert [call["order"].nsc_id for call in calls] == ["SEQ-1", "SEQ-2", "SEQ-3"]


def test_fail_closed_unknown_broker():
    broker = FakeBroker("Broker-A")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    account = make_account("ACC-001")
    order = make_order("SYM-A", side=BUY, price=100, quantity=10)
    plan = build_plan(
        [(order, account.account_id, "UnknownBroker")],
        plan_id="unknown-broker",
    )
    attach_accounts(plan, [account])
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert result.order_count == 0
    assert calls == []


def test_fail_closed_missing_account_binding():
    broker = FakeBroker("Broker-A")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    account = make_account("ACC-001")
    order = make_order("SYM-A", side=BUY, price=100, quantity=10)
    plan = build_plan(
        [(order, account.account_id, "Broker-A")],
        plan_id="missing-account",
    )
    attach_accounts(plan, [account])
    plan.conditions["binding"][1].pop("account_id")
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert result.order_count == 0
    assert calls == []


def test_fail_closed_missing_broker_binding():
    broker = FakeBroker("Broker-A")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    account = make_account("ACC-001")
    order = make_order("SYM-A", side=BUY, price=100, quantity=10)
    plan = build_plan(
        [(order, account.account_id, "Broker-A")],
        plan_id="missing-broker",
    )
    attach_accounts(plan, [account])
    plan.conditions["binding"][1].pop("broker_name")
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert result.order_count == 0
    assert calls == []


def test_fail_closed_conflicting_binding_rejected_by_planner():
    order_1 = make_order("SYM-A", side=BUY, price=100, quantity=10)
    order_2 = make_order("SYM-B", side=SELL, price=200, quantity=20)
    with pytest.raises(PlannerValidationError):
        build_plan(
            [
                (order_1, "ACC-001", "Broker-A"),
                (order_2, "ACC-001", "Broker-B"),
            ],
            plan_id="conflict-planner",
        )


def test_fail_closed_conflicting_binding_dispatch_blocked():
    broker_a = FakeBroker("Broker-A")
    broker_b = FakeBroker("Broker-B")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A", "Broker-B"], [broker_a, broker_b])
    account = make_account("ACC-001")
    order = make_order("SYM-A", side=BUY, price=100, quantity=10)
    plan = build_plan(
        [(order, account.account_id, "Broker-A")],
        plan_id="conflict-dispatch",
    )
    attach_accounts(plan, [account])
    plan.conditions["binding"][1]["broker_name"] = "Broker-B"
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert result.order_count == 0
    assert calls == []


def test_fail_closed_unknown_instrument():
    broker = FakeBroker(
        "Broker-A",
        unknown_instruments={"UNKNOWN-001"},
    )
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    account = make_account("ACC-001")
    order = make_order("UNKNOWN-001", side=BUY, price=100, quantity=10)
    plan = build_plan(
        [(order, account.account_id, "Broker-A")],
        plan_id="unknown-instrument",
    )
    attach_accounts(plan, [account])
    core = DispatchCore(broker_manager=manager)
    result = core.dispatch(plan)
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert result.order_count == 1
    assert broker.place_order_calls == []


def test_fail_closed_invalid_sequence_mapping():
    broker = FakeBroker("Broker-A")
    manager = BrokerManager()
    register_brokers(manager, ["Broker-A"], [broker])
    account = make_account("ACC-001")
    order = make_order("SYM-A", side=BUY, price=100, quantity=10)
    plan = build_plan(
        [(order, account.account_id, "Broker-A")],
        plan_id="invalid-sequence",
    )
    attach_accounts(plan, [account])
    plan.execution_order = [999]
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert result.order_count == 0
    assert calls == []


def test_zero_fallback_zero_cross_routing():
    brokers = [FakeBroker(f"Broker-{index}") for index in range(1, 4)]
    manager = BrokerManager()
    register_brokers(
        manager,
        ["Broker-1", "Broker-2", "Broker-3"],
        brokers,
    )
    accounts = [
        make_account("ACC-001"),
        make_account("ACC-002"),
        make_account("ACC-003"),
    ]
    orders = [
        make_order("SYM-A", side=BUY, price=100, quantity=10),
        make_order("SYM-B", side=SELL, price=200, quantity=20),
        make_order("SYM-C", side=BUY, price=300, quantity=30),
    ]
    pairs = [
        (orders[0], accounts[0].account_id, "Broker-1"),
        (orders[1], accounts[1].account_id, "Broker-2"),
        (orders[2], accounts[2].account_id, "Broker-3"),
    ]
    plan = build_plan(pairs, plan_id="zero-cross-routing")
    attach_accounts(plan, accounts)
    core = DispatchCore(broker_manager=manager)
    spy, calls = make_spy(plan)
    core.order_engine.execute_by_ins_code = spy
    result = core.dispatch(plan)
    assert_successful_dispatch(result, calls, len(pairs))
    for index, call in enumerate(calls):
        order, account_id, broker_name = pairs[index]
        assert call["broker"] is brokers[index]
        assert call["account"] is accounts[index]
        assert call["order"] is order
        assert call["broker_name"] == broker_name
        assert call["ins_code"] == order.nsc_id
