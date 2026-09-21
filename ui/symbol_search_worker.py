"""
ui/symbol_search_worker.py — UI-3.2A background symbol search threads.

Moves the REAL ``SymbolResolver.search()`` / ``SymbolResolver.resolve()``
calls off the GUI thread so the UI never freezes while searching:

    UI (typing, debounced)
        ↓
    SymbolSearchWorker (QThread subclass, run() override)
        ↓
    market.SymbolResolver        (the existing resolver — REUSED, never
        ↓                          copied, never re-implemented)
    existing market/TSETMC infrastructure

The threads are plain ``QThread`` subclasses whose ``run()`` performs the
work and emits the result: when ``run()`` returns the thread finishes by
itself — no event loop, no quit bookkeeping, fully deterministic for
tests.

The UI module itself never imports ``market`` at module level (offline
test contracts preserved); the resolver object is built lazily per run
via the *factory* parameter (production: MainWindow._real_symbol_resolver,
which imports ``market.symbol_resolver`` lazily).

Stale-result protection is explicit and deterministic: every search is
issued with a monotonically increasing sequence number. Only the result
carrying the CURRENT sequence is applied; an older (stale) result is
discarded — "only the latest search result may update the UI".

Boundaries (unchanged from UI-3.1): no new resolver is built, no TSETMC
logic is copied, no ``ins_code`` is guessed, no ``nsc_id`` is produced
and no broker/core component is touched.
"""

from PySide6.QtCore import QThread, Signal


# Debounce window for symbol typing (ms) — the same 300 ms pattern the
# legacy application already uses; no new timing constant is invented.
SYMBOL_SEARCH_DEBOUNCE_MS = 300

# Sequence numbers for search generations start at 1 (0 means "no active
# search" in the page).
FIRST_SEARCH_SEQUENCE = 1


def _default_symbol_resolver():
    """
    Lazily import and build the REAL project resolver.

    This indirection keeps every ``import ui`` and MainWindow/page
    construction fully offline (no ``market``/``requests`` import unless
    a real search is actually about to run), while guaranteeing the UI
    uses the existing repository resolver — never a copy or a re-write.
    """
    from market.symbol_resolver import SymbolResolver

    return SymbolResolver()


class SymbolSearchWorker(QThread):
    """
    Runs ``SymbolResolver.search(text)`` on a background thread.

    ``resolver_factory`` must return the real ``market.SymbolResolver``
    (default: the lazily created repository resolver). Tests pass a stub
    factory here; production code never stubs anything.
    """

    # (sequence, results) — the list of the REAL resolver result dicts,
    # passed as ``object`` so the list (and every dict inside it) travels
    # BY REFERENCE: Qt signal payloads are marshalled/copied for
    # structured types, and result identity must never be copied or
    # rebuilt.
    search_succeeded = Signal(int, object)
    # (sequence, message) — a user-presentable failure message.
    search_failed = Signal(int, str)

    def __init__(self, text, sequence, resolver_factory=None, parent=None):
        super().__init__(parent)
        self.text = text
        self.sequence = sequence
        self._resolver_factory = (
            resolver_factory
            if resolver_factory is not None
            else _default_symbol_resolver
        )

    def run(self):
        """Perform the real search; report success or failure by sequence."""
        try:
            resolver = self._resolver_factory()
            # The real repository resolver — reused, not re-implemented.
            results = resolver.search(self.text)
        except Exception as exc:  # noqa: BLE001 — failure must never crash the UI
            self.search_failed.emit(self.sequence, str(exc))
            return
        self.search_succeeded.emit(self.sequence, list(results or []))


class SymbolResolveWorker(QThread):
    """
    Runs ``SymbolResolver.resolve(result)`` on a background thread for
    one selected search result. On success emits the REAL
    ``models.instrument.Instrument`` produced by the resolver itself.
    """

    resolve_succeeded = Signal(int, object)
    resolve_failed = Signal(int, str)

    def __init__(self, result, sequence, resolver_factory=None, parent=None):
        super().__init__(parent)
        self.result = result
        self.sequence = sequence
        self._resolver_factory = (
            resolver_factory
            if resolver_factory is not None
            else _default_symbol_resolver
        )

    def run(self):
        try:
            resolver = self._resolver_factory()
            # Identity comes from the real search-result object; the
            # resolver produces the real Instrument (no guessing).
            instrument = resolver.resolve(self.result)
        except Exception as exc:  # noqa: BLE001 — failure must never crash the UI
            self.resolve_failed.emit(self.sequence, str(exc))
            return
        self.resolve_succeeded.emit(self.sequence, instrument)


__all__ = [
    "SYMBOL_SEARCH_DEBOUNCE_MS",
    "FIRST_SEARCH_SEQUENCE",
    "_default_symbol_resolver",
    "SymbolSearchWorker",
    "SymbolResolveWorker",
]
