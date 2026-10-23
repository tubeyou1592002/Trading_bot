"""Offline tests for Agah NATS bootstrap safe diagnostics.

These tests cover the DIAGNOSTIC surface only. They never issue a live
request, never build a real credential and never print a response body.
The transport is imported with an offline ``nats`` stub when the optional
runtime dependency is not installed on the test machine.
"""

import asyncio
import logging
import sys
import types
from unittest.mock import AsyncMock, patch

import pytest
import requests


def _ensure_nats_importable():
    """Provide a minimal stub only when nats-py is not installed."""
    try:
        import nats  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    nats_stub = types.ModuleType("nats")
    errors_stub = types.ModuleType("nats.errors")

    class _ConnectionClosedError(Exception):
        pass

    class _NatsTimeoutError(Exception):
        pass

    errors_stub.ConnectionClosedError = _ConnectionClosedError
    errors_stub.TimeoutError = _NatsTimeoutError
    nats_stub.errors = errors_stub
    nats_stub.connect = lambda **kwargs: None
    sys.modules["nats"] = nats_stub
    sys.modules["nats.errors"] = errors_stub


_ensure_nats_importable()

from brokers.agaah import nats_transport as nt  # noqa: E402


LOGGER_NAME = "brokers.agaah.nats_transport"


class FakeResponse:
    def __init__(
        self,
        payload,
        *,
        status_code=200,
        content_type="application/json; charset=utf-8",
        extra_headers=None,
    ):
        self._payload = payload
        self.status_code = status_code
        self.headers = (
            {"Content-Type": content_type} if content_type is not None else {}
        )
        if extra_headers:
            self.headers.update(extra_headers)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeBroker:
    """Synchronous shim for ``AgaahBroker._authed_get_with_recovery``."""

    def __init__(self, response=None, exception=None):
        self.response = response
        self.exception = exception
        self.calls = []

    def _authed_get_with_recovery(self, path, params=None):
        self.calls.append(path)
        if self.exception is not None:
            raise self.exception
        return self.response


def _run(coro):
    return asyncio.run(coro)


def _fetch_types(response=None, exception=None):
    broker = FakeBroker(response=response, exception=exception)
    transport = nt.AgahNatsTransport(broker)
    with pytest.raises(Exception):
        _run(transport._fetch_message_types())
    return broker


# ---------------------------------------------------------------------------
# 1) What the message-types parser accepts — documented shapes only
# ---------------------------------------------------------------------------


def test_code_100_under_data_groups_is_accepted(caplog):
    payload = {
        "isSuccess": True,
        "data": {
            "groups": [
                {
                    "code": 100,
                    "groupNames": ["oms.state.changed.AGAH"],
                    "schema": ["code", "action", "decisionId"],
                }
            ]
        },
    }

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        broker = FakeBroker(response=FakeResponse(payload))
        transport = nt.AgahNatsTransport(broker)
        _run(transport._fetch_message_types())

    assert transport._oms_schema.code == 100
    assert transport._oms_schema.group_names == ["oms.state.changed.AGAH"]
    assert transport._decoder.field_names == ["code", "action", "decisionId"]
    assert "response diagnostic" not in caplog.text


def test_code_100_under_data_messagetypes_is_accepted(caplog):
    payload = {
        "isSuccess": True,
        "data": {
            "messageTypes": [
                {
                    "code": 100,
                    "groupNames": ["oms.subject"],
                    "schema": ["code", "action"],
                }
            ]
        },
    }

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        broker = FakeBroker(response=FakeResponse(payload))
        transport = nt.AgahNatsTransport(broker)
        _run(transport._fetch_message_types())

    assert transport._oms_schema.group_names == ["oms.subject"]
    assert "response diagnostic" not in caplog.text


def test_code_100_in_a_top_level_data_list_is_accepted(caplog):
    payload = {
        "isSuccess": True,
        "data": [
            {
                "code": 100,
                "groupNames": ["oms.list.subject"],
                "schema": ["code", "action"],
            }
        ],
    }

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        broker = FakeBroker(response=FakeResponse(payload))
        transport = nt.AgahNatsTransport(broker)
        _run(transport._fetch_message_types())

    assert transport._oms_schema.group_names == ["oms.list.subject"]
    assert "response diagnostic" not in caplog.text


# ---------------------------------------------------------------------------
# 2) Why code 100 is (or is not) found — safe structure evidence
# ---------------------------------------------------------------------------


def test_string_code_100_is_not_coerced_and_shape_is_logged(caplog):
    """The parser requires Python-equal int 100; "100" is not generalized."""
    payload = {
        "isSuccess": True,
        "accessToken": "TOP-LEVEL-SECRET-TOKEN",
        "data": {
            "groups": [
                {"code": "100", "groupNames": ["oms"], "schema": []},
                {"code": 200, "message": "other", "token": "INNER-SECRET"},
            ],
            "privateKey": "PRIVATE-KEY-SECRET",
        },
    }

    response = FakeResponse(
        payload,
        extra_headers={
            "Authorization": "Bearer AUTH-HEADER-SECRET",
            "Cookie": "SESSION-HEADER-SECRET",
        },
    )
    broker = FakeBroker(response=response)
    transport = nt.AgahNatsTransport(broker)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(
            RuntimeError, match=r"OmsStateChanged \(code 100\) not found"
        ):
            _run(transport._fetch_message_types())

    text = caplog.text
    assert nt._ENDPOINT_MESSAGE_TYPES in text
    assert "'http_status': 200" in text
    assert "application/json" in text
    assert "'is_success': True" in text
    assert "'groups_source': 'data.groups'" in text
    assert "'group_count': 2" in text
    assert "'group_keys': ['code', 'groupNames', 'message', 'schema', 'token']" in text
    assert "'value': '100', 'type': 'str'" in text
    assert "'value': 200, 'type': 'int'" in text
    # Secret values and full bodies must never be logged.
    assert "TOP-LEVEL-SECRET-TOKEN" not in text
    assert "INNER-SECRET" not in text
    assert "PRIVATE-KEY-SECRET" not in text
    assert "AUTH-HEADER-SECRET" not in text
    assert "SESSION-HEADER-SECRET" not in text
    assert "Bearer" not in text


def test_unknown_group_container_is_reported_without_guessing(caplog):
    payload = {
        "isSuccess": True,
        "data": {"items": [{"code": 100, "groupNames": ["oms"], "schema": []}]},
    }

    broker = FakeBroker(response=FakeResponse(payload))
    transport = nt.AgahNatsTransport(broker)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(RuntimeError):
            _run(transport._fetch_message_types())

    text = caplog.text
    assert "'groups_source': None" in text
    assert "'top_level_keys': ['data', 'isSuccess']" in text
    assert "'data_keys': ['items']" in text


def test_non_dict_group_item_logs_shape_and_preserves_attribute_error(caplog):
    payload = {"isSuccess": True, "data": {"groups": ["not-a-mapping"]}}

    broker = FakeBroker(response=FakeResponse(payload))
    transport = nt.AgahNatsTransport(broker)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(AttributeError):
            _run(transport._fetch_message_types())

    text = caplog.text
    assert "'group_item_types': ['str']" in text
    assert "'code_100_found': False" in text


def test_is_success_false_is_logged_and_still_fails(caplog):
    payload = {"isSuccess": False, "message": "denied", "data": {}}

    broker = FakeBroker(response=FakeResponse(payload))
    transport = nt.AgahNatsTransport(broker)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(RuntimeError, match="Failed to get message types"):
            _run(transport._fetch_message_types())

    assert "'is_success': False" in caplog.text
    assert "'code_100_found': False" in caplog.text


def test_unparsable_json_logs_only_status_and_content_type(caplog):
    response = FakeResponse(ValueError("invalid json"))

    broker = FakeBroker(response=response)
    transport = nt.AgahNatsTransport(broker)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError):
            _run(transport._fetch_message_types())

    text = caplog.text
    assert nt._ENDPOINT_MESSAGE_TYPES in text
    assert "unparsable JSON" in text
    assert "http_status=200" in text
    assert "content_type=application/json" in text
    assert "error_type=ValueError" in text


# ---------------------------------------------------------------------------
# 3) Timeout: which endpoint, which phase, how long — no retry added
# ---------------------------------------------------------------------------


def test_connection_info_timeout_reports_its_own_endpoint(caplog):
    exc = requests.exceptions.ConnectTimeout("offline")

    broker = FakeBroker(exception=exc)
    transport = nt.AgahNatsTransport(broker)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(requests.exceptions.ConnectTimeout):
            _run(transport._fetch_connection_info())

    text = caplog.text
    assert "'endpoint': 'pusher/nats'" in text
    assert "'timeout_kind': 'connect'" in text
    assert "'error_type': 'ConnectTimeout'" in text
    assert "'elapsed_ms':" in text
    assert len(broker.calls) == 1  # no retry added


def test_message_types_timeout_reports_its_own_endpoint(caplog):
    exc = requests.exceptions.ReadTimeout("offline")

    broker = FakeBroker(exception=exc)
    transport = nt.AgahNatsTransport(broker)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(requests.exceptions.ReadTimeout):
            _run(transport._fetch_message_types())

    text = caplog.text
    assert "'endpoint': 'Pusher/message-types'" in text
    assert "'timeout_kind': 'read'" in text
    assert "'error_type': 'ReadTimeout'" in text
    assert len(broker.calls) == 1  # no retry added


def test_nats_connect_timeout_is_labelled_separately(caplog):
    broker = FakeBroker()
    transport = nt.AgahNatsTransport(broker)
    transport._connection_info = nt.NatsConnectionInfo(
        urls=["nats://example.invalid:4222"],
        token="not-logged",
        private_key="",
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with patch.object(
            nt.nats, "connect", new=AsyncMock(side_effect=TimeoutError("slow"))
        ):
            with pytest.raises(TimeoutError):
                _run(transport._connect())

    text = caplog.text
    assert "'endpoint': 'nats-connect'" in text
    assert "'timeout_kind': 'timeout'" in text
    assert "not-logged" not in text
