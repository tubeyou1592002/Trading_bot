"""Offline acceptance safety checks for scheduled Live boundaries."""

import asyncio
import socket
import urllib.request

import pytest


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app



class _NetworkDenied:
    def __init__(self, original):
        self._original = original
        self._internal_pair = False
        self._original_pair = socket.socketpair

    def __call__(self, family=socket.AF_INET, type=socket.SOCK_STREAM,
                 proto=0, fileno=None):
        if fileno is not None:
            return self._original(family, type, proto, fileno)
        if family == getattr(socket, "AF_UNIX", None) or self._internal_pair:
            return self._original(family, type, proto, fileno)
        raise AssertionError("external network socket attempted")

    def socketpair(self, *args, **kwargs):
        self._internal_pair = True
        try:
            return self._original_pair(*args, **kwargs)
        finally:
            self._internal_pair = False


def _deny_network(*_args, **_kwargs):
    raise AssertionError("external network connection attempted")


def test_external_network_block_allows_windows_internal_socketpair(monkeypatch):
    original = socket.socket
    denied = _NetworkDenied(original)
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "socketpair", denied.socketpair)
    for name in ("create_connection", "create_server", "create_unix_connection",
                 "create_unix_server", "open_connection", "start_server"):
        if hasattr(asyncio, name):
            monkeypatch.setattr(asyncio, name, _deny_network)
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    if hasattr(socket, "create_server"):
        monkeypatch.setattr(socket, "create_server", _deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", _deny_network)
    monkeypatch.setattr(urllib.request, "urlopen", _deny_network)
    if hasattr(socket, "AF_UNIX"):
        left, right = socket.socketpair()
        left.close()
        right.close()
    else:
        # Windows implements socketpair through local loopback TCP. The test
        # allows only that internal helper's private socket calls.
        pair = socket.socketpair()
        pair[0].close()
        pair[1].close()
    with pytest.raises(AssertionError, match="external network"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "AF_INET6"):
        with pytest.raises(AssertionError, match="external network"):
            socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    with pytest.raises(AssertionError, match="external network"):
        socket.create_connection(("example.invalid", 443))
    with pytest.raises(AssertionError, match="external network"):
        asyncio.run(asyncio.open_connection("example.invalid", 443))
    with pytest.raises(AssertionError, match="external network"):
        urllib.request.urlopen("https://example.invalid")


def test_prepared_async_transport_has_no_public_send_bypass():
    from brokers.agaah.broker import AsyncPreparedOrderTransport
    transport = AsyncPreparedOrderTransport(
        owner=object(), account_id="A", user_identifier="u", access_token="t",
        session=object(),
    )
    with pytest.raises(RuntimeError, match="Direct async"):
        asyncio.run(transport.submit({"security": "must-not-post"}))
