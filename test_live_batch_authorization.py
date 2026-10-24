"""Offline acceptance tests for Task 11.3 batch-scoped Live permission."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from core.live_order_authorization import (
    validate_prepared_submission,
)
from core.order_engine import OrderEngine
from core.order_engine import PreparedBatch
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order
from models.trading_state import TradingState
from ui.live_order_gate import (
    check_live_batch_readiness,
    validate_live_batch_authorization,
)
from ui.order_authorization import authorize_destination
from ui.session_manager import SessionManager


class Provider:
    def __init__(self, instrument):
        self.instrument = instrument
        self.calls = 0

    def get_instrument(self, _):
        self.calls += 1
        return None, self.instrument


class Broker:
    live_trading_enabled = True

    def __init__(self, name):
        self.name = name
        self.submits = []

    def get_trading_state(self, _):
        return TradingState(True, True, self.name, "allowed")

    def get_buy_capacity(self, **_):
        return 10000

    def get_sell_capacity(self, **_):
        return 10000

    def build_order_payload(self, order):
        return order.to_payload()

    def submit_prepared_order(self, payload, live=False):
        self.submits.append((payload, live))
        return {"mode": "LIVE" if live else "DRY_RUN"}


class Store:
    def __init__(self, records, active="not-a-destination"):
        self.records = records
        self.active = active

    def get(self, account_id):
        return self.records[account_id]

    def active_account_id(self):
        return self.active


class Authentication:
    def __init__(self):
        self.adapters = {}

    def is_logged_in(self, account_id):
        return self.adapters[account_id].is_authenticated()

    def get_adapter(self, account_id):
        return self.adapters.get(account_id)


class Adapter:
    def __init__(self, broker_name, token):
        self.broker_name = broker_name
        self.token = token

    def is_authenticated(self):
        return True

    def get_authenticated_session(self):
        return SimpleNamespace(access_token=self.token)


class BrokerManager:
    def __init__(self, brokers):
        self.brokers = brokers

    def get_for_account(self, account_id, broker_name):
        return self.brokers[(account_id, broker_name)]


class QueueEntry:
    def __init__(self, order, account_id, broker_name):
        self.order = order
        self.account_id = account_id
        self.broker_name = broker_name


class Target:
    def __init__(self, entry, account):
        self.entry = entry
        self.account_id = entry.account_id
        self.broker_name = entry.broker_name
        self.account = account


def _setup(monkeypatch):
    engine = OrderEngine()
    assert engine.PREPARED_SOURCE_TTLS == {}
    execution_id = f"scheduled-run-{id(engine)}"

    records = {}
    brokers = {}
    session_manager = SessionManager()
    authentication = Authentication()
    targets = []
    prepared = []
    for account_id, broker_name, suffix in (
        ("A1", "SIM-1", "N1"),
        ("A2", "SIM-2", "N2"),
    ):
        account = Account(account_id=account_id, tradable_balance_t1=100000)
        records[account_id] = SimpleNamespace(
            account=account, account_id=account_id, broker_name=broker_name
        )
        broker = Broker(broker_name)
        brokers[(account_id, broker_name)] = broker
        session_manager.register(account_id, broker_name)
        session_manager.begin_login(account_id)
        session_manager.mark_logged_in(account_id, f"token-{account_id}")
        authentication.adapters[account_id] = Adapter(
            broker_name, f"token-{account_id}"
        )
        order = Order(suffix, BUY, 10, 2)
        instrument = BrokerInstrument(
            nsc_id=suffix,
            tse_id=suffix,
            minimum_order_quantity=1,
            lot_size=1,
            maximum_order_quantity_for_buy=1000,
            maximum_order_quantity_for_sell=1000,
            fixed_price_tick=1,
            lower_price_threshold=1,
            upper_price_threshold=1000,
        )
        entry = QueueEntry(order, account_id, broker_name)
        targets.append(Target(entry, account))
        item, result = engine.prepare_order(
            broker=broker,
            provider=Provider(instrument),
            ins_code=suffix,
            order=order,
            account=account,
            account_id=account_id,
            broker_name=broker_name,
            execution_id=execution_id,
            _execution_claimed=(account_id == "A1"),
        )
        assert result.success and item is not None and item.scheduled_valid
        prepared.append(item)

    start = datetime.now(timezone.utc) + timedelta(seconds=30)
    end = start + timedelta(seconds=10)
    timing = SimpleNamespace(start_time=start, end_time=end)
    return {
        "engine": engine,
        "records": records,
        "brokers": brokers,
        "sessions": session_manager,
        "auth": authentication,
        "manager": BrokerManager(brokers),
        "targets": tuple(targets),
        "prepared": tuple(prepared),
        "execution_id": execution_id,
        "timing": timing,
        "now": datetime.now(timezone.utc),
    }


def _readiness(state, *, human_approval=True, targets=None, prepared=None,
               timing=None, interval_ms=5000, now=None, turns=None):
    return check_live_batch_readiness(
        account_store=Store(state["records"]),
        authentication_service=state["auth"],
        session_manager=state["sessions"],
        broker_manager=state["manager"],
        targets=targets if targets is not None else state["targets"],
        prepared_batch=prepared if prepared is not None else PreparedBatch(
            state["prepared"], True, "", True, state["execution_id"]
        ),
        timing=timing if timing is not None else state["timing"],
        interval_ms=interval_ms,
        planned_turns=turns,
        execution_id=state["execution_id"],
        queue_revision=42,
        engine=state["engine"],
        explicit_live_request=True,
        human_approval=human_approval,
        now=now if now is not None else state["now"],
    )


def test_authorization_uses_real_per_destination_sessions_and_not_active_account(monkeypatch):
    state = _setup(monkeypatch)
    assert authorize_destination(
        Store(state["records"]), state["auth"], state["sessions"], "A2", "SIM-2"
    ).authorized

    readiness = _readiness(state)
    assert readiness.allowed


def test_pre_arm_local_validation_accepts_future_start_but_submit_rejects_it(monkeypatch):
    state = _setup(monkeypatch)
    readiness = _readiness(state)
    authorization = readiness.authorization
    assert authorization is not None
    check = validate_live_batch_authorization(
        authorization=authorization,
        account_store=Store(state["records"]),
        authentication_service=state["auth"],
        session_manager=state["sessions"],
        broker_manager=state["manager"], targets=state["targets"],
        prepared_batch=PreparedBatch(state["prepared"], True, "", True,
                                     state["execution_id"]),
        timing=state["timing"], interval_ms=5000,
        execution_id=state["execution_id"], queue_revision=42,
        engine=state["engine"], now=state["now"], pre_arm=True,
    )
    assert check.allowed
    item = state["prepared"][0]
    target = state["targets"][0]
    result = state["engine"].submit_prepared_order(
        item, state["brokers"][(target.account_id, target.broker_name)],
        target.account, target.account_id, target.broker_name, live=True,
        authorization=authorization, now=state["now"],
    )
    assert not result.success
    authorization = readiness.authorization
    assert authorization.snapshot.schedule.order_count == 2
    assert authorization.snapshot.schedule.planned_turns == 3
    assert authorization.snapshot.schedule.max_submissions == 6
    assert {item.execution_id for item in authorization.snapshot.orders} == {
        state["execution_id"]
    }
    assert {item.account_id for item in authorization.snapshot.destinations} == {
        "A1", "A2"
    }


def test_missing_destination_session_or_broker_capability_blocks_entire_batch(monkeypatch):
    state = _setup(monkeypatch)
    state["sessions"].logout("A2")
    assert not _readiness(state).allowed
    assert all(not broker.submits for broker in state["brokers"].values())

    state = _setup(monkeypatch)
    state["brokers"][("A1", "SIM-1")].live_trading_enabled = False
    assert not _readiness(state).allowed
    assert all(not broker.submits for broker in state["brokers"].values())


def test_destination_session_generation_change_invalidates_existing_permit(monkeypatch):
    state = _setup(monkeypatch)
    authorization = _readiness(state).authorization
    assert authorization is not None
    state["sessions"].replace_token("A2", "replacement-token-A2")
    check = validate_live_batch_authorization(
        authorization=authorization,
        account_store=Store(state["records"]),
        authentication_service=state["auth"],
        session_manager=state["sessions"],
        broker_manager=state["manager"],
        targets=state["targets"],
        prepared_batch=PreparedBatch(
            state["prepared"], True, "", True, state["execution_id"]
        ),
        timing=state["timing"],
        interval_ms=5000,
        planned_turns=3,
        execution_id=state["execution_id"],
        queue_revision=42,
        engine=state["engine"],
        now=state["timing"].start_time,
    )
    assert not check.allowed


def test_m6_failures_and_inconsistent_schedule_counts_never_issue_permission(monkeypatch):
    state = _setup(monkeypatch)
    failed = replace(state["prepared"][0], scheduled_valid=False)
    assert not _readiness(state, prepared=(failed, state["prepared"][1])).allowed
    assert all(not broker.submits for broker in state["brokers"].values())

    invalid_batch = PreparedBatch((), False, "failed fixture", False)
    assert not _readiness(state, prepared=invalid_batch).allowed
    assert all(not broker.submits for broker in state["brokers"].values())

    state = _setup(monkeypatch)
    assert not _readiness(state, turns=999).allowed
    assert all(not broker.submits for broker in state["brokers"].values())


def test_explicit_approval_is_required_after_real_preflight(monkeypatch):
    state = _setup(monkeypatch)
    readiness = _readiness(state, human_approval=False)
    assert not readiness.allowed
    assert readiness.ready_for_confirmation
    assert readiness.authorization is None


def test_snapshot_change_or_window_end_revokes_authorization(monkeypatch):
    state = _setup(monkeypatch)
    authorization = _readiness(state).authorization
    ledger = authorization.usage_ledger
    assert authorization is not None

    valid = validate_live_batch_authorization(
        authorization=authorization,
        account_store=Store(state["records"]),
        authentication_service=state["auth"],
        session_manager=state["sessions"],
        broker_manager=state["manager"],
        targets=state["targets"],
        prepared_batch=PreparedBatch(
            state["prepared"], True, "", True, state["execution_id"]
        ),
        timing=state["timing"],
        interval_ms=5000,
        planned_turns=3,
        execution_id=state["execution_id"],
        queue_revision=42,
        engine=state["engine"],
        now=state["timing"].start_time,
    )
    assert valid.allowed

    early = validate_live_batch_authorization(
        authorization=authorization,
        account_store=Store(state["records"]),
        authentication_service=state["auth"],
        session_manager=state["sessions"],
        broker_manager=state["manager"],
        targets=state["targets"],
        prepared_batch=PreparedBatch(
            state["prepared"], True, "", True, state["execution_id"]
        ),
        timing=state["timing"],
        interval_ms=5000,
        planned_turns=3,
        execution_id=state["execution_id"],
        queue_revision=42,
        engine=state["engine"],
        now=state["timing"].start_time - timedelta(microseconds=1),
    )
    assert not early.allowed

    changed_order = state["targets"][0].entry.order
    changed_order.quantity += 1
    invalid = validate_live_batch_authorization(
        authorization=authorization,
        account_store=Store(state["records"]),
        authentication_service=state["auth"],
        session_manager=state["sessions"],
        broker_manager=state["manager"],
        targets=state["targets"],
        prepared_batch=state["prepared"],
        timing=state["timing"],
        interval_ms=5000,
        planned_turns=3,
        execution_id=state["execution_id"],
        queue_revision=42,
        engine=state["engine"],
        now=state["timing"].start_time,
    )
    assert not invalid.allowed

    # A source TTL crossing after approval does not trigger another source
    # read or invalidate the same scheduled execution.
    refreshed = _setup(monkeypatch)
    refreshed["timing"] = SimpleNamespace(
        start_time=refreshed["prepared"][0].m6_completed_at,
        end_time=refreshed["prepared"][0].m6_completed_at + timedelta(minutes=1),
    )
    authorization = _readiness(refreshed).authorization
    assert authorization is not None
    later = validate_live_batch_authorization(
        authorization=authorization,
        account_store=Store(refreshed["records"]),
        authentication_service=refreshed["auth"],
        session_manager=refreshed["sessions"],
        broker_manager=refreshed["manager"],
        targets=refreshed["targets"],
        prepared_batch=PreparedBatch(
            refreshed["prepared"], True, "", True, refreshed["execution_id"]
        ),
        timing=refreshed["timing"],
        interval_ms=5000,
        planned_turns=None,
        execution_id=refreshed["execution_id"],
        queue_revision=42,
        engine=refreshed["engine"],
        now=refreshed["prepared"][0].m6_completed_at + timedelta(seconds=1),
    )
    assert later.allowed

    # A second prepare attempt cannot reuse the same execution identity to
    # rebind run-1 M6 evidence into another scheduled run.
    order, instrument, account = Order("retry", BUY, 10, 2), BrokerInstrument(
        nsc_id="retry", tse_id="retry", minimum_order_quantity=1,
        lot_size=1, maximum_order_quantity_for_buy=1000,
        maximum_order_quantity_for_sell=1000, fixed_price_tick=1,
        lower_price_threshold=1, upper_price_threshold=1000,
    ), Account(account_id="acct", tradable_balance_t1=100000)
    broker = Broker("SIM-1")
    duplicate, duplicate_result = state["engine"].prepare_order(
        broker, Provider(instrument), "retry", order, account, "acct", "test",
        execution_id=state["execution_id"],
    )
    assert duplicate is None and not duplicate_result.success

    expired = validate_live_batch_authorization(
        authorization=authorization,
        account_store=Store(state["records"]),
        authentication_service=state["auth"],
        session_manager=state["sessions"],
        broker_manager=state["manager"],
        targets=state["targets"],
        prepared_batch=PreparedBatch(
            state["prepared"], True, "", True, state["execution_id"]
        ),
        timing=state["timing"],
        interval_ms=5000,
        planned_turns=3,
        execution_id=state["execution_id"],
        queue_revision=42,
        engine=state["engine"],
        now=state["timing"].end_time + timedelta(microseconds=1),
    )
    assert not expired.allowed


def test_live_submit_requires_matching_authorization_and_never_rechecks_m6(monkeypatch):
    state = _setup(monkeypatch)
    authorization = _readiness(state).authorization
    ledger = authorization.usage_ledger
    prepared = state["prepared"][0]
    broker = state["brokers"][("A1", "SIM-1")]
    account = state["targets"][0].account
    fire_time = state["timing"].start_time

    blocked = state["engine"].submit_prepared_order(
        prepared, broker, account, "A1", "SIM-1", live=True
    )
    assert not blocked.success and broker.submits == []

    # Re-capture the whole batch immediately before use. This check is local
    # and does not call any M6/network/provider endpoint.
    current_check = validate_live_batch_authorization(
        authorization=authorization,
        account_store=Store(state["records"]),
        authentication_service=state["auth"],
        session_manager=state["sessions"],
        broker_manager=state["manager"],
        targets=state["targets"],
        prepared_batch=PreparedBatch(
            state["prepared"], True, "", True, state["execution_id"]
        ),
        timing=state["timing"],
        interval_ms=5000,
        planned_turns=3,
        execution_id=state["execution_id"],
        queue_revision=42,
        engine=state["engine"],
        now=fire_time,
    )
    assert current_check.allowed and current_check.current_snapshot is not None
    result = state["engine"].submit_prepared_order(
        prepared, broker, account, "A1", "SIM-1",
        live=True, authorization=authorization,
        now=fire_time,
        current_snapshot=current_check.current_snapshot,
        authorization_ledger=ledger,
    )
    assert result.success and result.sent
    assert len(broker.submits) == 1
    assert broker.submits[0][1] is True
    assert ledger.used == 1

    # Each prepared order is limited to the approved planned turn count.
    for _ in range(2):
        repeated = state["engine"].submit_prepared_order(
            prepared, broker, account, "A1", "SIM-1",
            live=True, authorization=authorization,
            now=fire_time,
            current_snapshot=current_check.current_snapshot,
            authorization_ledger=ledger,
        )
        assert repeated.success
    before_exhausted = len(broker.submits)
    exhausted = state["engine"].submit_prepared_order(
        prepared, broker, account, "A1", "SIM-1",
        live=True, authorization=authorization,
        now=fire_time,
        current_snapshot=current_check.current_snapshot,
        authorization_ledger=ledger,
    )
    assert not exhausted.success
    assert len(broker.submits) == before_exhausted

    altered = replace(prepared, payload_json=prepared.payload_json + " ")
    before = len(broker.submits)
    denied = state["engine"].submit_prepared_order(
        altered, broker, account, "A1", "SIM-1",
        live=True, authorization=authorization,
        now=fire_time,
        current_snapshot=current_check.current_snapshot,
        authorization_ledger=ledger,
    )
    assert not denied.success
    assert len(broker.submits) == before

    divergent_payload = replace(
        prepared,
        payload_json=prepared.payload_json.replace('"price":10', '"price":11'),
    )
    divergent = state["engine"].submit_prepared_order(
        divergent_payload, broker, account, "A1", "SIM-1",
        live=True, authorization=authorization,
        now=fire_time,
        current_snapshot=current_check.current_snapshot,
        authorization_ledger=ledger,
    )
    assert not divergent.success
    assert len(broker.submits) == before



def test_missing_prepared_item_and_maximum_send_scope_are_rejected(monkeypatch):
    state = _setup(monkeypatch)
    readiness = _readiness(state, prepared=state["prepared"][:1])
    assert not readiness.allowed

    authorization = _readiness(state).authorization
    ledger = authorization.usage_ledger
    altered_snapshot = replace(
        authorization.snapshot,
        queue_revision=43,
    )
    assert not validate_prepared_submission(
        replace(authorization, snapshot=altered_snapshot),
        prepared=state["prepared"][0],
        broker=state["brokers"][("A1", "SIM-1")],
        account=state["targets"][0].account,
        order=state["prepared"][0].order,
        account_id="A1",
        broker_name="SIM-1",
        now=state["timing"].start_time,
        current_snapshot=altered_snapshot,
        usage_ledger=ledger,
    ).allowed
