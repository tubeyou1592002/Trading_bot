"""
Block UI-4 — Task 2: independent pre-dispatch Order Queue.

``OrderQueue`` is a standalone, minimal FIFO holder for orders that are
ready but not yet dispatched. It stores each order together with its own
explicit ``account_id`` and ``broker_name`` binding.

The queue deliberately does NOT:
  * clone or rebuild orders (the exact order object is preserved),
  * read or mutate any ``Order`` field,
  * guess ``account_id`` / ``broker_name`` from the order, its symbol, or the
    broker (values are the exact inputs, per entry),
  * provide any default/fallback account or broker,
  * connect to ``DispatchCore``, ``DispatchIntegration``,
    ``ExecutionTracker``, ``ExecutionPlanner``, ``OrderEngine``,
    ``BrokerManager``, ``AgaahBroker``, Login, Network, UI, or Persistence,
  * implement any dispatch / lifecycle state machine.

The only internal notion of "pending" is presence in the queue itself:
an entry returned by ``list_pending()`` is still pending by definition.
No ``QUEUED -> DISPATCHED -> REGISTERED -> FAILED`` lifecycle exists here;
that belongs to later tasks.

Validation: no new rules are invented here. The queue is a pure holder; the
same ``Order`` objects and the exact ``account_id`` / ``broker_name`` values
pass through untouched and unvalidated, exactly as provided.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List


@dataclass(frozen=True)
class QueueEntry:
    """
    Immutable holder for one queued order and its explicit Account -> Broker
    binding. ``order`` is the exact Order object (never cloned or rebuilt).
    """

    order: Any
    account_id: str
    broker_name: str


class OrderQueue:
    """
    Independent FIFO queue of orders waiting to be dispatched.

    Only two operations are exposed (the minimal contract):
      * ``enqueue(order, account_id, broker_name)`` — append one entry;
      * ``list_pending()`` — return all entries in insertion order.
    """

    def __init__(self) -> None:
        self._entries: List[QueueEntry] = []

    def enqueue(
        self,
        order: Any,
        account_id: str,
        broker_name: str,
    ) -> None:
        """
        Append ``order`` to the queue, keeping the exact ``account_id`` and
        ``broker_name`` passed by the caller. No guessing, no defaults.
        """
        self._entries.append(
            QueueEntry(
                order=order,
                account_id=account_id,
                broker_name=broker_name,
            )
        )

    def list_pending(self) -> List[QueueEntry]:
        """
        Return all queued (still pending) entries in insertion order.

        A new list (not internal storage) is returned so callers cannot
        mutate the queue through it; the entry objects themselves are the
        same objects. No dispatch, no broker call, no side effects.
        """
        return list(self._entries)