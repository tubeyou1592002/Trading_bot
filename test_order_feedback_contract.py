from dataclasses import FrozenInstanceError

import pytest

from brokers.order_feedback_contract import (
    FeedbackMilestone,
    FeedbackUnavailable,
    OrderFeedbackEvent,
    normalize_correlation,
)
from brokers.agaah.order_feedback_adapter import AgahOrderFeedbackAdapter


def event(**overrides):
    values = dict(
        broker_name="broker", account_id="account",
        milestone=FeedbackMilestone.API_RESPONSE,
        app_received_monotonic_ns=123, source="native-api",
    )
    values.update(overrides)
    return OrderFeedbackEvent(**values)


def test_event_is_immutable_and_optional_fields_are_allowed():
    item = event()
    assert item.decision_id is None
    assert item.order_id is None
    assert item.external_wall_timestamp is None
    with pytest.raises(FrozenInstanceError):
        item.source = "changed"
    assert FeedbackUnavailable("native feedback unsupported").reason


@pytest.mark.parametrize("value", [-1, True, False])
def test_monotonic_ns_rejects_negative_and_bool(value):
    with pytest.raises(ValueError):
        event(app_received_monotonic_ns=value)


def test_milestones_are_distinct():
    api = event(milestone=FeedbackMilestone.API_RESPONSE)
    oms = event(milestone=FeedbackMilestone.OMS_ACCEPTED_BY_BOURSE)
    assert api.milestone is not oms.milestone


def test_correlation_uses_native_ids_only_never_symbol_or_time():
    assert normalize_correlation(symbol="ABC", event_time=123) == {}
    assert normalize_correlation(
        decision_id="decision", symbol="ABC", event_time=123
    ) == {"decision_id": "decision"}


def test_two_broker_offline_feedback_contract_does_not_cross_correlate():
    """OMS capability may differ; unavailable feedback cannot hide API metrics."""
    from core.latency_instrumentation import (
        BrokerApiCallTiming,
        DispatchLatencyReport,
        OrderLatency,
        StageTiming,
    )

    class FeedbackRecorder:
        def __init__(self):
            self.events = []
            self.unavailable = []

        def record(self, result):
            if isinstance(result, OrderFeedbackEvent):
                self.events.append(result)
            else:
                assert isinstance(result, FeedbackUnavailable)
                self.unavailable.append(result)

    # Deterministic fake adapters; Mofid declares no feedback support and
    # does not infer it from matching account, symbol, or event time.
    class NoFeedbackAdapter:
        def normalize(self, _native_event):
            return FeedbackUnavailable("native feedback capability unavailable")

    recorder = FeedbackRecorder()
    agah = AgahOrderFeedbackAdapter("agah-account", clock_ns=lambda: 456789)
    agah_event = agah.normalize({
        "action": 5, "decision_id": "agah-order", "account_id": "agah-account",
        "symbol": "SAME", "event_time": 123,
    })
    recorder.record(agah_event)
    assert agah_event.milestone is FeedbackMilestone.OMS_ACCEPTED_BY_BOURSE
    assert agah_event.app_received_monotonic_ns == 456789
    assert agah_event.account_id == "agah-account"

    mofid_order = "mofid-order"
    unavailable = NoFeedbackAdapter().normalize({
        "account_id": "mofid-account", "symbol": "SAME", "event_time": 123,
    })
    recorder.record(unavailable)
    assert unavailable.reason
    assert recorder.events == [agah_event]
    assert len(recorder.unavailable) == 1

    # A successful offline diagnostic report retains API/Block8 measurements
    # for the no-feedback order; feedback absence is not report failure.
    mofid_timing = OrderLatency(
        sequence=1, account_id="mofid-account", broker_name="mofid",
        ins_code="INS-MOFID", stages=[StageTiming("order_engine_path", 10, 30)],
        broker_api_calls=[BrokerApiCallTiming("place_order", 20, 25)],
    )
    report = DispatchLatencyReport(
        trace_id="offline-trace", dispatch_start=10, dispatch_end=30,
        orders=[mofid_timing],
    )
    assert report is not None
    assert report.orders[0].duration_ns("order_engine_path") == 20
    assert report.orders[0].broker_api_call("place_order").duration_ns == 5

    # Neither shared symbol/time nor the other account's decision may bind
    # this order; only exact native IDs are accepted by the contract.
    assert normalize_correlation(
        decision_id="agah-order", symbol="SAME", event_time=123
    ) == {"decision_id": "agah-order"}
    assert normalize_correlation(symbol="SAME", event_time=123) == {}


def test_two_broker_feedback_is_rendered_through_real_diagnostic_page():
    from types import SimpleNamespace
    from datetime import datetime

    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
    from core.latency_instrumentation import (
        BrokerApiCallTiming, DispatchLatencyReport, OrderLatency, StageTiming,
    )
    from core.order_engine import OrderExecutionResult
    from models.order import BUY, Order
    from ui.account_store import AccountStore
    from ui.order_configuration_page import OrderConfigurationPage
    from core.order_queue import OrderQueue
    from brokers.order_feedback_contract import OrderFeedbackEvent

    class Binder(QObject):
        order_registered = Signal(str, object, object)
        normalized_feedback = Signal(object)

    app = QApplication.instance() or QApplication([])
    store = AccountStore(repository=False)
    store.add("agah-account", "agaah", "Agah")
    store.add("mofid-account", "mofid", "Mofid")
    store.set_active("agah-account")
    page = OrderConfigurationPage(store, order_queue=OrderQueue())
    agah_binder = Binder()
    page.set_feedback_binder_factory(
        lambda account, _broker: agah_binder if account == "agah-account" else None
    )
    agah_order = Order(nsc_id="INS-AGAH", side=BUY, price=100, quantity=1)
    agah_order.order_id = "broker-order-agah"
    mofid_order = Order(nsc_id="INS-MOFID", side=BUY, price=100, quantity=1)
    entries, results = [], []
    for order, account, broker, decision in (
        (agah_order, "agah-account", "agaah", "agah-decision"),
        (mofid_order, "agah-account", "agaah", "mofid-decision"),
    ):
        entries.append(SimpleNamespace(order=order, account_id=account, broker_name=broker))
        results.append(OrderExecutionResult(
        success=True, sent=True, mode="LIVE", order=order, broker_name=broker,
        response={"isSuccess": True, "data": {"decisionId": decision}},
        ))
    mofid_result = results[1]
    page._last_test_entries = [entries[0]]
    page._last_order_results = [results[0]]
    # Page send/log correlation is scoped to the active account+broker.
    page._append_order_log_rows(page._last_test_entries, datetime(2026, 9, 30), page._last_order_results)
    # Mofid's independent no-feedback diagnostics are represented by its
    # report execution result below, not by a page send on another account.
    page._ensure_feedback_binding()
    assert page._feedback_binders[("agah-account", "agaah")] is agah_binder
    page._last_test_run_mode = "diagnostic"

    agah_event = AgahOrderFeedbackAdapter(
        "agah-account", clock_ns=lambda: 456789,
    ).normalize({
        "action": 5, "decision_id": "agah-decision",
        "account_id": "agah-account", "symbol": "SAME", "event_time": 123,
    })
    assert isinstance(agah_event, OrderFeedbackEvent)
    wrong = [
        AgahOrderFeedbackAdapter("agah-account", clock_ns=lambda: 456789).normalize({
            "action": 5, "decision_id": "unknown", "order_id": "broker-order-agah",
            "account_id": "agah-account",
        }),
        AgahOrderFeedbackAdapter("other-account", clock_ns=lambda: 456789).normalize({
            "action": 5, "decision_id": "agah-decision", "order_id": "broker-order-agah",
            "account_id": "other-account",
        }),
    ]
    try:
        report = DispatchLatencyReport(
            trace_id="offline-two-broker", dispatch_start=10, dispatch_end=40,
            orders=[
                OrderLatency(sequence=0, stages=[StageTiming("order_engine_path", 10, 40)],
                    execution_result=results[0]),
                OrderLatency(sequence=1, stages=[StageTiming("order_engine_path", 10, 40)],
                        execution_result=mofid_result,
                        account_id="mofid-account", broker_name="mofid",
                        ins_code="INS-MOFID",
                    broker_api_calls=[BrokerApiCallTiming("place_order", 20, 25)]),
            ],
        )
        page._last_latency_report = report
        for event in wrong:
            agah_binder.normalized_feedback.emit(event)
        assert not page._normalized_feedback_by_order
        agah_binder.normalized_feedback.emit(agah_event)
        page._refresh_diagnostic_latency_display()
        rows = [
            [page.latency_detail_list.item(r, c).text()
             if page.latency_detail_list.item(r, c) else ""
             for c in range(page.latency_detail_list.columnCount())]
            for r in range(page.latency_detail_list.rowCount())
        ]
        rendered = "\n".join(map(str, rows))
        assert "پذیرش در بورس" in rendered
        assert "Broker/API place_order" in rendered
        oms_acceptance_rows = [row for row in rows if "OMS" in row[4] and "پذیرش در بورس" in row[4]]
        external_wall_rows = [row for row in rows if "زمان خارجی رویداد OMS" in row[4]]
        assert len(oms_acceptance_rows) == 1
        assert len(external_wall_rows) == 1
        assert "پذیرش در بورس" in oms_acceptance_rows[0][4]
        assert external_wall_rows[0][4] == "زمان خارجی رویداد OMS"
        assert external_wall_rows[0][5] == "ناموجود"
        # Block 8 identity is the recorded stage/operation, not an inferred
        # Mofid instrument display name (no order-symbol mapping was installed).
        assert any("order_engine_path" in row[4] for row in rows)
        assert any("Broker/API place_order" in row[4] for row in rows)
        assert "agah-decision" not in rendered and "broker-order-agah" not in rendered
        assert page._diagnostic_latency_report() is report
        app.processEvents()
    finally:
        page.close()
