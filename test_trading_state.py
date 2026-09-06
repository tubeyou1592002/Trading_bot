"""M5 — TSETMC Trading State Integration tests.

Tests the cEtaval mapping and order permission policy
as defined in Decision 020.

No real order is sent. TSETMC calls are mocked.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch, MagicMock
from models.trading_state import UNVERIFIED
from brokers.agaah.broker import AgaahBroker


class _StubBrokerInstrument:
    def __init__(self, tse_id=None):
        self.tse_id = tse_id


class _StubTsetmc:
    """Stub TSETMC client that returns a fixed instrument state list."""

    def __init__(self, states=None, raise_error=False):
        self._states = states
        self._raise_error = raise_error
        self.last_ins_code = None

    def get_trading_state(self, ins_code):
        self.last_ins_code = ins_code
        if self._raise_error:
            raise ConnectionError("network error")
        return self._states if self._states else []


def _make_states(c_etaval, tse_id="60235881999727383"):
    """Create a state list with the cEtaval value and matching insCode."""
    return [
        {
            "idn": 0,
            "dEven": 20260906,
            "hEven": 105028,
            "insCode": tse_id,
            "lVal18AFC": None,
            "lVal30": None,
            "cEtaval": c_etaval,
            "realHeven": 0,
            "underSupervision": 0,
            "cEtavalTitle": "test-title",
        }
    ]


def _make_broker_and_patch(states=None, raise_error=False, tse_id="60235881999727383"):
    """Create a broker with TSETMC and get_instrument patched."""
    broker = AgaahBroker()
    stub = _StubTsetmc(states=states, raise_error=raise_error)

    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=stub,
    ), patch.object(
        broker,
        "get_instrument",
        return_value=_StubBrokerInstrument(tse_id=tse_id),
    ):
        result = broker.get_trading_state("IRO1TEST0001")

    return result


def test_cEtaval_A_allows_order():
    result = _make_broker_and_patch(_make_states("A "))
    assert result.is_order_entry_allowed is True
    assert result.is_verified is True
    assert result.source == "tsetmc:cEtaval"


def test_cEtaval_AR_allows_order():
    result = _make_broker_and_patch(_make_states("AR"))
    assert result.is_order_entry_allowed is True
    assert result.is_verified is True


def test_cEtaval_I_blocks_order():
    result = _make_broker_and_patch(_make_states("I "))
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_cEtaval_AG_blocks_order():
    result = _make_broker_and_patch(_make_states("AG"))
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_cEtaval_AS_blocks_order():
    result = _make_broker_and_patch(_make_states("AS"))
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_cEtaval_IG_blocks_order():
    result = _make_broker_and_patch(_make_states("IG"))
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_cEtaval_IS_blocks_order():
    result = _make_broker_and_patch(_make_states("IS"))
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_cEtaval_IR_blocks_order():
    result = _make_broker_and_patch(_make_states("IR"))
    assert result.is_order_entry_allowed is False
    assert result.is_verified is True


def test_unknown_cEtaval_blocks_order():
    result = _make_broker_and_patch(_make_states("ZZ"))
    assert result.is_order_entry_allowed is False
    assert result.is_verified is False


def test_missing_cEtaval_blocks_order():
    result = _make_broker_and_patch([])
    assert result.is_order_entry_allowed is False
    assert result.is_verified is False


def test_network_error_blocks_order():
    result = _make_broker_and_patch(raise_error=True)
    assert result.is_order_entry_allowed is False
    assert result == UNVERIFIED


def test_invalid_response_blocks_order():
    result = _make_broker_and_patch(states=["not a dict"])
    assert result.is_order_entry_allowed is False
    assert result.is_verified is False


def test_nsc_id_resolved_to_tse_id_for_tsetmc():
    """nsc_id is resolved to tse_id via get_instrument,
    and tse_id is used as ins_code for TSETMC."""
    from unittest.mock import patch

    broker = AgaahBroker()
    expected_tse_id = "60235881999727383"
    stub = _StubTsetmc(_make_states("A ", tse_id=expected_tse_id))

    with patch(
        "brokers.agaah.broker.TSETMC",
        return_value=stub,
    ), patch.object(
        broker,
        "get_instrument",
        return_value=_StubBrokerInstrument(tse_id=expected_tse_id),
    ):
        result = broker.get_trading_state("IRO1TEST0001")

    assert result.is_order_entry_allowed is True
    assert stub.last_ins_code == expected_tse_id


def test_ins_code_mismatch_blocks_order():
    """If returned insCode doesn't match expected, UNVERIFIED."""
    result = _make_broker_and_patch(
        _make_states("A ", tse_id="WRONG_INS_CODE"),
        tse_id="60235881999727383",
    )
    assert result == UNVERIFIED
    assert result.is_order_entry_allowed is False


def test_missing_tse_id_returns_unverified():
    """If tse_id is missing on the broker instrument, UNVERIFIED."""
    result = _make_broker_and_patch(
        _make_states("A "),
        tse_id=None,
    )
    assert result == UNVERIFIED


def test_get_instrument_failure_returns_unverified():
    """If get_instrument fails, UNVERIFIED."""
    broker = AgaahBroker()
    with patch.object(
        broker,
        "get_instrument",
        side_effect=Exception("lookup failed"),
    ):
        result = broker.get_trading_state("IRO1TEST0001")
    assert result == UNVERIFIED


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
        test_nsc_id_resolved_to_tse_id_for_tsetmc,
        test_ins_code_mismatch_blocks_order,
        test_missing_tse_id_returns_unverified,
        test_get_instrument_failure_returns_unverified,
    ]
    for test in tests:
        test()
        print("PASS: " + test.__name__)
    print("\nAll M5 trading state tests passed. (" + str(len(tests)) + " tests)")
