"""Focused offline checks for Task 11.4's pre-arm primitives."""

from test_live_batch_authorization import _readiness, _setup
from core.order_engine import PreparedBatch
from ui.live_order_gate import validate_live_batch_authorization


def test_prearm_snapshot_check_is_local_and_submit_keeps_start_guard(monkeypatch):
    state = _setup(monkeypatch)
    ready = _readiness(state)
    assert ready.authorization is not None
    check = validate_live_batch_authorization(
        authorization=ready.authorization,
        account_store=type("Store", (), {"get": lambda self, key: state["records"][key]})(),
        authentication_service=state["auth"],
        session_manager=state["sessions"],
        broker_manager=state["manager"],
        targets=state["targets"],
        prepared_batch=PreparedBatch(state["prepared"], True, "", True,
                                     state["execution_id"]),
        timing=state["timing"], interval_ms=5000,
        execution_id=state["execution_id"], queue_revision=42,
        engine=state["engine"], now=state["now"], pre_arm=True,
    )
    assert check.allowed
    target = state["targets"][0]
    result = state["engine"].submit_prepared_order(
        state["prepared"][0], state["brokers"][(target.account_id, target.broker_name)],
        target.account, target.account_id, target.broker_name, live=True,
        authorization=ready.authorization, now=state["now"],
    )
    assert not result.success
