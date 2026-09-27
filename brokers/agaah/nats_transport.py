"""
Agah NATS Transport for OMS Order State Messages.

This module implements the NATS transport for receiving
real-time OmsStateChanged (code 100) messages from Agah.

The transport:
1. Fetches NATS connection info from /api/v1/pusher/nats
2. Fetches message types schema from /api/v1/Pusher/message-types
3. Establishes NATS connection with JWT/NKey authentication
4. Subscribes to OmsStateChanged subject from server-provided groupNames
5. Decodes messages using server-provided schema
6. Emits parsed OMS events for order correlation

All configuration is fetched from Agah APIs at runtime; no hardcoded
URLs, subjects, or schemas.

Note: This module does NOT import broker at runtime. The broker dependency
is injected via the constructor to avoid circular imports.
"""

import asyncio
import binascii
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

import nats
from nats.errors import ConnectionClosedError, TimeoutError as NatsTimeoutError

if TYPE_CHECKING:
    from collections.abc import Coroutine


logger = logging.getLogger(__name__)


@dataclass
class NatsConnectionInfo:
    """NATS connection information from Agah API."""
    urls: list[str]
    token: str
    private_key: str


@dataclass
class MessageTypeSchema:
    """Message type schema for decoding."""
    code: int
    group_names: list[str]
    schema: dict[str, Any]


@dataclass
class OmsStateChanged:
    """Parsed OmsStateChanged message (code 100)."""
    code: int
    action: int
    decision_id: str
    request_id: str
    current_trade_count: int
    message: str
    channel: str
    nsc_id: str
    raw_timestamp: float = field(default_factory=time.time)


class OmsMessageDecoder:
    """
    Decodes OMS messages using server-provided schema.

    The schema comes from GET /api/v1/Pusher/message-types, for code 100,
    specifically groups[100].schema which is an ordered list of field names:

      ["code", "action", "decisionId", "requestId",
       "currentTradeCount", "message", "channel", "nscId"]

    The payload is a comma-separated string where field order matches
    the schema exactly.
    """

    def __init__(self, schema: Any):
        self.schema = schema
        self.field_names = self._extract_field_names(schema)

    def _extract_field_names(self, schema: Any) -> list[str]:
        """
        Extract field names from the server-provided schema in order.

        Handles the real server response structure where schema can be:
        - A list of strings: ["code", "action", ...]
        - A dict with a "fields" key containing a list of field name strings
        - A dict with a "names" key (some server variants)
        """
        if isinstance(schema, list):
            return [str(f) for f in schema]

        if isinstance(schema, dict):
            if "fields" in schema:
                fields = schema["fields"]
                if isinstance(fields, list):
                    if fields and isinstance(fields[0], dict):
                        return [f["name"] for f in fields]
                    return [str(f) for f in fields]
            if "names" in schema:
                names = schema["names"]
                if isinstance(names, list):
                    return [str(f) for f in names]
            if "properties" in schema:
                return list(schema["properties"].keys())

        return []

    def decode(self, payload: str) -> dict[str, Any]:
        """Decode comma-separated payload using schema field names."""
        parts = payload.split(",")
        result = {}
        for i, field_name in enumerate(self.field_names):
            if i < len(parts):
                result[field_name] = parts[i]
        return result

    @property
    def field_order(self) -> list[str]:
        """Return the ordered field names (for testing/verification)."""
        return self.field_names


class AgahNatsTransport:
    """
    NATS transport for Agah OMS messages using nats-py.

    Handles the full lifecycle:
    - Fetch connection info and message schema from Agah
    - Establish NATS connection with JWT/NKey auth
    - Subscribe to OmsStateChanged subject from server groupNames
    - Decode and emit parsed events
    """

    def __init__(
        self,
        broker: Any,
        on_oms_state_changed: Optional[Callable[["OmsStateChanged"], Any]] = None,
    ):
        self.broker = broker
        self.on_oms_state_changed = on_oms_state_changed
        self._nc: Optional[Any] = None
        self._running = False
        self._connection_info: Optional[NatsConnectionInfo] = None
        self._oms_schema: Optional[MessageTypeSchema] = None
        self._decoder: Optional[OmsMessageDecoder] = None
        self._subscription: Optional[Any] = None

    async def start(self) -> None:
        """Start the NATS transport."""
        if self._running:
            return

        # Fetch connection info and message types
        await self._fetch_connection_info()
        await self._fetch_message_types()

        # Connect to NATS with JWT/NKey auth
        await self._connect()

        # Subscribe to OmsStateChanged
        await self._subscribe_oms_state_changed()

        self._running = True
        logger.info("Agah NATS transport started")

    async def stop(self) -> None:
        """Stop the NATS transport."""
        self._running = False
        if self._subscription:
            await self._subscription.unsubscribe()
            self._subscription = None
        if self._nc:
            await self._nc.drain()
            self._nc = None
        logger.info("Agah NATS transport stopped")

    async def _fetch_connection_info(self) -> None:
        """Fetch NATS connection info from Agah."""
        url = self.broker._url("pusher/nats")
        headers = self.broker._auth_headers()

        # Run sync HTTP in thread pool to avoid blocking event loop
        response = await asyncio.to_thread(
            self.broker.session.get, url, headers=headers, timeout=10
        )
        response.raise_for_status()

        data = response.json()
        if not data.get("isSuccess"):
            raise RuntimeError(
                f"Failed to get NATS connection info: {data.get('message')}"
            )

        conn_data = data.get("data", {})
        self._connection_info = NatsConnectionInfo(
            urls=conn_data.get("urls", []),
            token=conn_data.get("token", ""),
            private_key=conn_data.get("privateKey", ""),
        )

        if not self._connection_info.urls:
            raise RuntimeError("No NATS URLs returned from Agah")
        if not self._connection_info.token:
            raise RuntimeError("No NATS token returned from Agah")

        logger.debug(
            "Fetched NATS connection info: %d URLs, token=%s",
            len(self._connection_info.urls),
            "<present>" if self._connection_info.token else "<empty>",
        )

    async def _fetch_message_types(self) -> None:
        """Fetch message types schema from Agah."""
        url = self.broker._url("Pusher/message-types")
        headers = self.broker._auth_headers()

        response = await asyncio.to_thread(
            self.broker.session.get, url, headers=headers, timeout=10
        )
        response.raise_for_status()

        data = response.json()
        if not data.get("isSuccess"):
            raise RuntimeError(
                f"Failed to get message types: {data.get('message')}"
            )

        # Parse real server response structure
        groups = []
        resp_data = data.get("data", {})
        if isinstance(resp_data, dict):
            groups = resp_data.get("groups", []) or resp_data.get("messageTypes", []) or []
        elif isinstance(resp_data, list):
            groups = resp_data

        oms_group = next((g for g in groups if g.get("code") == 100), None)

        if not oms_group:
            raise RuntimeError("OmsStateChanged (code 100) not found in message types")

        # Extract group names (subjects) and schema from actual response
        group_names = oms_group.get("groupNames", []) or oms_group.get("subjects", []) or []
        schema = oms_group.get("schema", [])

        self._oms_schema = MessageTypeSchema(
            code=oms_group.get("code", 100),
            group_names=group_names,
            schema=schema,
        )

        self._decoder = OmsMessageDecoder(self._oms_schema.schema)
        logger.debug(
            "Fetched OMS schema: %d group names, %d fields",
            len(self._oms_schema.group_names),
            len(self._decoder.field_names),
        )

    async def _connect(self) -> None:
        """
        Establish NATS connection with JWT/NKey authentication.

        Authentication strategy:
        1. If privateKey is present, parse it as NKey seed and use nkeys_seed_str.
        2. If privateKey parsing fails, FAIL CLOSED (no fallback to token-only).
        3. Token is always included as additional auth.
        """
        if not self._connection_info or not self._connection_info.urls:
            raise RuntimeError("No connection info available")

        nats_url = self._connection_info.urls[0]
        token = self._connection_info.token
        private_key = self._connection_info.private_key

        connect_options: dict[str, Any] = {
            "servers": [nats_url],
            "token": token,
        }

        # NKey authentication
        if private_key:
            try:
                from nkeys import from_seed

                seed_bytes = self._extract_nkey_seed(private_key)
                kp = from_seed(seed_bytes)
                _ = kp.public_key
                kp.wipe()
                del kp

                connect_options["nkeys_seed_str"] = private_key
                logger.debug("NKey authentication configured from privateKey")
            except Exception as e:
                # FAIL CLOSED: if privateKey is present but cannot be used,
                # do NOT fall back to token-only authentication.
                logger.error(
                    "Failed to parse privateKey for NKey authentication: %s. "
                    "FAILING CLOSED (no token-only fallback).",
                    e,
                )
                raise RuntimeError(
                    f"NKey authentication failed for privateKey: {e}"
                ) from e
        else:
            logger.warning(
                "No privateKey available; using token-only authentication. "
                "This may fail if server requires NKey."
            )

        # Connect
        self._nc = await nats.connect(**connect_options)
        logger.debug("NATS connected to %s", nats_url)

    def _extract_nkey_seed(self, private_key: str) -> bytearray:
        """
        Extract a valid NKey seed from the private_key string.

        The private_key from Agah's /pusher/nats endpoint is an NKey seed
        (starts with 'S'). Returns it as bytearray for nkeys.from_seed.
        """
        if isinstance(private_key, bytearray):
            seed = private_key
        elif isinstance(private_key, bytes):
            seed = bytearray(private_key)
        else:
            seed = bytearray(private_key.encode().strip())

        return seed

    async def _subscribe_oms_state_changed(self) -> None:
        """Subscribe to OmsStateChanged subject from server groupNames."""
        if not self._oms_schema or not self._oms_schema.group_names:
            raise RuntimeError("No OMS group names available for subscription")

        subject = self._oms_schema.group_names[0]

        async def message_handler(msg: Any) -> None:
            await self._process_oms_message(msg.data.decode())

        self._subscription = await self._nc.subscribe(subject, cb=message_handler)
        logger.info("Subscribed to OmsStateChanged on subject: %s", subject)

    async def _process_oms_message(self, payload: str) -> None:
        """Process and decode OmsStateChanged message."""
        if not self._decoder:
            return

        try:
            decoded = self._decoder.decode(payload)

            oms = OmsStateChanged(
                code=int(decoded.get("code", 0)),
                action=int(decoded.get("action", 0)),
                decision_id=str(decoded.get("decisionId", "")),
                request_id=str(decoded.get("requestId", "")),
                current_trade_count=int(decoded.get("currentTradeCount", 0)),
                message=str(decoded.get("message", "")),
                channel=str(decoded.get("channel", "")),
                nsc_id=str(decoded.get("nscId", "")),
            )

            if oms.code == 100:
                callback = self.on_oms_state_changed
                if callback:
                    result = callback(oms)
                    if isinstance(result, asyncio.Future) or asyncio.iscoroutine(result):
                        await result

        except (ValueError, KeyError, binascii.Error, TypeError) as e:
            logger.error("Failed to process OMS message: %s", e, exc_info=True)
        except Exception as e:
            logger.error("Unexpected error processing OMS message: %s", e, exc_info=True)


class AgahQueuePositionService:
    """
    Service for fetching queue position from Agah.

    Requires three parameters obtained from OMS events:
    - nscId
    - hostOrderNumber (from AcceptedByBourse message)
    - orderDate (from SavedInAsa message)
    """

    def __init__(self, broker: Any):
        self.broker = broker

    def get_queue_position(
        self,
        nsc_id: str,
        host_order_number: str,
        order_date: str,
    ) -> Optional[int]:
        """
        Fetch queue position for an order (synchronous version for thread pool).

        Args:
            nsc_id: Instrument NSC ID
            host_order_number: Host order number from AcceptedByBourse (5)
            order_date: Order date in ISO 8601 format from SavedInAsa (2)

        Returns:
            Queue position as integer, or None if unavailable
        """
        if not nsc_id or not host_order_number or not order_date:
            return None

        try:
            url = self.broker._url("order/getorderposition")
            headers = self.broker._auth_headers()

            params = {
                "nscId": nsc_id,
                "hostOrderNumber": host_order_number,
                "orderDate": order_date,
            }

            response = self.broker.session.get(
                url, headers=headers, params=params, timeout=10
            )
            response.raise_for_status()

            data = response.json()

            if not data.get("isSuccess"):
                logger.warning(
                    "Queue position request failed: %s",
                    data.get("message", "unknown error"),
                )
                return None

            position_data = data.get("data")
            if not position_data:
                return None

            position = position_data.get("position")
            if position is None:
                return None

            if isinstance(position, bool) or not isinstance(position, (int, float)):
                logger.warning("Invalid position type: %s", type(position))
                return None

            return int(position)

        except Exception as e:
            logger.error("Failed to get queue position: %s", e)
            return None