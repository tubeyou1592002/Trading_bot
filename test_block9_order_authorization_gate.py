"""Focused offline tests for the Block 9 order authorization gate."""

from types import SimpleNamespace

from ui.account_store import AccountStore
from ui.order_authorization import authorize_order
from ui.session_manager import SessionManager


class Adapter:
    broker_name = "Broker"

    def __init__(self, token="secret", raises=False):
        self.token, self.raises = token, raises

    def is_authenticated(self):
        if self.raises:
            raise RuntimeError("sensitive secret")
        return True

    def get_authenticated_session(self):
        if self.raises:
            raise RuntimeError("sensitive secret")
        return SimpleNamespace(access_token=self.token)


class Auth:
    def __init__(self, adapter=None, logged=True):
        self.adapter, self.logged = adapter, logged

    def is_logged_in(self, account_id):
        return self.logged

    def get_adapter(self, account_id):
        return self.adapter


class Brokers:
    pass


def setup(account_id="A", active=True, token="secret", state="logged"):
    store = AccountStore()
    store.add(account_id, "Broker", account_id)
    if active:
        store.set_active(account_id)
    sessions = SessionManager()
    sessions.register(account_id, "Broker")
    if state == "logged":
        sessions.begin_login(account_id)
        sessions.mark_logged_in(account_id, token)
    elif state == "pending":
        sessions.begin_login(account_id)
    return store, sessions


def test_gate_accepts_only_matching_account_session_and_token():
    store, sessions = setup()
    result = authorize_order(store, Auth(Adapter()), sessions, "A", "Broker")
    assert result.authorized and result.reason == "authorized"


def test_gate_rejects_missing_account_or_mismatched_context():
    store, sessions = setup(active=False)
    assert not authorize_order(store, Auth(Adapter()), sessions, "A", "Broker").authorized
    store.set_active("A")
    assert not authorize_order(store, Auth(Adapter()), sessions, "A", "Other").authorized
    assert not authorize_order(store, Auth(Adapter()), sessions, "B", "Broker").authorized


def test_gate_rejects_missing_services_logged_out_pending_or_missing_adapter():
    store, sessions = setup(state="pending")
    assert not authorize_order(store, None, sessions, "A", "Broker").authorized
    assert not authorize_order(store, Auth(Adapter()), sessions, "A", "Broker").authorized
    store, sessions = setup(state="logged")
    assert not authorize_order(store, Auth(None), sessions, "A", "Broker").authorized
    assert not authorize_order(store, Auth(Adapter(token="other")), sessions, "A", "Broker").authorized


def test_gate_rejects_adapter_errors_without_leaking_details_and_accounts_are_independent():
    store, sessions = setup("A")
    store.add("B", "Broker", "B")
    sessions.register("B", "Broker")
    assert authorize_order(store, Auth(Adapter()), sessions, "A", "Broker").authorized
    denied = authorize_order(store, Auth(Adapter(raises=True)), sessions, "A", "Broker")
    assert not denied.authorized
    assert "secret" not in repr(denied)
    assert not authorize_order(store, Auth(Adapter()), sessions, "B", "Broker").authorized
