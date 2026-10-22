"""
core/trading_state_query.py — Read-only TradingState query seams.

``TradingStateQuery`` resolves an instrument through an account-owned
broker/provider and is kept for callers that already use that path.

``TsetmcTradingStateQuery`` reads the market status DIRECTLY from TSETMC
using only the TSETMC ``ins_code``. It needs no Account, BrokerManager or
InstrumentProvider, so the UI status display is independent of the active
account and of the order-entry path.

Fail-closed: expected runtime failures return UNVERIFIED (or raise
TradingStateUnavailable for the direct source), and programming errors
propagate.
"""

from typing import TYPE_CHECKING

import requests

from models.trading_state import (
    CETAVAL_ALLOWED,
    CETAVAL_BLOCKED,
    TradingState,
    TradingStateUnavailable,
    UNVERIFIED,
    market_status_from_code,
)
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

class TsetmcTradingStateQuery:
    """
    Read-only TSETMC query keyed by ``Instrument.ins_code``.

    This path deliberately bypasses the active account, BrokerManager,
    InstrumentProvider and broker order path. The returned display fields
    still use the Decision 020 mapping in ``models.trading_state``.
    """

    def __init__(self, client=None):
        self._client = client

    def _make_client(self):
        if self._client is not None:
            return self._client
        from market.tsetmc import TSETMC

        return TSETMC()

    def get_trading_state(self, ins_code: str) -> TradingState:
        if not ins_code:
            return UNVERIFIED

        client = self._make_client()
        try:
            states = client.get_trading_state(ins_code)
        except (requests.RequestException, ConnectionError, TimeoutError) as exc:
            raise TradingStateUnavailable(
                f"Failed to get trading state for ins_code={ins_code}: {exc}"
            ) from exc

        if not isinstance(states, list) or not states:
            return UNVERIFIED

        matching = [
            state
            for state in states
            if isinstance(state, dict)
            and str(state.get("insCode")) == str(ins_code)
        ]
        if not matching:
            return UNVERIFIED

        latest = max(
            matching,
            key=lambda state: (
                state.get("dEven", 0),
                state.get("hEven", 0),
            ),
        )

        c_etaval = latest.get("cEtaval")
        c_etaval = c_etaval.strip() if isinstance(c_etaval, str) else c_etaval

        c_etaval_title = latest.get("cEtavalTitle")
        c_etaval_title = (
            c_etaval_title.strip()
            if isinstance(c_etaval_title, str) and c_etaval_title.strip()
            else None
        )

        market_status = market_status_from_code(c_etaval)
        common = {
            "source": "tsetmc:cEtaval",
            "market_status": market_status,
            "market_status_title": c_etaval_title,
        }

        if c_etaval in CETAVAL_ALLOWED:
            return TradingState(
                is_order_entry_allowed=True,
                is_verified=True,
                reason=f"cEtaval={c_etaval}",
                **common,
            )

        if c_etaval in CETAVAL_BLOCKED:
            return TradingState(
                is_order_entry_allowed=False,
                is_verified=True,
                reason=f"cEtaval={c_etaval}",
                **common,
            )

        return TradingState(
            is_order_entry_allowed=False,
            is_verified=False,
            reason=f"cEtaval ناشناخته: ({c_etaval!r})",
            **common,
        )


__all__ = ["TradingStateQuery", "TsetmcTradingStateQuery"]
