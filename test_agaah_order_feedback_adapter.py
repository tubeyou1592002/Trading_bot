from types import SimpleNamespace

import pytest

from brokers.agaah.order_feedback_adapter import AgahOrderFeedbackAdapter
from brokers.order_feedback_contract import FeedbackMilestone, FeedbackUnavailable


def test_action_five_normalizes_ids_and_keeps_clocks_separate():
    adapter = AgahOrderFeedbackAdapter("acct-1", clock_ns=lambda: 1234)
    result = adapter.normalize(SimpleNamespace(
        action=5, decision_id="decision-1", raw_timestamp=987.5,
        symbol="ABC", event_time=987.5,
    ))
    assert result.milestone is FeedbackMilestone.OMS_ACCEPTED_BY_BOURSE
    assert result.app_received_monotonic_ns == 1234
    assert result.external_wall_timestamp == 987.5
    assert result.account_id == "acct-1"
    assert result.decision_id == "decision-1"
    assert result.order_id is None


@pytest.mark.parametrize("action", [None, 2, 4, "5"])
def test_non_five_action_is_unavailable(action):
    result = AgahOrderFeedbackAdapter("acct").normalize(
        {"action": action, "decision_id": "d"}
    )
    assert isinstance(result, FeedbackUnavailable)


def test_missing_decision_id_or_account_scope_is_unavailable():
    adapter = AgahOrderFeedbackAdapter("")
    assert isinstance(adapter.normalize({"action": 5}), FeedbackUnavailable)
    assert isinstance(
        adapter.normalize({"action": 5, "decision_id": "d"}),
        FeedbackUnavailable,
    )


def test_symbol_and_time_never_substitute_for_decision_id():
    result = AgahOrderFeedbackAdapter("acct").normalize(
        {"action": 5, "symbol": "ABC", "event_time": 12}
    )
    assert isinstance(result, FeedbackUnavailable)


@pytest.mark.parametrize("clock", [-1, True, 1.5])
def test_invalid_monotonic_clock_value_rejected(clock):
    adapter = AgahOrderFeedbackAdapter("acct", clock_ns=lambda: clock)
    with pytest.raises((TypeError, ValueError)):
        adapter.normalize({"action": 5, "decision_id": "d"})
