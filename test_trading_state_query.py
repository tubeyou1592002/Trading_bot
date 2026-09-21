"""
Tests for core/trading_state_query.py — Read-only TradingState query seam.

Offline, mocked tests. No network, no real broker, no credentials.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import MagicMock, patch

from models.trading_state import TradingState, TradingStateUnavailable, UNVERIFIED, VERIFIED_TRADABLE, VERIFIED_BLOCKED
from models.instrument import Instrument
from models.broker_instrument import BrokerInstrument
from brokers.base import InstrumentLookupError
from core.trading_state_query import TradingStateQuery


class TestTradingStateQuery:
    """Test suite for TradingStateQuery."""

    def setup_method(self):
        """Create fresh mocks for each test."""
        self.mock_broker = MagicMock()
        self.mock_provider = MagicMock()
        self.query = TradingStateQuery(
            broker=self.mock_broker,
            provider=self.mock_provider,
        )

    def _make_instrument(self, ins_code="60235881999727383"):
        return Instrument(
            symbol="TEST",
            name="Test Company",
            ins_code=ins_code,
            instrument_id="123",
            isin="IRO1TEST0001",
            market="بورس",
            flow=1,
        )

    def _make_broker_instrument(self, nsc_id="IRO1TEST0001"):
        return BrokerInstrument(
            name="TEST",
            company_name="Test Company",
            nsc_id=nsc_id,
            tse_id="60235881999727383",
            market_title="بورس",
            state_code="A",
            group_state_code="B",
        )

    # ============================================================
    # Happy path tests
    # ============================================================

    def test_happy_path_returns_verified_tradable(self):
        """Valid ins_code -> provider -> nsc_id -> broker -> TradingState."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.return_value = VERIFIED_TRADABLE

        result = self.query.get_trading_state("60235881999727383")

        assert result is VERIFIED_TRADABLE
        self.mock_provider.get_instrument.assert_called_once_with("60235881999727383")
        self.mock_broker.get_trading_state.assert_called_once_with("IRO1TEST0001")

    def test_happy_path_returns_verified_blocked(self):
        """Valid path but broker returns blocked state."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.return_value = VERIFIED_BLOCKED

        result = self.query.get_trading_state("60235881999727383")

        assert result is VERIFIED_BLOCKED
        self.mock_broker.get_trading_state.assert_called_once_with("IRO1TEST0001")

    def test_ins_code_passed_to_provider(self):
        """The exact ins_code is forwarded to provider.get_instrument()."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.return_value = UNVERIFIED

        test_ins_code = "99999999999999999"
        self.query.get_trading_state(test_ins_code)

        self.mock_provider.get_instrument.assert_called_once_with(test_ins_code)

    def test_nsc_id_from_broker_instrument_used(self):
        """nsc_id is extracted from BrokerInstrument, not guessed."""
        instrument = self._make_instrument()
        custom_nsc_id = "CUSTOM_NSC_ID_123"
        broker_instrument = self._make_broker_instrument(nsc_id=custom_nsc_id)
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.return_value = UNVERIFIED

        self.query.get_trading_state("60235881999727383")

        self.mock_broker.get_trading_state.assert_called_once_with(custom_nsc_id)

    def test_same_nsc_id_passed_to_broker(self):
        """The exact nsc_id from BrokerInstrument is passed to broker.get_trading_state()."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument(nsc_id="SPECIFIC_NSC_ID")
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.return_value = UNVERIFIED

        self.query.get_trading_state("60235881999727383")

        args, _ = self.mock_broker.get_trading_state.call_args
        assert args[0] == "SPECIFIC_NSC_ID"

    # ============================================================
    # Fail-closed: resolution failures (InstrumentLookupError)
    # ============================================================

    def test_empty_ins_code_returns_unverified(self):
        """Empty ins_code returns UNVERIFIED without calling provider."""
        result = self.query.get_trading_state("")
        assert result is UNVERIFIED
        self.mock_provider.get_instrument.assert_not_called()

    def test_none_ins_code_returns_unverified(self):
        """None ins_code returns UNVERIFIED."""
        result = self.query.get_trading_state(None)
        assert result is UNVERIFIED
        self.mock_provider.get_instrument.assert_not_called()

    def test_provider_raises_instrument_lookup_error_returns_unverified(self):
        """Provider raises InstrumentLookupError -> UNVERIFIED (fail-closed)."""
        self.mock_provider.get_instrument.side_effect = InstrumentLookupError("network error")

        result = self.query.get_trading_state("60235881999727383")

        assert result is UNVERIFIED
        self.mock_broker.get_trading_state.assert_not_called()

    def test_provider_raises_generic_exception_propagates(self):
        """Provider raises generic Exception (not InstrumentLookupError) -> propagates."""
        self.mock_provider.get_instrument.side_effect = Exception("unexpected error")

        try:
            self.query.get_trading_state("60235881999727383")
        except Exception as e:
            assert type(e) is Exception
            assert str(e) == "unexpected error"
            return
        assert False, "Expected Exception to propagate"

    def test_provider_raises_type_error_propagates(self):
        """Provider raises TypeError (programming error) -> propagates."""
        self.mock_provider.get_instrument.side_effect = TypeError("bad arg")

        try:
            self.query.get_trading_state("60235881999727383")
        except TypeError as e:
            assert str(e) == "bad arg"
            return
        assert False, "Expected TypeError to propagate"

    def test_provider_raises_attribute_error_propagates(self):
        """Provider raises AttributeError (programming error) -> propagates."""
        self.mock_provider.get_instrument.side_effect = AttributeError("missing attr")

        try:
            self.query.get_trading_state("60235881999727383")
        except AttributeError as e:
            assert str(e) == "missing attr"
            return
        assert False, "Expected AttributeError to propagate"

    def test_provider_raises_not_implemented_error_propagates(self):
        """Provider raises NotImplementedError (programming error) -> propagates."""
        self.mock_provider.get_instrument.side_effect = NotImplementedError("not implemented")

        try:
            self.query.get_trading_state("60235881999727383")
        except NotImplementedError as e:
            assert str(e) == "not implemented"
            return
        assert False, "Expected NotImplementedError to propagate"

    def test_provider_returns_non_tuple_returns_unverified(self):
        """Provider returns non-tuple -> UNVERIFIED."""
        self.mock_provider.get_instrument.return_value = "not a tuple"

        result = self.query.get_trading_state("60235881999727383")

        assert result is UNVERIFIED
        self.mock_broker.get_trading_state.assert_not_called()

    def test_provider_returns_wrong_tuple_length_returns_unverified(self):
        """Provider returns tuple of wrong length -> UNVERIFIED."""
        self.mock_provider.get_instrument.return_value = (Instrument(symbol="X", name="Y", ins_code="1"),)

        result = self.query.get_trading_state("60235881999727383")

        assert result is UNVERIFIED
        self.mock_broker.get_trading_state.assert_not_called()

    def test_missing_nsc_id_on_broker_instrument_returns_unverified(self):
        """BrokerInstrument without nsc_id -> UNVERIFIED."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument(nsc_id=None)
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)

        result = self.query.get_trading_state("60235881999727383")

        assert result is UNVERIFIED
        self.mock_broker.get_trading_state.assert_not_called()

    def test_empty_nsc_id_on_broker_instrument_returns_unverified(self):
        """BrokerInstrument with empty nsc_id -> UNVERIFIED."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument(nsc_id="")
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)

        result = self.query.get_trading_state("60235881999727383")

        assert result is UNVERIFIED
        self.mock_broker.get_trading_state.assert_not_called()

    # ============================================================
    # Fail-closed: broker failures
    # ============================================================

    def test_broker_raises_trading_state_unavailable_returns_unverified(self):
        """Broker raises TradingStateUnavailable (source failure) -> UNVERIFIED (fail-closed)."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.side_effect = TradingStateUnavailable("source unavailable")

        result = self.query.get_trading_state("60235881999727383")

        assert result is UNVERIFIED
        self.mock_broker.get_trading_state.assert_called_once_with("IRO1TEST0001")

    def test_broker_raises_value_error_propagates(self):
        """Broker raises ValueError (programming error, e.g., empty nsc_id) -> propagates."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.side_effect = ValueError("nsc_id cannot be empty")

        try:
            self.query.get_trading_state("60235881999727383")
        except ValueError as e:
            assert str(e) == "nsc_id cannot be empty"
            return
        assert False, "Expected ValueError to propagate"

    def test_broker_raises_connection_error_propagates(self):
        """Broker raises ConnectionError (not TradingStateUnavailable) -> propagates."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.side_effect = ConnectionError("broker down")

        try:
            self.query.get_trading_state("60235881999727383")
        except ConnectionError as e:
            assert str(e) == "broker down"
            return
        assert False, "Expected ConnectionError to propagate"

    def test_broker_raises_type_error_propagates(self):
        """Broker raises TypeError (programming error) -> propagates."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.side_effect = TypeError("bad arg")

        try:
            self.query.get_trading_state("60235881999727383")
        except TypeError as e:
            assert str(e) == "bad arg"
            return
        assert False, "Expected TypeError to propagate"

    def test_broker_raises_attribute_error_propagates(self):
        """Broker raises AttributeError (programming error) -> propagates."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.side_effect = AttributeError("missing attr")

        try:
            self.query.get_trading_state("60235881999727383")
        except AttributeError as e:
            assert str(e) == "missing attr"
            return
        assert False, "Expected AttributeError to propagate"

    def test_broker_raises_not_implemented_error_propagates(self):
        """Broker raises NotImplementedError (programming error) -> propagates."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.side_effect = NotImplementedError("not implemented")

        try:
            self.query.get_trading_state("60235881999727383")
        except NotImplementedError as e:
            assert str(e) == "not implemented"
            return
        assert False, "Expected NotImplementedError to propagate"

    def test_broker_returns_non_tradingstate_returns_unverified(self):
        """Broker returns non-TradingState -> UNVERIFIED."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.return_value = {"status": "ok"}

        result = self.query.get_trading_state("60235881999727383")

        assert result is UNVERIFIED

    def test_broker_returns_none_returns_unverified(self):
        """Broker returns None -> UNVERIFIED."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.return_value = None

        result = self.query.get_trading_state("60235881999727383")

        assert result is UNVERIFIED

    # ============================================================
    # No execution path invocation
    # ============================================================

    def test_never_calls_orderengine_prepare(self):
        """Query does not invoke OrderEngine.prepare or any execution path."""
        from core.order_engine import OrderEngine

        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.return_value = VERIFIED_TRADABLE

        # Ensure OrderEngine.prepare is never called
        with patch.object(OrderEngine, 'prepare') as mock_prepare:
            self.query.get_trading_state("60235881999727383")
            mock_prepare.assert_not_called()

    def test_never_calls_orderengine_execute_by_ins_code(self):
        """Query does not invoke OrderEngine.execute_by_ins_code."""
        from core.order_engine import OrderEngine

        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.return_value = VERIFIED_TRADABLE

        with patch.object(OrderEngine, 'execute_by_ins_code') as mock_exec:
            self.query.get_trading_state("60235881999727383")
            mock_exec.assert_not_called()

    def test_never_calls_dispatch_core(self):
        """Query does not invoke DispatchCore."""
        from core.dispatch_core import DispatchCore

        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.return_value = VERIFIED_TRADABLE

        with patch.object(DispatchCore, 'dispatch') as mock_dispatch:
            self.query.get_trading_state("60235881999727383")
            mock_dispatch.assert_not_called()

    # ============================================================
    # Contract compliance
    # ============================================================

    def test_returns_tradingstate_instance(self):
        """Return value is always a TradingState instance (or UNVERIFIED)."""
        instrument = self._make_instrument()
        broker_instrument = self._make_broker_instrument()
        self.mock_provider.get_instrument.return_value = (instrument, broker_instrument)
        self.mock_broker.get_trading_state.return_value = VERIFIED_TRADABLE

        result = self.query.get_trading_state("60235881999727383")

        assert isinstance(result, TradingState)

    def test_unverified_has_correct_defaults(self):
        """UNVERIFIED has is_order_entry_allowed=False, is_verified=False."""
        self.mock_provider.get_instrument.side_effect = InstrumentLookupError("fail")

        result = self.query.get_trading_state("60235881999727383")

        assert result is UNVERIFIED
        assert result.is_order_entry_allowed is False
        assert result.is_verified is False
        assert result.source == "unverified"


if __name__ == "__main__":
    test = TestTradingStateQuery()
    test.setup_method()

    tests = [
        test.test_happy_path_returns_verified_tradable,
        test.test_happy_path_returns_verified_blocked,
        test.test_ins_code_passed_to_provider,
        test.test_nsc_id_from_broker_instrument_used,
        test.test_same_nsc_id_passed_to_broker,
        test.test_empty_ins_code_returns_unverified,
        test.test_none_ins_code_returns_unverified,
        test.test_provider_raises_instrument_lookup_error_returns_unverified,
        test.test_provider_raises_generic_exception_propagates,
        test.test_provider_raises_type_error_propagates,
        test.test_provider_raises_attribute_error_propagates,
        test.test_provider_raises_not_implemented_error_propagates,
        test.test_provider_returns_non_tuple_returns_unverified,
        test.test_provider_returns_wrong_tuple_length_returns_unverified,
        test.test_missing_nsc_id_on_broker_instrument_returns_unverified,
        test.test_empty_nsc_id_on_broker_instrument_returns_unverified,
        test.test_broker_raises_trading_state_unavailable_returns_unverified,
        test.test_broker_raises_value_error_propagates,
        test.test_broker_raises_connection_error_propagates,
        test.test_broker_raises_type_error_propagates,
        test.test_broker_raises_attribute_error_propagates,
        test.test_broker_raises_not_implemented_error_propagates,
        test.test_broker_returns_non_tradingstate_returns_unverified,
        test.test_broker_returns_none_returns_unverified,
        test.test_never_calls_orderengine_prepare,
        test.test_never_calls_orderengine_execute_by_ins_code,
        test.test_never_calls_dispatch_core,
        test.test_returns_tradingstate_instance,
        test.test_unverified_has_correct_defaults,
    ]

    passed = 0
    failed = 0

    for t in tests:
        try:
            test.setup_method()
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    print(f"{'='*50}")

    if failed:
        sys.exit(1)