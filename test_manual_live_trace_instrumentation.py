"""Offline acceptance tests for manual Live Engine/broker trace events."""

import json

import pytest

from brokers.agaah.broker import AgaahBroker, ManualLiveUnknownError
from core.live_order_authorization import (
    ManualLivePermit,
    _MANUAL_PERMIT_ISSUER,
    prepared_fingerprint,
)
from core.order_engine import OrderEngine
from core.safety_gate import SafetyGateDecision
from ui import manual_live_trace


class _Response:
    status_code = 200

    def __init__(self, data=None, json_error=None):
        self._data = data if data is not None else {"isSuccess": True}
        self._json_error = json_error

    def raise_for_status(self):
        return None

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._data


class _HttpErrorResponse(_Response):
    status_code = 503

    def raise_for_status(self):
        raise RuntimeError("HTTP_RESPONSE_SECRET")


class _Transport:
    def __init__(self, events, response=None, error=None):
        self.events = events
        self.headers = {}
        self.response = response or _Response()
        self.error = error
        self.posts = 0
        self.closed = 0

    def post(self, *_args, **_kwargs):
        self.posts += 1
        if getattr(self, "require_trace_event", True):
            assert self.events[-1]["stage"] == "transport_call_started"
        if self.error:
            raise self.error
        return self.response

    def close(self):
        self.closed += 1


class _Prepared:
    execution_id = "execution-test"
    order = object()
    payload = {"quantity": 3, "sensitive": "PAYLOAD_SECRET"}
    payload_json = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    account_id = "account-test"
    broker_name = "agaah"
    prepared_at = None
    expires_at = None
    order_fingerprint = None
    account_fingerprint = None
    m6_fingerprint = None
    evidence_order_fingerprint = None
    evidence_account_id = None


def _setup(monkeypatch, *, response=None, transport_error=None, sender_error=None, log_callback=None, transport_override=None):
    events = []
    monkeypatch.setattr(
        manual_live_trace,
        "log_event",
        log_callback or (lambda trace, stage, order_index=None, reason_code=None, extra=None: events.append({
            "trace_id": trace,
            "stage": stage,
            "order_index": order_index,
            "reason_code": reason_code,
            "extra": extra,
        })),
    )
    broker = AgaahBroker()
    broker.bind_account_identity("account-test")
    broker.access_token = "TOKEN_SECRET"
    broker.user_identifier = "user-test"
    broker.live_trading_enabled = False
    transport = transport_override or _Transport(events, response=response, error=transport_error)
    if hasattr(transport, "events"):
        transport.events = events
        transport.require_trace_event = False
    if sender_error:
        broker.prepare_manual_order_sender = lambda *_a, **_k: (_ for _ in ()).throw(sender_error)
    else:
        original = broker.prepare_manual_order_sender
        broker.prepare_manual_order_sender = lambda account_id, transport_factory=None: original(
            account_id, transport_factory=lambda: transport
        )
    prepared = _Prepared()
    prepared.broker_identity = id(broker)
    fingerprint = prepared_fingerprint(prepared)
    permit = ManualLivePermit(
        execution_id=prepared.execution_id,
        account_id=prepared.account_id,
        broker_name=prepared.broker_name,
        broker=broker,
        queue_fingerprint="queue-fingerprint",
        prepared_fingerprints=(fingerprint,),
        gate_decision=SafetyGateDecision(True, "ALLOWED", None, "ok"),
        _issuer=_MANUAL_PERMIT_ISSUER,
    )
    engine = OrderEngine()
    engine.validate_prepared_order = lambda *_a, **_k: (True, "")
    result = engine.submit_manual_prepared_order(
        prepared,
        permit=permit,
        broker=broker,
        account=None,
        account_id=prepared.account_id,
        broker_name=prepared.broker_name,
        queue_fingerprint="queue-fingerprint",
        index=0,
        trace_id="trace-test",
    )
    return result, broker, transport, events


def test_success_trace_correlation_order_and_sender_close(monkeypatch):
    result, _broker, transport, events = _setup(monkeypatch)
    assert result.mode == "LIVE"
    assert transport.posts == 1
    assert transport.closed == 1
    stages = [event["stage"] for event in events]
    assert stages.index("transport_call_started") < stages.index("http_response")
    assert stages.index("http_response") < stages.index("api_result")
    assert stages.index("api_result") < stages.index("engine_result")
    assert all(e["trace_id"] == "trace-test" for e in events)
    assert all(e["order_index"] == 0 for e in events)
    assert [e["stage"] for e in events] == [
        "engine_entry", "sender_setup", "transport_call_started",
        "http_response", "api_result", "engine_result",
    ]


def test_timeout_once_unknown_and_classified(monkeypatch):
    result, _broker, transport, events = _setup(
        monkeypatch, transport_error=TimeoutError("EXCEPTION_SECRET")
    )
    assert result.mode == "UNKNOWN"
    assert transport.posts == 1
    unknown = [e for e in events if e["reason_code"] == "TRANSPORT_EXCEPTION"]
    assert len(unknown) == 1
    assert unknown[0]["stage"] == "transport_result"
    assert unknown[0]["extra"]["classification"] == "UNKNOWN"
    assert sum(e["stage"] == "transport_call_started" for e in events) == 1
    assert all(e["trace_id"] == "trace-test" and e["order_index"] == 0 for e in events)


@pytest.mark.parametrize(
    ("response", "expected_mode", "classification"),
    [
        (_Response({"isSuccess": False, "message": "BODY_SECRET"}), "ERROR", "REJECTED"),
        (_Response(json_error=ValueError("JSON_SECRET")), "UNKNOWN", None),
    ],
)
def test_api_rejection_and_unreadable_response(monkeypatch, response, expected_mode, classification):
    result, _broker, transport, events = _setup(monkeypatch, response=response)
    assert result.mode == expected_mode
    assert transport.posts == 1
    if classification:
        assert any(e["stage"] == "api_result" and e["extra"]["classification"] == classification for e in events)
    else:
        assert any(e["reason_code"] == "HTTP_PARSE_FAILED" for e in events)


def test_validation_rejection_has_no_post(monkeypatch):
    events = []
    monkeypatch.setattr(manual_live_trace, "log_event", lambda *a, **k: events.append((a, k)))
    engine = OrderEngine()
    engine.validate_prepared_order = lambda *_a, **_k: (False, "sensitive details")
    prepared = _Prepared()
    broker = type("Broker", (), {"live_trading_enabled": False})()
    permit = object()
    result = engine.submit_manual_prepared_order(
        prepared, permit=permit, broker=broker, account=None,
        account_id="account-test", broker_name="agaah",
        queue_fingerprint="queue-fingerprint", index=0, trace_id="trace-test",
    )
    assert result.mode == "BLOCKED"
    assert any(k.get("reason_code") == "PERMIT_INVALID" for _, k in events)


@pytest.mark.parametrize(
    ("failure", "reason_code", "expected_mode"),
    [
        ("engine_validation", "ENGINE_EVIDENCE_INVALID", "BLOCKED"),
        ("permit_invalid", "PERMIT_INVALID", "BLOCKED"),
        ("permit_binding", "PERMIT_INVALID", "BLOCKED"),
        ("broker_claim", "BROKER_PERMIT_CLAIM_FAILED", "ERROR"),
        ("sender_setup", "SENDER_SETUP_FAILED", "ERROR"),
    ],
)
def test_pre_post_failures_never_handoff_and_preserve_trace(
    monkeypatch, failure, reason_code, expected_mode
):
    events = []
    monkeypatch.setattr(
        manual_live_trace, "log_event",
        lambda trace, stage, order_index=None, reason_code=None, extra=None: events.append({
            "trace_id": trace, "stage": stage, "order_index": order_index,
            "reason_code": reason_code, "extra": extra,
        }),
    )
    broker = AgaahBroker()
    broker.bind_account_identity("account-test")
    broker.access_token, broker.user_identifier = "TOKEN_SECRET", "user-test"
    transport = _Transport(events)
    original_prepare = broker.prepare_manual_order_sender
    broker.prepare_manual_order_sender = lambda account_id: original_prepare(
        account_id, transport_factory=lambda: transport
    )
    prepared = _Prepared()
    prepared.broker_identity = id(broker)
    fingerprint = prepared_fingerprint(prepared)
    permit = ManualLivePermit(
        execution_id=prepared.execution_id, account_id=prepared.account_id,
        broker_name=prepared.broker_name, broker=broker,
        queue_fingerprint="queue-fingerprint", prepared_fingerprints=(fingerprint,),
        gate_decision=SafetyGateDecision(True, "ALLOWED", None, "ok"),
        _issuer=_MANUAL_PERMIT_ISSUER,
    )
    engine = OrderEngine()
    engine.validate_prepared_order = lambda *_a, **_k: (
        (False, "invalid") if failure == "engine_validation" else (True, "")
    )
    supplied_permit = object() if failure == "permit_invalid" else permit
    queue_fingerprint = "wrong-queue" if failure == "permit_binding" else "queue-fingerprint"
    if failure == "broker_claim":
        monkeypatch.setattr(ManualLivePermit, "claim", lambda self, **_kwargs: False)
    if failure == "sender_setup":
        broker.prepare_manual_order_sender = lambda *_a, **_k: (_ for _ in ()).throw(
            RuntimeError("SETUP_SECRET")
        )
    result = engine.submit_manual_prepared_order(
        prepared, permit=supplied_permit, broker=broker, account=None,
        account_id=prepared.account_id, broker_name=prepared.broker_name,
        queue_fingerprint=queue_fingerprint,
        index=0 if failure in ("broker_claim", "sender_setup") else 3,
        trace_id="trace-stop-test",
    )
    assert result.mode == expected_mode
    assert transport.posts == 0
    matching = [e for e in events if e["reason_code"] == reason_code]
    assert matching
    expected_index = 0 if failure in ("broker_claim", "sender_setup") else 3
    assert all(e["trace_id"] == "trace-stop-test" and e["order_index"] == expected_index for e in events)
    assert transport.closed == 0
    terminal = [e for e in events if e["stage"] == "engine_result"]
    assert len(terminal) == 1
    assert terminal[0]["extra"]["classification"] == expected_mode


def test_http_error_is_unknown_once_and_trace_classified(monkeypatch):
    result, _broker, transport, events = _setup(monkeypatch, response=_HttpErrorResponse())
    assert result.mode == "UNKNOWN"
    assert transport.posts == 1
    assert transport.closed == 1
    assert any(e["stage"] == "http_response" and e["extra"]["http_status"] == 503 for e in events)
    http_error = next(e for e in events if e["stage"] == "http_response" and e["reason_code"] == "HTTP_PARSE_FAILED")
    assert http_error["extra"]["classification"] == "UNKNOWN"
    assert sum(e["stage"] == "transport_call_started" for e in events) == 1
    assert all(e["trace_id"] == "trace-test" and e["order_index"] == 0 for e in events)


def test_logger_failure_does_not_change_order_result(monkeypatch):
    monkeypatch.setattr(manual_live_trace, "log_event", lambda *a, **k: (_ for _ in ()).throw(OSError("LOGGER_SECRET")))
    result, _broker, transport, _events = _setup(monkeypatch)
    assert result.mode == "LIVE"
    assert transport.posts == 1
    assert transport.closed == 1


def test_integrated_path_never_serializes_sensitive_values(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_BOT_TRACE_DIR", str(tmp_path))
    from importlib import reload

    logger = reload(manual_live_trace)
    result, _broker, transport, events = _setup(
        monkeypatch,
        response=_Response(json_error=ValueError("RESPONSE_SECRET EXCEPTION_SECRET")),
        log_callback=logger.log_event,
    )
    # Exercise the real logger again with broker-shaped sensitive metadata.
    logger.log_event("trace-test", "probe", order_index=0, extra={
        "payload": "PAYLOAD_SECRET", "token": "TOKEN_SECRET",
        "header": "HEADER_SECRET", "body": "BODY_SECRET",
        "classification": "UNKNOWN",
    })
    content = (tmp_path / "manual_live_trace.jsonl").read_text(encoding="utf-8")
    status = repr(logger.last_error())
    assert result.mode == "UNKNOWN" and transport.posts == 1 and transport.closed == 1
    assert '"stage": "engine_entry"' in content
    for secret in (
        "PAYLOAD_SECRET", "TOKEN_SECRET", "HEADER_SECRET", "BODY_SECRET",
        "EXCEPTION_SECRET", "RESPONSE_SECRET",
    ):
        assert secret not in content
        assert secret not in status
    assert '"classification": "UNKNOWN"' in content


@pytest.mark.parametrize("data", [[], None, "secret", 7, {}, {"isSuccess": "true"}, {"isSuccess": 1}])
def test_invalid_api_shape_is_unknown_without_retry(monkeypatch, data):
    response = _Response()
    response._data = data
    result, _, transport, events = _setup(monkeypatch, response=response)
    assert result.mode == "UNKNOWN"
    assert transport.posts == 1 and transport.closed == 1
    assert any(e["reason_code"] == "API_RESPONSE_INVALID" for e in events)
    assert events[-1]["stage"] == "engine_result"
    assert events[-1]["extra"]["classification"] == "UNKNOWN"
