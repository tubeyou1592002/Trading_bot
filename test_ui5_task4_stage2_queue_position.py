"""
UI-5 Task 4 Stage 2 — Queue Position Tests.

Tests for Agah NATS transport, OMS message decoding,
order correlation, and queue position fetching.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brokers.agaah.nats_transport import (
    AgahNatsTransport,
    AgahQueuePositionService,
    NatsConnectionInfo,
    OmsMessageDecoder,
    OmsStateChanged,
)
from brokers.agaah.queue_position import (
    AgahOrderCorrelator,
    AgahQueuePositionProvider,
    OrderTrackingInfo,
)
from models.order import BUY, Order
from models.account import Account
from models.trading_state import VERIFIED_TRADABLE


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_NKEY_SEED = "SUAAAEJCGNCFKZTXRCM2VO6M3XXP6AAREIZUIVLGO6EJTKV3ZTO657YAAA"


# ---------------------------------------------------------------------------
# Fixtures and Fakes
# ---------------------------------------------------------------------------


class FakeBroker:
    def __init__(self):
        self.session = MagicMock()
        self.access_token = "test-token"
        self.user_identifier = "test-user"
        self.name = "آگاه"
        self.live_trading_enabled = True

        # Mock _url and _auth_headers
        self._url = MagicMock(side_effect=lambda path: f"https://tseonlineapi.agah.com/api/v1/{path}")
        self._auth_headers = MagicMock(return_value={
            "Authorization": "Bearer test-token",
            "UserIdentifier": "test-user",
        })

    def _auth_headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "UserIdentifier": self.user_identifier,
        }


class MockWebSocket:
    def __init__(self, messages=None):
        self.messages = messages or []
        self.sent_messages = []
        self.closed = False

    async def send(self, message):
        self.sent_messages.append(message)

    async def recv(self):
        if self.messages:
            return self.messages.pop(0)
        await asyncio.sleep(0.1)
        raise websockets.exceptions.ConnectionClosed(1000, "test")

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.messages:
            return self.messages.pop(0)
        raise StopAsyncIteration


# ---------------------------------------------------------------------------
# OmsMessageDecoder Tests
# ---------------------------------------------------------------------------


def test_oms_message_decoder_with_schema():
    """Decoder extracts fields in schema order."""
    schema = {
        "fields": [
            {"name": "code"},
            {"name": "action"},
            {"name": "decisionId"},
            {"name": "requestId"},
            {"name": "currentTradeCount"},
            {"name": "message"},
            {"name": "channel"},
            {"name": "nscId"},
        ]
    }
    decoder = OmsMessageDecoder(schema)

    payload = "100,5,DEC-123,REQ-456,0,12345,channel1,NSC-789"
    result = decoder.decode(payload)

    assert result["code"] == "100"
    assert result["action"] == "5"
    assert result["decisionId"] == "DEC-123"
    assert result["requestId"] == "REQ-456"
    assert result["currentTradeCount"] == "0"
    assert result["message"] == "12345"
    assert result["channel"] == "channel1"
    assert result["nscId"] == "NSC-789"


def test_oms_message_decoder_missing_fields():
    """Decoder handles missing fields gracefully."""
    schema = {"fields": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}
    decoder = OmsMessageDecoder(schema)

    # Only 2 fields provided
    result = decoder.decode("1,2")
    assert result["a"] == "1"
    assert result["b"] == "2"
    assert "c" not in result


# ---------------------------------------------------------------------------
# AgahQueuePositionService Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_broker():
    return FakeBroker()


@pytest.fixture
def queue_position_service(fake_broker):
    return AgahQueuePositionService(fake_broker)


def test_get_queue_position_success(queue_position_service, fake_broker):
    """Successful queue position fetch."""
    fake_broker.session.get.return_value.json.return_value = {
        "isSuccess": True,
        "data": {"position": 5},
    }
    fake_broker.session.get.return_value.raise_for_status = MagicMock()

    position = queue_position_service.get_queue_position(
        nsc_id="NSC-123",
        host_order_number="12345",
        order_date="2026-09-26T10:00:00Z",
    )

    assert position == 5
    fake_broker.session.get.assert_called_once()
    call_args = fake_broker.session.get.call_args
    assert call_args[1]["params"]["nscId"] == "NSC-123"
    assert call_args[1]["params"]["hostOrderNumber"] == "12345"
    assert call_args[1]["params"]["orderDate"] == "2026-09-26T10:00:00Z"


def test_get_queue_position_missing_params(queue_position_service):
    """Missing required parameters returns None."""
    assert queue_position_service.get_queue_position("", "123", "date") is None
    assert queue_position_service.get_queue_position("nsc", "", "date") is None
    assert queue_position_service.get_queue_position("nsc", "123", "") is None
    assert queue_position_service.get_queue_position(None, "123", "date") is None


def test_get_queue_position_invalid_response(queue_position_service, fake_broker):
    """Invalid response returns None."""
    fake_broker.session.get.return_value.json.return_value = {
        "isSuccess": True,
        "data": {},  # missing position
    }
    fake_broker.session.get.return_value.raise_for_status = MagicMock()

    position = queue_position_service.get_queue_position("nsc", "123", "date")
    assert position is None


def test_get_queue_position_non_numeric(queue_position_service, fake_broker):
    """Non-numeric position returns None."""
    fake_broker.session.get.return_value.json.return_value = {
        "isSuccess": True,
        "data": {"position": "invalid"},
    }
    fake_broker.session.get.return_value.raise_for_status = MagicMock()

    position = queue_position_service.get_queue_position("nsc", "123", "date")
    assert position is None


def test_get_queue_position_api_failure(queue_position_service, fake_broker):
    """API failure returns None."""
    fake_broker.session.get.side_effect = Exception("Network error")

    position = queue_position_service.get_queue_position("nsc", "123", "date")
    assert position is None


def test_get_queue_position_is_success_false(queue_position_service, fake_broker):
    """isSuccess=false returns None."""
    fake_broker.session.get.return_value.json.return_value = {
        "isSuccess": False,
        "message": "Error",
    }
    fake_broker.session.get.return_value.raise_for_status = MagicMock()

    position = queue_position_service.get_queue_position("nsc", "123", "date")
    assert position is None


# ---------------------------------------------------------------------------
# OrderTrackingInfo Tests
# ---------------------------------------------------------------------------


def test_order_tracking_info_creation():
    """OrderTrackingInfo stores all required fields."""
    info = OrderTrackingInfo(
        decision_id="DEC-123",
        nsc_id="NSC-123",
    )

    assert info.decision_id == "DEC-123"
    assert info.nsc_id == "NSC-123"
    assert info.host_order_number is None
    assert info.order_date is None
    assert info.queue_position is None
    assert info.error is None


# ---------------------------------------------------------------------------
# AgahOrderCorrelator Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def correlator(fake_broker):
    c = AgahOrderCorrelator(fake_broker)
    c._running = True  # Enable event handling for tests
    return c


def test_register_order(correlator):
    """Register order stores decisionId and nscId."""
    correlator.register_order("DEC-123", "NSC-123")

    info = correlator.get_order_info("DEC-123")
    assert info is not None
    assert info.decision_id == "DEC-123"
    assert info.nsc_id == "NSC-123"


def test_handle_saved_in_asa_extracts_order_date(correlator):
    """SavedInAsa (action=2) extracts orderDate from message field 11."""
    correlator.register_order("DEC-123", "NSC-123")

    # Pipe-separated message, field 11 (0-indexed: 11) is dateTime
    parts = ["f0", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "2026-09-26T10:00:00Z"]
    message = "|".join(parts)

    oms = OmsStateChanged(
        code=100,
        action=2,  # SavedInAsa
        decision_id="DEC-123",
        request_id="REQ-1",
        current_trade_count=0,
        message=message,
        channel="ch1",
        nsc_id="NSC-123",
    )

    correlator._handle_oms_event(oms)

    info = correlator.get_order_info("DEC-123")
    assert info.order_date is not None
    assert "2026-09-26T10:00:00" in info.order_date


def test_handle_accepted_by_bourse_extracts_host_order_number(correlator):
    """AcceptedByBourse (action=5) extracts hostOrderNumber from message."""
    correlator.register_order("DEC-123", "NSC-123")

    oms = OmsStateChanged(
        code=100,
        action=5,  # AcceptedByBourse
        decision_id="DEC-123",
        request_id="REQ-1",
        current_trade_count=0,
        message="12345",  # hostOrderNumber
        channel="ch1",
        nsc_id="NSC-123",
    )

    correlator._handle_oms_event(oms)

    info = correlator.get_order_info("DEC-123")
    assert info.host_order_number == "12345"


def test_both_events_then_fetch_queue_position(correlator, fake_broker):
    """Both events received -> fetch queue position."""
    async def run():
        fake_broker.session.get.return_value.json.return_value = {
            "isSuccess": True,
            "data": {"position": 3},
        }
        fake_broker.session.get.return_value.raise_for_status = MagicMock()

        correlator.register_order("DEC-123", "NSC-123")

        # Send SavedInAsa
        parts = ["f"] * 11 + ["2026-09-26T10:00:00Z"]
        oms1 = OmsStateChanged(
            code=100, action=2, decision_id="DEC-123", request_id="REQ-1",
            current_trade_count=0, message="|".join(parts), channel="ch1", nsc_id="NSC-123",
        )
        correlator._handle_oms_event(oms1)

        # Send AcceptedByBourse
        oms2 = OmsStateChanged(
            code=100, action=5, decision_id="DEC-123", request_id="REQ-1",
            current_trade_count=0, message="98765", channel="ch1", nsc_id="NSC-123",
        )
        correlator._handle_oms_event(oms2)

        # Wait for async fetch to complete
        await asyncio.sleep(0.1)

        info = correlator.get_order_info("DEC-123")
        assert info.queue_position == 3
        assert info.host_order_number == "98765"
        assert info.order_date is not None

    asyncio.run(run())


def test_missing_host_order_number_no_fetch(correlator, fake_broker):
    """Only SavedInAsa -> no queue position fetch."""
    fake_broker.session.get.return_value.json.return_value = {
        "isSuccess": True,
        "data": {"position": 3},
    }
    fake_broker.session.get.return_value.raise_for_status = MagicMock()

    correlator.register_order("DEC-123", "NSC-123")

    # Only SavedInAsa
    parts = ["f"] * 11 + ["2026-09-26T10:00:00Z"]
    oms = OmsStateChanged(
        code=100, action=2, decision_id="DEC-123", request_id="REQ-1",
        current_trade_count=0, message="|".join(parts), channel="ch1", nsc_id="NSC-123",
    )
    correlator._handle_oms_event(oms)

    info = correlator.get_order_info("DEC-123")
    assert info.queue_position is None
    fake_broker.session.get.assert_not_called()


def test_missing_order_date_no_fetch(correlator, fake_broker):
    """Only AcceptedByBourse -> no queue position fetch."""
    fake_broker.session.get.return_value.json.return_value = {
        "isSuccess": True,
        "data": {"position": 3},
    }
    fake_broker.session.get.return_value.raise_for_status = MagicMock()

    correlator.register_order("DEC-123", "NSC-123")

    # Only AcceptedByBourse
    oms = OmsStateChanged(
        code=100, action=5, decision_id="DEC-123", request_id="REQ-1",
        current_trade_count=0, message="98765", channel="ch1", nsc_id="NSC-123",
    )
    correlator._handle_oms_event(oms)

    info = correlator.get_order_info("DEC-123")
    assert info.queue_position is None
    fake_broker.session.get.assert_not_called()


def test_order_correlation_isolated(correlator, fake_broker):
    """Different orders don't share queue position."""
    async def run():
        fake_broker.session.get.return_value.json.return_value = {
            "isSuccess": True,
            "data": {"position": 1},
        }
        fake_broker.session.get.return_value.raise_for_status = MagicMock()

        correlator.register_order("DEC-A", "NSC-1")
        correlator.register_order("DEC-B", "NSC-2")

        # Complete DEC-A
        parts = ["f"] * 11 + ["2026-09-26T10:00:00Z"]
        oms1 = OmsStateChanged(code=100, action=2, decision_id="DEC-A", request_id="REQ-1",
                              current_trade_count=0, message="|".join(parts), channel="ch1", nsc_id="NSC-1")
        correlator._handle_oms_event(oms1)

        oms2 = OmsStateChanged(code=100, action=5, decision_id="DEC-A", request_id="REQ-1",
                              current_trade_count=0, message="111", channel="ch1", nsc_id="NSC-1")
        correlator._handle_oms_event(oms2)

        # DEC-B not completed
        oms3 = OmsStateChanged(code=100, action=2, decision_id="DEC-B", request_id="REQ-2",
                              current_trade_count=0, message="|".join(parts), channel="ch1", nsc_id="NSC-2")
        correlator._handle_oms_event(oms3)

        # Wait for async fetch
        await asyncio.sleep(0.1)

        info_a = correlator.get_order_info("DEC-A")
        info_b = correlator.get_order_info("DEC-B")

        assert info_a.queue_position == 1
        assert info_b.queue_position is None

    asyncio.run(run())


def test_callback_on_queue_position(correlator, fake_broker):
    """Callback invoked when queue position received."""
    async def run():
        fake_broker.session.get.return_value.json.return_value = {
            "isSuccess": True,
            "data": {"position": 7},
        }
        fake_broker.session.get.return_value.raise_for_status = MagicMock()

        results = []

        def callback(decision_id, position):
            results.append((decision_id, position))

        correlator.on_queue_position = callback
        correlator.register_order("DEC-123", "NSC-123")

        parts = ["f"] * 11 + ["2026-09-26T10:00:00Z"]
        oms1 = OmsStateChanged(code=100, action=2, decision_id="DEC-123", request_id="REQ-1",
                              current_trade_count=0, message="|".join(parts), channel="ch1", nsc_id="NSC-123")
        correlator._handle_oms_event(oms1)

        oms2 = OmsStateChanged(code=100, action=5, decision_id="DEC-123", request_id="REQ-1",
                              current_trade_count=0, message="555", channel="ch1", nsc_id="NSC-123")
        correlator._handle_oms_event(oms2)

        # Wait for async fetch and callback
        await asyncio.sleep(0.1)

        assert results == [("DEC-123", 7)]

    asyncio.run(run())


def test_invalid_host_order_number(correlator):
    """Non-numeric hostOrderNumber is rejected."""
    correlator.register_order("DEC-123", "NSC-123")

    oms = OmsStateChanged(
        code=100, action=5, decision_id="DEC-123", request_id="REQ-1",
        current_trade_count=0, message="not-a-number", channel="ch1", nsc_id="NSC-123",
    )

    correlator._handle_oms_event(oms)

    info = correlator.get_order_info("DEC-123")
    assert info.host_order_number is None


# ---------------------------------------------------------------------------
# AgahQueuePositionProvider Tests
# ---------------------------------------------------------------------------


def test_provider_registers_order_on_placed(fake_broker):
    """Provider registers order when on_order_placed called."""
    provider = AgahQueuePositionProvider(fake_broker)
    provider.on_order_placed("DEC-123", "NSC-123")

    info = provider.get_order_info("DEC-123")
    assert info is not None
    assert info.decision_id == "DEC-123"
    assert info.nsc_id == "NSC-123"


def test_provider_get_queue_position(fake_broker):
    """Provider returns queue position."""
    provider = AgahQueuePositionProvider(fake_broker)
    provider.on_order_placed("DEC-123", "NSC-123")

    # Manually set position
    info = provider.get_order_info("DEC-123")
    info.queue_position = 5

    assert provider.get_queue_position("DEC-123") == 5


def test_provider_unknown_order_returns_none(fake_broker):
    """Unknown decisionId returns None."""
    provider = AgahQueuePositionProvider(fake_broker)
    assert provider.get_queue_position("UNKNOWN") is None


# ---------------------------------------------------------------------------
# Integration with AgaahBroker Tests
# ---------------------------------------------------------------------------


def test_broker_has_queue_position_provider():
    """AgaahBroker has queue position provider."""
    from brokers.agaah.broker import AgaahBroker

    broker = AgaahBroker()
    assert hasattr(broker, "_queue_position_provider")
    assert hasattr(broker, "on_order_placed")
    assert hasattr(broker, "get_queue_position")


# ---------------------------------------------------------------------------
# NATS Transport Tests (Runtime URL, Auth, Schema, Subscription, Message Decode)
# ---------------------------------------------------------------------------


def test_nats_transport_runtime_url_fetching(fake_broker):
    """
    Test 1: Runtime URL fetching from /api/v1/pusher/nats.

    Verifies that NATS URLs come from the API response, not hardcoded.
    """
    async def run():
        fake_broker.session.get.return_value.json.return_value = {
            "isSuccess": True,
            "data": {
                "urls": ["npush101://npush101.agah.com:4222"],
                "token": "test-token",
                "privateKey": "SUAFN2UMSQF2X2LZE2YKKXP6Y7XN3LJ6Q5F2L7X7U2T3U5T7M5K3M5K3M5K",
            },
        }
        fake_broker.session.get.return_value.raise_for_status = MagicMock()

        transport = AgahNatsTransport(fake_broker)

        await transport._fetch_connection_info()

        assert transport._connection_info.urls == ["npush101://npush101.agah.com:4222"]
        assert transport._connection_info.token == "test-token"
        assert transport._connection_info.private_key == "SUAFN2UMSQF2X2LZE2YKKXP6Y7XN3LJ6Q5F2L7X7U2T3U5T7M5K3M5K3M5K"

    asyncio.run(run())


def test_nats_transport_auth_token_only(fake_broker):
    """
    Test 2: Authentication path uses token when no privateKey.

    When privateKey is empty, token-only auth is used (connect_options has token).
    """
    async def run():
        fake_broker.session.get.return_value.json.return_value = {
            "isSuccess": True,
            "data": {
                "urls": ["npush101://npush101.agah.com:4222"],
                "token": "test-token",
                "privateKey": "",
            },
        }
        fake_broker.session.get.return_value.raise_for_status = MagicMock()

        transport = AgahNatsTransport(fake_broker)

        # Capture connect options by patching nats.connect
        captured = {}
        async def mock_connect(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        with patch("nats.connect", mock_connect):
            await transport._fetch_connection_info()
            await transport._connect()

        assert captured.get("token") == "test-token"
        assert "nkeys_seed_str" not in captured

    asyncio.run(run())


def test_nats_transport_auth_with_nkeys_seed_str(fake_broker):
    """
    Test 3: Authentication path uses privateKey/NKey when present.

    When privateKey is present, it's passed as nkeys_seed_str to nats.connect.
    """
    async def run():
        fake_broker.session.get.return_value.json.return_value = {
            "isSuccess": True,
            "data": {
                "urls": ["npush101://npush101.agah.com:4222"],
                "token": "test-token",
                "privateKey": VALID_NKEY_SEED,
            },
        }
        fake_broker.session.get.return_value.raise_for_status = MagicMock()

        transport = AgahNatsTransport(fake_broker)

        captured = {}
        async def mock_connect(**kwargs):
            captured.update(kwargs)
            return AsyncMock()

        with patch("nats.connect", mock_connect):
            await transport._fetch_connection_info()
            await transport._connect()

        assert captured.get("token") == "test-token"
        assert "nkeys_seed_str" in captured
        assert captured["nkeys_seed_str"] == VALID_NKEY_SEED

    asyncio.run(run())


def test_nats_transport_privatekey_failure_fail_closed(fake_broker):
    """
    Test 4: privateKey failure → fail-closed.

    If privateKey is present but invalid, the connection must fail
    (NOT fall back to token-only).
    """
    async def run():
        fake_broker.session.get.return_value.json.return_value = {
            "isSuccess": True,
            "data": {
                "urls": ["npush101://npush101.agah.com:4222"],
                "token": "test-token",
                "privateKey": "INVALID_KEY_DATA_NOT_A_REAL_NKEY_SEED",
            },
        }
        fake_broker.session.get.return_value.raise_for_status = MagicMock()

        transport = AgahNatsTransport(fake_broker)

        await transport._fetch_connection_info()

        with pytest.raises(RuntimeError, match="NKey authentication failed"):
            await transport._connect()

    asyncio.run(run())


def test_nats_transport_runtime_groupnames(fake_broker):
    """
    Test 5: Runtime groupNames extraction from message-types.

    groupNames should come from the server response, not hardcoded.
    """
    async def run():
        fake_broker.session.get.return_value.json.return_value = {
            "isSuccess": True,
            "data": {
                "groups": [
                    {
                        "code": 100,
                        "groupNames": ["oms.state.changed.AGAH"],
                        "schema": ["code", "action", "decisionId", "requestId",
                                   "currentTradeCount", "message", "channel", "nscId"],
                    }
                ],
            },
        }
        fake_broker.session.get.return_value.raise_for_status = MagicMock()

        transport = AgahNatsTransport(fake_broker)
        await transport._fetch_message_types()

        assert transport._oms_schema.group_names == ["oms.state.changed.AGAH"]
        assert len(transport._decoder.field_names) == 8

    asyncio.run(run())


def test_nats_transport_runtime_schema(fake_broker):
    """
    Test 6: Runtime schema parsing for code 100.

    The schema field names must come from the server response.
    """
    async def run():
        server_schema = ["code", "action", "decisionId", "requestId",
                         "currentTradeCount", "message", "channel", "nscId"]
        fake_broker.session.get.return_value.json.return_value = {
            "isSuccess": True,
            "data": {
                "groups": [
                    {
                        "code": 100,
                        "groupNames": ["oms.subject.123"],
                        "schema": server_schema,
                    }
                ],
            },
        }
        fake_broker.session.get.return_value.raise_for_status = MagicMock()

        transport = AgahNatsTransport(fake_broker)
        await transport._fetch_message_types()

        assert transport._decoder.field_names == server_schema

    asyncio.run(run())


def test_nats_transport_subscription(fake_broker):
    """
    Test 7: Subscription to OmsStateChanged subject from server groupNames.
    """
    from brokers.agaah.nats_transport import MessageTypeSchema

    async def run():
        fake_broker.session.get.return_value.json.return_value = {
            "isSuccess": True,
            "data": {
                "groups": [
                    {
                        "code": 100,
                        "groupNames": ["oms.state.changed.test"],
                        "schema": ["code", "action", "decisionId", "requestId",
                                   "currentTradeCount", "message", "channel", "nscId"],
                    }
                ],
            },
        }
        fake_broker.session.get.return_value.raise_for_status = MagicMock()

        transport = AgahNatsTransport(fake_broker)

        # Mock NATS connection
        mock_nc = AsyncMock()
        mock_sub = AsyncMock()
        mock_nc.subscribe = AsyncMock(return_value=mock_sub)
        transport._nc = mock_nc
        transport._oms_schema = MessageTypeSchema(
            code=100,
            group_names=["oms.state.changed.test"],
            schema=["code", "action", "decisionId", "requestId",
                    "currentTradeCount", "message", "channel", "nscId"],
        )
        transport._decoder = OmsMessageDecoder(transport._oms_schema.schema)

        await transport._subscribe_oms_state_changed()

        mock_nc.subscribe.assert_called_once()
        call_args = mock_nc.subscribe.call_args
        assert call_args[0][0] == "oms.state.changed.test"

    asyncio.run(run())


def test_nats_transport_incoming_message_decode(fake_broker):
    """
    Test 8: Incoming message decode with server-provided schema.

    Verifies the full decode pipeline: payload → fields → OmsStateChanged.
    """
    schema = ["code", "action", "decisionId", "requestId",
              "currentTradeCount", "message", "channel", "nscId"]
    decoder = OmsMessageDecoder(schema)

    # Payload matches schema order
    payload = "100,5,DEC-123,REQ-456,0,some message,CH001,NSC-789"
    decoded = decoder.decode(payload)

    assert decoded["code"] == "100"
    assert decoded["action"] == "5"
    assert decoded["decisionId"] == "DEC-123"
    assert decoded["requestId"] == "REQ-456"
    assert decoded["currentTradeCount"] == "0"
    assert decoded["message"] == "some message"
    assert decoded["channel"] == "CH001"
    assert decoded["nscId"] == "NSC-789"


def test_nats_transport_code_100_filtering(fake_broker):
    """
    Test 9: OmsStateChanged code 100 is processed, other codes filtered.
    """
    schema = ["code", "action", "decisionId", "requestId",
              "currentTradeCount", "message", "channel", "nscId"]
    transport = AgahNatsTransport(fake_broker)
    transport._decoder = OmsMessageDecoder(schema)

    results = []
    transport.on_oms_state_changed = lambda oms: results.append(oms)

    async def run():
        # Payload with code 100
        payload = "100,2,DEC-123,REQ-1,0,msg|field,CH001,NSC-789"
        await transport._process_oms_message(payload)
        assert len(results) == 1
        assert results[0].code == 100
        assert results[0].decision_id == "DEC-123"

        # Payload with code 200 (should be filtered)
        payload2 = "200,5,DEC-456,REQ-2,0,msg2,CH002,NSC-888"
        await transport._process_oms_message(payload2)
        assert len(results) == 1  # Still only 1, code 200 filtered

    asyncio.run(run())


def test_orderdate_timezone_conversion_tehran_to_utc(correlator):
    """
    Test 15: timezone conversion from Asia/Tehran to UTC.

    2026-09-26T16:08:15.027 (Tehran, UTC+3:30) → 2026-09-26T12:38:15.027+00:00
    """
    correlator.register_order("DEC-123", "NSC-123")

    # Tehran datetime (UTC+3:30) at field index 11
    parts = ["f"] * 11 + ["2026-09-26T16:08:15.027"]
    oms = OmsStateChanged(
        code=100, action=2, decision_id="DEC-123", request_id="REQ-1",
        current_trade_count=0, message="|".join(parts), channel="ch1", nsc_id="NSC-123",
    )

    correlator._handle_oms_event(oms)

    info = correlator.get_order_info("DEC-123")
    assert info.order_date == "2026-09-26T12:38:15.027000+00:00"


def test_orderdate_timezone_conversion_with_z_suffix(correlator):
    """
    Test: datetime already in UTC with Z suffix is normalized.
    """
    correlator.register_order("DEC-TZ", "NSC-123")

    parts = ["f"] * 11 + ["2026-09-26T10:00:00Z"]
    oms = OmsStateChanged(
        code=100, action=2, decision_id="DEC-TZ", request_id="REQ-1",
        current_trade_count=0, message="|".join(parts), channel="ch1", nsc_id="NSC-123",
    )

    correlator._handle_oms_event(oms)

    info = correlator.get_order_info("DEC-TZ")
    assert info.order_date is not None
    assert "2026-09-26T10:00:00" in info.order_date


# ---------------------------------------------------------------------------
# NATS Transport Lifecycle Tests
# ---------------------------------------------------------------------------


def test_transport_start_and_stop(fake_broker):
    """
    Test 10/11: start tracking and stop tracking lifecycle.
    """
    async def run():
        # _fetch_connection_info and _fetch_message_types both call session.get
        nats_response = MagicMock()
        nats_response.json.return_value = {
            "isSuccess": True,
            "data": {
                "urls": ["nats://test:4222"],
                "token": "test-token",
                "privateKey": "",
            },
        }
        nats_response.raise_for_status = MagicMock()

        schema_response = MagicMock()
        schema_response.json.return_value = {
            "isSuccess": True,
            "data": {
                "groups": [
                    {
                        "code": 100,
                        "groupNames": ["oms.state.changed.test"],
                        "schema": ["code", "action", "decisionId", "requestId",
                                   "currentTradeCount", "message", "channel", "nscId"],
                    }
                ],
            },
        }
        schema_response.raise_for_status = MagicMock()

        fake_broker.session.get.side_effect = [nats_response, schema_response]

        transport = AgahNatsTransport(fake_broker)

        # Mock nats.connect
        mock_nc = AsyncMock()
        mock_nc.drain = AsyncMock()
        mock_nc.subscribe = AsyncMock()
        with patch("nats.connect", AsyncMock(return_value=mock_nc)):
            await transport.start()

        assert transport._running is True

        # Stop
        await transport.stop()
        assert transport._running is False

    asyncio.run(run())


def test_oms_handler_non_blocking(fake_broker):
    """
    Test 12: OMS handler does not block on HTTP.

    The message handler returns immediately after scheduling the async fetch.
    """
    async def run():
        correlator = AgahOrderCorrelator(fake_broker)
        correlator._running = True

        # Mock the queue position service to track calls
        call_count = 0
        original = correlator._queue_position_service.get_queue_position

        def counting_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return 5

        correlator._queue_position_service.get_queue_position = counting_get

        correlator.register_order("DEC-123", "NSC-123")

        # Send both events
        parts = ["f"] * 11 + ["2026-09-26T10:00:00Z"]
        oms1 = OmsStateChanged(
            code=100, action=2, decision_id="DEC-123", request_id="REQ-1",
            current_trade_count=0, message="|".join(parts), channel="ch1", nsc_id="NSC-123",
        )
        correlator._handle_oms_event(oms1)

        oms2 = OmsStateChanged(
            code=100, action=5, decision_id="DEC-123", request_id="REQ-1",
            current_trade_count=0, message="98765", channel="ch1", nsc_id="NSC-123",
        )
        correlator._handle_oms_event(oms2)

        # _handle_oms_event returns immediately - HTTP call not yet made
        assert call_count == 0

        # Wait for async fetch
        await asyncio.sleep(0.1)

        assert call_count == 1
        assert correlator.get_queue_position("DEC-123") == 5

    asyncio.run(run())


def test_order_placement_non_blocking(fake_broker):
    """
    Test 13: Order placement does not wait for queue position.

    on_order_placed is synchronous and returns immediately.
    """
    from brokers.agaah.queue_position import AgahQueuePositionProvider

    provider = AgahQueuePositionProvider(fake_broker)

    # on_order_placed should not fetch or wait for anything
    provider.on_order_placed("DEC-123", "NSC-123")

    # Order is registered but queue position is not yet fetched
    info = provider.get_order_info("DEC-123")
    assert info is not None
    assert info.queue_position is None  # Not fetched yet
    fake_broker.session.get.assert_not_called()  # No HTTP call during registration


def test_no_duplicate_registration(fake_broker):
    """
    Test 14: Registering the same order twice does not cause duplicate work.
    """
    from brokers.agaah.queue_position import AgahQueuePositionProvider

    provider = AgahQueuePositionProvider(fake_broker)

    provider.on_order_placed("DEC-123", "NSC-123")
    provider.on_order_placed("DEC-123", "NSC-123")  # Should not duplicate

    info = provider.get_order_info("DEC-123")
    assert info is not None
    assert provider.correlator._orders.get("DEC-123") is info


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# OrderEngine Integration Tests
# ---------------------------------------------------------------------------


def test_stage2_registration_without_collector():
    """
    Test A: Stage 2 registration must not depend on Stage 1 collector.

    * live=True
    * broker response is successful (isSuccess=true, data.decisionId)
    * collector=None
    * sequence=None
    * broker.on_order_placed(...) is called exactly once
    * correct decision_id and order.nsc_id are passed
    """
    from core.order_engine import OrderEngine
    from models.broker_instrument import BrokerInstrument
    from models.trading_state import VERIFIED_TRADABLE

    order = Order(
        nsc_id="NSC-123",
        side=BUY,
        price=1000,
        quantity=10,
    )
    instrument = BrokerInstrument(
        name="Test",
        nsc_id="NSC-123",
        minimum_order_quantity=1,
        lot_size=1,
        fixed_price_tick=1,
        lower_price_threshold=1,
        upper_price_threshold=10000,
        maximum_order_quantity_for_buy=100,
    )
    account = Account(account_id="acc-1", tradable_balance_t1=10000)

    # Mock broker with on_order_placed
    mock_broker = MagicMock()
    mock_broker.name = "Agah"
    mock_broker.live_trading_enabled = True
    mock_broker.get_trading_state.return_value = VERIFIED_TRADABLE
    mock_broker.get_buy_capacity.return_value = 10000
    mock_broker.place_order.return_value = {
        "isSuccess": True,
        "data": {"decisionId": "DEC-123"},
    }

    engine = OrderEngine()

    result = engine.execute(
        broker=mock_broker,
        order=order,
        instrument=instrument,
        account=account,
        live=True,
    )

    assert result is not None
    assert result.success is True
    assert result.sent is True
    # on_order_placed called exactly once with correct args
    mock_broker.on_order_placed.assert_called_once_with("DEC-123", "NSC-123")


def test_stage2_not_registered_on_failed_response():
    """
    Test B: failed registration must NOT register Stage 2.

    When isSuccess is False, broker.on_order_placed(...) must not be called.
    """
    from core.order_engine import OrderEngine
    from models.broker_instrument import BrokerInstrument
    from models.trading_state import VERIFIED_TRADABLE

    order = Order(
        nsc_id="NSC-123",
        side=BUY,
        price=1000,
        quantity=10,
    )
    instrument = BrokerInstrument(
        name="Test",
        nsc_id="NSC-123",
        minimum_order_quantity=1,
        lot_size=1,
        fixed_price_tick=1,
        lower_price_threshold=1,
        upper_price_threshold=10000,
        maximum_order_quantity_for_buy=100,
    )
    account = Account(account_id="acc-1", tradable_balance_t1=10000)

    mock_broker = MagicMock()
    mock_broker.name = "Agah"
    mock_broker.live_trading_enabled = True
    mock_broker.get_trading_state.return_value = VERIFIED_TRADABLE
    mock_broker.get_buy_capacity.return_value = 10000
    mock_broker.place_order.return_value = {
        "isSuccess": False,
        "data": {},
        "message": "Order rejected",
    }

    engine = OrderEngine()

    result = engine.execute(
        broker=mock_broker,
        order=order,
        instrument=instrument,
        account=account,
        live=True,
    )

    assert result is not None
    # on_order_placed must NOT be called when isSuccess is False
    mock_broker.on_order_placed.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])