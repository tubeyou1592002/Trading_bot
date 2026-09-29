"""
ui/order_feedback_service.py — Stage 3 prerequisite: feedback-activation bridge.

Activates the existing Stage 2 OMS/NATS feedback path so it becomes active
during program execution and can reach the UI. This is the boundary that
makes the matching-engine registration (AcceptedByBourse) observable to
the order-log UI without changing the existing Stage 2 plumbing.

Architecture:

    MainWindow (owns a single lazy BrokerManager)
        |
        +----> TestRunner
        |         |
        |         +----> DispatchCore(broker_manager=shared_manager)
        |                        |
        |                        +----> shared AgaahBroker (on_order_placed etc.)
        |
        +----> OrderFeedbackService
                  |
                  +----> shared AgaahBroker (add_*_listener + tracking)

This guarantees that the ``AgaahBroker`` instance registered for OMS
feedback (via ``add_order_registered_listener`` and
``start_queue_position_tracking``) is the SAME instance used by the
order execution path — so ``decisionId`` registration and
``AcceptedByBourse`` feedback land on the same broker object.

Lifetime / async rules (mirroring UI-3.2A / UI-3.2B worker pattern):

  * The asyncio event loop for the NATS transport runs on a DEDICATED
    background QThread — it never touches the GUI thread and never blocks
    order sends. This is a RECEIVING path only: no scheduler/timer, no
    order sending.
  * ``broker_factory`` returns the shared AgaahBroker. In production
    MainWindow supplies ``lambda: shared_manager.get("آگاه")``. Tests
    inject a fake broker factory. Construction of the service is fully
    offline (no broker/core import until start()).
  * start() / stop() are idempotent and safe; all failures emit
    ``feedback_error`` rather than crashing the UI.

This is the green trigger seam for Stage 3: a row turns green ONLY when
``AcceptedByBourse`` (matching-engine registration) arrives for that
order's ``decision_id`` — never on the initial broker response.
"""

import asyncio
import logging
from typing import Any, Callable, Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class OrderFeedbackService(QThread):
    """
    Hosts the Stage 2 async OMS feedback transport on a dedicated
    background thread and forwards matching-engine registration events
    into Qt signals on the GUI thread.

    Signals:
        order_registered (decision_id, order_info)
            Emitted when AcceptedByBourse (matching-engine registration)
            is received for an order. This is the GREEN trigger for the
            order log.
        queue_position (decision_id, position)
            Emitted when a queue position is fetched for an order.
        feedback_error (message)
            Emitted on any failure that should not crash the UI.
        started
            Emitted once the background loop + transport are running.
        start_failed (message)
            Emitted if start() could not complete.
        stopped
            Emitted when the service has fully stopped.
    """

    order_registered = Signal(str, object)
    queue_position = Signal(str, int)
    feedback_error = Signal(str)
    started = Signal()
    start_failed = Signal(str)
    stopped = Signal()

    def __init__(self, broker_factory=None, parent=None):
        """
        Args:
            broker_factory: zero-arg callable returning the SHARED
                AgaahBroker instance. Production: MainWindow supplies
                ``lambda: shared_manager.get("آگاه")``. Tests inject a
                fake. Must not create a new BrokerManager.
        """
        super().__init__(parent)
        self._broker_factory = (
            broker_factory
            if broker_factory is not None
            else self._default_broker_factory
        )
        self._broker: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False

    @staticmethod
    def _default_broker_factory():
        """
        Production fallback ONLY for isolated use.

        Builds the shared BrokerManager lazily and returns the Agah broker
        from it. This creates a BrokerManager — the MainWindow wiring
        supplies an explicit shared factory and does NOT use this.
        """
        from brokers.manager import BrokerManager

        return BrokerManager().get("آگاه")

    def run(self) -> None:
        """
        Entry point for the background thread.

        Creates a dedicated asyncio event loop on this thread, lazily builds
        the shared broker via ``broker_factory``, registers listeners, and
        starts the Stage 2 queue-position tracking. The loop runs until
        stop() is requested.
        """
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            self._broker = self._broker_factory()

            # Wire the green trigger: AcceptedByBourse -> order_registered signal
            self._broker.add_order_registered_listener(
                self._on_order_registered
            )
            # Wire queue-position and error forwarders
            self._broker.add_queue_position_listener(
                self._on_queue_position
            )
            self._broker.add_order_error_listener(
                self._on_order_error
            )

            # Ensure the provider exists (with callbacks wired) and start it
            self._ensure_provider()
            self._loop.run_until_complete(
                self._broker.start_queue_position_tracking()
            )

            self._running = True
            self.started.emit()

            # Run the event loop until stop is requested. The NATS transport
            # callbacks fire within this loop, keeping feedback off the GUI
            # thread and never blocking order sends.
            self._loop.run_forever()

        except Exception as exc:
            logger.error("OrderFeedbackService failed to start: %s", exc)
            self.start_failed.emit(str(exc))
        finally:
            self._cleanup()

    def _ensure_provider(self) -> None:
        """Ensure the lazy provider is created so callbacks are wired."""
        if self._broker._queue_position_provider is None:
            self._broker._ensure_queue_position_provider()

    def _on_order_registered(self, decision_id: str, order_info: Any) -> None:
        """
        Listener for AcceptedByBourse — forwarded to the GUI thread via signal.

        This is the GREEN trigger. It fires on matching-engine registration,
        NOT on the initial broker POST /order response.
        """
        self.order_registered.emit(decision_id, order_info)

    def _on_queue_position(self, decision_id: str, position: int) -> None:
        """Listener for queue position updates."""
        self.queue_position.emit(decision_id, position)

    def _on_order_error(self, decision_id: str, error: str) -> None:
        """Listener for order-tracking errors."""
        self.feedback_error.emit(f"{decision_id}: {error}")

    def start_service(self) -> None:
        """
        Start the feedback service thread (idempotent).

        Starts the underlying QThread. The asyncio loop and NATS transport
        are initialized inside run() on this dedicated thread.

        Guard against double-start: if the thread is already running or
        about to start, no second ``QThread.start()`` is issued. If a prior
        startup failed, the thread can be retried after recovery.
        """
        if self._running:
            return
        if self.isRunning():
            return
        self.start()

    def stop_service(self) -> None:
        """
        Stop the feedback service (graceful, idempotent).

        Schedules the loop to stop from within its own context, then waits
        for the thread to finish.
        """
        if not self._running and self._loop is None:
            return

        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        if not self.wait(5000):
            logger.warning(
                "OrderFeedbackService thread did not stop within timeout"
            )

    def _cleanup(self) -> None:
        """Clean up async resources in the background thread."""
        self._running = False
        try:
            if self._broker is not None:
                try:
                    self._loop.run_until_complete(
                        self._broker.stop_queue_position_tracking()
                    )
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            if self._loop is not None:
                try:
                    self._loop.close()
                except Exception:
                    pass
            asyncio.set_event_loop(None)
        self.stopped.emit()

    def get_queue_position(self, decision_id: str) -> Optional[int]:
        """
        Synchronous read of the current queue position for an order.

        Delegates to the broker's sync ``get_queue_position``. Safe to call
        from the GUI thread.
        """
        if self._broker is None:
            return None
        try:
            return self._broker.get_queue_position(decision_id)
        except AttributeError:
            return None


__all__ = ["OrderFeedbackService"]
