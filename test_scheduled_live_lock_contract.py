"""Offline lock-separation acceptance tests for Agaah scheduled/manual Live."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from brokers.agaah.broker import AgaahBroker
from core.live_order_authorization import reserve_schedule_table
from core.order_engine import OrderEngine, PreparedBatch
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order
from models.trading_state import TradingState
from ui.live_order_gate import check_live_batch_readiness
from ui.session_manager import SessionManager
from ui.order_configuration_page import OrderConfigurationPage


class _Response:
    status = 200

    def raise_for_status(self):
        return None

    async def json(self):
        return {"isSuccess": True}


class _Post:
    async def __aenter__(self):
        return _Response()

    async def __aexit__(self, *_args):
        return False


class _Session:
    def __init__(self, **_kwargs):
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return _Post()

    async def close(self):
        self.closed = True


class _ManualResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"isSuccess": True}


class _ManualTransport:
    def __init__(self):
        self.headers = {}
        self.posts = []
        self.closed = False

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return _ManualResponse()

    def close(self):
        self.closed = True


class _Auth:
    def __init__(self):
        self.adapter = SimpleNamespace(
            broker_name="آگاه", is_authenticated=lambda: True,
            get_authenticated_session=lambda: SimpleNamespace(access_token="offline-token"),
        )

    def is_logged_in(self, _account_id):
        return True

    def get_adapter(self, _account_id):
        return self.adapter

    def get_purchase_power(self, _account_id):
        return 100000


def test_scheduled_prearm_failure_returns_specific_batch_reason():
    reason = "M6-C capacity unavailable"
    target = SimpleNamespace(entry=SimpleNamespace(order=SimpleNamespace(side="SELL")))
    batch = PreparedBatch((), False, reason, False)

    class Coordinator:
        engine = object()

        def prepare(self, targets):
            assert targets == (target,)
            return "offline-execution", batch

    page = SimpleNamespace(
        _frozen_dispatch_targets=lambda: (target,),
        _live_prearm_factory=lambda targets: Coordinator(),
        _live_batch_gate_factory=lambda **_kwargs: pytest.fail(
            "invalid prearm batch must stop before the readiness gate"
        ),
    )

    result = OrderConfigurationPage._prepare_live_schedule(page, None, 5000)

    assert result == (False, None, None, None, reason)


@pytest.mark.parametrize(("response", "expected"), [
    ({"isSuccess": True}, "\u0627\u0631\u0633\u0627\u0644 \u0645\u0648\u0641\u0642"),
    ({"isSuccess": False}, "پاسخ رد/ناموفق کارگزاری"),
    ({"unexpected": True}, "پاسخ کارگزاری با ساختار نامعتبر"),
])
def test_scheduled_ticket_dict_outcomes_are_visible_and_accumulate(response, expected):
    class Label:
        text = ""
        def setText(self, value):
            self.text = value
    page = SimpleNamespace(
        _scheduled_ticket_results=[],
        scheduled_ticket_results_label=Label(),
        _scheduled_feedback_ids={},
        _scheduled_fire_runtime=None,
    )
    page._append_scheduled_ticket_result = lambda ticket, verdict: OrderConfigurationPage._append_scheduled_ticket_result(page, ticket, verdict)
    first_ticket = SimpleNamespace(turn_index=0, ticket_id="opaque-first")
    second_ticket = SimpleNamespace(turn_index=1, ticket_id="opaque-second")
    OrderConfigurationPage._handle_scheduled_ticket_complete(page, second_ticket, {"isSuccess": False})
    OrderConfigurationPage._handle_scheduled_ticket_complete(page, first_ticket, response)
    assert expected in page.scheduled_ticket_results_label.text
    assert "پاسخ رد/ناموفق کارگزاری" in page.scheduled_ticket_results_label.text
    assert page.scheduled_ticket_results_label.text.count("ticket") == 2
    assert "نوبت 1، ticket opaque-first" in page.scheduled_ticket_results_label.text
    assert "نوبت 2، ticket opaque-second" in page.scheduled_ticket_results_label.text
    assert page.scheduled_ticket_results_label.text.index("opaque-second") < page.scheduled_ticket_results_label.text.index("opaque-first")


@pytest.mark.parametrize(("post_started", "expected"), [
    (False, "ارسال نشد (خطای پیش از ارسال)"),
    (True, "نامشخص؛ احتمال ثبت سفارش وجود دارد"),
])
def test_scheduled_ticket_exception_preserves_safe_send_classification(post_started, expected):
    class Label:
        text = ""
        def setText(self, value):
            self.text = value
    record = SimpleNamespace(post_start_ns=1 if post_started else None)
    runtime = SimpleNamespace(latency_report=lambda: SimpleNamespace(
        ticket=lambda *_args: record
    ))
    page = SimpleNamespace(
        _scheduled_ticket_results=[], scheduled_ticket_results_label=Label(),
        _scheduled_fire_runtime=runtime,
        _schedule_cancel_event=__import__("threading").Event(),
        _live_authorization=SimpleNamespace(snapshot=SimpleNamespace(orders=())),
    )
    page._append_scheduled_ticket_result = lambda ticket, verdict: OrderConfigurationPage._append_scheduled_ticket_result(page, ticket, verdict)
    ticket = SimpleNamespace(turn_index=0, ticket_id="safe-id")
    OrderConfigurationPage._handle_scheduled_ticket_complete(page, ticket, RuntimeError("secret"))
    assert expected in page.scheduled_ticket_results_label.text


def test_scheduled_ticket_signal_queues_result_slot_on_gui_thread():
    import threading

    from PySide6.QtCore import QCoreApplication, QEvent, QThread
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])
    page = OrderConfigurationPage.__new__(OrderConfigurationPage)
    # Initialize only QObject/QWidget internals; no account, network, or send setup.
    from PySide6.QtWidgets import QWidget
    QWidget.__init__(page)
    page._scheduled_ticket_results = []

    class ObservedLabel(QLabel):
        def __init__(self):
            super().__init__("")
            self.set_text_threads = []

        def setText(self, value):
            self.set_text_threads.append(QThread.currentThread())
            super().setText(value)

    page.scheduled_ticket_results_label = ObservedLabel()
    page._scheduled_feedback_ids = {}
    page._scheduled_fire_runtime = None
    page._dispatcher = None
    page._schedule_cancel_event = None
    page._schedule_timer = None
    page.scheduled_ticket_completed.connect(page._handle_scheduled_ticket_complete)
    observed_threads = []
    original_append = page._append_scheduled_ticket_result

    def observe_append(ticket, verdict):
        observed_threads.append(QThread.currentThread())
        original_append(ticket, verdict)

    page._append_scheduled_ticket_result = observe_append
    ticket = SimpleNamespace(turn_index=0, ticket_id="signal-ticket")
    worker_threads = []

    def emit_from_worker():
        worker_threads.append(QThread.currentThread())
        page.scheduled_ticket_completed.emit(ticket, {"isSuccess": True})

    worker = threading.Thread(target=emit_from_worker)
    worker.start()
    worker.join()
    app.processEvents()
    assert page.scheduled_ticket_results_label.text().endswith("\u0627\u0631\u0633\u0627\u0644 \u0645\u0648\u0641\u0642")
    assert worker_threads and worker_threads[0] is not app.thread()
    assert observed_threads == [app.thread()]
    assert page.scheduled_ticket_results_label.set_text_threads == [app.thread()]

    # Avoid QWidget.close(): OrderConfigurationPage.closeEvent expects the
    # complete runtime state, while this test intentionally initializes only
    # the signal/UI pieces. Deferred deletion destroys the widget without
    # entering that application-level close path.
    page.deleteLater()
    QCoreApplication.sendPostedEvents(page, QEvent.DeferredDelete)
    app.processEvents()


@pytest.mark.parametrize("bad", [None, True, -1, float("nan"), float("inf"), "100"])
def test_scheduled_t1_invalid_second_account_does_not_mutate_or_prepare(bad):
    accounts = [Account(account_id="a", tradable_balance_t1=1),
                Account(account_id="b", tradable_balance_t1=2)]
    targets = tuple(SimpleNamespace(account_id=account.account_id, account=account,
                                    entry=SimpleNamespace(order=SimpleNamespace(side=BUY)))
                    for account in accounts)
    reads = []
    def read(account_id):
        reads.append(account_id)
        return 100 if account_id == "a" else bad
    page = SimpleNamespace(
        _frozen_dispatch_targets=lambda: targets,
        _authentication_service_factory=lambda: SimpleNamespace(get_purchase_power=read),
        _live_prearm_factory=lambda _targets: pytest.fail("prearm must not run"),
        _live_batch_gate_factory=object(),
    )
    result = OrderConfigurationPage._prepare_live_schedule(page, None, 5000)
    assert not result[0] and "T1" in result[4]
    assert reads == ["a", "b"]
    assert [account.tradable_balance_t1 for account in accounts] == [1, 2]


def test_scheduled_t1_unique_buy_accounts_are_independent():
    accounts = [Account(account_id="a"), Account(account_id="b")]
    targets = tuple(SimpleNamespace(account_id=account.account_id, account=account,
                                    entry=SimpleNamespace(order=SimpleNamespace(side=BUY)))
                    for account in (accounts[0], accounts[0], accounts[1]))
    reads = []
    def read(account_id):
        reads.append(account_id)
        return {"a": 100, "b": 200}[account_id]
    class Coordinator:
        def prepare(self, prepared_targets):
            assert prepared_targets == targets
            assert [account.tradable_balance_t1 for account in accounts] == [100, 200]
            return "execution", PreparedBatch((), False, "stopped", False)
    page = SimpleNamespace(
        _frozen_dispatch_targets=lambda: targets,
        _authentication_service_factory=lambda: SimpleNamespace(get_purchase_power=read),
        _live_prearm_factory=lambda _targets: Coordinator(),
        _live_batch_gate_factory=object(),
    )
    assert OrderConfigurationPage._prepare_live_schedule(page, None, 5000)[4] == "stopped"
    assert reads == ["a", "b"]


def test_scheduled_confirmation_summary_uses_contract_planned_turns():
    start = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)
    timing = SimpleNamespace(start_time=start, end_time=start + timedelta(seconds=5))
    targets = tuple(
        SimpleNamespace(
            account_id="acct",
            broker_name="offline",
            account=SimpleNamespace(),
            entry=SimpleNamespace(order=SimpleNamespace(side="SELL")),
        )
        for _ in range(2)
    )
    summaries = []

    class Coordinator:
        engine = object()

        def prepare(self, prepared_targets):
            return "execution", PreparedBatch(
                tuple(object() for _ in prepared_targets), True, "", True
            )

    class GateResult:
        ready_for_confirmation = True

    page = SimpleNamespace(
        _frozen_dispatch_targets=lambda: targets,
        _live_prearm_factory=lambda _targets: Coordinator(),
        _live_batch_gate_factory=lambda **_kwargs: GateResult(),
        _authentication_service_factory=None,
        _dispatch_snapshot=lambda current: tuple(current),
        _dispatch_set_rejection=lambda: None,
        _confirm_live_start=lambda summary: summaries.append(summary) or False,
        order_queue=SimpleNamespace(revision=1),
    )

    result = OrderConfigurationPage._prepare_live_schedule(page, timing, 5000)

    assert result[0] is False
    assert "حداکثر ارسال‌ها: 4" in summaries[0]
    assert "None" not in summaries[0]


def test_freeze_snapshot_binds_frozen_live_mode_and_dispatch_interval():
    interval_ms = 5000
    page = SimpleNamespace(
        _pending_dispatch_interval_ms=interval_ms,
        _pending_live_mode=True,
        _pending_live_gate=object(),
        _pending_dispatch_targets=(),
        _pending_dispatch_snapshot=None,
        _dispatch_set_rejection=lambda: None,
        _ensure_schedule_queue_listener=lambda: None,
        # The dispatcher is constructed as part of freezing; keep its runner
        # factory inert so this regression test cannot dispatch or use a
        # network/live execution path.
        _new_send_runner=lambda: None,
        _frozen_dispatch_targets=lambda: (),
        _schedule_timing=None,
        _schedule_parsed=None,
        _run_mode="live",
        _get_session_manager=lambda: None,
        _schedule_cancel_lock=__import__("threading").RLock(),
    )

    # The session-validation fail-closed path occurs after the snapshot is
    # captured. Inspect the binding before that path clears it.
    def session_manager():
        return None

    page._get_session_manager = session_manager
    # Supply the account-free pieces needed to reach snapshot construction.
    page._schedule_apply_queue_revision = None
    page._effective_order_fingerprint = OrderConfigurationPage._effective_order_fingerprint
    page._immutable_schedule_entry = lambda entry: entry
    page.order_queue = SimpleNamespace(revision=0)
    page._schedule_cancel_event = object()
    page._locked_base_time = datetime.now(timezone.utc)
    page._locked_mono_anchor = 0.0
    page._set_schedule_locked = lambda _locked: None
    page._set_schedule_state = lambda _state: None
    page._set_schedule_summary = lambda _summary: None
    page.store = SimpleNamespace(
        get=lambda account_id: SimpleNamespace(
            account_id=account_id, broker_name="offline"
        ) if account_id == "acct" else None
    )
    page._schedule_destination_ids = ()
    page._stop_dispatcher = lambda: None
    page._clear_accepted_schedule = lambda: None
    page._pending_schedule = None
    page._schedule_times = ()
    page._schedule_assessment = None
    page._pending_dispatch_interval_ms = interval_ms
    page._dispatch_interval_ms = None
    page._dispatch_set_rejection = lambda: None
    page._schedule_queue_listener_bound = True

    # A logged-in account lets freezing complete without a broker/network path.
    session = SimpleNamespace(account_id="acct", broker_name="offline", state=SimpleNamespace(value="logged_in"))
    manager = SimpleNamespace(get=lambda _account_id: session,
                              revision=lambda _account_id: 1)
    page._get_session_manager = lambda: manager
    target = SimpleNamespace(account_id="acct", broker_name="offline", account=object(),
                             entry=SimpleNamespace(order=object()))
    page._pending_dispatch_targets = (target,)
    page._frozen_dispatch_targets = lambda: (target,)
    page._schedule_queue_entries = (target.entry,)
    page._run_mode = "live"
    page._ensure_schedule_queue_listener = lambda: None
    page._dispatch_interval_ms = None
    page._frozen_targets = ()
    page._schedule_snapshot = None
    page._frozen_live_mode = False
    page._pending_live_gate = object()
    page._dispatch_turns_lock = __import__("threading").Lock()
    page._dispatch_cursor = 0
    page._schedule_session_identity = lambda account_id: (
        "acct", "offline", "logged_in", 1
    )
    page._schedule_apply_queue_revision = 0
    page._frozen_targets = (target,)

    assert OrderConfigurationPage._freeze_dispatch_set(page) is True
    assert page._schedule_snapshot["mode"] == "live"
    assert page._schedule_snapshot["dispatch_interval_ms"] == interval_ms
    assert OrderConfigurationPage._schedule_integrity_error(page) is None


async def _scheduled_case():
    broker = AgaahBroker()
    broker_name = broker.name
    broker.scheduled_live_enabled = True
    assert broker.live_trading_enabled is False
    broker.access_token = "offline-token"
    broker.user_identifier = "offline-user"
    broker.bind_account_identity("acct")
    account = Account(account_id="acct", tradable_balance_t1=100000)
    record = SimpleNamespace(account=account, account_id="acct", broker_name=broker_name)
    sessions = SessionManager()
    sessions.register("acct", broker_name)
    sessions.begin_login("acct")
    sessions.mark_logged_in("acct", "offline-token")
    order = Order("SYM", BUY, 10, 2)
    entry = SimpleNamespace(order=order, account_id="acct", broker_name=broker_name)
    target = SimpleNamespace(entry=entry, account_id="acct", broker_name=broker_name,
                             account=account)
    instrument = BrokerInstrument(
        nsc_id="SYM", tse_id="SYM", minimum_order_quantity=1, lot_size=1,
        maximum_order_quantity_for_buy=1000, maximum_order_quantity_for_sell=1000,
        fixed_price_tick=1, lower_price_threshold=1, upper_price_threshold=1000,
    )
    broker.get_trading_state = lambda _symbol: TradingState(True, True, broker_name, "allowed")
    broker.get_buy_capacity = lambda **_kwargs: 100000
    broker.get_sell_capacity = lambda **_kwargs: 100000
    execution_id = f"lock-contract-{uuid4().hex}"
    engine = OrderEngine()
    prepared, result = engine.prepare_order(
        broker=broker, provider=SimpleNamespace(
            get_instrument=lambda _code: (None, instrument)),
        ins_code="SYM", order=order, account=account, account_id="acct",
        broker_name=broker_name, execution_id=execution_id,
    )
    assert result.success and prepared is not None

    start = datetime.now(timezone.utc) - timedelta(seconds=1)
    ready = check_live_batch_readiness(
        account_store=SimpleNamespace(get=lambda _key: record),
        authentication_service=_Auth(), session_manager=sessions,
        broker_manager=SimpleNamespace(get_for_account=lambda *_args: broker),
        targets=(target,),
        prepared_batch=PreparedBatch((prepared,), True, "", True, execution_id),
        timing=SimpleNamespace(start_time=start, end_time=start + timedelta(seconds=5)),
        interval_ms=5000, explicit_live_request=True, human_approval=True,
        planned_turns=2, execution_id=execution_id, queue_revision=1,
        engine=engine, now=datetime.now(timezone.utc),
    )
    assert ready.allowed and ready.authorization is not None
    authorization = ready.authorization
    table = reserve_schedule_table(authorization, (target,), (prepared,), 0.0, 5000)
    ticket = table.tickets[0]
    assert authorization.ticket_ledger.start_ticket(authorization, ticket).allowed
    session = _Session()
    aiohttp_stub = SimpleNamespace(
        ClientTimeout=lambda **_kwargs: nullcontext(),
        TCPConnector=lambda **_kwargs: object(),
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setitem(sys.modules, "aiohttp", aiohttp_stub)
    try:
        transport = await broker.prepare_async_order_transport(
            "acct", lambda **_kwargs: session,
            connector_factory=aiohttp_stub.TCPConnector,
        )
    finally:
        monkeypatch.undo()
    return broker, session, ticket, authorization, transport


@pytest.mark.asyncio
async def test_scheduled_live_posts_once_with_legacy_lock_closed():
    broker, session, ticket, authorization, transport = await _scheduled_case()
    try:
        result = await broker.submit_from_async_prepared_transport(
            transport, "acct", ticket.payload, ticket=ticket,
            authorization=authorization, broker=broker,
        )
    finally:
        await broker.close_async_prepared_transport(transport)
    assert result == {"isSuccess": True}
    assert len(session.posts) == 1
    assert broker.scheduled_live_enabled is True
    assert broker.live_trading_enabled is False


def test_legacy_place_order_blocked_when_scheduled_live_is_enabled():
    broker = AgaahBroker()
    broker.scheduled_live_enabled = True
    with pytest.raises(RuntimeError, match="live_trading_enabled=False"):
        broker.place_order(Order("SYM", BUY, 10, 1), live=True)
    assert broker.live_trading_enabled is False


def test_scheduled_lock_arm_restores_prior_value_on_stop():
    broker = AgaahBroker()
    broker.scheduled_live_enabled = False
    page = SimpleNamespace(_scheduled_lock_states=[(broker, False)])
    broker.scheduled_live_enabled = True
    OrderConfigurationPage._restore_scheduled_locks(page)
    assert broker.scheduled_live_enabled is False
    assert broker.live_trading_enabled is False


def test_live_batch_capture_requires_lock_after_human_confirmation(monkeypatch):
    from test_live_batch_authorization import _setup, _readiness

    state = _setup(monkeypatch)
    for broker in state["brokers"].values():
        broker.scheduled_live_enabled = False
    readiness = _readiness(state, human_approval=True)
    assert not readiness.allowed
    assert readiness.authorization is None
    assert all(broker.live_trading_enabled is True for broker in state["brokers"].values())


def test_manual_permit_submission_works_with_scheduled_live_enabled():
    from core.order_engine import OrderEngine
    from ui.live_order_gate import check_manual_live_preflight, issue_manual_live_permit

    broker = AgaahBroker()
    broker.scheduled_live_enabled = True
    assert broker.live_trading_enabled is False
    broker.access_token = "offline-token"
    broker.user_identifier = "offline-user"
    broker.bind_account_identity("acct")
    broker.get_trading_state = lambda _symbol: TradingState(True, True, broker.name, "allowed")
    broker.get_buy_capacity = lambda **_kwargs: 100000
    broker.get_sell_capacity = lambda **_kwargs: 100000
    account = Account(account_id="acct", tradable_balance_t1=100000)
    broker_name = broker.name
    record = SimpleNamespace(account=account, account_id="acct", broker_name=broker_name)
    instrument = BrokerInstrument(
        nsc_id="SYM", tse_id="SYM", minimum_order_quantity=1, lot_size=1,
        maximum_order_quantity_for_buy=1000, maximum_order_quantity_for_sell=1000,
        fixed_price_tick=1, lower_price_threshold=1, upper_price_threshold=1000,
    )
    manager = SimpleNamespace(
        get_for_account=lambda *_args: broker,
        get_instrument_provider_for_account=lambda *_args: SimpleNamespace(
            get_instrument=lambda _code: (None, instrument)),
    )
    store = SimpleNamespace(get=lambda _key: record, active_account_id=lambda: "acct")
    sessions = SessionManager()
    sessions.register("acct", broker_name)
    sessions.begin_login("acct")
    sessions.mark_logged_in("acct", "offline-token")
    order = Order("SYM", BUY, 10, 2)
    entry = SimpleNamespace(order=order, account_id="acct", broker_name=broker_name)
    provider = SimpleNamespace(get_instrument=lambda _code: (None, instrument))
    engine = OrderEngine()
    execution = f"manual-lock-contract-{uuid4().hex}"
    batch = engine.prepare_batch([dict(
        broker=broker, provider=provider, ins_code="SYM", order=order,
        account=account, account_id="acct", broker_name=broker_name,
    )], execution_id=execution)
    assert batch.valid
    check = check_manual_live_preflight(
        account_store=store, authentication_service=_Auth(), session_manager=sessions,
        broker_manager=manager, account_id="acct", broker_name=broker_name,
        execution_id=execution, entries=(entry,), prepared_batch=batch, engine=engine,
        live_selected=True, human_approval=True, include_missing_broker_ack=True,
        confirmation_acknowledged=True,
    )
    assert check.allowed
    permit, queue_fp = issue_manual_live_permit(
        execution_id=execution, account_id="acct", broker_name=broker_name,
        broker=broker, entries=(entry,), prepared_batch=batch,
        gate_decision=check.gate.evaluate(manual_broker_acknowledged=True),
        confirmation_acknowledged=True, include_missing_broker_ack=True,
    )
    transport = _ManualTransport()
    broker.prepare_manual_order_sender = lambda account_id: AgaahBroker.prepare_manual_order_sender(
        broker, account_id, transport_factory=lambda: transport,
    )
    try:
        sent = engine.submit_manual_prepared_order(
            batch.orders[0], permit=permit, broker=broker, account=account,
            account_id="acct", broker_name=broker_name, queue_fingerprint=queue_fp,
            index=0, acknowledge_missing_broker_readiness=True,
        )
    finally:
        permit.close()
    assert sent.success and sent.sent
    assert len(transport.posts) == 1
    assert transport.closed
    assert broker.live_trading_enabled is False
    assert broker.scheduled_live_enabled is True


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidation", ["queue_change", "session_invalidation"])
async def test_apply_confirm_due_posts_once_and_closes_runtime(monkeypatch, invalidation):
    """Drive real UI prearm, gates, authorization and runtime entirely offline."""
    from zoneinfo import ZoneInfo

    from ui.account_store import AccountStore
    from ui.order_configuration_page import OrderConfigurationPage
    from ui.prearm_service import LivePrearmService
    from PySide6.QtWidgets import QApplication
    import socket

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def local_connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            raise AssertionError("External network access is forbidden in this test")
        return original_connect(sock, address)

    def local_connect_ex(sock, address):
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            raise AssertionError("External network access is forbidden in this test")
        return original_connect_ex(sock, address)

    def block_network(*_args, **_kwargs):
        raise AssertionError("Network access is forbidden in this test")

    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", local_connect_ex)
    monkeypatch.setattr(socket, "create_connection", block_network)

    app = QApplication.instance() or QApplication([])

    import asyncio

    class _AsyncResponse:
        def __init__(self, session, post_index):
            self._session = session
            self._post_index = post_index

        status = 200

        def raise_for_status(self):
            return None

        async def json(self):
            if self._post_index == 1:
                self._session.first_response_waiting.set()
                await self._session.release_first_response.wait()
            return {"isSuccess": True, "data": {"decisionId": "offline-decision"}}

    class _AsyncPost:
        def __init__(self, session, post_index):
            self._session = session
            self._post_index = post_index

        async def __aenter__(self):
            return _AsyncResponse(self._session, self._post_index)

        async def __aexit__(self, *_args):
            return False

    class _AsyncSession:
        def __init__(self, **_kwargs):
            self.posts = []
            self.post_correlations = []
            self.closed = False
            self.release_first_response = asyncio.Event()
            self.first_response_waiting = asyncio.Event()
            self.second_post_started = asyncio.Event()

        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            post_index = len(self.posts)
            ticket = transport._instrument_ticket
            assert ticket.payload == kwargs["json"]
            order_index = next(
                index for index, entry in enumerate(page._schedule_queue_entries)
                if entry is ticket.queue_entry
            )
            self.post_correlations.append(
                (kwargs["json"], (ticket.turn_index, order_index), ticket.ticket_id)
            )
            if post_index == 2:
                self.second_post_started.set()
            return _AsyncPost(self, post_index)

        async def close(self):
            self.closed = True

    broker = AgaahBroker()
    broker.scheduled_live_enabled = True
    assert broker.live_trading_enabled is False
    broker.access_token = "offline-token"
    broker.user_identifier = "offline-user"
    broker.bind_account_identity("acct")
    broker.get_trading_state = lambda _symbol: TradingState(True, True, broker.name, "allowed")
    broker.get_buy_capacity = lambda **_kwargs: 100000
    broker.get_sell_capacity = lambda **_kwargs: 100000
    instrument = BrokerInstrument(
        nsc_id="SYM", tse_id="SYM", minimum_order_quantity=1, lot_size=1,
        maximum_order_quantity_for_buy=1000, maximum_order_quantity_for_sell=1000,
        fixed_price_tick=1, lower_price_threshold=1, upper_price_threshold=1000,
    )
    provider = SimpleNamespace(get_instrument=lambda _code: (None, instrument))

    class _Manager:
        def get_for_account(self, _account_id, _broker_name):
            return broker

        def get_instrument_provider_for_account(self, _account_id, _broker_name):
            return provider

    manager = _Manager()
    store = AccountStore()
    store.add("acct", broker.name, "offline").account.tradable_balance_t1 = 100000
    store.set_active("acct")
    sessions = SessionManager()
    sessions.register("acct", broker.name)
    sessions.begin_login("acct")
    sessions.mark_logged_in("acct", "offline-token")
    auth = _Auth()
    auth.get_purchase_power = lambda _account_id: 100000

    import ui.order_configuration_page as page_module
    from ui import scheduled_fire_runtime as runtime_module

    apply_clock = datetime.now(ZoneInfo("Asia/Tehran")).replace(microsecond=0)
    now = apply_clock + timedelta(minutes=2)
    monkeypatch.setattr(page_module, "system_wall_now", lambda: apply_clock)
    monkeypatch.setattr(page_module, "sample_system_clocks", lambda: (apply_clock, 0.0))
    monkeypatch.setattr(page_module, "system_monotonic", lambda: 0.0)
    monkeypatch.setattr(page_module, "schedule_monotonic", lambda: 0.0)

    page = OrderConfigurationPage(store)
    page.set_session_manager(sessions)
    page.set_manual_live_services(lambda: manager, lambda: auth)
    page.set_order_authorizer_factory(
        lambda: lambda account_id, broker_name: __import__(
            "ui.order_authorization", fromlist=["authorize_destination"]
        ).authorize_destination(store, auth, sessions, account_id, broker_name)
    )
    diagnostics = []
    class _ObservedPrearm(LivePrearmService):
        def prepare(self, targets):
            execution_id, batch = super().prepare(targets)
            diagnostics.append(("prearm", batch))
            return execution_id, batch

    def batch_gate(**kwargs):
        result = check_live_batch_readiness(
            account_store=store, authentication_service=auth, session_manager=sessions,
            broker_manager=manager, **kwargs,
        )
        diagnostics.append(("gate", result))
        return result

    page.set_live_prearm_factory(lambda _targets: _ObservedPrearm(store, sessions, manager))
    page.set_live_batch_gate_factory(batch_gate)
    from ui.live_order_gate import validate_live_batch_authorization
    page.set_live_batch_validator(lambda **kwargs: validate_live_batch_authorization(
        account_store=store, authentication_service=auth, session_manager=sessions,
        broker_manager=manager, **kwargs,
    ))
    runtime_factory_calls = []
    ui_runtime_closes = []
    ticket_stages = {}
    due_gates = {}
    ticket_trace = {}
    def runtime_factory(**kwargs):
        runtime = runtime_module.ScheduledFireRuntime(
            monotonic_clock=lambda: -0.1, **kwargs,
        )
        original_close = runtime.close
        def observed_close():
            ui_runtime_closes.append(runtime)
            return original_close()
        runtime.close = observed_close
        runtime_factory_calls.append(runtime)
        return runtime
    page.set_scheduled_runtime_factory(runtime_factory)
    page.set_scheduled_broker_manager_factory(lambda: manager)
    page.set_live_confirmation_handler(lambda _summary: True)
    original_asyncio_sleep = asyncio.sleep
    submitted_cleanup = []
    original_submit = asyncio.run_coroutine_threadsafe
    def observe_submission(coroutine, loop):
        coroutine_name = coroutine.__qualname__
        future = original_submit(coroutine, loop)
        if runtime_factory_calls and loop is runtime_factory_calls[-1]._loop:
            submitted_cleanup.append((coroutine_name, future))
        return future
    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", observe_submission)

    async def controlled_sleep(delay, *args, **kwargs):
        task = asyncio.current_task()
        name = task.get_name() if task is not None else ""
        if name.startswith("scheduled-ticket-"):
            ticket_id = name.removeprefix("scheduled-ticket-")
            ticket_stages.setdefault(ticket_id, []).append("due")
            await due_gates.setdefault(ticket_id, asyncio.Event()).wait()
            return
        return await original_asyncio_sleep(delay, *args, **kwargs)

    monkeypatch.setattr(runtime_module.asyncio, "sleep", controlled_sleep)
    sessions_live = _AsyncSession
    aiohttp_stub = SimpleNamespace(
        ClientSession=sessions_live,
        ClientTimeout=lambda **_kwargs: nullcontext(),
        TCPConnector=lambda **_kwargs: object(),
    )
    monkeypatch.setitem(sys.modules, "aiohttp", aiohttp_stub)

    order = Order("SYM", BUY, 10, 2, ins_code="12345")
    second_order = Order("SYM", BUY, 20, 2, ins_code="12345")
    page.order_queue.enqueue(order, "acct", broker.name)
    page.order_queue.enqueue(second_order, "acct", broker.name)
    page.live_mode_button.click()
    page.schedule_start_input.setText(now.strftime("%H:%M:%S"))
    page.schedule_end_input.setText((now + timedelta(seconds=6)).strftime("%H:%M:%S"))
    page.schedule_interval_input.setText("15")
    page.dispatch_interval_input.setText("5000")
    page.apply_schedule_button.click()
    app.processEvents()
    runtime = page._scheduled_fire_runtime
    try:
        if runtime is None:
            pytest.fail(f"{page.schedule_summary_label.text()} diagnostics={diagnostics!r}")
        assert page._schedule_locked, page.schedule_summary_label.text()
        assert "منقضی" not in page._schedule_state
        assert page._live_authorization is not None
        assert page._live_authorization.ticket_ledger is not None
        assert broker.live_trading_enabled is False
        tickets = page._scheduled_send_table.tickets
        for ticket in tickets:
            due_gates.setdefault(ticket.ticket_id, asyncio.Event())
            ticket_stages.setdefault(ticket.ticket_id, [])
            ticket_trace.setdefault(ticket.ticket_id, [])
        assert len(tickets) == 4
        assert (page._scheduled_send_table.order_count,
                page._scheduled_send_table.planned_turns) == (2, 2)
        expected_cells = [(turn, id(entry))
                          for turn in range(2)
                          for entry in page._schedule_queue_entries]
        assert [(ticket.turn_index, id(ticket.queue_entry)) for ticket in tickets] == expected_cells
        due = tickets[0].due_mono
        second_due = tickets[2].due_mono
        assert tickets[1].due_mono == due
        assert tickets[3].due_mono == second_due > due
        assert due > runtime._clock(), "first ticket must remain in the future"
        assert len(runtime._tasks) == len(page._scheduled_send_table.tickets)
        assert all(not task.done() for task in runtime._tasks.values())
        assert len(runtime._transports) == 1

        transport = next(iter(runtime._transports.values()))
        fake_session = transport._session
        ledger = page._live_authorization.ticket_ledger
        original_start_ticket = ledger.start_ticket
        def observed_start_ticket(authorization, ticket):
            result = original_start_ticket(authorization, ticket)
            ticket_trace[ticket.ticket_id].append(("start_ticket", result.allowed, result.reason))
            return result
        ledger.start_ticket = observed_start_ticket

        original_handoff = broker.submit_from_async_prepared_transport
        async def observed_handoff(*args, **kwargs):
            ticket = kwargs.get("ticket")
            ticket_trace[ticket.ticket_id].append(("handoff", "entered"))
            return await original_handoff(*args, **kwargs)
        broker.submit_from_async_prepared_transport = observed_handoff

        original_authorized = broker._scheduled_ticket_is_authorized
        def observed_authorized(ticket, authorization):
            result = original_authorized(ticket, authorization)
            ticket_trace[ticket.ticket_id].append(("authorized", result, "" if result else "scheduled ticket authorization is invalid"))
            return result
        broker._scheduled_ticket_is_authorized = observed_authorized

        original_submit_ticket = transport.submit_ticket
        async def observed_submit_ticket(ticket, authorization, broker_arg, payload=None, on_post_start=None):
            ticket_trace[ticket.ticket_id].append(("submit_ticket", "entered"))
            transport._instrument_ticket = ticket
            def observed_callback():
                ticket_trace[ticket.ticket_id].append(("post_started", "called"))
                return on_post_start() if callable(on_post_start) else None
            return await original_submit_ticket(ticket, authorization, broker_arg, payload=payload,
                                                on_post_start=observed_callback)
        transport.submit_ticket = observed_submit_ticket

        original_begin_post = ledger.begin_post
        def observed_begin_post(authorization, ticket):
            result = original_begin_post(authorization, ticket)
            ticket_trace[ticket.ticket_id].append(("begin_post", result, "" if result else "ledger.begin_post returned False"))
            return result
        ledger.begin_post = observed_begin_post

        original_session_post = transport._session.post
        def observed_session_post(url, **kwargs):
            match = next(ticket for ticket in tickets if ticket.payload == kwargs.get("json"))
            ticket_trace[match.ticket_id].append(("session.post", "called"))
            return original_session_post(url, **kwargs)
        transport._session.post = observed_session_post
        runtime._clock = lambda: due - 0.001
        runtime._call(asyncio.sleep(0.02))
        assert transport._session.posts == [], "no POST may start before the first due time"

        first_ticket = tickets[0]
        runtime._clock = lambda: due
        async def _wait_until(predicate):
            while not predicate():
                await original_asyncio_sleep(0)

        runtime._call(_wait_until(lambda: "due" in ticket_stages[first_ticket.ticket_id]))
        ticket_trace[first_ticket.ticket_id].append(("due", "reached"))
        due_gates[first_ticket.ticket_id].set()
        runtime._call(_wait_until(lambda: len(transport._session.posts) == 1))
        runtime._call(_wait_until(lambda: transport._session.first_response_waiting.is_set()))
        assert first_ticket.ticket_id in runtime._started
        changed_order = Order("SYM", BUY, 30, 1, ins_code="12345")
        if invalidation == "queue_change":
            page.order_queue.enqueue(changed_order, "acct", broker.name)
            assert page._schedule_cancel_event.is_set()
            assert page._schedule_cancel_reason == "QUEUE_CHANGED"
        else:
            invalidated = sessions.invalidate_session("acct")
            assert invalidated.state.value == "logged_out"
            assert page._schedule_cancel_event.is_set()
            assert page._schedule_cancel_reason == "SESSION_CHANGED"
        assert runtime.stop_reason() == "USER_STOP"
        runtime.stop()
        await asyncio.sleep(0.02)
        assert len(transport._session.posts) == 1
        assert [row[2] for row in transport._session.post_correlations] == [first_ticket.ticket_id]
        assert first_ticket.ticket_id in runtime._started
        transport._session.release_first_response.set()
        runtime._call(_wait_until(lambda: first_ticket.ticket_id in runtime._outcomes))
        outcomes = runtime.outcomes()
        assert outcomes[first_ticket.ticket_id]["isSuccess"] is True
        if invalidation == "queue_change":
            assert all(payload["quantity"] != changed_order.quantity
                       for _url, kwargs in transport._session.posts
                       for payload in (kwargs["json"],))
        unstarted_tickets = [ticket for ticket in tickets if ticket is not first_ticket]
        assert all(ticket.ticket_id not in runtime._started for ticket in unstarted_tickets)
        assert all(ticket.ticket_id not in runtime._unknown_ticket_ids for ticket in unstarted_tickets)
        assert len(fake_session.posts) == 1
        app.processEvents()
        assert len(fake_session.posts) == 1
    finally:
        if runtime is not None:
            transport = transport or next(iter(runtime._transports.values()), None)
            if transport is not None and transport._session is not None:
                transport._session.release_first_response.set()

            async def _cleanup_runtime():
                runtime._cancelled = True
                runtime._closing = True
                for ticket_id, task in runtime._tasks.items():
                    if ticket_id not in runtime._started and not task.done():
                        task.cancel()
                if runtime._tasks:
                    await asyncio.gather(*runtime._tasks.values(), return_exceptions=True)
                await runtime._close()
                runtime._loop.call_soon(runtime._loop.stop)

            if runtime in ui_runtime_closes:
                assert runtime._closing
                await asyncio.wait_for(
                    asyncio.to_thread(runtime.wait_closed), timeout=15
                )
            else:
                pytest_loop = asyncio.get_running_loop()
                cleanup_future = pytest_loop.create_future()

                def start_cleanup_on_runtime_loop():
                    task = runtime._loop.create_task(_cleanup_runtime())

                    def finish_cleanup(completed):
                        try:
                            result = completed.result()
                        except BaseException as exc:
                            pytest_loop.call_soon_threadsafe(
                                cleanup_future.set_exception, exc
                            )
                        else:
                            pytest_loop.call_soon_threadsafe(
                                cleanup_future.set_result, result
                            )

                    task.add_done_callback(finish_cleanup)

                runtime._loop.call_soon_threadsafe(start_cleanup_on_runtime_loop)
                await asyncio.wait_for(cleanup_future, timeout=15)
            assert runtime.wait_closed()
    assert fake_session is not None
    assert fake_session.closed
    assert len(fake_session.posts) == 1
    assert transport._closed
    assert transport._session is None
    assert broker.live_trading_enabled is False
    assert broker.scheduled_live_enabled is True


@pytest.mark.asyncio
async def test_apply_two_orders_two_turns_posts_all_tickets(monkeypatch):
    """Apply a real two-order schedule and verify every ticket submission."""
    from zoneinfo import ZoneInfo
    from ui.account_store import AccountStore
    from ui.order_configuration_page import OrderConfigurationPage
    from ui.prearm_service import LivePrearmService
    from PySide6.QtWidgets import QApplication
    import asyncio
    import socket

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    def local_connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            raise AssertionError("External network access is forbidden in this test")
        return original_connect(sock, address)
    def local_connect_ex(sock, address):
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            raise AssertionError("External network access is forbidden in this test")
        return original_connect_ex(sock, address)
    def block_network(*_args, **_kwargs):
        raise AssertionError("Network access is forbidden in this test")
    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", local_connect_ex)
    monkeypatch.setattr(socket, "create_connection", block_network)

    app = QApplication.instance() or QApplication([])
    class _Response:
        status = 200
        def raise_for_status(self):
            return None
        async def json(self):
            return {"isSuccess": True, "data": {"decisionId": "offline-decision"}}
    class _Post:
        async def __aenter__(self):
            return _Response()
        async def __aexit__(self, *_args):
            return False
    class _Session:
        def __init__(self, **_kwargs):
            self.posts = []
            self.closed = False
        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            ticket = transport._instrument_ticket
            order_index = next(i for i, entry in enumerate(page._schedule_queue_entries)
                               if entry is ticket.queue_entry)
            correlations.append((ticket, ticket.turn_index, order_index, kwargs["json"]))
            return _Post()
        async def close(self):
            self.closed = True

    broker = AgaahBroker()
    broker.scheduled_live_enabled = True
    broker.access_token = "offline-token"
    broker.user_identifier = "offline-user"
    broker.bind_account_identity("acct")
    broker.get_trading_state = lambda _symbol: TradingState(True, True, broker.name, "allowed")
    broker.get_buy_capacity = lambda **_kwargs: 100000
    broker.get_sell_capacity = lambda **_kwargs: 100000
    instrument = BrokerInstrument(
        nsc_id="SYM", tse_id="SYM", minimum_order_quantity=1, lot_size=1,
        maximum_order_quantity_for_buy=1000, maximum_order_quantity_for_sell=1000,
        fixed_price_tick=1, lower_price_threshold=1, upper_price_threshold=1000,
    )
    provider = SimpleNamespace(get_instrument=lambda _code: (None, instrument))
    class _Manager:
        def get_for_account(self, _account_id, _broker_name):
            return broker
        def get_instrument_provider_for_account(self, _account_id, _broker_name):
            return provider
    manager = _Manager()
    store = AccountStore()
    account_record = store.add("acct", broker.name, "offline")
    assert account_record.account.tradable_balance_t1 is None
    original_account = account_record.account
    store.set_active("acct")
    sessions = SessionManager()
    sessions.register("acct", broker.name)
    sessions.begin_login("acct")
    sessions.mark_logged_in("acct", "offline-token")
    auth = _Auth()
    purchase_power_reads = []
    def get_purchase_power(account_id):
        purchase_power_reads.append(account_id)
        return 100000
    auth.get_purchase_power = get_purchase_power
    import ui.order_configuration_page as page_module
    from ui import scheduled_fire_runtime as runtime_module
    apply_clock = datetime.now(ZoneInfo("Asia/Tehran")).replace(microsecond=0)
    now = apply_clock + timedelta(minutes=2)
    monkeypatch.setattr(page_module, "system_wall_now", lambda: apply_clock)
    monkeypatch.setattr(page_module, "sample_system_clocks", lambda: (apply_clock, 0.0))
    monkeypatch.setattr(page_module, "system_monotonic", lambda: 0.0)
    monkeypatch.setattr(page_module, "schedule_monotonic", lambda: 0.0)
    page = OrderConfigurationPage(store)
    page.set_session_manager(sessions)
    page.set_manual_live_services(lambda: manager, lambda: auth)
    page.set_order_authorizer_factory(lambda: lambda account_id, broker_name: __import__(
        "ui.order_authorization", fromlist=["authorize_destination"]
    ).authorize_destination(store, auth, sessions, account_id, broker_name))
    page.set_live_prearm_factory(lambda _targets: LivePrearmService(store, sessions, manager))
    page.set_live_batch_gate_factory(lambda **kwargs: check_live_batch_readiness(
        account_store=store, authentication_service=auth, session_manager=sessions,
        broker_manager=manager, **kwargs,
    ))
    from ui.live_order_gate import validate_live_batch_authorization
    page.set_live_batch_validator(lambda **kwargs: validate_live_batch_authorization(
        account_store=store, authentication_service=auth, session_manager=sessions,
        broker_manager=manager, **kwargs,
    ))
    runtime = None
    original_sleep = asyncio.sleep
    due_events = {}
    due_waiting = set()
    async def controlled_sleep(delay, *args, **kwargs):
        task = asyncio.current_task()
        name = task.get_name() if task else ""
        if name.startswith("scheduled-ticket-"):
            ticket_id = name.removeprefix("scheduled-ticket-")
            due_waiting.add(ticket_id)
            await due_events.setdefault(ticket_id, asyncio.Event()).wait()
            return
        return await original_sleep(delay, *args, **kwargs)
    monkeypatch.setattr(runtime_module.asyncio, "sleep", controlled_sleep)
    aiohttp_stub = SimpleNamespace(
        ClientSession=_Session,
        ClientTimeout=lambda **_kwargs: nullcontext(),
        TCPConnector=lambda **_kwargs: object(),
    )
    monkeypatch.setitem(sys.modules, "aiohttp", aiohttp_stub)
    correlations = []
    runtime_calls = []
    def runtime_factory(**kwargs):
        instance = runtime_module.ScheduledFireRuntime(monotonic_clock=lambda: -0.1, **kwargs)
        runtime_calls.append(instance)
        return instance
    page.set_scheduled_runtime_factory(runtime_factory)
    page.set_scheduled_broker_manager_factory(lambda: manager)
    page.set_live_confirmation_handler(lambda _summary: True)
    page.order_queue.enqueue(Order("SYM", BUY, 10, 2, ins_code="12345"), "acct", broker.name)
    page.order_queue.enqueue(Order("SYM", BUY, 20, 2, ins_code="12345"), "acct", broker.name)
    page.live_mode_button.click()
    page.schedule_start_input.setText(now.strftime("%H:%M:%S"))
    page.schedule_end_input.setText((now + timedelta(seconds=6)).strftime("%H:%M:%S"))
    page.schedule_interval_input.setText("15")
    page.dispatch_interval_input.setText("5000")
    page.apply_schedule_button.click()
    app.processEvents()
    runtime = page._scheduled_fire_runtime
    transport = None
    fake_session = None
    try:
        assert runtime is not None, page.schedule_summary_label.text()
        assert purchase_power_reads == ["acct"]
        assert account_record.account is original_account
        assert account_record.account.tradable_balance_t1 == 100000
        assert page._schedule_locked
        assert page._live_authorization is not None
        tickets = page._scheduled_send_table.tickets
        assert len(tickets) == 4
        assert (page._scheduled_send_table.order_count,
                page._scheduled_send_table.planned_turns) == (2, 2)
        transport = next(iter(runtime._transports.values()))
        fake_session = transport._session
        original_submit = transport.submit_ticket
        async def observed_submit(ticket, authorization, broker_arg, payload=None, on_post_start=None):
            transport._instrument_ticket = ticket
            return await original_submit(ticket, authorization, broker_arg,
                                         payload=payload, on_post_start=on_post_start)
        transport.submit_ticket = observed_submit
        runtime._clock = lambda: tickets[0].due_mono
        for ticket in tickets:
            due_events.setdefault(ticket.ticket_id, asyncio.Event())
        async def wait_until(predicate):
            while not predicate():
                await original_sleep(0)
        runtime._call(wait_until(lambda: all(
            ticket.ticket_id in due_waiting
            for ticket in tickets[:2]
        )))
        for ticket in tickets[:2]:
            due_events[ticket.ticket_id].set()
        runtime._call(wait_until(lambda: len(fake_session.posts) == 2))
        second_due = tickets[2].due_mono
        runtime._clock = lambda: second_due
        runtime._call(wait_until(lambda: all(
            ticket.ticket_id in due_waiting
            for ticket in tickets[2:]
        )))
        for ticket in tickets[2:]:
            due_events[ticket.ticket_id].set()
        runtime._call(wait_until(lambda: len(fake_session.posts) == 4))
        runtime._call(wait_until(lambda: len(runtime._outcomes) == 4))
        expected = [(ticket.ticket_id, ticket.turn_index,
                     next(i for i, entry in enumerate(page._schedule_queue_entries)
                          if entry is ticket.queue_entry)) for ticket in tickets]
        actual = [(ticket.ticket_id, turn, order_index)
                  for ticket, turn, order_index, _payload in correlations]
        assert len(fake_session.posts) == 4
        assert actual == expected
        assert set(runtime._outcomes) == {ticket.ticket_id for ticket in tickets}
        assert all(runtime._outcomes[ticket.ticket_id]["isSuccess"] is True for ticket in tickets)
    finally:
        if runtime is not None:
            if fake_session is not None:
                # All fake responses are immediate; no response remains blocked.
                pass
            async def cleanup():
                runtime._cancelled = True
                runtime._closing = True
                for task in runtime._tasks.values():
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*runtime._tasks.values(), return_exceptions=True)
                await runtime._close()
                runtime._loop.call_soon(runtime._loop.stop)
            pytest_loop = asyncio.get_running_loop()
            done = pytest_loop.create_future()
            def launch_cleanup():
                task = runtime._loop.create_task(cleanup())
                def on_done(completed):
                    try:
                        value = completed.result()
                    except BaseException as exc:
                        pytest_loop.call_soon_threadsafe(done.set_exception, exc)
                    else:
                        pytest_loop.call_soon_threadsafe(done.set_result, value)
                task.add_done_callback(on_done)
            runtime._loop.call_soon_threadsafe(launch_cleanup)
            await asyncio.wait_for(done, timeout=15)
            assert runtime.wait_closed()
    assert fake_session.closed
    assert transport._closed and transport._session is None
