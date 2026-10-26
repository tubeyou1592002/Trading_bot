"""
ui/order_feedback_service.py — Stage 3 prerequisite: feedback-activation bridge.

Activates the existing Stage 2 OMS/NATS feedback path so it becomes active
during program execution and can reach the UI. This is the boundary that
makes the matching-engine registration (AcceptedByBourse) observable to
the order-log UI without changing the existing Stage 2 plumbing.

Architecture (Block 9 Task 9B — account-aware):

    MainWindow (owns a single lazy BrokerManager)
        |
        +----> TestRunner
        |         |
        |         +----> DispatchCore(broker_manager=shared_manager)
        |                        |
        |                        +----> BrokerManager.get_for_account(
        |                                   account_id, broker_name)
        |
        +----> OrderFeedbackService  (ONE per (account_id, broker_name))
                  |
                  +----> the SAME account-scoped broker instance
                         (add_*_listener + tracking)

This guarantees that the account-scoped broker instance registered for
OMS feedback (via ``add_order_registered_listener`` and
``start_queue_position_tracking``) is the SAME instance used by the
order execution path for that account — so ``decisionId`` registration
and ``AcceptedByBourse`` feedback land on the same broker object.

Two accounts on the same broker get two independent
``OrderFeedbackService`` runtimes, each bound to its own
``BrokerManager.get_for_account(account_id, broker_name)`` broker; an
event received for one account can never reach the other account's
runtime. The service is constructed lazily (never at ``MainWindow``
construction) and the broker factory is resolved only inside ``run()``.

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
        order_registered (decision_id, accepted_at_ts, order_info)
            Emitted when AcceptedByBourse (matching-engine registration)
            is received for an order. ``accepted_at_ts`` is the REAL
            wall-clock moment (``time.time()`` epoch seconds) that event
            was received, captured by the correlator from the event
            itself — never fabricated here; ``None`` when the event
            carried no usable timestamp. This is the GREEN trigger for
            the order log.
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

    order_registered = Signal(str, object, object)
    order_registered_monotonic = Signal(str, int)
    queue_position = Signal(str, int)
    feedback_error = Signal(str)
    started = Signal()
    start_failed = Signal(str)
    feedback_unavailable = Signal()
    stopped = Signal()

    def __init__(
        self,
        broker_factory=None,
        *,
        account_id: Optional[str] = None,
        broker_name: Optional[str] = None,
        parent=None,
    ):
        """
        Args:
            broker_factory: zero-arg callable returning the ACCOUNT-SCOPED
                AgaahBroker instance. Production: MainWindow supplies a
                factory closing over ``BrokerManager.get_for_account(
                account_id, broker_name)``. Tests inject a fake. Must not
                resolve a global/name-only broker.
            account_id: the account this runtime is dedicated to. Routing
                metadata only — never rendered, never sent to the broker.
            broker_name: the account's broker association. Routing
                metadata only.
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
        self.account_id = account_id
        self.broker_name = broker_name
        # The exact broker instance whose listener lists already hold this
        # service's callbacks. Installing listeners is idempotent per
        # broker instance: starting the service again must never register
        # a second copy of the same callbacks (no duplicate delivery).
        self._listeners_broker: Any = None
        self._stop_requested = False
        self.startup_error = None

    def _default_broker_factory(self):
        """
        Fallback ONLY for isolated use, and only when account identity is
        known.

        Resolves the broker through ``BrokerManager.get_for_account`` for
        exactly this service's ``(account_id, broker_name)`` — never a
        name-only/global ``get(...)``. MainWindow always supplies an
        explicit shared factory and does NOT use this. Without account
        identity no broker can be resolved fail-closed.
        """
        if not self.account_id or not self.broker_name:
            raise ValueError(
                "OrderFeedbackService requires an account-scoped "
                "broker_factory (account_id/broker_name missing)"
            )
        from brokers.manager import BrokerManager

        return BrokerManager().get_for_account(
            self.account_id, self.broker_name
        )

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

            # Wire the green trigger: AcceptedByBourse -> order_registered
            # signal, plus the queue-position and error forwarders. Installing
            # is idempotent per broker instance, so a start/stop/restart of
            # THIS service never registers duplicate callbacks.
            self._install_listeners()

            # Ensure the provider exists (with callbacks wired) and start it
            self._ensure_provider()
            self._loop.run_until_complete(
                self._broker.start_queue_position_tracking()
            )

            self._running = True
            self.started.emit()

            if self._stop_requested:
                return

            # Run the event loop until stop is requested. The NATS transport
            # callbacks fire within this loop, keeping feedback off the GUI
            # thread and never blocking order sends.
            self._loop.run_forever()

        except Exception as exc:
            self.startup_error = type(exc).__name__
            logger.error(
                "OrderFeedbackService feedback startup failed (error_type=%s)",
                type(exc).__name__,
            )
            self.feedback_unavailable.emit()
            self.start_failed.emit(type(exc).__name__)
        finally:
            self._cleanup()

    def _install_listeners(self) -> None:
        """
        Register the forwarding callbacks on the account-scoped broker.

        Idempotent per broker instance: the broker exposes no listener
        removal API, so re-registering the same service on the same broker
        would double every event. This guard installs the three callbacks
        exactly once for the broker this runtime currently uses; a broker
        change (a different account runtime) installs on the new broker.
        """
        broker = self._broker
        if broker is None or broker is self._listeners_broker:
            return
        broker.add_order_registered_listener(self._on_order_registered)
        broker.add_queue_position_listener(self._on_queue_position)
        broker.add_order_error_listener(self._on_order_error)
        unavailable_listener = getattr(
            broker, "add_feedback_unavailable_listener", None
        )
        if callable(unavailable_listener):
            unavailable_listener(self._on_feedback_unavailable)
        self._listeners_broker = broker

    def _ensure_provider(self) -> None:
        """Ensure the lazy provider is created so callbacks are wired."""
        if self._broker._queue_position_provider is None:
            self._broker._ensure_queue_position_provider()

    def _on_order_registered(
        self, decision_id: str, order_info: Any
    ) -> None:
        """
        Listener for AcceptedByBourse — forwarded to the GUI thread via signal.

        This is the GREEN trigger. It fires on matching-engine registration,
        NOT on the initial broker POST /order response. The event's own real
        receive timestamp (kept by the correlator on ``order_info``) travels
        with the signal; nothing is re-read or synthesized here.
        """
        accepted_at_ts = getattr(
            order_info, "accepted_by_bourse_at", None
        )
        import time
        self.order_registered_monotonic.emit(decision_id, time.monotonic_ns())
        self.order_registered.emit(decision_id, accepted_at_ts, order_info)

    def _on_queue_position(self, decision_id: str, position: int) -> None:
        """Listener for queue position updates."""
        self.queue_position.emit(decision_id, position)

    def _on_order_error(self, decision_id: str, error: str) -> None:
        """Listener for order-tracking errors."""
        self.feedback_error.emit(f"{decision_id}: {error}")

    def _on_feedback_unavailable(self, _reason="") -> None:
        """Report optional transport loss as feedback-only status."""
        self.feedback_unavailable.emit()

    def start_service(self) -> None:
        """
        Start the feedback service thread (idempotent).

        Starts the underlying QThread. The asyncio loop and NATS transport
        are initialized inside run() on this dedicated thread.

        Guard against double-start: if the thread is already running or
        about to start, no second ``QThread.start()`` is issued. If a prior
        startup failed, the thread can be retried after recovery.
        """
        if self._running or self.isRunning():
            return
        self._stop_requested = False
        self.start()

    def stop_service(self) -> None:
        """
        Stop the feedback service (graceful, idempotent, restart-safe).

        Requests the dedicated loop to stop from within its own context and
        waits for the thread to finish. If the thread has not yet created
        its loop, the stop request is remembered so ``run()`` returns
        immediately after it starts. Restarting later reuses this same
        service object (and thus the same broker listeners) — it never
        creates a duplicate listener registration.
        """
        self._stop_requested = True
        loop = self._loop
        try:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            # The loop was closed between the check and the call.
            pass

        if self.isRunning() or self._running:
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
