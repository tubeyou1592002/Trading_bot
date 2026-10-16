"""Offline tests for account-bound trading-state and instrument reads."""

from types import SimpleNamespace
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from brokers.manager import BrokerManager
from models.instrument import Instrument
from models.order import BUY
from models.trading_state import VERIFIED_TRADABLE
from ui.account_store import AccountStore
from ui.main_window import MainWindow
from ui.order_configuration_page import OrderConfigurationPage
from core.order_queue import OrderQueue


BROKER = "آگاه"
ACCOUNT_A = "READ-A"
ACCOUNT_B = "READ-B"
INS_CODE = "shared-ins-code"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_shared_manager_resolves_independent_runtime_per_account(monkeypatch):
    from brokers import manager as manager_module

    real_manager_class = BrokerManager
    created = []

    class FakeBroker:
        name = BROKER

        def login(self, *args, **kwargs): pass
        def get_instrument(self, nsc_id): return None
        def get_account(self): return None
        def place_order(self, *args, **kwargs): pass
        def cancel_order(self, *args, **kwargs): pass
        def get_trading_state(self, nsc_id):
            self.last_nsc_id = nsc_id
            return VERIFIED_TRADABLE
        def get_buy_capacity(self, *args, **kwargs): pass
        def get_sell_capacity(self, *args, **kwargs): pass

        def __init__(self):
            self.session = object()
            self.account_id = None

    class FakeProvider:
        def __init__(self, broker):
            self._broker = broker
            self.cache = {}

        def get_instrument(self, ins_code):
            self.cache[ins_code] = self._broker.account_id
            return object(), SimpleNamespace(nsc_id=f"nsc-{self._broker.account_id}")

        def get_nsc_id(self, ins_code):
            self.cache[ins_code] = self._broker.account_id
            return f"nsc-{self._broker.account_id}"

        def refresh_cache(self): pass

    class RuntimeManager(real_manager_class):
        def __init__(self):
            self.brokers = {BROKER: FakeBroker()}
            self.providers = {}
            self._provider_classes = {BROKER: FakeProvider}
            self._broker_factories = {BROKER: FakeBroker}
            self.account_brokers = {}
            self.account_providers = {}
            self._account_lock = __import__("threading").RLock()
            self._account_provider_instances = []

        def get_for_account(self, account_id, broker_name):
            key = (account_id, broker_name)
            if key not in self.account_brokers:
                broker = FakeBroker()
                broker.account_id = account_id
                self.account_brokers[key] = broker
            return self.account_brokers[key]

    monkeypatch.setattr(manager_module, "BrokerManager", RuntimeManager)
    window = MainWindow.__new__(MainWindow)
    store = AccountStore()
    window.account_store = store
    window._broker_manager_cache = None
    store.add(ACCOUNT_A, BROKER, "A")
    store.add(ACCOUNT_B, BROKER, "B")
    store.set_active(ACCOUNT_A)
    manager = window._shared_broker_manager()

    query_a = window._real_trading_state_query(ACCOUNT_A, BROKER)
    provider_a = window._real_order_identity_resolver(ACCOUNT_A, BROKER)
    store.set_active(ACCOUNT_B)
    query_b = window._real_trading_state_query(ACCOUNT_B, BROKER)
    provider_b = window._real_order_identity_resolver(ACCOUNT_B, BROKER)

    broker_a = manager.get_for_account(ACCOUNT_A, BROKER)
    broker_b = manager.get_for_account(ACCOUNT_B, BROKER)
    assert broker_a is not broker_b
    assert broker_a.session is not broker_b.session
    assert provider_a is not provider_b
    assert provider_a._broker is broker_a
    assert provider_b._broker is broker_b
    assert query_a.get_trading_state(INS_CODE) is VERIFIED_TRADABLE
    assert query_b.get_trading_state(INS_CODE) is VERIFIED_TRADABLE
    assert broker_a.last_nsc_id == f"nsc-{ACCOUNT_A}"
    assert broker_b.last_nsc_id == f"nsc-{ACCOUNT_B}"
    assert provider_a.get_nsc_id(INS_CODE) == f"nsc-{ACCOUNT_A}"
    assert provider_b.get_nsc_id(INS_CODE) == f"nsc-{ACCOUNT_B}"
    assert manager.get_for_account(ACCOUNT_A, BROKER) is broker_a
    assert manager.get_instrument_provider_for_account(ACCOUNT_A, BROKER) is provider_a


def test_read_result_scope_rejects_late_same_broker_same_symbol_result(qapp):
    store = AccountStore()
    store.add(ACCOUNT_A, BROKER, "A")
    store.add(ACCOUNT_B, BROKER, "B")
    store.set_active(ACCOUNT_A)
    page = OrderConfigurationPage(store, order_queue=OrderQueue())
    instrument = Instrument(
        ins_code=INS_CODE, symbol="SYM", name="Symbol", market="TSE"
    )
    page.config.select_instrument(instrument)
    scope_a = (ACCOUNT_A, BROKER, INS_CODE)
    page._trading_state_instrument = INS_CODE
    page._trading_state_account_scope = scope_a
    page._order_identity_instrument = INS_CODE
    page._order_identity_broker = BROKER
    page._order_identity_account = ACCOUNT_A
    page._order_identity_scope = scope_a

    store.set_active(ACCOUNT_B)
    page._on_trading_state_succeeded(scope_a, INS_CODE, object())
    page._on_order_identity_succeeded(scope_a, INS_CODE, "stale-nsc-id")
    assert page._trading_state_shown is None
    assert page._order_nsc_id is None

    page.config.set_side(BUY)
    page.config.set_price(100)
    page.config.set_quantity(1)
    assert page._on_add_to_queue() is False
    assert page.order_queue.list_pending() == []
    page.close()


def _active_window_with_fake_runtime(store_accounts=((ACCOUNT_A, BROKER), (ACCOUNT_B, BROKER))):
    window = MainWindow()
    for account_id, broker_name in store_accounts:
        window.account_store.add(account_id, broker_name, account_id)

    class FakeBroker:
        name = BROKER

        def __init__(self, account_id):
            self.account_id = account_id
            self.session = object()
            self.state_calls = []

        def get_trading_state(self, nsc_id):
            self.state_calls.append(nsc_id)
            return VERIFIED_TRADABLE

    class FakeProvider:
        def __init__(self, account_id, broker):
            self.account_id = account_id
            self._broker = broker
            self.identity_calls = []
            self.instrument_calls = []
            self.identity_gate = None
            self.instrument_gate = None

        def get_nsc_id(self, ins_code):
            self.identity_calls.append(ins_code)
            if self.identity_gate is not None:
                self.identity_gate.wait(timeout=5)
            return f"nsc-{self.account_id}"

        def get_instrument(self, ins_code):
            self.instrument_calls.append(ins_code)
            if self.instrument_gate is not None:
                self.instrument_gate.wait(timeout=5)
            return object(), SimpleNamespace(nsc_id=f"nsc-{self.account_id}")

        def refresh_cache(self):
            pass

    class SharedManager:
        def __init__(self):
            self.calls = []
            self.brokers = {}
            self.providers = {}

        def get_for_account(self, account_id, broker_name):
            self.calls.append(("broker", account_id, broker_name))
            key = (account_id, broker_name)
            if key not in self.brokers:
                self.brokers[key] = FakeBroker(account_id)
            return self.brokers[key]

        def get_instrument_provider_for_account(self, account_id, broker_name):
            self.calls.append(("provider", account_id, broker_name))
            key = (account_id, broker_name)
            if key not in self.providers:
                self.providers[key] = FakeProvider(
                    account_id, self.get_for_account(account_id, broker_name)
                )
            return self.providers[key]

    manager = SharedManager()
    window._broker_manager_cache = manager
    window.account_store.set_active(ACCOUNT_A)
    return window, manager


def _pump_until(qapp, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    qapp.processEvents()
    return predicate()


def test_actual_page_workers_use_active_account_runtime(qapp):
    window, manager = _active_window_with_fake_runtime()
    page = window.order_configuration_page
    instrument = Instrument(ins_code=INS_CODE, symbol="SYM", name="Symbol", market="TSE")
    page.config.select_instrument(instrument)

    page._start_trading_state_query(instrument)
    page._start_order_identity_resolution(instrument)
    page.wait_for_trading_state_workers(5000)
    page.wait_for_order_identity_workers(5000)
    assert _pump_until(qapp, lambda: page._order_nsc_id is not None)

    provider = manager.providers[(ACCOUNT_A, BROKER)]
    broker = manager.brokers[(ACCOUNT_A, BROKER)]
    assert provider.instrument_calls == [INS_CODE]
    assert provider.identity_calls == [INS_CODE]
    assert broker.state_calls == [f"nsc-{ACCOUNT_A}"]
    assert page._trading_state_shown is VERIFIED_TRADABLE
    assert page._order_nsc_id == f"nsc-{ACCOUNT_A}"
    assert page._order_identity_scope == (ACCOUNT_A, BROKER, INS_CODE)
    assert set(manager.providers) == {(ACCOUNT_A, BROKER)}
    window.close()


def test_real_page_workers_discard_late_account_a_result_after_switch(qapp):
    window, manager = _active_window_with_fake_runtime()
    page = window.order_configuration_page
    instrument = Instrument(ins_code=INS_CODE, symbol="SYM", name="Symbol", market="TSE")
    page.config.select_instrument(instrument)
    gate_a = threading.Event()
    manager.get_instrument_provider_for_account(
        ACCOUNT_A, BROKER
    ).instrument_gate = gate_a
    manager.get_instrument_provider_for_account(
        ACCOUNT_A, BROKER
    ).identity_gate = gate_a

    page._start_trading_state_query(instrument)
    page._start_order_identity_resolution(instrument)
    assert _pump_until(qapp, lambda: (
        manager.providers[(ACCOUNT_A, BROKER)].instrument_calls
        and manager.providers[(ACCOUNT_A, BROKER)].identity_calls
    ))

    window.account_store.set_active(ACCOUNT_B)
    page.refresh_active_account()
    page.wait_for_trading_state_workers(5000)
    page.wait_for_order_identity_workers(5000)
    assert _pump_until(qapp, lambda: page._order_nsc_id == f"nsc-{ACCOUNT_B}")
    assert page._order_identity_scope == (ACCOUNT_B, BROKER, INS_CODE)
    assert page._trading_state_account_scope == (ACCOUNT_B, BROKER, INS_CODE)

    gate_a.set()
    # Let both superseded A workers deliver their late results after B.
    _pump_until(qapp, lambda: (
        manager.brokers[(ACCOUNT_A, BROKER)].state_calls
        and manager.providers[(ACCOUNT_A, BROKER)].identity_calls
    ))
    page.wait_for_trading_state_workers(5000)
    page.wait_for_order_identity_workers(5000)
    qapp.processEvents()

    assert page._order_nsc_id == f"nsc-{ACCOUNT_B}"
    assert page._order_identity_scope == (ACCOUNT_B, BROKER, INS_CODE)
    assert page._trading_state_account_scope == (ACCOUNT_B, BROKER, INS_CODE)
    assert manager.providers[(ACCOUNT_A, BROKER)]._broker is manager.brokers[
        (ACCOUNT_A, BROKER)
    ]
    window.close()


def test_no_active_or_invalid_account_fails_closed_without_name_fallback(qapp):
    store = AccountStore()
    window = MainWindow.__new__(MainWindow)
    window.account_store = store
    window._broker_manager_cache = None
    with pytest.raises(ValueError):
        window._real_trading_state_query()
    assert window._broker_manager_cache is None

    calls = []

    class Manager:
        def get_for_account(self, account_id, broker_name):
            calls.append(("broker", account_id, broker_name))
            raise ValueError("resolution failed")

        def get_instrument_provider_for_account(self, account_id, broker_name):
            calls.append(("provider", account_id, broker_name))
            raise ValueError("resolution failed")

    window._broker_manager_cache = Manager()
    store.add(ACCOUNT_A, BROKER, "A")
    store.set_active(ACCOUNT_A)
    with pytest.raises(ValueError):
        window._real_trading_state_query(ACCOUNT_A, BROKER)
    with pytest.raises(ValueError):
        window._real_order_identity_resolver(ACCOUNT_A, BROKER)
    assert calls == [("broker", ACCOUNT_A, BROKER), ("provider", ACCOUNT_A, BROKER)]
    assert all(kind != "name-only" for kind, *_ in calls)


def test_main_window_read_runtime_remains_lazy_on_construction(qapp, monkeypatch):
    from brokers import manager as manager_module

    class ForbiddenManager:
        def __init__(self):
            raise AssertionError("manager must remain lazy")

    monkeypatch.setattr(manager_module, "BrokerManager", ForbiddenManager)
    # Exercise the real constructor with a real QApplication instance.
    window = MainWindow()
    assert window._broker_manager_cache is None
    assert window.order_configuration_page._trading_state_factory is not None
    assert window.order_configuration_page._order_identity_factory is not None
    assert window._broker_manager_cache is None
    window.close()
