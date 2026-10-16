"""
ui/trading_state_worker.py — UI-3.2B background trading-state query.

Moves the REAL ``core.trading_state_query.TradingStateQuery``
``get_trading_state(ins_code)`` call off the GUI thread so the UI never
freezes while the status is fetched:

    UI (real Instrument selected)
        ↓
    TradingStateWorker (QThread subclass, run() override)
        ↓
    core.trading_state_query.TradingStateQuery      (the EXISTING
        ↓                                            read-only seam —
    provider.get_instrument(ins_code)                reused, never
        ↓                                            re-implemented)
    broker.get_trading_state(nsc_id) → TradingState

No new contract, no new endpoint, no resolver and no Core change is
created here: the query seam, the ``TradingState`` constants and the
raw broker status mapping all stay exactly where the project already
defines them (core/trading_state_query.py, models/trading_state.py,
brokers/agaah/broker.py — Decision 020).

``query_factory`` must return the real ``(broker, provider)`` pair (or a
real ``TradingStateQuery``); production hands in a lazy factory that
builds the real BrokerManager-backed query only when a status is
actually needed, so UI construction stays offline. Tests inject a stub
factory — no network is ever touched.

The thread is a plain ``QThread`` subclass whose ``run()`` performs the
work and emits the result: when ``run()`` returns the thread finishes by
itself — no event loop, fully deterministic for tests.

Fail-closed display contract (unchanged from the project):

    VERIFIED_TRADABLE            → tradable
    VERIFIED_BLOCKED             → not tradable
    UNVERIFIED / unknown state   → unknown
    TradingStateUnavailable      → unknown (never a crash)

Boundaries: no Order creation, no submission, no OrderEngine /
DispatchCore / SafetyGate / BrokerManager call for ordering, and no
raw broker status logic is duplicated in the UI — the page only
renders what the existing path returned.
"""

from PySide6.QtCore import QThread, Signal


def _default_trading_state_query(account_store=None, broker_manager=None,
                                account_id=None, broker_name=None):
    """
    Lazily build the REAL project query seam.

    This indirection keeps every ``import ui`` and page construction
    fully offline (``brokers``/``core`` are imported only when a real
    status query is actually about to run), while guaranteeing the UI
    uses the existing repository path — never a copy or a re-write.

    Built exactly like the real dispatch path does:
        BrokerManager → get_instrument_provider(name) → TradingStateQuery
    """
    from core.trading_state_query import TradingStateQuery

    if account_store is None or broker_manager is None:
        raise ValueError("account-bound runtime is unavailable")
    if account_id is None or broker_name is None:
        raise ValueError("account identity is required")
    record = account_store.get(account_id)
    if record.account_id != account_id or record.broker_name != broker_name:
        raise ValueError("account binding does not match the account store")
    broker = broker_manager.get_for_account(account_id, broker_name)
    provider = broker_manager.get_instrument_provider_for_account(
        account_id, broker_name
    )
    return TradingStateQuery(broker, provider)


class TradingStateWorker(QThread):
    """
    Runs the REAL ``TradingStateQuery.get_trading_state(ins_code)`` on a
    background thread for one resolved Instrument.

    ``query_factory`` must return the real query seam (default: the
    lazily created BrokerManager-backed ``TradingStateQuery``). Tests
    pass a stub factory here; production code never stubs anything.
    """

    # (ins_code, TradingState) — the real state object travels as
    # ``object`` so it is passed BY REFERENCE (Qt signals copy structured
    # payloads; identity must never be copied or rebuilt).
    state_succeeded = Signal(object, str, object)
    # (ins_code, message) — the query itself failed (expected runtime
    # failure, e.g. TradingStateUnavailable escaping the seam). The page
    # renders "unknown"; nothing crashes.
    state_failed = Signal(object, str, str)

    def __init__(self, ins_code, query_factory=None, parent=None, identity=None):
        super().__init__(parent)
        self.ins_code = ins_code
        self.identity = identity
        self._query_factory = (
            query_factory if query_factory is not None
            else _default_trading_state_query
        )

    def run(self):
        try:
            query = self._query_factory()
            # The real repository seam — reused, not re-implemented.
            state = query.get_trading_state(self.ins_code)
        except Exception as exc:  # noqa: BLE001 — failure must never crash the UI
            self.state_failed.emit(self.identity, self.ins_code, str(exc))
            return
        self.state_succeeded.emit(self.identity, self.ins_code, state)


__all__ = [
    "_default_trading_state_query",
    "TradingStateWorker",
]
