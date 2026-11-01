"""Offline tests for manual Live UI gate trace instrumentation."""

from types import SimpleNamespace
from dataclasses import dataclass

import pytest
from PySide6.QtWidgets import QApplication

from core.order_queue import OrderQueue
from models.order import Order
from ui.account_store import AccountStore
from ui.order_configuration_page import OrderConfigurationPage
from ui import manual_live_trace
from ui import order_authorization


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _page(qapp, monkeypatch, *, count=2, authorized=True):
    events = []
    monkeypatch.setattr(manual_live_trace, "new_trace_id", lambda: "ui-trace-test")
    monkeypatch.setattr(
        manual_live_trace, "log_event",
        lambda trace, stage, order_index=None, reason_code=None, extra=None: events.append({
            "trace_id": trace, "stage": stage, "order_index": order_index,
            "reason_code": reason_code, "extra": extra,
        }),
    )
    monkeypatch.setattr(order_authorization, "authorize_order",
                        lambda *_args: SimpleNamespace(authorized=True))
    store = AccountStore()
    store.add("ACC-1", "SIM", "Account One")
    store.set_active("ACC-1")
    queue = OrderQueue()
    for i in range(count):
        queue.enqueue(Order(f"N{i}", 1, 100, 1), "ACC-1", "SIM")
    page = OrderConfigurationPage(store, order_queue=queue)
    page.set_order_authorizer_factory(
        lambda: lambda *_args: SimpleNamespace(authorized=authorized)
    )
    page.live_mode_button.setChecked(True)
    page._test_mode = True
    page._test_runner_factory = lambda **_kwargs: pytest.fail("Engine/runner must not run")
    return page, events, queue


def test_ui_authorization_rejection_is_traced_without_engine(qapp, monkeypatch):
    page, events, _queue = _page(qapp, monkeypatch, authorized=False)
    try:
        page._run_test_pass()
        rejected = [e for e in events if e["reason_code"] == "UI_AUTHORIZATION_REJECTED"]
        assert len(rejected) == 2
        assert [e["order_index"] for e in rejected] == [0, 1]
        assert all(e["trace_id"] == "ui-trace-test" for e in rejected)
        assert page._last_order_results and all(r.mode == "NOT_SENT" for r in page._last_order_results)
    finally:
        page.close()


def test_scope_rejection_has_one_correlated_event_per_order(qapp, monkeypatch):
    page, events, queue = _page(qapp, monkeypatch)
    try:
        page._live_prearm_factory = lambda *_args: None
        queue.enqueue(Order("OTHER", 1, 100, 1), "ACC-1", "OTHER-BROKER")
        page._run_test_pass()
        rejected = [e for e in events if e["reason_code"] == "ENTRY_SCOPE_MISMATCH"]
        assert len(rejected) == 3
        assert [e["order_index"] for e in rejected] == [0, 1, 2]
        assert all(e["trace_id"] == "ui-trace-test" for e in rejected)
        assert not any(e["stage"] == "engine_entry" for e in events)
    finally:
        page.close()


def test_logger_failure_does_not_change_blocked_ui_gate(qapp, monkeypatch):
    page, _events, _queue = _page(qapp, monkeypatch, authorized=False)
    monkeypatch.setattr(
        manual_live_trace, "log_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("LOGGER_SECRET")),
    )
    try:
        page._run_test_pass()
        assert page._last_order_results and all(r.mode == "NOT_SENT" for r in page._last_order_results)
        assert page._last_test_run is None
    finally:
        page.close()


def test_confirm_yes_occurs_between_prearm_and_post_confirm_gates(qapp, monkeypatch):
    page, events, _queue = _page(qapp, monkeypatch)
    calls = {"snapshot": 0, "auth": 0, "balance": 0, "prearm": 0}

    class PreparedBatch:
        valid = True
        checks_succeeded = True
        message = ""
        orders = (object(), object())

    class Coordinator:
        engine = object()
        def prepare(self, targets):
            calls["prearm"] += 1
            return "execution", PreparedBatch()

    class Auth:
        def get_purchase_power(self, _account_id):
            calls["balance"] += 1
            return 1000

    try:
        page._authentication_service_factory = lambda: Auth()
        page._order_authorizer_factory = lambda: lambda *_args: SimpleNamespace(authorized=True)
        page._live_prearm_factory = lambda _targets: Coordinator()
        page._live_scope_rejection = lambda *_args: None
        page._live_snapshot = lambda *_args: calls.__setitem__("snapshot", calls["snapshot"] + 1) or "snap"
        page._live_snapshot_unchanged = lambda *_args: calls.__setitem__("snapshot", calls["snapshot"] + 1) or True
        page.set_session_manager(object())
        import ui.order_authorization as authorization_module
        monkeypatch.setattr(
            authorization_module, "authorize_order",
            lambda *_args: SimpleNamespace(authorized=True),
        )
        page._confirm_live_start = lambda _summary: True
        monkeypatch.setattr(
            "ui.live_order_gate.check_manual_live_preflight",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("GATE_SECRET")),
        )
        page._run_test_pass()
        stages = [e["stage"] for e in events]
        assert stages.index("prearm_m6_result") < stages.index("confirm_yes")
        assert stages.index("confirm_yes") < stages.index("snapshot_post_confirm_start")
        assert calls == {"snapshot": 2, "auth": 0, "balance": 1, "prearm": 1}
        assert any(e["reason_code"] == "READINESS_PREFLIGHT_EXCEPTION" for e in events)
        confirm_events = [e for e in events if e["stage"] == "confirm_yes"]
        assert [e["order_index"] for e in confirm_events] == [0, 1]
        assert all(e["trace_id"] == "ui-trace-test" for e in events)
        assert not any(e["stage"] == "engine_entry" for e in events)
    finally:
        page.close()


def test_full_allowed_ui_path_resolves_permit_and_calls_engine_once_per_order(qapp, monkeypatch):
    page, events, queue = _page(qapp, monkeypatch)
    from core.live_order_authorization import ManualLivePermit, _MANUAL_PERMIT_ISSUER
    from core.safety_gate import SafetyGateDecision

    calls = []
    broker = object()
    orders = tuple(entry.order for entry in queue.list_pending())
    permit = ManualLivePermit(
        execution_id="execution", account_id="ACC-1", broker_name="SIM",
        broker=broker, queue_fingerprint="queue-fp",
        prepared_fingerprints=("fp-0", "fp-1"),
        gate_decision=SafetyGateDecision(True, "ALLOWED", None, "ok"),
        _issuer=_MANUAL_PERMIT_ISSUER,
    )

    class Auth:
        def get_purchase_power(self, _account_id): return 1000

    class Coordinator:
        def __init__(self):
            self.engine = SimpleNamespace(submit_manual_prepared_order=self.submit)
        def prepare(self, _targets):
            return "execution", SimpleNamespace(
                valid=True, checks_succeeded=True, message="",
                orders=tuple(SimpleNamespace(order=order) for order in orders),
            )
        def submit(self, prepared, **kwargs):
            calls.append((prepared.order, kwargs.copy()))
            return SimpleNamespace(success=True, sent=True, mode="LIVE", order=prepared.order)

    manager = SimpleNamespace(get_for_account=lambda *_args: broker)
    try:
        page._order_authorizer_factory = lambda: lambda *_args: SimpleNamespace(authorized=True)
        page._authentication_service_factory = lambda: Auth()
        page._manual_broker_manager_factory = lambda: manager
        page._live_prearm_factory = lambda _targets: Coordinator()
        page._live_scope_rejection = lambda *_args: None
        page._live_snapshot = lambda *_args: "snapshot"
        page._live_snapshot_unchanged = lambda *_args: True
        page.set_session_manager(object())
        page._confirm_live_start = lambda _summary: True
        monkeypatch.setattr(
            "ui.live_order_gate.check_manual_live_preflight",
            lambda **_kwargs: __import__("ui.live_order_gate", fromlist=["LiveReadiness"]).LiveReadiness(
                True, "ready", gate=object(),
                send_table=("queue-fp", SafetyGateDecision(True, "ALLOWED", None, "ok"), broker),
            ),
        )
        monkeypatch.setattr(
            "ui.live_order_gate.issue_manual_live_permit",
            lambda **_kwargs: (permit, "queue-fp"),
        )
        monkeypatch.setattr(page, "_test_runner", lambda **_kwargs: object())
        page._ensure_feedback_binding = lambda: None
        page._feedback_binders = {}
        page._refresh_result_display = lambda: None
        page._refresh_diagnostic_trace_display = lambda: None
        page._refresh_diagnostic_latency_display = lambda: None
        page._run_test_pass()

        assert len(calls) == len(orders) == 2
        assert [call[0] for call in calls] == list(orders)
        assert [call[1]["index"] for call in calls] == [0, 1]
        assert all(call[1]["broker"] is broker for call in calls)
        assert all(call[1]["permit"] is permit for call in calls)
        assert all(call[1]["trace_id"] == "ui-trace-test" for call in calls)
        by_order = {event["order_index"] for event in events}
        assert by_order == {0, 1}
        assert all(event["trace_id"] == "ui-trace-test" for event in events)
        stages = [event["stage"] for event in events]
        assert stages.index("confirm_yes") < stages.index("readiness_preflight_start")
        assert stages.index("permit_issue_result") < stages.index("snapshot_final_result")
        assert stages.index("permit_validation") < stages.index("broker_resolve_start")
        assert stages.index("broker_resolve_result") < stages.index("permit_validation_final")
        assert [e["order_index"] for e in events if e["stage"] == "confirm_yes"] == [0, 1]
        assert all(e["trace_id"] == "ui-trace-test" for e in events)
    finally:
        page.close()


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("balance", "READINESS_BALANCE_INVALID"),
        ("engine_validation", "READINESS_ENGINE_VALIDATION_FAILED"),
        ("session_binding", "READINESS_SESSION_BINDING_INVALID"),
        ("safety_gate", "READINESS_SAFETY_GATE_REJECTED"),
    ],
)
def test_internal_preflight_stops_have_specific_reason_and_correlation(
    qapp, monkeypatch, failure, reason
):
    from ui.live_order_gate import check_manual_live_preflight

    events = []
    entry = SimpleNamespace(account_id="ACC-1", broker_name="SIM",
                            order=SimpleNamespace(side=1, price=10, quantity=1,
                                                  to_payload=lambda: {}))
    @dataclass
    class Prepared:
        order: object
        scheduled_valid: bool = True
        account_fingerprint: str = "before"
    @dataclass
    class AccountCopy:
        account_id: str
        tradable_balance_t1: int
    prepared = Prepared(entry.order)
    batch = SimpleNamespace(orders=(prepared,), valid=True,
                            checks_succeeded=True, execution_id="execution")
    account = AccountCopy("ACC-1", 100)
    record = SimpleNamespace(account=account, broker_name="SIM")
    broker = SimpleNamespace(submit_manual_prepared_order=lambda **_kwargs: pytest.fail("no submit"))
    store = SimpleNamespace(get=lambda _aid: record, active_account_id=lambda: "ACC-1")
    session = SimpleNamespace(state=SimpleNamespace(value="logged_out" if failure == "session_binding" else "logged_in"), account_id="ACC-1",
                              broker_name="SIM")
    sessions = SimpleNamespace(get=lambda _aid: session, get_token=lambda _aid: "fake-token")
    auth = SimpleNamespace(
        get_purchase_power=lambda _aid: None if failure == "balance" else 100,
    )
    engine = SimpleNamespace(
        _fingerprint=lambda _value: "fresh",
        validate_prepared_order=lambda *_args, **_kwargs: (
            (False, "safe internal detail") if failure == "engine_validation" else (True, "")
        ),
    )
    callback = lambda stage, **kwargs: events.append({
        "trace_id": "helper-trace", "stage": stage,
        "order_index": 4, **kwargs,
    })
    import ui.order_authorization as auth_module
    monkeypatch.setattr(auth_module, "authorize_order",
                        lambda *_args: SimpleNamespace(authorized=True))
    monkeypatch.setattr("core.safety_gate.SafetyGate.evaluate",
                        lambda *_args, **_kwargs: SimpleNamespace(
                            allowed=failure != "safety_gate",
                            blocked_by="safety_gate", reason="safe reason"))

    result = check_manual_live_preflight(
        account_store=store, authentication_service=auth,
        session_manager=sessions,
        broker_manager=SimpleNamespace(get_for_account=lambda *_args: broker),
        account_id="ACC-1", broker_name="SIM", execution_id="execution",
        entries=(entry,), prepared_batch=batch, engine=engine,
        live_selected=True, human_approval=True,
        include_missing_broker_ack=True, confirmation_acknowledged=True,
        trace_callback=callback,
    )
    stopped = [event for event in events if event.get("reason_code") == reason]
    assert len(stopped) == 1
    assert stopped[0]["trace_id"] == "helper-trace"
    assert stopped[0]["order_index"] == 4
    assert result.allowed is False
    if failure == "balance":
        assert not any(e["stage"] == "readiness_engine_validation_start" for e in events)
    if failure == "engine_validation":
        assert not any(e["stage"] == "readiness_session_binding" for e in events)
    if failure == "session_binding":
        assert any(e["stage"] == "readiness_session_binding" for e in events)
        assert not any(e["stage"] == "readiness_safety_gate" for e in events)
    if failure == "safety_gate":
        assert any(e["stage"] == "readiness_safety_gate" for e in events)
    assert "safe internal detail" not in repr(events)


def test_preflight_auth_and_broker_resolve_stop_before_balance(qapp, monkeypatch):
    from ui.live_order_gate import check_manual_live_preflight

    events = []
    entry = SimpleNamespace(account_id="ACC-1", broker_name="SIM", order=object())
    record = SimpleNamespace(account=SimpleNamespace(account_id="ACC-1"), broker_name="SIM")
    callback = lambda stage, **kwargs: events.append({
        "trace_id": "helper-trace", "stage": stage, "order_index": 2, **kwargs,
    })
    import ui.order_authorization as auth_module
    monkeypatch.setattr(auth_module, "authorize_order",
                        lambda *_args: SimpleNamespace(authorized=False))
    result = check_manual_live_preflight(
        account_store=SimpleNamespace(get=lambda _aid: record),
        authentication_service=SimpleNamespace(get_purchase_power=lambda *_: pytest.fail("balance after auth stop")),
        session_manager=object(), broker_manager=object(), account_id="ACC-1",
        broker_name="SIM", execution_id="execution", entries=(entry,),
        prepared_batch=SimpleNamespace(orders=()), engine=object(),
        live_selected=True, human_approval=True, confirmation_acknowledged=True,
        trace_callback=callback,
    )
    assert result.allowed is False
    event = next(event for event in events if event.get("reason_code") == "READINESS_AUTH_REJECTED")
    assert (event["trace_id"], event["order_index"]) == ("helper-trace", 2)
    assert not any(event["stage"] == "readiness_broker_resolve_start" for event in events)
    assert not any(event["stage"] == "readiness_balance_start" for event in events)


def test_preflight_broker_resolve_exception_has_safe_reason(qapp, monkeypatch):
    from ui.live_order_gate import check_manual_live_preflight

    events = []
    entry = SimpleNamespace(account_id="ACC-1", broker_name="SIM", order=object())
    record = SimpleNamespace(account=SimpleNamespace(account_id="ACC-1"), broker_name="SIM")
    monkeypatch.setattr("ui.order_authorization.authorize_order",
                        lambda *_args: SimpleNamespace(authorized=True))
    result = check_manual_live_preflight(
        account_store=SimpleNamespace(get=lambda _aid: record),
        authentication_service=SimpleNamespace(get_purchase_power=lambda _aid: 100),
        session_manager=object(),
        broker_manager=SimpleNamespace(get_for_account=lambda *_args: (_ for _ in ()).throw(RuntimeError("BROKER_SECRET"))),
        account_id="ACC-1", broker_name="SIM", execution_id="execution",
        entries=(entry,), prepared_batch=SimpleNamespace(orders=()), engine=object(),
        live_selected=True, human_approval=True, confirmation_acknowledged=True,
        trace_callback=lambda stage, **kwargs: events.append({
            "trace_id": "helper-trace", "stage": stage, "order_index": 1, **kwargs,
        }),
    )
    assert result.allowed is False
    failure = next(event for event in events if event.get("reason_code") == "READINESS_PREFLIGHT_EXCEPTION")
    assert (failure["trace_id"], failure["order_index"]) == ("helper-trace", 1)
    assert "BROKER_SECRET" not in repr(events)
    assert not any(event["stage"] == "readiness_balance_start" for event in events)


def test_live_dispatch_exception_does_not_convert_unknown_or_completed_results(qapp, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from core.order_engine import OrderExecutionResult
    from ui.order_configuration_page import _collect_manual_live_results

    entries = [SimpleNamespace(order=object(), broker_name="SIM") for _ in range(2)]
    completed_unknown = OrderExecutionResult(False, False, "UNKNOWN", entries[0].order,
                                             broker_name="SIM")
    calls = []
    def submit_one(pair):
        index, _prepared = pair
        calls.append(index)
        if index == 0:
            return completed_unknown
        raise RuntimeError("failure after Engine entry")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = _collect_manual_live_results(
            pool, entries, (object(), object()), submit_one, OrderExecutionResult,
        )
    assert sorted(calls) == [0, 1]
    assert [result.mode for result in results] == ["UNKNOWN", "UNKNOWN"]
    assert results[0] is completed_unknown
    assert all(result.mode != "NOT_SENT" for result in results)


def test_ui_final_result_is_correlated_fixed_and_deduplicated_on_refresh(qapp, monkeypatch):
    from core.order_engine import OrderExecutionResult

    page, events, _queue = _page(qapp, monkeypatch)
    try:
        entries = list(page.order_queue.list_pending())
        orders = [entry.order for entry in entries]
        page._last_test_run_mode = "live"
        page._last_test_trace_id = "ui-trace-test"
        page._active_result_execution_id = "exec-test-1"
        page._last_test_entries = entries
        page._last_order_results = [
            OrderExecutionResult(True, True, "LIVE", orders[0], broker_name="SIM"),
            OrderExecutionResult(False, False, "UNKNOWN", orders[1], broker_name="SIM",
                                 message="SENSITIVE_EXCEPTION"),
        ]
        page._refresh_result_display()
        page._refresh_result_display()
        final = [event for event in events if event["stage"] == "ui_final_result"]
        assert [(event["trace_id"], event["order_index"], event["extra"]["ui_result"])
                for event in final] == [
                    ("ui-trace-test", 0, "SUCCESS"),
                    ("ui-trace-test", 1, "UNKNOWN"),
                ]
        assert "SENSITIVE_EXCEPTION" not in repr(final)
    finally:
        page.close()


def test_ui_final_result_preserves_partial_status_and_ignores_logger_failure(qapp, monkeypatch):
    from core.order_engine import OrderExecutionResult

    page, events, _queue = _page(qapp, monkeypatch)
    original_results = [
        OrderExecutionResult(True, True, "LIVE", object(), broker_name="SIM"),
        OrderExecutionResult(False, False, "BLOCKED", object(), broker_name="SIM"),
    ]
    page._last_test_run_mode = "live"
    page._last_test_trace_id = "ui-trace-test"
    page._active_result_execution_id = "exec-test-partial"
    page._last_test_entries = list(page.order_queue.list_pending())
    page._last_order_results = original_results
    monkeypatch.setattr(manual_live_trace, "log_event",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("LOGGER_SECRET")))
    try:
        page._refresh_result_display()
        page._refresh_result_display()
        assert page._last_order_results == original_results
        from ui.order_configuration_page import RESULT_STATUS_LIVE_SUCCESS, RESULT_STATUS_BLOCKED
        assert RESULT_STATUS_LIVE_SUCCESS in page.result_list.item(0).text()
        assert RESULT_STATUS_BLOCKED in page.result_list.item(1).text()
    finally:
        page.close()


@pytest.mark.parametrize(
    ("stop", "reason"),
    [
        ("snapshot_post", "SNAPSHOT_POST_CONFIRM_CHANGED"),
        ("auth_post", "AUTH_POST_CONFIRM_REJECTED"),
        ("readiness", "READINESS_PREFLIGHT_REJECTED"),
    ],
)
def test_post_confirm_stop_gates_trace_and_do_not_enter_engine(qapp, monkeypatch, stop, reason):
    page, events, _queue = _page(qapp, monkeypatch)
    from ui.live_order_gate import LiveReadiness

    class PreparedBatch:
        valid = True
        checks_succeeded = True
        message = ""
        orders = (object(), object())

    class Coordinator:
        engine = object()
        def prepare(self, targets):
            return "execution", PreparedBatch()

    class Auth:
        def get_purchase_power(self, _account_id): return 1000

    calls = {"auth": 0, "engine": 0, "readiness": 0}
    try:
        page._authentication_service_factory = lambda: Auth()
        page._live_prearm_factory = lambda _targets: Coordinator()
        page._live_scope_rejection = lambda *_args: None
        page._live_snapshot = lambda *_args: "snap"
        page._live_snapshot_unchanged = lambda *_args: stop != "snapshot_post"
        page.set_session_manager(object())
        import ui.order_authorization as auth_module
        def auth(*_args):
            calls["auth"] += 1
            return SimpleNamespace(authorized=stop != "auth_post" or calls["auth"] == 1)
        monkeypatch.setattr(auth_module, "authorize_order", auth)
        page._confirm_live_start = lambda _summary: True
        monkeypatch.setattr(
            "ui.live_order_gate.check_manual_live_preflight",
            lambda **_kwargs: (calls.__setitem__("readiness", calls["readiness"] + 1)
                               or LiveReadiness(False, "blocked")),
        )
        page._run_test_pass()
        stopped = [e for e in events if e["reason_code"] == reason]
        assert stopped and all(e["trace_id"] == "ui-trace-test" for e in stopped)
        assert [e["order_index"] for e in stopped] == [0, 1]
        assert calls["engine"] == 0
        if stop == "snapshot_post":
            assert calls["auth"] == 1 and calls["readiness"] == 0
        elif stop == "auth_post":
            assert calls["auth"] == 2 and calls["readiness"] == 0
        else:
            assert calls["readiness"] == 1
    finally:
        page.close()


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("permit_issue", "PERMIT_ISSUE_EXCEPTION"),
        ("auth_final", "AUTH_FINAL_REJECTED"),
        ("snapshot_final", "SNAPSHOT_FINAL_CHANGED"),
        ("permit_validation", "PERMIT_POST_ISSUE_INVALID"),
        ("broker_resolve", "BROKER_RESOLVE_EXCEPTION"),
    ],
)
def test_permit_final_and_broker_stops_are_correlated_and_block_engine(
    qapp, monkeypatch, failure, reason
):
    page, events, _queue = _page(qapp, monkeypatch)
    from ui.live_order_gate import LiveReadiness

    class PreparedBatch:
        valid = True
        checks_succeeded = True
        message = ""
        orders = (object(), object())

    class Coordinator:
        engine = object()
        def prepare(self, _targets): return "execution", PreparedBatch()

    class Auth:
        def get_purchase_power(self, _account_id): return 1000

    class Permit:
        closed = False
        def close(self): self.closed = True

    calls = {"auth": 0, "permit": 0, "broker": 0, "engine": 0, "snapshot": 0}
    fake_permit = Permit()
    try:
        page._order_authorizer_factory = lambda: lambda *_args: SimpleNamespace(authorized=True)
        page._authentication_service_factory = lambda: Auth()
        page._live_prearm_factory = lambda _targets: Coordinator()
        page._live_scope_rejection = lambda *_args: None
        page._live_snapshot = lambda *_args: "snap"
        def snapshot_check(*_args):
            calls["snapshot"] += 1
            return not (failure == "snapshot_final" and calls["snapshot"] == 2)
        page._live_snapshot_unchanged = snapshot_check
        page.set_session_manager(object())
        page._manual_broker_manager_factory = lambda: SimpleNamespace(
            get_for_account=lambda *_args: resolve_broker()
        )
        def resolve_broker():
            calls["broker"] += 1
            if failure == "broker_resolve":
                raise RuntimeError("BROKER_SECRET")
            return readiness_broker
        import ui.order_authorization as auth_module
        def authorize(*_args):
            calls["auth"] += 1
            return SimpleNamespace(authorized=not (failure == "auth_final" and calls["auth"] == 3))
        monkeypatch.setattr(auth_module, "authorize_order", authorize)
        page._confirm_live_start = lambda _summary: True
        readiness_broker = object()
        monkeypatch.setattr(
            "ui.live_order_gate.check_manual_live_preflight",
            lambda **kwargs: LiveReadiness(
                True, "ready", gate=object(),
                send_table=("queue-fp", object(), readiness_broker),
            ),
        )
        if failure == "permit_issue":
            monkeypatch.setattr(
                "ui.live_order_gate.issue_manual_live_permit",
                lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("PERMIT_SECRET")),
            )
        else:
            monkeypatch.setattr(
                "ui.live_order_gate.issue_manual_live_permit",
                lambda **_kwargs: (fake_permit, "queue-fp"),
            )
        if failure == "permit_validation":
            # Return an opaque permit so the post-issue capability type check stops it.
            monkeypatch.setattr(
                "ui.live_order_gate.issue_manual_live_permit",
                lambda **_kwargs: (object(), "queue-fp"),
            )
        page._ensure_feedback_binding = lambda: None
        page._refresh_result_display = lambda: None
        page._refresh_diagnostic_trace_display = lambda: None
        page._refresh_diagnostic_latency_display = lambda: None
        page._feedback_binders = {}
        if failure == "broker_resolve":
            from core.live_order_authorization import ManualLivePermit, _MANUAL_PERMIT_ISSUER
            from core.safety_gate import SafetyGateDecision
            valid_permit = ManualLivePermit(
                execution_id="execution", account_id="ACC-1", broker_name="SIM",
                broker=readiness_broker, queue_fingerprint="queue-fp",
                prepared_fingerprints=("one", "two"),
                gate_decision=SafetyGateDecision(True, "ALLOWED", None, "ok"),
                _issuer=_MANUAL_PERMIT_ISSUER,
            )
            monkeypatch.setattr(
                "ui.live_order_gate.issue_manual_live_permit",
                lambda **_kwargs: (valid_permit, "queue-fp"),
            )
            page._live_prearm_factory = lambda _targets: SimpleNamespace(
                engine=SimpleNamespace(submit_manual_prepared_order=lambda *_a, **_kw:
                                       calls.__setitem__("engine", calls["engine"] + 1)),
                prepare=lambda _targets: ("execution", SimpleNamespace(
                    valid=True, checks_succeeded=True, message="",
                    orders=tuple(SimpleNamespace(order=e.order) for e in _queue.list_pending()),
                )),
            )
            page._test_runner_factory = lambda **_kwargs: object()
            monkeypatch.setattr(page, "_test_runner", lambda **_kwargs: object())
        page._run_test_pass()
        stopped = [event for event in events if event["reason_code"] == reason]
        assert len(stopped) == 2
        assert [event["order_index"] for event in stopped] == [0, 1]
        assert all(event["trace_id"] == "ui-trace-test" for event in stopped)
        assert calls["engine"] == 0
        assert page._last_order_results and all(r.mode == "NOT_SENT" for r in page._last_order_results)
        if failure == "permit_issue":
            assert calls["auth"] == 2 and calls["broker"] == 0
        elif failure == "auth_final":
            assert calls["auth"] == 3 and calls["broker"] == 0 and fake_permit.closed
        elif failure == "snapshot_final":
            assert calls["snapshot"] == 2 and calls["broker"] == 0 and fake_permit.closed
        elif failure == "permit_validation":
            assert calls["broker"] == 0
        elif failure == "broker_resolve":
            assert calls["broker"] == 1
    finally:
        page.close()
