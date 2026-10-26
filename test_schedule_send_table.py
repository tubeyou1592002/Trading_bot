"""Offline acceptance of the pre-countdown schedule ticket reservation."""

from dataclasses import replace
from uuid import uuid4

import pytest
import time
from types import SimpleNamespace

from core.live_order_authorization import (
    LiveAuthorizationError,
    ScheduledSendTable,
    reserve_schedule_table,
)
from core.order_engine import PreparedBatch
from test_live_batch_authorization import _readiness, _setup
from ui.live_order_gate import check_live_batch_readiness
from types import SimpleNamespace
from datetime import timedelta
from core.order_engine import OrderEngine


def _table(state, authorization, turns=3):
    from core.live_order_authorization import ScheduledSendTable, ScheduledSendTicket
    tickets = []
    for turn in range(authorization.snapshot.schedule.planned_turns):
        for target in state["targets"]:
            prepared = next(item for item in state["prepared"]
                            if item.order is target.entry.order)
            snapshot = next(item for item in authorization.snapshot.orders
                            if item.entry_identity == id(target.entry))
            tickets.append(ScheduledSendTicket(
                authorization.snapshot.execution_id, uuid4().hex, target.entry,
                prepared, turn, 100.0 + turn * 5, prepared.payload_json,
                target.account_id, target.broker_name,
                authorization.authorization_id, snapshot.order_fingerprint,
                snapshot.prepared_fingerprint,
            ))
    return ScheduledSendTable(
        authorization.snapshot.execution_id, authorization.authorization_id,
        tuple(tickets), authorization.snapshot.schedule.order_count,
        authorization.snapshot.schedule.planned_turns,
    )


def _approved(state, turns=3):
    return check_live_batch_readiness(
        account_store=SimpleNamespace(get=lambda key: state["records"][key]),
        authentication_service=state["auth"],
        session_manager=state["sessions"],
        broker_manager=state["manager"],
        targets=state["targets"],
        prepared_batch=PreparedBatch(
            state["prepared"], True, "", True, state["execution_id"]
        ),
        timing=state["timing"], interval_ms=5000,
        explicit_live_request=True, human_approval=True,
        planned_turns=turns, execution_id=state["execution_id"],
        queue_revision=42, engine=state["engine"], now=state["now"],
        first_due_mono=100.0,
    )


def test_exact_full_table_and_atomic_reservation(monkeypatch):
    state = _setup(monkeypatch)
    ready = _approved(state, turns=3)
    table = ready.send_table
    assert len(table.tickets) == 6
    assert len({ticket.ticket_id for ticket in table.tickets}) == 6
    assert len(table.tickets_for_turn(1)) == 2
    consumed = ready.authorization.ticket_ledger.consume(
        ready.authorization, table.tickets[0]
    )
    assert consumed.allowed
    assert not ready.authorization.ticket_ledger.consume(
        ready.authorization, table.tickets[0]
    ).allowed
    assert all(not broker.submits for broker in state["brokers"].values())


def test_incomplete_or_duplicate_table_does_not_reserve(monkeypatch):
    state = _setup(monkeypatch)
    authorization = _readiness(state, turns=3).authorization
    table = _table(state, authorization)
    with pytest.raises(LiveAuthorizationError, match="incomplete"):
        replace(table, tickets=table.tickets[:-1])
    with pytest.raises(LiveAuthorizationError, match="unique"):
        replace(table, tickets=table.tickets[:-1] + (table.tickets[0],))
    assert not authorization.ticket_ledger._reserved


def test_reservation_rejects_changed_destination_or_payload(monkeypatch):
    state = _setup(monkeypatch)
    authorization = _readiness(state, turns=3).authorization
    from types import SimpleNamespace
    original = state["targets"][0]
    bad_target = SimpleNamespace(
        entry=original.entry, account_id="OTHER", broker_name="OTHER",
        account=original.account,
    )
    with pytest.raises(LiveAuthorizationError, match="binding"):
        reserve_schedule_table(
            authorization, (bad_target, state["targets"][1]), state["prepared"],
            100.0, 5000,
        )
    changed = replace(state["prepared"][0], payload_json="{}")
    with pytest.raises(LiveAuthorizationError, match="payload"):
        reserve_schedule_table(
            authorization, state["targets"], (changed, state["prepared"][1]),
            100.0, 5000,
        )
    assert not authorization.ticket_ledger._reserved


def _large_ready(monkeypatch, order_count=10, turns=80):
    state = _setup(monkeypatch)
    base_targets = state["targets"]
    base_prepared = state["prepared"]
    targets = []
    prepared = []
    target_accounts = {}
    for index in range(order_count):
        source = base_targets[index % len(base_targets)]
        account_id, broker_name = source.account_id, source.broker_name
        order = replace(source.entry.order)
        order.quantity += index
        entry = SimpleNamespace(order=order, account_id=account_id,
                                broker_name=broker_name)
        account = replace(source.account)
        target_accounts[account_id] = account
        target = SimpleNamespace(entry=entry, account_id=account_id,
                                 broker_name=broker_name, account=account)
        targets.append(target)
        prepared.append(replace(
            base_prepared[index % len(base_prepared)], order=order,
            order_fingerprint=state["engine"]._fingerprint(order.to_payload()),
            evidence_order_fingerprint=state["engine"]._fingerprint(order.to_payload()),
            execution_id=state["execution_id"],
        ))
    # Build a fully-shaped offline authorization snapshot from the accepted
    # destination evidence, with unique entry/order bindings for each cell.
    from core.live_order_authorization import (
        MODE_ALLOWED, OrderAuthorizationSnapshot, build_snapshot,
        issue_authorization, m6_fingerprint, payload_fingerprint,
        prepared_fingerprint,
    )
    original = _readiness(state, turns=3).authorization.snapshot
    destination_by_key = {(d.account_id, d.broker_name): d
                          for d in original.destinations}
    orders = []
    for target, item in zip(targets, prepared):
        orders.append(OrderAuthorizationSnapshot(
            entry_identity=id(target.entry), order_identity=id(item.order),
            order_fingerprint=state["engine"]._fingerprint(item.order.to_payload()),
            payload_fingerprint=payload_fingerprint(item.payload_json),
            payload_json=item.payload_json, account_id=target.account_id,
            broker_name=target.broker_name,
            broker_identity=item.broker_identity, prepared_identity=id(item),
            prepared_fingerprint=prepared_fingerprint(item),
            m6_fingerprint=m6_fingerprint(item),
            m6_completed_at=item.m6_completed_at, prepared_at=item.prepared_at,
            m6_passed=True, scheduled_valid=True,
            execution_id=state["execution_id"],
        ))
    from core.live_order_authorization import ScheduleSnapshot
    start = state["timing"].start_time
    schedule = ScheduleSnapshot(start, start + timedelta(milliseconds=79000),
                                1000.0, turns, order_count, order_count * turns)
    snapshot = build_snapshot(
        orders=tuple(orders),
            destinations=tuple(replace(
                destination_by_key[(key[0], key[1])],
                account_identity=id(target_accounts[key[0]]),
                account_fingerprint=__import__("core.live_order_authorization",
                    fromlist=["fingerprint"]).fingerprint(vars(target_accounts[key[0]])),
            ) for key in dict.fromkeys((t.account_id, t.broker_name) for t in targets)),
        schedule=schedule, execution_id=state["execution_id"],
        queue_revision=42, queue_fingerprint="offline-queue",
    )
    authorization = issue_authorization(
        snapshot, explicit_live_request=True, human_approval=True,
        gate_mode=MODE_ALLOWED, gate_reason="offline test", issued_at=state["now"],
    )
    table = reserve_schedule_table(authorization, targets, prepared, 500.0, 1000.0)
    return state, authorization, table, targets, prepared


def test_ten_orders_eighty_turns_reserve_exactly_800_tickets(monkeypatch):
    state, authorization, table, targets, prepared = _large_ready(monkeypatch)
    runtime = None
    assert len(table.tickets) == 800
    assert len(table.tickets_for_turn(0)) == 10
    assert len(table.tickets_for_turn(79)) == 10
    assert len(authorization.ticket_ledger._reserved) == 800
    assert len({ticket.ticket_id for ticket in table.tickets}) == 800
    assert all(not broker.submits for broker in state["brokers"].values())


def test_reserved_ticket_hand_off_is_once_and_does_not_retry(monkeypatch):
    state, authorization, table, targets, prepared = _large_ready(monkeypatch)
    engine = OrderEngine()
    ticket = table.tickets[0]
    broker = state["brokers"][(ticket.account_id, ticket.broker_name)]
    first = engine.submit_reserved_ticket(ticket, authorization, broker,
                                          targets[0].account)
    assert first.success
    count_after_first = len(broker.submits)
    duplicate = engine.submit_reserved_ticket(ticket, authorization, broker,
                                              targets[0].account)
    assert not duplicate.success
    assert len(broker.submits) == count_after_first
    another = table.tickets[1]
    another_broker = state["brokers"][(another.account_id, another.broker_name)]
    second = engine.submit_reserved_ticket(another, authorization, another_broker,
                                           targets[1].account)
    assert second.success
    assert len(another_broker.submits) == 1


@pytest.mark.parametrize("tamper", ["payload", "fingerprint"])
def test_tampered_ticket_payload_or_prepared_fingerprint_is_not_handed_off(
        monkeypatch, tamper):
    state, authorization, table, targets, prepared = _large_ready(monkeypatch)
    ticket = table.tickets[0]
    if tamper == "payload":
        ticket = replace(ticket, payload_json='{"tampered":true}')
    else:
        prepared_item = replace(ticket.prepared_order, payload_json='{"tampered":true}')
        ticket = replace(ticket, prepared_order=prepared_item)
    broker = state["brokers"][(ticket.account_id, ticket.broker_name)]
    before = len(broker.submits)
    result = OrderEngine().submit_reserved_ticket(
        ticket, authorization, broker, targets[0].account,
    )
    assert not result.success
    assert len(broker.submits) == before


def test_ticket_handoff_uses_no_db_readiness_m6_or_retry(monkeypatch):
    state, authorization, table, targets, prepared = _large_ready(monkeypatch)
    ticket = table.tickets[0]
    broker = state["brokers"][(ticket.account_id, ticket.broker_name)]
    broker.submit_prepared_order = lambda payload, live=False: (_ for _ in ()).throw(
        TimeoutError("ambiguous timeout")
    )
    def forbidden(*_args, **_kwargs):
        raise AssertionError("runtime must not reread readiness, DB or M6")
    engine = OrderEngine()
    engine.validate_prepared_order = forbidden
    result = engine.submit_reserved_ticket(ticket, authorization, broker,
                                           targets[0].account)
    assert not result.success
    assert "ambiguous timeout" in result.message
    assert not engine.submit_reserved_ticket(
        ticket, authorization, broker, targets[0].account
    ).success


def test_prestarted_async_runtime_starts_every_ticket_without_factory_after_arm(monkeypatch):
    import asyncio
    import json
    import time
    from ui.scheduled_fire_runtime import ScheduledFireRuntime

    state, authorization, table, targets, prepared = _large_ready(monkeypatch)
    factory_calls = {"sessions": 0}
    submitted = []
    class FakeResponse:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None
        def raise_for_status(self):
            return None
        async def json(self):
            return {"isSuccess": True}
    class FakeSession:
        def __init__(self, **_):
            factory_calls["sessions"] += 1
            self.posts = []
        def post(self, url, **kwargs):
            self.posts.append((url, kwargs["json"]))
            return FakeResponse()
        async def close(self):
            return None
    account_brokers = dict(state["brokers"])
    for broker in account_brokers.values():
        broker._session_factory_calls = 0
    for key, broker in account_brokers.items():
        broker.bind_account_identity = lambda account_id, k=key: setattr(
            broker, "_account_id", account_id
        ) if account_id == k[0] else (_ for _ in ()).throw(RuntimeError())
        broker._account_id = key[0]
        broker._async_prepared_transports = set()
        async def prepare(account_id, session_factory, *, connector_limit, _broker=broker):
            session = session_factory(connector_limit=connector_limit)
            transport = type("Transport", (), {})()
            transport.account_id = account_id
            transport.session = session
            _broker._async_prepared_transports.add(transport)
            return transport
        async def handoff(transport, account_id, payload, *, ticket,
                          authorization, broker=broker):
            submitted.append(payload)
            if not broker.live_trading_enabled:
                raise RuntimeError("live lock disabled")
            if (transport not in broker._async_prepared_transports
                    or account_id != broker._account_id):
                raise RuntimeError("wrong account")
            consumed = authorization.ticket_ledger.consume(authorization, ticket)
            if not consumed.allowed:
                raise RuntimeError(consumed.reason)
            broker.submits.append((ticket.ticket_id, payload))
            return {"isSuccess": True}
        async def close_transport(transport, _broker=broker):
            _broker._async_prepared_transports.discard(transport)
        broker.prepare_async_order_transport = prepare
        broker.submit_from_async_prepared_transport = handoff
        broker.close_async_prepared_transport = close_transport
        broker.live_trading_enabled = True
    table = replace(table, tickets=tuple(
        replace(ticket, due_mono=time.monotonic() - 0.1) for ticket in table.tickets
    ))
    authorization.ticket_ledger._reserved = {
        ticket.ticket_id: ticket for ticket in table.tickets
    }
    runtime = ScheduledFireRuntime(monotonic_clock=time.monotonic)
    runtime._clock = lambda: time.monotonic()
    try:
        transports, tasks = runtime.arm(
            table, authorization, account_brokers, FakeSession
        )
        assert (transports, tasks) == (2, 800)
        assert runtime.session_factory_calls == 2
        assert runtime.task_factory_calls == 800
        assert factory_calls["sessions"] == 2
        before = dict(factory_calls)
        runtime._call(asyncio.sleep(0.01))
        assert factory_calls == before
        runtime._call(asyncio.sleep(0.06))
        outcomes = runtime.outcomes()
        assert len(outcomes) == 800
        assert len(set(outcomes)) == 800
        assert len(submitted) == 800
        assert len({json.dumps(payload, sort_keys=True) for payload in submitted}) == 2
        errors = [str(value) for value in outcomes.values()
                  if isinstance(value, Exception)]
        assert not errors, errors[:3]
    finally:
        runtime.close()
    runtime.wait_closed()
    assert all(not broker._async_prepared_transports
               for broker in account_brokers.values())


def test_async_stop_prevents_future_ticket_handoffs_and_live_lock_stays_closed(
        monkeypatch):
    from ui.scheduled_fire_runtime import ScheduledFireRuntime

    state, authorization, table, targets, prepared = _large_ready(monkeypatch)
    class FakeResponse:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        def raise_for_status(self): return None
        async def json(self): return {"isSuccess": True}
    class FakeSession:
        def __init__(self, **_): pass
        def post(self, *_args, **_kwargs): return FakeResponse()
        async def close(self): pass
    account_brokers = dict(state["brokers"])
    for key, broker in account_brokers.items():
        broker.bind_account_identity = lambda account_id, k=key: setattr(
            broker, "_account_id", account_id
        )
        broker._account_id = key[0]
        broker._async_prepared_transports = set()
        async def prepare(account_id, session_factory, *, connector_limit, _broker=broker):
            transport = type("Transport", (), {})()
            transport.account_id = account_id
            _broker._async_prepared_transports.add(transport)
            return transport
        async def handoff(*_args, **_kwargs):
            raise AssertionError("Live lock must prevent hand-off")
        async def close_transport(transport, _broker=broker):
            _broker._async_prepared_transports.discard(transport)
        broker.prepare_async_order_transport = prepare
        broker.submit_from_async_prepared_transport = handoff
        broker.close_async_prepared_transport = close_transport
        broker.live_trading_enabled = False
    runtime = ScheduledFireRuntime(monotonic_clock=lambda: 0.0)
    runtime.arm(table, authorization, account_brokers, FakeSession)
    runtime.stop()
    runtime.close()
    runtime.wait_closed()
    assert runtime.outcomes() == {}


def test_real_connector_capacity_and_pre_countdown_oversize_rejection(monkeypatch):
    from ui.scheduled_fire_runtime import (
        MAX_ACCOUNT_CONNECTOR_LIMIT, ScheduledFireRuntime,
        required_account_connections,
    )

    state, authorization, table, targets, prepared = _large_ready(monkeypatch)
    # With 1 s cadence, five distinct QueueEntry values per account overlap
    # ten turns (bounded by 80 planned turns): 50 per account.
    expected = required_account_connections(table, authorization)
    assert sorted(expected.values()) == [50, 50]
    captured = []

    class SessionFactory:
        def __init__(self, **kwargs):
            captured.append(kwargs["connector"])
        async def close(self):
            pass

    account_brokers = dict(state["brokers"])
    for key, broker in account_brokers.items():
        broker.bind_account_identity = lambda account_id, k=key: setattr(
            broker, "_account_id", account_id
        )
        broker._account_id = key[0]
        async def prepare(account_id, session_factory, *, connector_limit, _broker=broker):
            class Connector:
                def __init__(self, limit): self.limit = limit
            session = session_factory(connector=Connector(limit=connector_limit))
            transport = type("Transport", (), {})()
            transport.account_id, transport.session = account_id, session
            return transport
        async def close_transport(transport):
            await transport.session.close()
        broker.prepare_async_order_transport = prepare
        broker.close_async_prepared_transport = close_transport

    runtime = ScheduledFireRuntime()
    runtime.arm(table, authorization, account_brokers, SessionFactory)
    assert [connector.limit for connector in captured] == [50, 50]
    runtime.close()
    runtime.wait_closed()

    # Ten orders, 80 turns and 100 ms cadence require 400 connections per
    # account; this fits the 512 application-side cap and is accepted.
    overloaded_auth = replace(
        authorization,
        snapshot=replace(authorization.snapshot,
                         schedule=replace(authorization.snapshot.schedule,
                                          interval_ms=100)),
    )
    overloaded = table
    assert sorted(required_account_connections(overloaded, overloaded_auth).values()) == [400, 400]
    runtime = ScheduledFireRuntime()
    never_called = []
    connector_limits = []
    class Broker:
        async def prepare_async_order_transport(self, account_id, session_factory,
                                                *, connector_limit):
            connector_limits.append(connector_limit)
            return object()
        async def close_async_prepared_transport(self, transport):
            pass
    overloaded_brokers = {key: Broker() for key in required_account_connections(
        overloaded, overloaded_auth
    )}
    try:
        runtime.arm(overloaded, overloaded_auth,
                    overloaded_brokers,
                    lambda **kwargs: never_called.append(kwargs))
        assert never_called == []
        assert runtime.session_factory_calls == 2
        assert sorted(connector_limits) == [400, 400]
    finally:
        runtime.close()
        runtime.wait_closed()

    # A capacity of 513 on one account rejects the complete schedule before
    # constructing any session (and thus before countdown can begin).
    too_many_auth = replace(
        authorization,
        snapshot=replace(authorization.snapshot,
                         schedule=replace(authorization.snapshot.schedule,
                                          interval_ms=10)),
    )
    # Give every scheduled ticket a distinct queue-entry identity on its
    # account; at 80 turns this computes 3,200 per account, above 512.
    too_many_table = replace(table, tickets=tuple(
        replace(ticket, queue_entry=object()) for ticket in table.tickets
    ))
    too_many_capacity = required_account_connections(too_many_table, too_many_auth)
    assert max(too_many_capacity.values()) >= 513
    runtime = ScheduledFireRuntime()
    never_called = []
    try:
        try:
            runtime.arm(too_many_table, too_many_auth,
                        {key: object() for key in too_many_capacity},
                        lambda **kwargs: never_called.append(kwargs))
        except RuntimeError as exc:
            assert "above supported limit 512" in str(exc)
        else:
            raise AssertionError("oversized account schedule was accepted")
        assert never_called == []
        assert runtime.session_factory_calls == 0
    finally:
        runtime.close()
        runtime.wait_closed()


def test_identical_fingerprint_queue_entries_count_as_separate_orders(monkeypatch):
    from ui.scheduled_fire_runtime import required_account_connections

    state, authorization, table, targets, prepared = _large_ready(monkeypatch)
    # Distinct queue entries for one account are allowed to carry identical
    # order fingerprints; capacity follows queue-entry identity, not payload.
    account = table.tickets[0].account_id
    selected = [ticket for ticket in table.tickets if ticket.account_id == account]
    same_fingerprint = tuple(
        replace(ticket, order_fingerprint="same") for ticket in table.tickets
    )
    same_fingerprint_table = replace(table, tickets=same_fingerprint)
    capacity = required_account_connections(same_fingerprint_table, authorization)
    # Five QueueEntry identities × ten overlapping turns; 80 turns are
    # planned, but the 10-second timeout only overlaps ten at this cadence.
    assert capacity[(account, selected[0].broker_name)] == 50


def test_async_runtime_waits_for_due_monotonic_instant():
    import asyncio
    import threading
    from ui.scheduled_fire_runtime import ScheduledFireRuntime

    now = {"value": 10.0}
    runtime = ScheduledFireRuntime(monotonic_clock=lambda: now["value"])
    started = []

    async def wait_until_due():
        task = asyncio.create_task(asyncio.sleep(0.01))
        await task
        started.append(now["value"])

    try:
        runtime._call(wait_until_due())
        assert started == [10.0]
    finally:
        runtime.close()
        runtime.wait_closed()


def test_runtime_constructor_chains_event_loop_thread_startup_error(monkeypatch):
    import asyncio
    from ui.scheduled_fire_runtime import ScheduledFireRuntime

    cause = OSError("event loop unavailable")
    monkeypatch.setattr(asyncio, "new_event_loop",
                        lambda: (_ for _ in ()).throw(cause))
    with pytest.raises(RuntimeError, match="failed to start") as error:
        ScheduledFireRuntime()
    assert error.value.__cause__ is cause


def test_async_ticket_timeout_is_not_retried_and_slow_prior_ticket_does_not_serialize(
        monkeypatch):
    import asyncio
    import time
    async_started = []
    async_release = {}

    class Clock:
        def __call__(self):
            return 10.0

    # This checks independent precreated asyncio task progress and timeout
    # finality; HTTP submission itself is tested above through fake transports.
    async def delayed(ticket_id):
        async_started.append(ticket_id)
        if ticket_id == "slow":
            await async_release["event"].wait()
            raise TimeoutError("offline ambiguous timeout")
        return ticket_id

    async def exercise():
        async_release["event"] = asyncio.Event()
        tasks = [asyncio.create_task(delayed("slow"))]
        tasks.extend(asyncio.create_task(delayed(f"fast-{i}")) for i in range(19))
        await asyncio.sleep(0)
        assert len(async_started) == 20
        async_release["event"].set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert sum(isinstance(result, TimeoutError) for result in results) == 1

    asyncio.run(exercise())
    assert len(async_started) == len(set(async_started)) == 20


def test_scheduled_latency_is_ticket_turn_scoped_and_nats_requires_exact_decision_id(monkeypatch):
    import asyncio
    from ui.scheduled_fire_runtime import ScheduledFireRuntime

    state, authorization, table, targets, prepared = _large_ready(monkeypatch)
    ticket = table.tickets[0]
    tick = {"seconds": ticket.due_mono - 0.01}
    def clock():
        tick["seconds"] += 0.00000001
        return tick["seconds"]

    class Response:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        def raise_for_status(self): return None
        async def json(self): return {"isSuccess": True, "data": {"decisionId": "D-ONE"}}

    class Session:
        def __init__(self, **_): pass
        def post(self, *_args, **_kwargs): return Response()
        async def close(self): pass

    broker = state["brokers"][(ticket.account_id, ticket.broker_name)]
    key = (ticket.account_id, ticket.broker_name)
    broker._account_id = key[0]
    broker._async_prepared_transports = set()
    async def prepare(account_id, session_factory, *, connector_limit):
        transport = type("Transport", (), {})()
        transport.account_id, transport.session = account_id, session_factory()
        transport.supports_post_start_callback = True
        broker._async_prepared_transports.add(transport)
        return transport
    async def submit(transport, account_id, payload, **kwargs):
        kwargs["on_post_start"]()
        kwargs["ticket"].authorization_id
        kwargs["authorization"].ticket_ledger.consume(authorization, kwargs["ticket"])
        return {"isSuccess": True, "data": {"decisionId": "D-ONE"}}
    async def close(transport): pass
    broker.prepare_async_order_transport = prepare
    broker.submit_from_async_prepared_transport = submit
    broker.close_async_prepared_transport = close
    broker.live_trading_enabled = True
    one_ticket_table = replace(table, tickets=(ticket,), order_count=1, planned_turns=1)
    authorization.ticket_ledger._reserved = {ticket.ticket_id: ticket}
    runtime = ScheduledFireRuntime(monotonic_clock=clock)
    try:
        runtime.arm(one_ticket_table, authorization, {key: broker}, Session)
        runtime._call(asyncio.sleep(0.02))
        record = runtime.latency_report().ticket(ticket.ticket_id, ticket.turn_index)
        assert record is not None
        assert isinstance(record.planned_due_ns, int)
        assert record.scheduler_wake_ns is not None
        assert record.handoff_start_ns is not None
        assert record.post_start_ns is not None
        assert record.http_response_ns is not None
        assert record.wake_lateness_ns is not None
        assert record.wake_to_handoff_ns is not None
        assert record.handoff_to_post_ns is not None
        assert record.http_round_trip_ns is not None
        assert runtime.bind_decision_id(ticket.ticket_id, ticket.turn_index, "D-ONE")
        assert not runtime.record_nats_feedback(ticket.ticket_id, ticket.turn_index, "D-OTHER")
        runtime._ticket_refs[ticket.ticket_id] = ticket
        runtime._decision_ids[(ticket.account_id, ticket.broker_name, "D-ONE")] = (
            ticket.ticket_id, ticket.turn_index
        )
        assert runtime.record_nats_feedback(ticket.ticket_id, ticket.turn_index, "D-ONE")
        record = runtime.latency_report().ticket(ticket.ticket_id, ticket.turn_index)
        assert record.nats_after_post_ns is not None
    finally:
        runtime.close()
        runtime.wait_closed()


def test_scheduled_latency_early_nats_is_bounded_and_correlated_after_http(monkeypatch):
    from ui.scheduled_fire_runtime import ScheduledFireRuntime

    state, authorization, table, *_ = _large_ready(monkeypatch)
    ticket = table.tickets[0]
    key = (ticket.account_id, ticket.broker_name)
    now = {"ns": __import__("time").monotonic_ns() + 1_000_000}
    runtime = ScheduledFireRuntime(monotonic_clock=lambda: now["ns"] / 1_000_000_000)
    runtime._clock_injected = False
    runtime._latency_clock = lambda: now["ns"]
    runtime._ticket_refs[ticket.ticket_id] = ticket
    runtime._latency_records[(ticket.ticket_id, ticket.turn_index)] = True
    from core.latency_instrumentation import ScheduledTicketLatency
    runtime._latency_report = __import__(
        "core.latency_instrumentation", fromlist=["ScheduledLatencyReport"]
    ).ScheduledLatencyReport(ticket.execution_id, [ScheduledTicketLatency(
        ticket.execution_id, ticket.ticket_id, ticket.turn_index,
            int(ticket.due_mono * 1_000_000_000),
        post_start_ns=now["ns"], http_response_ns=now["ns"] + 1,
    )])
    try:
        assert not runtime.record_nats_feedback_by_decision(*key, "EARLY", now["ns"] + 1)
        assert runtime._pending_nats[(key[0], key[1], "EARLY")] == now["ns"] + 1
        assert not runtime.record_nats_feedback_by_decision(*key, "EARLY", now["ns"] + 2)
        assert runtime.bind_decision_id(ticket.ticket_id, ticket.turn_index, "EARLY")
        record = runtime.latency_report().ticket(ticket.ticket_id, ticket.turn_index)
        assert record.nats_feedback_ns == now["ns"] + 1
        assert record.nats_after_post_ns == 1
        assert not runtime.record_nats_feedback_by_decision(
            *key, "EARLY", record.post_start_ns - 1
        )
        assert not runtime.record_nats_feedback_by_decision(*key, "EARLY", 102)

        other = runtime.record_nats_feedback_by_decision(
            "OTHER", key[1], "MISMATCH", now["ns"] + 3
        )
        assert not other
        assert len(runtime._pending_nats) == 1
        runtime._pending_nats.clear()
        for index in range(runtime._max_pending_nats + 1):
            runtime.record_nats_feedback_by_decision(
                key[0], key[1], f"D-{index}", now["ns"] + 10 + index
            )
        assert len(runtime._pending_nats) == runtime._max_pending_nats
        assert (key[0], key[1], "D-0") not in runtime._pending_nats
        runtime._pending_nats.clear()
        assert runtime.latency_report().ticket(ticket.ticket_id, ticket.turn_index).nats_feedback_ns == now["ns"] + 1
    finally:
        runtime.close()
        runtime.wait_closed()


def test_scheduled_latency_durations_are_integer_nanoseconds():
    from core.latency_instrumentation import ScheduledTicketLatency

    record = ScheduledTicketLatency(
        "execution", "ticket", 2, 1_000_000_000,
        scheduler_wake_ns=1_000_000_007,
        handoff_start_ns=1_000_000_011,
        post_start_ns=1_000_000_013,
        http_response_ns=1_000_000_019,
        nats_feedback_ns=1_000_000_023,
        nats_correlated=True,
    )
    assert record.wake_lateness_ns == 7
    assert record.wake_to_handoff_ns == 4
    assert record.handoff_to_post_ns == 2
    assert record.http_round_trip_ns == 6
    assert record.nats_after_post_ns == 10
    assert all(isinstance(value, int) for value in (
        record.wake_lateness_ns, record.wake_to_handoff_ns,
        record.handoff_to_post_ns, record.http_round_trip_ns,
        record.nats_after_post_ns,
    ))


@pytest.mark.parametrize("failure", ["http_error", "timeout"])
def test_scheduled_latency_records_failed_http_and_never_retries(monkeypatch, failure):
    import asyncio
    from ui.scheduled_fire_runtime import ScheduledFireRuntime

    state, authorization, table, targets, prepared = _large_ready(monkeypatch)
    ticket = table.tickets[0]
    tick = {"seconds": ticket.due_mono - 0.01}
    def clock():
        tick["seconds"] += 0.00000001
        return tick["seconds"]

    key = (ticket.account_id, ticket.broker_name)
    broker = state["brokers"][key]
    broker._account_id = key[0]
    broker._async_prepared_transports = set()
    class Transport:
        def __init__(self):
            self.account_id = key[0]
            self.supports_post_start_callback = True
    async def prepare(account_id, *_args, **_kwargs):
        transport = Transport()
        broker._async_prepared_transports.add(transport)
        return transport
    calls = []
    async def submit(_transport, _account_id, _payload, **kwargs):
        calls.append(kwargs["ticket"].ticket_id)
        kwargs["on_post_start"]()
        if failure == "timeout":
            raise TimeoutError("ambiguous")
        raise RuntimeError("HTTP failed")
    async def close(_transport): pass
    broker.prepare_async_order_transport = prepare
    broker.submit_from_async_prepared_transport = submit
    broker.close_async_prepared_transport = close
    broker.live_trading_enabled = True
    one_ticket_table = replace(table, tickets=(ticket,), order_count=1, planned_turns=1)
    authorization.ticket_ledger._reserved = {ticket.ticket_id: ticket}
    runtime = ScheduledFireRuntime(monotonic_clock=clock)
    try:
        runtime.arm(one_ticket_table, authorization, {key: broker}, lambda **_: None)
        runtime._call(asyncio.sleep(0.02))
        record = runtime.latency_report().ticket(ticket.ticket_id, ticket.turn_index)
        assert len(calls) == 1
        assert record.post_start_ns is not None
        assert record.http_response_ns is not None
        assert record.http_round_trip_ns is not None
        assert record.http_ok is False
        assert record.nats_after_post_ns is None
        runtime._call(asyncio.sleep(0))
        assert calls == [ticket.ticket_id]
    finally:
        runtime.close()
        runtime.wait_closed()
