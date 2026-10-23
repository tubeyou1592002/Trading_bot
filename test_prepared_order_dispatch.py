from datetime import datetime, timedelta, timezone
from dataclasses import replace
import requests

from core.order_engine import OrderEngine
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, SELL, Order
from models.trading_state import TradingState


class Provider:
    def __init__(self, instrument):
        self.instrument = instrument
        self.calls = 0

    def get_instrument(self, _):
        self.calls += 1
        return None, self.instrument


class Broker:
    name = "test"
    live_trading_enabled = False

    def __init__(self):
        self.builds = 0
        self.submits = []

    def get_trading_state(self, _):
        return TradingState(True, True, "test", "allowed")

    def get_buy_capacity(self, **_):
        return 100

    def get_sell_capacity(self, **_):
        return 100

    def build_order_payload(self, order):
        self.builds += 1
        return order.to_payload()

    def submit_prepared_order(self, payload, live=False):
        self.submits.append(payload)
        return {"mode": "DRY_RUN", "sent": False, "payload": payload}

    def place_order(self, order, live=False):
        return {"mode": "DRY_RUN", "sent": False,
                "payload": self.build_order_payload(order)}


def _setup():
    order = Order("nsc", BUY, 10, 2)
    instrument = BrokerInstrument(nsc_id="nsc", tse_id="tse",
        minimum_order_quantity=1, lot_size=1, maximum_order_quantity_for_buy=100,
        maximum_order_quantity_for_sell=100, fixed_price_tick=1,
        lower_price_threshold=1, upper_price_threshold=1000)
    account = Account(account_id="acct", tradable_balance_t1=1000)
    return order, instrument, account


def _document_test_ttls(engine):
    from datetime import timedelta
    engine.PREPARED_SOURCE_TTLS = {
        "OrderEngine.order.nsc_id/BrokerInstrument.nsc_id": timedelta(minutes=1),
        "broker.get_trading_state": timedelta(minutes=1),
        "OrderValidator.validate": timedelta(minutes=1),
        "broker.get_buy_capacity": timedelta(minutes=1),
        "broker.get_sell_capacity": timedelta(minutes=1),
        "OrderEngine._check_capacity": timedelta(minutes=1),
    }


def test_prepare_submit_reuses_payload_and_rejects_mutation():
    order, instrument, account = _setup()
    broker = Broker()
    provider = Provider(instrument)
    engine = OrderEngine()
    _document_test_ttls(engine)
    prepared, result = engine.prepare_order(broker, provider, "nsc", order,
        account, "acct", "test")
    assert result.success and prepared is not None
    assert provider.calls == 1 and broker.builds == 1
    sent = engine.submit_prepared_order(prepared, broker, account, "acct", "test")
    assert sent.success and broker.builds == 1 and provider.calls == 1
    order.quantity += 1
    assert not engine.submit_prepared_order(prepared, broker, account, "acct", "test").success
    assert len(broker.submits) == 1


def test_unsupported_broker_fails_closed_and_timeout_is_not_retried():
    order, instrument, account = _setup()
    broker = Broker()
    provider = Provider(instrument)
    engine = OrderEngine()
    _document_test_ttls(engine)
    prepared, _ = engine.prepare_order(broker, provider, "nsc", order, account,
        "acct", "test")
    # A broker without the capability cannot be used for prepared submission.
    class OldBroker(Broker):
        submit_prepared_order = None
    old = OldBroker()
    prepared, _ = engine.prepare_order(old, provider, "nsc", order, account,
        "acct", "test")
    assert not engine.submit_prepared_order(prepared, old, account, "acct", "test").success


def test_legacy_place_order_remains_callable_and_builds_payload():
    order, _, _ = _setup()
    broker = Broker()
    result = broker.place_order(order)
    assert result["mode"] == "DRY_RUN"
    assert result["payload"] == order.to_payload()
    assert broker.builds == 1


def test_batch_preparation_failure_prevents_any_submit():
    order, instrument, account = _setup()
    broker = Broker()
    engine = OrderEngine()
    _document_test_ttls(engine)
    requests = [
        dict(broker=broker, provider=Provider(instrument), ins_code="nsc",
             order=order, account=account, account_id="acct", broker_name="test"),
        dict(broker=broker, provider=Provider(instrument), ins_code="nsc",
             order=Order("different", BUY, 10, 2), account=account,
             account_id="acct", broker_name="test"),
    ]
    batch = engine.prepare_batch(requests)
    assert not batch.valid and batch.orders == ()
    assert broker.submits == []


def test_expired_preparation_rejected():
    order, instrument, account = _setup()
    broker = Broker()
    engine = OrderEngine()
    _document_test_ttls(engine)
    prepared, _ = engine.prepare_order(broker, Provider(instrument), "nsc", order,
        account, "acct", "test")
    expired_freshness = tuple((source, ended, ended - timedelta(seconds=1))
                              for source, ended, _ in prepared.freshness)
    prepared = replace(prepared, freshness=expired_freshness)
    assert not engine.submit_prepared_order(prepared, broker, account, "acct", "test").success


def test_two_accounts_and_brokers_receive_only_their_payloads():
    engine = OrderEngine()
    _document_test_ttls(engine)
    pairs = []
    for account_id, broker_name, symbol in (("a1", "b1", "s1"), ("a2", "b2", "s2")):
        order, instrument, _ = _setup()
        order.nsc_id = symbol
        instrument.nsc_id = symbol
        account = Account(account_id=account_id, tradable_balance_t1=1000)
        broker = Broker()
        broker.name = broker_name
        prepared, result = engine.prepare_order(broker, Provider(instrument), symbol,
            order, account, account_id, broker_name)
        assert result.success and prepared is not None
        pairs.append((prepared, broker, account, account_id, broker_name, symbol))
    for prepared, broker, account, account_id, broker_name, _ in pairs:
        assert engine.submit_prepared_order(prepared, broker, account, account_id,
            broker_name).success
    assert [item["nscId"] for item in pairs[0][1].submits[0:1]] == ["s1"]
    assert [item["nscId"] for item in pairs[1][1].submits[0:1]] == ["s2"]
    assert not engine.submit_prepared_order(pairs[0][0], pairs[1][1], pairs[0][2],
        pairs[0][3], pairs[0][4]).success


def test_prepared_timeout_is_not_retried():
    order, instrument, account = _setup()
    broker = Broker()
    def timeout_once(payload, live=False):
        broker.submits.append(payload)
        raise requests.Timeout("ambiguous POST timeout")
    broker.submit_prepared_order = timeout_once
    engine = OrderEngine()
    _document_test_ttls(engine)
    prepared, result = engine.prepare_order(broker, Provider(instrument), "nsc",
        order, account, "acct", "test")
    assert result.success
    sent = engine.submit_prepared_order(prepared, broker, account, "acct", "test")
    assert not sent.success and len(broker.submits) == 1


def test_missing_or_invalid_preparation_evidence_rejected():
    order, instrument, account = _setup()
    broker = Broker()
    engine = OrderEngine()
    prepared, result = engine.prepare_order(broker, Provider(instrument), "nsc",
        order, account, "acct", "test")
    assert result.success and prepared.m6_results
    incomplete = replace(prepared, m6_results=())
    invalid = replace(prepared, m6_results=(("M6-B", False, 10),))
    for candidate in (None, incomplete, invalid):
        result = engine.submit_prepared_order(candidate, broker, account, "acct", "test")
        assert not result.success
    assert broker.submits == []


def test_each_required_gate_missing_unknown_or_duplicate_is_rejected():
    order, instrument, account = _setup()
    broker = Broker()
    engine = OrderEngine()
    prepared, result = engine.prepare_order(broker, Provider(instrument), "nsc",
        order, account, "acct", "test")
    assert result.success
    gates = prepared.m6_results
    assert {item[0] for item in gates} == {
        "M6-A-identity", "M6-A-trading-state", "M6-B-validation",
        "M6-C-buy-capacity", "M6-E-capacity-check",
    }
    malformed = [
        replace(prepared, m6_results=tuple(x for x in gates if x[0] != gate[0]))
        for gate in gates
    ]
    malformed.append(replace(prepared, m6_results=gates + (("M6-UNKNOWN", True, 1),)))
    malformed.append(replace(prepared, m6_results=gates + (gates[0],)))
    malformed.append(replace(prepared, m6_results=tuple(
        ("M6-D-sell-capacity" if x[0] == "M6-C-buy-capacity" else x[0], x[1], x[2])
        for x in gates
    )))
    for candidate in malformed:
        assert not engine.submit_prepared_order(candidate, broker, account,
            "acct", "test").success
    assert broker.submits == []


def test_valid_buy_and_sell_preparations_have_side_specific_evidence():
    engine = OrderEngine()
    _document_test_ttls(engine)
    for side, expected_capacity in ((BUY, "M6-C-buy-capacity"),
                                    (SELL, "M6-D-sell-capacity")):
        order, instrument, account = _setup()
        order.side = side
        broker = Broker()
        prepared, result = engine.prepare_order(broker, Provider(instrument), "nsc",
            order, account, "acct", "test")
        assert result.success and prepared is not None
        assert expected_capacity in {item[0] for item in prepared.m6_results}
        assert engine.submit_prepared_order(prepared, broker, account,
            "acct", "test").success


def test_each_source_expiry_is_checked_independently(monkeypatch):
    order, instrument, account = _setup()
    broker = Broker()
    engine = OrderEngine()
    names = {
        "OrderEngine.order.nsc_id/BrokerInstrument.nsc_id",
        "broker.get_trading_state", "OrderValidator.validate",
        "broker.get_buy_capacity", "OrderEngine._check_capacity",
    }
    monkeypatch.setattr(engine, "PREPARED_SOURCE_TTLS",
        {name: timedelta(seconds=60) for name in names})
    prepared, result = engine.prepare_order(broker, Provider(instrument), "nsc",
        order, account, "acct", "test")
    assert result.success and all(item[2] is not None for item in prepared.freshness)
    current = tuple((source, ended, ended + timedelta(seconds=60))
                    for source, ended, _ in prepared.freshness)
    prepared = replace(prepared, freshness=current)
    assert engine.submit_prepared_order(prepared, broker, account, "acct", "test").success
    for index in range(len(prepared.freshness)):
        stale = list(prepared.freshness)
        source, ended_at, _ = stale[index]
        stale[index] = (source, ended_at, datetime.now(timezone.utc) - timedelta(seconds=1))
        candidate = replace(prepared, freshness=tuple(stale))
        before = len(broker.submits)
        assert not engine.submit_prepared_order(candidate, broker, account,
            "acct", "test").success
        assert len(broker.submits) == before


def test_undocumented_source_ttl_disallows_scheduled_use():
    order, instrument, account = _setup()
    broker = Broker()
    engine = OrderEngine()
    prepared, result = engine.prepare_order(broker, Provider(instrument), "nsc",
        order, account, "acct", "test")
    assert result.success and any(expiry is None for _, _, expiry in prepared.freshness)
    assert not engine.submit_prepared_order(prepared, broker, account,
        "acct", "test").success
    assert broker.submits == []


def test_empty_production_policy_rejects_entire_batch():
    order, instrument, account = _setup()
    broker = Broker()
    engine = OrderEngine()
    assert engine.PREPARED_SOURCE_TTLS == {}
    request = dict(broker=broker, provider=Provider(instrument), ins_code="nsc",
        order=order, account=account, account_id="acct", broker_name="test")
    batch = engine.prepare_batch([request])
    assert batch.checks_succeeded
    assert not batch.valid and batch.orders == ()
    assert not batch.orders
    assert broker.submits == []


def test_freshness_source_timestamp_or_expiry_tampering_rejected(monkeypatch):
    order, instrument, account = _setup()
    broker = Broker()
    engine = OrderEngine()
    _document_test_ttls(engine)
    prepared, result = engine.prepare_order(broker, Provider(instrument), "nsc",
        order, account, "acct", "test")
    assert result.success and prepared.scheduled_valid
    assert engine.submit_prepared_order(prepared, broker, account,
        "acct", "test").success

    swapped = list(prepared.freshness)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    tampered = replace(prepared, freshness=tuple(swapped))
    assert not engine.submit_prepared_order(tampered, broker, account,
        "acct", "test").success

    changed_expiry = list(prepared.freshness)
    source, ended, expiry = changed_expiry[0]
    changed_expiry[0] = (source, ended, expiry + timedelta(seconds=1))
    tampered = replace(prepared, freshness=tuple(changed_expiry))
    assert not engine.submit_prepared_order(tampered, broker, account,
        "acct", "test").success

    missing = replace(prepared, freshness=prepared.freshness[:-1])
    assert not engine.submit_prepared_order(missing, broker, account,
        "acct", "test").success
