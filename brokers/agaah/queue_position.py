"""
Agah Order Correlation and Queue Position Tracking.

This module correlates OMS events with orders using decisionId,
extracts hostOrderNumber and orderDate, and fetches queue position.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .nats_transport import AgahNatsTransport, AgahQueuePositionService, OmsStateChanged

logger = logging.getLogger(__name__)


@dataclass
class OrderTrackingInfo:
    """Tracking information for a single order."""
    decision_id: str
    nsc_id: str
    host_order_number: Optional[str] = None
    order_date: Optional[str] = None
    queue_position: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: Optional[str] = None
    # UI-5 Task 4 Stage 3 Task 3 — the REAL wall-clock moment (``time.time()``
    # epoch seconds) the AcceptedByBourse event itself was received, captured
    # verbatim from the event's own ``raw_timestamp``. It stays ``None`` for
    # every other action (e.g. SavedInAsa) and is never a fabricated or
    # converted value. ``None`` means "no matching-engine registration event
    # has been received".
    accepted_by_bourse_at: Optional[float] = None


class AgahOrderCorrelator:
    """
    Correlates OMS events with orders and fetches queue positions.

    Flow:
    1. Order placed -> decisionId captured (Stage 1)
    2. OMS events received via NATS
       - SavedInAsa (2): extracts orderDate from message field 11
       - AcceptedByBourse (5): extracts hostOrderNumber from message
    3. When both hostOrderNumber and orderDate available, fetch queue position
    4. Notify callback with result
    """

    def __init__(
        self,
        broker,
        on_order_registered: Optional[Callable[[str, "OrderTrackingInfo"], None]] = None,
        on_queue_position: Optional[Callable[[str, int], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None,
    ):
        self.broker = broker
        self.on_order_registered = on_order_registered
        self.on_queue_position = on_queue_position
        self.on_error = on_error

        # Import here to avoid circular import
        from .nats_transport import AgahNatsTransport, AgahQueuePositionService

        self._transport = AgahNatsTransport(
            broker,
            on_oms_state_changed=self._handle_oms_event,
        )
        self._queue_position_service = AgahQueuePositionService(broker)

        # Track orders by decisionId
        self._orders: dict[str, OrderTrackingInfo] = {}
        self._running = False

    async def start(self) -> None:
        """Start the correlator and NATS transport."""
        if self._running:
            return
        await self._transport.start()
        self._running = True
        logger.info("Agah order correlator started")

    async def stop(self) -> None:
        """Stop the correlator."""
        self._running = False
        await self._transport.stop()
        logger.info("Agah order correlator stopped")

    def register_order(self, decision_id: str, nsc_id: str) -> None:
        """
        Register a new order for tracking.

        Called when order is placed and decisionId is received.
        """
        if decision_id in self._orders:
            logger.warning("Order already registered: %s", decision_id)
            return

        self._orders[decision_id] = OrderTrackingInfo(
            decision_id=decision_id,
            nsc_id=nsc_id,
        )
        logger.debug("Registered order for tracking: %s", decision_id)

    def _handle_oms_event(self, oms: "OmsStateChanged") -> None:
        """Handle incoming OmsStateChanged event."""
        if not self._running:
            return

        decision_id = oms.decision_id
        if not decision_id or decision_id not in self._orders:
            # Not an order we're tracking
            return

        order_info = self._orders[decision_id]

        if oms.action == 2:  # SavedInAsa
            self._handle_saved_in_asa(order_info, oms)
        elif oms.action == 5:  # AcceptedByBourse
            self._handle_accepted_by_bourse(order_info, oms)

        # Check if we can now fetch queue position
        self._try_fetch_queue_position(order_info)

    def _handle_saved_in_asa(self, order_info: OrderTrackingInfo, oms: "OmsStateChanged") -> None:
        """Handle SavedInAsa (2) - extract orderDate from message field 11."""
        # message format: pipe-separated, field 11 is dateTime
        parts = oms.message.split("|")
        if len(parts) > 11:
            date_time_str = parts[11].strip()
            if date_time_str:
                try:
                    # Parse dateTime - assume Asia/Tehran if no timezone
                    # Convert to UTC ISO-8601 as per frontend: new Date(dateTime).toISOString()
                    dt = self._parse_tehran_datetime(date_time_str)
                    order_info.order_date = dt.isoformat()
                    logger.debug(
                        "Extracted orderDate for %s: %s",
                        order_info.decision_id,
                        order_info.order_date,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to parse dateTime from SavedInAsa: %s",
                        e,
                    )

    def _parse_tehran_datetime(self, date_time_str: str) -> datetime:
        """Parse dateTime string and convert to UTC, assuming Asia/Tehran if no tz."""
        # Try parsing as ISO format first
        try:
            dt = datetime.fromisoformat(date_time_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                # No timezone - assume Asia/Tehran (UTC+3:30)
                from datetime import timedelta
                tehran_offset = timedelta(hours=3, minutes=30)
                dt = dt.replace(tzinfo=timezone(tehran_offset))
            return dt.astimezone(timezone.utc)
        except ValueError:
            # Try other common formats
            for fmt in [
                "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
            ]:
                try:
                    dt = datetime.strptime(date_time_str, fmt)
                    # Assume Asia/Tehran
                    from datetime import timedelta
                    tehran_offset = timedelta(hours=3, minutes=30)
                    dt = dt.replace(tzinfo=timezone(tehran_offset))
                    return dt.astimezone(timezone.utc)
                except ValueError:
                    continue
            raise ValueError(f"Unable to parse dateTime: {date_time_str}")

    def _handle_accepted_by_bourse(self, order_info: OrderTrackingInfo, oms: "OmsStateChanged") -> None:
        """Handle AcceptedByBourse (5) - extract hostOrderNumber from message."""
        message = oms.message.strip()
        if message.isdigit():
            order_info.host_order_number = message
            logger.debug(
                "Extracted hostOrderNumber for %s: %s",
                order_info.decision_id,
                order_info.host_order_number,
            )
        else:
            logger.warning(
                "Invalid hostOrderNumber in AcceptedByBourse: %s",
                message,
            )

        # UI-5 Task 4 Stage 3 Task 3 — keep the REAL receive moment of THIS
        # event, verbatim from the event's own timestamp (no clock is read
        # here, nothing is synthesized). Re-delivery overwrites with the
        # latest real value; it never invents one when absent.
        if oms.raw_timestamp is not None:
            order_info.accepted_by_bourse_at = oms.raw_timestamp

        # Fire on_order_registered callback ONLY on AcceptedByBourse (action=5).
        # This is the GREEN trigger for the order log UI — matching-engine
        # registration, NOT the initial broker POST /order response.
        if self.on_order_registered:
            self.on_order_registered(order_info.decision_id, order_info)

    def _try_fetch_queue_position(self, order_info: OrderTrackingInfo) -> None:
        """Try to fetch queue position if all required data is available."""
        if not order_info.host_order_number or not order_info.order_date:
            return  # Not ready yet

        if order_info.queue_position is not None:
            return  # Already fetched

        # Schedule async fetch to avoid blocking message loop
        asyncio.create_task(self._fetch_queue_position_async(order_info))

    async def _fetch_queue_position_async(self, order_info: OrderTrackingInfo) -> None:
        """Async queue position fetch to avoid blocking OMS message loop."""
        try:
            position = await asyncio.to_thread(
                self._queue_position_service.get_queue_position,
                nsc_id=order_info.nsc_id,
                host_order_number=order_info.host_order_number,
                order_date=order_info.order_date,
            )

            if position is not None:
                order_info.queue_position = position
                order_info.completed_at = time.time()
                logger.info(
                    "Queue position for %s: %d",
                    order_info.decision_id,
                    position,
                )

                if self.on_queue_position:
                    self.on_queue_position(order_info.decision_id, position)
            else:
                error_msg = "Queue position unavailable from API"
                order_info.error = error_msg
                if self.on_error:
                    self.on_error(order_info.decision_id, error_msg)

        except Exception as e:
            error_msg = f"Queue position fetch failed: {e}"
            order_info.error = error_msg
            logger.error("Queue position fetch error for %s: %s", order_info.decision_id, e)
            if self.on_error:
                self.on_error(order_info.decision_id, error_msg)

    def get_order_info(self, decision_id: str) -> Optional[OrderTrackingInfo]:
        """Get tracking info for an order."""
        return self._orders.get(decision_id)

    def get_queue_position(self, decision_id: str) -> Optional[int]:
        """Get queue position for an order."""
        info = self._orders.get(decision_id)
        return info.queue_position if info else None


class AgahQueuePositionProvider:
    """
    High-level provider for queue position functionality.

    Integrates with existing order execution flow:
    - Called when order is placed (to register decisionId)
    - Provides queue position lookup
    """

    def __init__(
        self,
        broker,
        on_order_registered: Optional[Callable[[str, "OrderTrackingInfo"], None]] = None,
        on_queue_position: Optional[Callable[[str, int], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None,
    ):
        self.correlator = AgahOrderCorrelator(
            broker,
            on_order_registered=on_order_registered,
            on_queue_position=on_queue_position,
            on_error=on_error,
        )

    async def start(self) -> None:
        """Start the correlator."""
        await self.correlator.start()

    async def stop(self) -> None:
        """Stop the correlator."""
        await self.correlator.stop()

    def on_order_placed(self, decision_id: str, nsc_id: str) -> None:
        """Called when order is successfully placed with decisionId."""
        self.correlator.register_order(decision_id, nsc_id)

    def get_queue_position(self, decision_id: str) -> Optional[int]:
        """Get queue position for an order by decisionId."""
        return self.correlator.get_queue_position(decision_id)

    def get_order_info(self, decision_id: str) -> Optional[Any]:
        """Get full order tracking info."""
        return self.correlator.get_order_info(decision_id)