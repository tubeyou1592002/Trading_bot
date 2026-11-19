"""Pure normalization for Agah OMS order-feedback observations."""

import time
from typing import Callable

from brokers.order_feedback_contract import (
    FeedbackMilestone,
    FeedbackUnavailable,
    OrderFeedbackEvent,
)


class AgahOrderFeedbackAdapter:
    """Normalize native OMS events when exact order and account scope exist.

    The existing correlated callback supplies a decision ID and tracking info,
    but not an account ID or action. It is therefore insufficient by itself;
    callers may pass the native event only when the actual action and account
    scope are represented in its fields.
    """

    def __init__(self, account_id: str, clock_ns: Callable[[], int] = time.monotonic_ns):
        self.account_id = account_id
        self._clock_ns = clock_ns

    @staticmethod
    def _field(event, name, default=None):
        return event.get(name, default) if isinstance(event, dict) else getattr(event, name, default)

    def normalize(self, native_event):
        action = self._field(native_event, "action")
        if type(action) is not int or action != 5:
            return FeedbackUnavailable("Agah event is not proven AcceptedByBourse (action 5)")

        decision_id = self._field(native_event, "decision_id")
        if self._field(native_event, "decision_registered", True) is not True:
            return FeedbackUnavailable("Agah decision is not registered")
        scope = self._field(native_event, "account_id") or self.account_id
        if not isinstance(decision_id, str) or not decision_id.strip():
            return FeedbackUnavailable("Agah feedback lacks a decision ID")
        if not isinstance(scope, str) or not scope.strip():
            return FeedbackUnavailable("Agah feedback lacks account scope")

        received_ns = self._field(native_event, "app_received_monotonic_ns")
        if received_ns is None:
            received_ns = self._clock_ns()
        if isinstance(received_ns, bool) or not isinstance(received_ns, int) or received_ns < 0:
            raise ValueError("monotonic clock must return a non-negative integer")

        return OrderFeedbackEvent(
            broker_name="agaah",
            account_id=scope,
            milestone=FeedbackMilestone.OMS_ACCEPTED_BY_BOURSE,
            app_received_monotonic_ns=received_ns,
            source="agaah-oms",
            decision_id=decision_id,
            external_wall_timestamp=self._field(native_event, "raw_timestamp"),
        )
