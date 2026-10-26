from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from brokers.agaah.broker import AgaahBroker


class Response:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"isSuccess": True}


class FakeTransport:
    def __init__(self):
        self.headers = {}
        self.posts = []
        self.closed = 0
        self.barrier = None

    def post(self, url, *, headers, json, timeout):
        if self.barrier is not None:
            self.barrier.wait(timeout=2)
        self.posts.append((url, headers, json, timeout))
        return Response()

    def close(self):
        self.closed += 1


def authenticated_broker(account, token, user):
    broker = AgaahBroker()
    broker.access_token = token
    broker.user_identifier = user
    broker.bind_account_identity(account)
    broker.live_trading_enabled = True  # offline fake broker only
    return broker


def test_senders_capture_independent_account_auth_and_transports():
    transports = []

    def factory():
        transport = FakeTransport()
        transports.append(transport)
        return transport

    a = authenticated_broker("acct-A", "token-A", "user-A")
    b = authenticated_broker("acct-B", "token-B", "user-B")
    sender_a = a.prepare_order_sender("acct-A", factory)
    sender_b = b.prepare_order_sender("acct-B", factory)

    assert sender_a.account_id == "acct-A" and sender_b.account_id == "acct-B"
    assert transports[0] is not transports[1]
    a.submit_from_prepared_sender(sender_a, "acct-A", {"id": "A"})
    b.submit_from_prepared_sender(sender_b, "acct-B", {"id": "B"})
    assert transports[0].posts[0][1]["Authorization"] == "Bearer token-A"
    assert transports[0].posts[0][1]["UserIdentifier"] == "user-A"
    assert transports[1].posts[0][1]["Authorization"] == "Bearer token-B"
    assert transports[1].posts[0][1]["UserIdentifier"] == "user-B"
    assert transports[0].posts[0][2] == {"id": "A"}
    assert transports[1].posts[0][2] == {"id": "B"}


def test_independent_senders_can_submit_concurrently_without_shared_state():
    broker = authenticated_broker("acct", "token", "user")
    transports = []
    barrier = Barrier(2)

    def factory():
        transport = FakeTransport()
        transport.barrier = barrier
        transports.append(transport)
        return transport

    senders = [broker.prepare_order_sender("acct", factory) for _ in range(2)]
    payloads = [{"order": 1}, {"order": 2}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(broker.submit_from_prepared_sender,
                               sender, "acct", payload)
                   for sender, payload in zip(senders, payloads)]
        [future.result(timeout=3) for future in futures]
    assert len({id(item) for item in transports}) == 2
    assert [transport.posts[0][2] for transport in transports] == payloads


def test_live_lock_and_account_broker_binding_are_enforced_before_post():
    broker = authenticated_broker("acct-A", "token-A", "user-A")
    other = authenticated_broker("acct-B", "token-B", "user-B")
    made = []

    def factory():
        item = FakeTransport()
        made.append(item)
        return item

    sender = broker.prepare_order_sender("acct-A", factory)
    with pytest.raises(RuntimeError, match="live_trading_enabled=False"):
        broker.live_trading_enabled = False
        broker.submit_from_prepared_sender(sender, "acct-A", {"x": 1})
    assert made[0].posts == []
    broker.live_trading_enabled = True
    with pytest.raises(RuntimeError, match="does not belong"):
        other.submit_from_prepared_sender(sender, "acct-A", {"x": 1})
    with pytest.raises(RuntimeError, match="does not belong"):
        broker.submit_from_prepared_sender(sender, "acct-B", {"x": 1})
    assert made[0].posts == []


def test_payload_is_forwarded_unchanged_and_close_is_idempotent():
    broker = authenticated_broker("acct", "token", "user")
    transport = FakeTransport()
    sender = broker.prepare_order_sender("acct", lambda: transport)
    payload = {"prepared": [1, 2]}
    broker.submit_from_prepared_sender(sender, "acct", payload)
    assert transport.posts[0][2] is payload
    broker.close_prepared_sender(sender)
    broker.close_prepared_sender(sender)
    assert transport.closed == 1
    with pytest.raises(RuntimeError, match="does not belong"):
        broker.submit_from_prepared_sender(sender, "acct", payload)


def test_close_all_prepared_senders_is_idempotent():
    broker = authenticated_broker("acct", "token", "user")
    transports = []

    def factory():
        item = FakeTransport()
        transports.append(item)
        return item

    broker.prepare_order_sender("acct", factory)
    broker.prepare_order_sender("acct", factory)
    broker.close_prepared_senders()
    broker.close_prepared_senders()
    assert [item.closed for item in transports] == [1, 1]


def test_sender_rejects_incomplete_auth_and_broker_account_rebinding():
    broker = AgaahBroker()
    broker.bind_account_identity("acct-A")
    with pytest.raises(RuntimeError, match="authenticated identity"):
        broker.prepare_order_sender("acct-A", FakeTransport)
    broker.access_token = "token"
    broker.user_identifier = "user"
    broker.prepare_order_sender("acct-A", FakeTransport)
    with pytest.raises(RuntimeError, match="another account"):
        broker.prepare_order_sender("acct-B", FakeTransport)


def test_legacy_order_apis_keep_dry_run_and_lock_behavior(monkeypatch):
    from models.order import BUY, Order

    broker = AgaahBroker()
    order = Order("nsc", BUY, 10, 1)
    dry_place = broker.place_order(order)
    assert dry_place["mode"] == "DRY_RUN" and dry_place["sent"] is False
    assert dry_place["payload"] == order.to_payload()
    payload = {"already": "prepared"}
    dry_submit = broker.submit_prepared_order(payload, live=False)
    assert dry_submit == {"mode": "DRY_RUN", "sent": False, "payload": payload}
    with pytest.raises(RuntimeError, match="live_trading_enabled=False"):
        broker.submit_prepared_order(payload, live=True)

    # The legacy Live branch remains broker/session-owned; replace the
    # existing session with a fake and enable only this local test instance.
    transport = FakeTransport()
    monkeypatch.setattr(broker, "session", transport)
    broker.access_token = "legacy-token"
    broker.user_identifier = "legacy-user"
    broker.live_trading_enabled = True
    assert broker.submit_prepared_order(payload, live=True) == {"isSuccess": True}
    assert transport.posts[0][2] is payload
