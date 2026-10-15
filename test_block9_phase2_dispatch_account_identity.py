"""Offline account-owned broker/provider resolution regression tests."""

from unittest.mock import Mock

from core.dispatch_core import DispatchCore
from core.execution_planner import ExecutionPlanner, LogicalOrderInstruction, PlannedOrder
from models.account import Account
from models.order import BUY, Order


def _account(account_id):
    account = Account(
        last_balance=0,
        adjusted_balance_t2=0,
        tradable_balance_t1=1_000_000,
        tradable_balance_t2=1_000_000,
        payable_balance_with_agah_credit_t0=0,
        payable_balance_with_agah_credit_t1=0,
        payable_balance_with_agah_credit_t2=0,
        payable_balance_without_agah_credit_t0=0,
        block=0,
        credit=0,
        settlement_date_t0=None,
        settlement_date_t1=None,
        settlement_date_t2=None,
    )
    account.account_id = account_id
    return account


def _plan(entries):
    orders = [
        PlannedOrder(
            order=Order(nsc_id=f"INS-{sequence}", side=BUY, price=100, quantity=1),
            account_id=account_id,
            broker_name="آگاه",
            sequence=sequence,
        )
        for sequence, account_id in entries
    ]
    plan = ExecutionPlanner().build_plan(
        LogicalOrderInstruction(plan_id="identity-test", orders=orders)
    )
    accounts = {account_id: _account(account_id) for _, account_id in entries}
    unique = []
    for _, account_id in entries:
        if account_id not in unique:
            unique.append(account_id)
    plan.accounts = [accounts[account_id] for account_id in unique]
    return plan


def _manager():
    manager = Mock()
    brokers = {}
    providers = {}

    def resolve_broker(account_id, broker_name):
        pair = (account_id, broker_name)
        broker = brokers.get(pair)
        if broker is None:
            broker = Mock()
            broker.name = broker_name
            brokers[pair] = broker
        return broker

    def resolve_provider(account_id, broker_name):
        pair = (account_id, broker_name)
        provider = providers.get(pair)
        if provider is None:
            provider = Mock(name=f"provider-{account_id}")
            provider.get_instrument.return_value = (None, Mock())
            providers[pair] = provider
        return provider

    manager.get_for_account.side_effect = resolve_broker
    manager.get_instrument_provider_for_account.side_effect = resolve_provider
    manager.brokers_by_pair = brokers
    manager.providers_by_pair = providers
    return manager


def _success():
    result = Mock()
    result.success = True
    result.sent = False
    result.mode = "READY"
    return result


def test_dispatch_uses_separate_account_broker_and_provider_instances():
    manager = _manager()
    core = DispatchCore(broker_manager=manager)
    plan = _plan([(0, "acct-A"), (1, "acct-B"), (2, "acct-A")])
    calls = []

    def execute(broker, provider, ins_code, order, account, live):
        calls.append((broker, provider, account.account_id, ins_code, live))
        return _success()

    core.order_engine.execute_by_ins_code = Mock(side_effect=execute)
    result = core.dispatch(plan)

    assert result.success is True
    broker_a = manager.brokers_by_pair[("acct-A", "آگاه")]
    broker_b = manager.brokers_by_pair[("acct-B", "آگاه")]
    provider_a = manager.providers_by_pair[("acct-A", "آگاه")]
    provider_b = manager.providers_by_pair[("acct-B", "آگاه")]
    assert broker_a is not broker_b
    assert provider_a is not provider_b
    assert [call[0] for call in calls] == [broker_a, broker_b, broker_a]
    assert [call[1] for call in calls] == [provider_a, provider_b, provider_a]
    assert [call[2] for call in calls] == ["acct-A", "acct-B", "acct-A"]
    assert [call[3] for call in calls] == ["INS-0", "INS-1", "INS-2"]
    assert all(call[4] is False for call in calls)
    manager.get_for_account.assert_any_call("acct-A", "آگاه")
    manager.get_for_account.assert_any_call("acct-B", "آگاه")
    manager.get_instrument_provider_for_account.assert_any_call("acct-A", "آگاه")
    manager.get_instrument_provider_for_account.assert_any_call("acct-B", "آگاه")
    manager.get.assert_not_called()
    manager.get_instrument_provider.assert_not_called()


def test_account_resolution_failure_happens_before_any_order_execution():
    manager = _manager()

    def fail_second_account(account_id, broker_name):
        if account_id == "acct-B":
            raise ValueError("unavailable account broker")
        broker = Mock()
        broker.name = broker_name
        return broker

    manager.get_for_account.side_effect = fail_second_account
    core = DispatchCore(broker_manager=manager)
    core.order_engine.execute_by_ins_code = Mock(return_value=_success())

    result = core.dispatch(_plan([(0, "acct-A"), (1, "acct-B")]))

    assert result.success is False
    assert result.mode == "BLOCKED"
    core.order_engine.execute_by_ins_code.assert_not_called()
    manager.get.assert_not_called()
    manager.get_instrument_provider.assert_not_called()


def test_provider_resolution_failure_blocks_without_name_only_fallback():
    manager = _manager()
    manager.get_instrument_provider_for_account.side_effect = ValueError(
        "unavailable account provider"
    )
    core = DispatchCore(broker_manager=manager)
    core.order_engine.execute_by_ins_code = Mock(return_value=_success())

    result = core.dispatch(_plan([(0, "acct-A")]))

    assert result.success is False
    assert result.mode == "BLOCKED"
    manager.get_for_account.assert_called_once_with("acct-A", "آگاه")
    manager.get_instrument_provider_for_account.assert_called_once_with(
        "acct-A", "آگاه"
    )
    core.order_engine.execute_by_ins_code.assert_not_called()
    manager.get.assert_not_called()
    manager.get_instrument_provider.assert_not_called()


def test_missing_account_scoped_resolution_fails_closed_without_name_fallback():
    manager = Mock()
    manager.get_for_account.side_effect = ValueError("resolution unavailable")
    core = DispatchCore(broker_manager=manager)
    core.order_engine.execute_by_ins_code = Mock(return_value=_success())

    result = core.dispatch(_plan([(0, "acct-A")]))

    assert result.success is False
    assert result.mode == "BLOCKED"
    core.order_engine.execute_by_ins_code.assert_not_called()
    manager.get.assert_not_called()
    manager.get_instrument_provider.assert_not_called()
