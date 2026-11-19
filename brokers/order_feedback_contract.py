"""Offline, broker-neutral contract for order feedback events."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, Union


class FeedbackMilestone(Enum):
    """Independent milestones; an API response is not OMS acceptance."""

    API_RESPONSE = "api_response"
    OMS_ACCEPTED_BY_BOURSE = "oms_accepted_by_bourse"


@dataclass(frozen=True)
class OrderFeedbackEvent:
    """Immutable normalized event with account scope and trustworthy IDs only."""

    broker_name: str
    account_id: str
    milestone: FeedbackMilestone
    app_received_monotonic_ns: int
    source: str
    decision_id: Optional[str] = None
    order_id: Optional[str] = None
    external_wall_timestamp: Optional[Union[str, int, float]] = None

    def __post_init__(self):
        if not isinstance(self.broker_name, str) or not self.broker_name.strip():
            raise ValueError("broker_name must be a non-empty string")
        if not isinstance(self.account_id, str) or not self.account_id.strip():
            raise ValueError("account_id must be a non-empty string")
        if not isinstance(self.milestone, FeedbackMilestone):
            raise TypeError("milestone must be a FeedbackMilestone")
        if (isinstance(self.app_received_monotonic_ns, bool)
                or not isinstance(self.app_received_monotonic_ns, int)
                or self.app_received_monotonic_ns < 0):
            raise ValueError("app_received_monotonic_ns must be a non-negative integer")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-empty string")
        for name in ("decision_id", "order_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string when supplied")
        if self.external_wall_timestamp is not None and isinstance(
            self.external_wall_timestamp, bool
        ):
            raise TypeError("external_wall_timestamp cannot be bool")


@dataclass(frozen=True)
class FeedbackUnavailable:
    """Explicit capability-unavailable result; no synthetic matching is implied."""

    reason: str

    def __post_init__(self):
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")


FeedbackNormalization = Union[OrderFeedbackEvent, FeedbackUnavailable]


class OrderFeedbackAdapter(Protocol):
    """Pure/local adapter contract; implementations perform no networking here."""

    def normalize(self, native_event: object) -> FeedbackNormalization:
        """Normalize a native event or report unsupported/unavailable."""


def normalize_correlation(*, decision_id=None, order_id=None, symbol=None,
                          event_time=None):
    """Return only supplied trustworthy IDs; symbol/time are never correlation."""
    del symbol, event_time
    return {key: value for key, value in (
        ("decision_id", decision_id), ("order_id", order_id)
    ) if value is not None}
