"""
core/trading_state_query.py — Read-only TradingState query seam.

Provides a minimal, read-only path to fetch TradingState for a given
TSETMC ins_code without requiring an Order, Account, or execution context.

Call chain:
    ins_code
        -> InstrumentProvider.get_instrument(ins_code)
        -> BrokerInstrument.nsc_id
        -> Broker.get_trading_state(nsc_id)
        -> TradingState

Fail-closed: expected runtime failures (InstrumentLookupError, TradingStateUnavailable) return UNVERIFIED.
Programming errors (TypeError, AttributeError, NotImplementedError, ValueError, etc.) propagate.
"""

from typing import TYPE_CHECKING

from models.trading_state import TradingState, TradingStateUnavailable, UNVERIFIED
from brokers.base import InstrumentLookupError

if TYPE_CHECKING:
    from brokers.base import InstrumentProvider
    from brokers.base import Broker
    from models.broker_instrument import BrokerInstrument
    from models.instrument import Instrument


class TradingStateQuery:
    """
    Read-only query for TradingState by ins_code.

    Uses existing InstrumentProvider and Broker contracts.
    No Order, Account, capacity checks, validation, or execution path.
    """

    def __init__(
        self,
        broker: "Broker",
        provider: "InstrumentProvider",
    ):
        """
        Args:
            broker: Broker instance implementing get_trading_state(nsc_id)
            provider: InstrumentProvider instance implementing get_instrument(ins_code)
        """
        self._broker = broker
        self._provider = provider

    def get_trading_state(self, ins_code: str) -> TradingState:
        """
        Fetch TradingState for the given TSETMC ins_code.

        Args:
            ins_code: TSETMC instrument code (e.g., "60235881999727383")

        Returns:
            TradingState: VERIFIED_TRADABLE, VERIFIED_BLOCKED, or UNVERIFIED.
            Expected runtime failures -> UNVERIFIED (fail-closed).
            Programming errors -> propagate (fail-loud).
        """
        if not ins_code:
            return UNVERIFIED

        # Step 1: Resolve (Instrument, BrokerInstrument) via provider
        # Contract: provider raises InstrumentLookupError for expected failures
        # (network, not found, no match, etc.). All other exceptions = bugs.
        try:
            resolution = self._provider.get_instrument(ins_code)
        except InstrumentLookupError:
            return UNVERIFIED

        # Validate resolution structure
        if not isinstance(resolution, tuple) or len(resolution) != 2:
            return UNVERIFIED

        instrument, broker_instrument = resolution

        # Step 2: Extract nsc_id from BrokerInstrument
        nsc_id = getattr(broker_instrument, "nsc_id", None)
        if not nsc_id:
            return UNVERIFIED

        # Step 3: Query broker for trading state
        # Contract: broker raises TradingStateUnavailable for source
        # failures (network, TSETMC, etc.). Programming errors
        # (ValueError for empty nsc_id, TypeError, etc.) propagate.
        try:
            state = self._broker.get_trading_state(nsc_id)
        except TradingStateUnavailable:
            return UNVERIFIED

        # Step 4: Validate returned state
        if not isinstance(state, TradingState):
            return UNVERIFIED

        return state