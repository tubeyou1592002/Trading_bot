"""M5 — TSETMC Trading State Integration tests.

Tests the cEtaval mapping and order permission policy
as defined in Decision 020.

No real order is sent. TSETMC calls are mocked.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch
from models.trading_state import UNVERIFIED
from brokers.agaah.broker import AgaahBroker


class _StubTsetmc:
    """Stub TSETMC client that returns a fixed instrument state."""

    def __init__(self, state=None, raise_error=False):
        self._state = state
        self._raise_error = raise_error
        self.last_ins_code = None

    def get_trading_state(self, ins_code):
        self.last_ins_code = ins_code
        if self._raise_error:
            raise ConnectionError("network error")
        return self._state


def _make_broker(tsetmc_stub):
    """Create a broker with TSETMC patched to return the stub."""
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=tsetmc_stub,
    ):
        return AgaahBroker()


def test_cEtaval_A_allows_order():
    state = {"cEtaval": "A ", "cEtavalTitle": "مجاز"}
    broker = _make_broker(_StubTsetmc(state))
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(state),
    ):
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is True
    assert result.is_verified is True
    assert result.source == "tsetmc:cEtaval"


def test_cEtaval_AR_allows_order():
    state = {"cEtaval": "AR", "cEtavalTitle": "مجاز-محفوظ"}
    broker = _make_broker(_StubTsetmc(state))
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(state),
    ):
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is True
    assert result.is_verified is True


def test_cEtaval_I_blocks_order():
    state = {"cEtaval": "I ", "cEtavalTitle": "ممنوع"}
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(state),
    ):
        broker = AgaahBroker()
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_cEtaval_AG_blocks_order():
    state = {"cEtaval": "AG", "cEtavalTitle": "مجاز-مسدود"}
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(state),
    ):
        broker = AgaahBroker()
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_cEtaval_AS_blocks_order():
    state = {"cEtaval": "AS", "cEtavalTitle": "مجاز-متوقف"}
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(state),
    ):
        broker = AgaahBroker()
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_cEtaval_IG_blocks_order():
    state = {"cEtaval": "IG", "cEtavalTitle": "ممنوع-مسدود"}
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(state),
    ):
        broker = AgaahBroker()
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_cEtaval_IS_blocks_order():
    state = {"cEtaval": "IS", "cEtavalTitle": "ممنوع-متوقف"}
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(state),
    ):
        broker = AgaahBroker()
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_cEtaval_IR_blocks_order():
    state = {"cEtaval": "IR", "cEtavalTitle": "ممنوع-محفوظ"}
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(state),
    ):
        broker = AgaahBroker()
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_unknown_cEtaval_blocks_order():
    state = {"cEtaval": "ZZ", "cEtavalTitle": "ناشناخته"}
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(state),
    ):
        broker = AgaahBroker()
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is False
    assert result.is_verified is False


def test_missing_cEtaval_blocks_order():
    state = {}
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(state),
    ):
        broker = AgaahBroker()
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is False
    assert result.is_verified is False


def test_network_error_blocks_order():
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(raise_error=True),
    ):
        broker = AgaahBroker()
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is False
    assert result == UNVERIFIED


def test_invalid_response_blocks_order():
    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=_StubTsetmc(state="not a dict"),
    ):
        broker = AgaahBroker()
        result = broker.get_trading_state("123")
    assert result.is_order_entry_allowed is False
    assert result.is_verified is False


if __name__ == "__main__":
    tests = [
        test_cEtaval_A_allows_order,
        test_cEtaval_AR_allows_order,
        test_cEtaval_I_blocks_order,
        test_cEtaval_AG_blocks_order,
        test_cEtaval_AS_blocks_order,
        test_cEtaval_IG_blocks_order,
        test_cEtaval_IS_blocks_order,
        test_cEtaval_IR_blocks_order,
        test_unknown_cEtaval_blocks_order,
        test_missing_cEtaval_blocks_order,
        test_network_error_blocks_order,
        test_invalid_response_blocks_order,
    ]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
    print("\nAll M5 trading state tests passed.")
