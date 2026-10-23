"""Offline integration coverage for per-QueueEntry scheduled destinations."""

from threading import RLock

from brokers.manager import BrokerManager
from core.simulation_harness import (
    SimulationBroker,
    SimulationInstrumentProvider,
    build_simulation_catalog,
)
from core.order_queue import OrderQueue
from models.order import SELL
from ui.schedule_dispatcher import DispatchTarget, PeriodicScheduleDispatcher
from ui.test_runner import TestRunner
from core.dispatch_core import DispatchCore
from core.block5_task4 import DispatchIntegration
from models.account import Account
from datetime import datetime, timezone


def _manager(names, accounts):
    manager = BrokerManager.__new__(BrokerManager)
    manager.brokers = {}
    manager.providers = {}
    manager._provider_classes = {}
    manager._broker_factories = {}
    manager.account_brokers = {}
    manager.account_providers = {}
    manager._account_lock = RLock()
    manager._account_provider_instances = []
    catalog = build_simulation_catalog(("I-A", "I-B", "I-C", "INS-SIM-1", "INS-SIM-2"))
    for name in names:
        broker = SimulationBroker(name, catalog)
        manager.brokers[name] = broker
        manager._provider_classes[name] = SimulationInstrumentProvider
    for account_id, broker_name, broker in accounts:
        manager.account_brokers[(account_id, broker_name)] = broker
        provider = SimulationInstrumentProvider(broker)
        manager.account_providers[(account_id, broker_name)] = provider
        manager._account_provider_instances.append(provider)
    return manager


def _run(entries, accounts, manager):
    core = DispatchCore(broker_manager=manager)
    runner = TestRunner(dispatch_core=core)
    plan, execution_id, result = runner.run(entries, account=accounts)
    return runner, plan, execution_id, result


def test_real_runner_routes_same_broker_accounts_by_their_own_account_id():
    from models.order import Order

    catalog = build_simulation_catalog(("INS-SIM-1", "INS-SIM-2"))
    broker_a1 = SimulationBroker("SIM", catalog)
    broker_a2 = SimulationBroker("SIM", catalog)
    manager = _manager(("SIM",), (("A1", "SIM", broker_a1), ("A2", "SIM", broker_a2)))
    queue = OrderQueue()
    queue.enqueue(Order(nsc_id="INS-SIM-1", side=SELL, price=10000, quantity=5), "A1", "SIM")
    queue.enqueue(Order(nsc_id="INS-SIM-2", side=SELL, price=10000, quantity=5), "A2", "SIM")
    entries = queue.list_pending()
    accounts = {"A1": Account(account_id="A1"), "A2": Account(account_id="A2")}

    runner, plan, _, result = _run(entries, accounts, manager)

    assert result.order_count == 2
    assert plan.conditions["binding"] == {
        0: {"account_id": "A1", "broker_name": "SIM"},
        1: {"account_id": "A2", "broker_name": "SIM"},
    }
    assert [order for order, _ in broker_a1.place_order_calls] == [entries[0].order]
    assert [order for order, _ in broker_a2.place_order_calls] == [entries[1].order]
    assert runner.last_order_results[0].order is entries[0].order
    assert runner.last_order_results[1].order is entries[1].order


def test_real_runner_routes_each_broker_and_active_selection_is_irrelevant():
    from models.order import Order

    catalog = build_simulation_catalog(("INS-SIM-1", "INS-SIM-2"))
    broker_a, broker_b = SimulationBroker("SIM-A", catalog), SimulationBroker("SIM-B", catalog)
    manager = _manager(("SIM-A", "SIM-B"),
                       (("A", "SIM-A", broker_a), ("B", "SIM-B", broker_b)))
    queue = OrderQueue()
    queue.enqueue(Order(nsc_id="INS-SIM-1", side=SELL, price=10000, quantity=5), "A", "SIM-A")
    queue.enqueue(Order(nsc_id="INS-SIM-2", side=SELL, price=10000, quantity=5), "B", "SIM-B")
    entries = queue.list_pending()

    _, plan, _, result = _run(entries, {"A": Account(account_id="A"), "B": Account(account_id="B")}, manager)

    assert result.success
    assert plan.account_routes == {"A": "SIM-A", "B": "SIM-B"}
    assert [o for o, _ in broker_a.place_order_calls] == [entries[0].order]
    assert [o for o, _ in broker_b.place_order_calls] == [entries[1].order]
    assert broker_a.live_trading_enabled is False and broker_b.live_trading_enabled is False


def test_dispatcher_fans_out_all_groups_before_waiting_for_slow_response():
    from models.order import Order
    import threading

    entered = {"A": threading.Event(), "B": threading.Event()}
    release = threading.Event()
    accounts = {"A": Account(account_id="A"), "B": Account(account_id="B")}
    queue = OrderQueue()
    queue.enqueue(Order(nsc_id="I-A", side=SELL, price=100, quantity=1), "A", "SIM-A")
    queue.enqueue(Order(nsc_id="I-B", side=SELL, price=100, quantity=1), "B", "SIM-B")
    entries = queue.list_pending()

    class Runner:
        def __init__(self):
            self.core = None
        def run(self, group, account):
            key = group[0].account_id
            entered[key].set()
            if key == "A":
                assert release.wait(2)
            return None, key, type("Result", (), {"success": True, "message": "ok", "trace_id": key})()

    dispatcher = PeriodicScheduleDispatcher(Runner)
    now = datetime.now(timezone.utc)
    targets = tuple(DispatchTarget(e, e.account_id, e.broker_name, accounts[e.account_id]) for e in entries)
    dispatcher.freeze(targets, 10, now, __import__("time").monotonic())
    worker = threading.Thread(target=lambda: dispatcher.service_due_turn(dispatcher.mono_now(), 0))
    worker.start()
    assert entered["A"].wait(1)
    assert entered["B"].wait(1)
    release.set()
    worker.join(2)
    assert not worker.is_alive()
