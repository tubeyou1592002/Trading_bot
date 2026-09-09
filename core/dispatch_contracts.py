"""
Block 0 — Dispatch Architecture Foundation.

This module defines the **base contracts** of the Dispatch Engine:
the architectural boundaries and data contracts that later blocks
(Planner, Dispatch Core, Timed/Burst, Event-Driven) build upon.

It is intentionally contract-only. There is no execution behavior,
no scheduler, no event bus, no polling, and no broker implementation
here.

Dispatch boundary (Block 0):

    Trigger
        │
        ▼
    Planner (Block 1)
        │
        ▼
    Dispatch Core (Block 2)
        │
        ▼
    existing M6-A … M6-E  (OrderEngine.prepare / execute)
        │
        ▼
    Broker

Scope (Block 0):
  - Trigger abstraction (time-based and event-based as contracts only).
  - ExecutionPlan (data contract between Planner and Dispatch Core).
  - Broker dispatch request/response contract (Dispatch Core <-> Broker).
  - DispatchResult (simple, explicit dispatch status).

Explicitly OUT of scope for Block 0:
  - Any scheduler, timer, event bus, or polling infrastructure.
  - Any broker implementation.
  - Any live order execution.
  - Any new abstraction, proof, token, capability, secret, guard,
    wrapper, or security mechanism for M6-A through M6-E.
  - Any change to the behavior of M6-A through M6-E.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from models.account import Account
    from models.broker_instrument import BrokerInstrument
    from models.order import Order


# ---------------------------------------------------------------------------
# 1. Trigger
# ---------------------------------------------------------------------------


class Trigger(ABC):
    """
    Abstraction for anything that can start a dispatch cycle.

    A Trigger is a *contract*, not an implementation. Concrete
    triggers (time-based, event-based, ...) are defined in later
    blocks. Block 0 only establishes that:
      - a Trigger has a single evaluation point,
      - evaluation is side-effect free at the contract level,
      - the result is a boolean: fired / not fired.

    No scheduler, event bus, timer, or polling loop lives here.
    """

    @abstractmethod
    def evaluate(self, now: datetime) -> bool:
        """
        Return ``True`` if the trigger has fired at ``now``.

        Implementations must be deterministic and side-effect free
        for a given ``now``. This contract deliberately does not
        expose any scheduling primitive.
        """
        raise NotImplementedError


class TimeTrigger(Trigger, ABC):
    """
    Contract for triggers driven by wall-clock time.

    Time-based triggers are introduced here ONLY as a contract.
    No timer, scheduler, or clock source is defined or implied.
    """


class EventTrigger(Trigger, ABC):
    """
    Contract for triggers driven by confirmed external events.

    Event-based triggers are introduced here ONLY as a contract.
    No event bus, listener, or polling infrastructure is defined.
    """


# ---------------------------------------------------------------------------
# 2. ExecutionPlan
# ---------------------------------------------------------------------------


@dataclass
class ExecutionPlan:
    """
    Data contract between the Planner (Block 1) and the Dispatch Core
    (Block 2).

    An ExecutionPlan is a pure data object. It carries everything the
    Dispatch Core needs to dispatch, and nothing else:
      - which orders,
      - for which accounts,
      - through which brokers,
      - in what execution order,
      - under what conditions.

    The plan is deliberately broker-agnostic: it references brokers
    by name only. The Dispatch Core resolves names to broker
    instances through the existing BrokerManager.
    """

    orders: List["Order"] = field(default_factory=list)
    accounts: List["Account"] = field(default_factory=list)
    broker_names: List[str] = field(default_factory=list)

    execution_order: List[int] = field(default_factory=list)
    conditions: dict = field(default_factory=dict)

    plan_id: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# 3. Broker Contract
# ---------------------------------------------------------------------------


@dataclass
class BrokerDispatchRequest:
    """
    Data contract: Dispatch Core -> Broker.

    A normalized request envelope. The Dispatch Core never constructs
    broker-specific payloads; it passes the normalized order and the
    broker adapter translates it.
    """

    broker_name: str
    order: "Order"
    account: "Account"
    instrument: "BrokerInstrument"
    live: bool = False
    trace_id: Optional[str] = None


@dataclass
class BrokerDispatchResponse:
    """
    Data contract: Broker -> Dispatch Core.

    A normalized response envelope. Broker adapters translate their
    native API responses into this shape.
    """

    success: bool
    mode: str
    message: Optional[str] = None
    broker_order_id: Optional[str] = None
    raw: Optional[dict] = None


# ---------------------------------------------------------------------------
# 4. DispatchResult
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    """
    Simple, explicit result of a dispatch attempt.

    This is the Dispatch Core's own result type. It reports
    dispatch-level status only and is distinct from
    ``OrderExecutionResult`` (which reports per-order engine status).
    """

    success: bool
    sent: bool
    mode: str
    message: Optional[str] = None
    broker_name: Optional[str] = None
    order_count: int = 0
    trace_id: Optional[str] = None