"""Offline regression tests for manual Live UNKNOWN result handling."""

from unittest.mock import MagicMock

from core.live_order_authorization import (
    ManualLivePermit, _MANUAL_PERMIT_ISSUER, prepared_fingerprint,
)
from core.order_engine import OrderEngine, OrderExecutionResult
from core.safety_gate import SafetyGateDecision
from ui.order_configuration_page import (
    _result_status_label, _result_reason_for_status,
    RESULT_STATUS_UNKNOWN,
)


class _FakeOrder:
    pass


def test_ui_unknown_status_label_and_reason():
    result = OrderExecutionResult(False, False, "UNKNOWN", _FakeOrder())
    status = _result_status_label(result)
    assert status == RESULT_STATUS_UNKNOWN
    assert status != "\u0646\u0627\u0645\u0648\u0641\u0642"
    assert status != "\u0645\u0633\u062f\u0648\u062f\u0634\u062f\u0647"
    reason = _result_reason_for_status(status)
    assert "\u06a9\u0627\u0631\u06af\u0632\u0627\u0631\u06cc" in reason


def test_engine_maps_unknown_exception():
    engine = OrderEngine()
    broker = MagicMock()
    broker.live_trading_enabled = False
    broker.submit_manual_prepared_order.side_effect = RuntimeError(
        "MANUAL_LIVE_UNKNOWN: timeout"
    )
    engine.validate_prepared_order = lambda *a, **k: (True, "")
    prepared = MagicMock()
    prepared.execution_id = "e"
    prepared.order = _FakeOrder()
    prepared.payload = {}
    prepared.payload_json = "{}"
    prepared.account_id = "a"
    prepared.broker_name = "b"
    prepared.broker_identity = id(broker)
    pf = prepared_fingerprint(prepared)
    gate = SafetyGateDecision(True, "ALLOWED", None, "ok")
    permit = ManualLivePermit(
        execution_id="e", account_id="a", broker_name="b", broker=broker,
        queue_fingerprint="fp", prepared_fingerprints=(pf,), gate_decision=gate,
        _issuer=_MANUAL_PERMIT_ISSUER,
    )
    res = engine.submit_manual_prepared_order(
        prepared, permit=permit, broker=broker, account=None,
        account_id="a", broker_name="b", queue_fingerprint="fp", index=0,
    )
    assert res.mode == "UNKNOWN"


import requests


class _TimeoutTransport:
    def __init__(self):
        self.headers = {}
        self.posts = 0
        self.closed = 0

    def post(self, url, *, headers, json, timeout):
        self.posts += 1
        raise requests.exceptions.Timeout("boom")

    def close(self):
        self.closed += 1


def test_full_timeout_path_unknown():
    from brokers.agaah.broker import AgaahBroker
    from core.order_engine import OrderEngine
    from core.live_order_authorization import (
        ManualLivePermit, _MANUAL_PERMIT_ISSUER, prepared_fingerprint,
    )
    from core.safety_gate import SafetyGateDecision
    from unittest.mock import MagicMock
    import json as _json

    broker = AgaahBroker()
    broker.bind_account_identity("acct")
    broker.access_token = "tok"
    broker.user_identifier = "uid"
    broker.live_trading_enabled = False

    transport = _TimeoutTransport()
    orig = broker.prepare_manual_order_sender
    broker.prepare_manual_order_sender = lambda account_id, transport_factory=None: orig(account_id, transport_factory=lambda: transport)

    payload = {"x": 1}
    prepared = MagicMock()
    prepared.execution_id = "exec1"
    prepared.order = _FakeOrder()
    prepared.payload = payload
    prepared.payload_json = _json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    prepared.account_id = "acct"
    prepared.broker_name = "agaah"
    prepared.broker_identity = id(broker)
    prepared.prepared_at = None
    prepared.expires_at = None
    prepared.order_fingerprint = None
    prepared.account_fingerprint = None
    prepared.m6_fingerprint = None
    prepared.evidence_order_fingerprint = None
    prepared.evidence_account_id = None

    pf = prepared_fingerprint(prepared)
    gate = SafetyGateDecision(True, "ALLOWED", None, "ok")
    permit = ManualLivePermit(
        execution_id="exec1", account_id="acct", broker_name="agaah",
        broker=broker, queue_fingerprint="fp", prepared_fingerprints=(pf,),
        gate_decision=gate, _issuer=_MANUAL_PERMIT_ISSUER,
    )

    engine = OrderEngine()
    engine.validate_prepared_order = lambda *a, **k: (True, "")

    res = engine.submit_manual_prepared_order(
        prepared, permit=permit, broker=broker, account=None,
        account_id="acct", broker_name="agaah", queue_fingerprint="fp", index=0,
    )
    assert res.mode == "UNKNOWN"
    assert transport.posts == 1

    res2 = engine.submit_manual_prepared_order(
        prepared, permit=permit, broker=broker, account=None,
        account_id="acct", broker_name="agaah", queue_fingerprint="fp", index=0,
    )
    assert res2.mode in ("BLOCKED", "ERROR")
    assert transport.posts == 1
    assert broker.live_trading_enabled is False
