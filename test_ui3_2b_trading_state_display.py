"""
test_ui3_2b_trading_state_display.py

UI-3.2B — Trading-state display for the selected symbol (fully offline;
every state query runs through a stub factory and NO network is touched;
no Order is created, submitted or dispatched).

Mandatory contract coverage:

    Test 1  — VERIFIED_TRADABLE  → «قابل معامله».
    Test 2  — VERIFIED_BLOCKED   → a clear NOT-tradable status
              («غیرقابل معامله»).
    Test 3  — UNVERIFIED         → «نامشخص».
    Test 4  — TradingStateUnavailable (and any query failure) → no
              crash and «نامشخص» is shown.
    Test 5  — selecting a second symbol → the first symbol's state does
              not survive.
    Test 6  — changing / clearing the symbol text → the previous
              state is never attributed to the new text.

Extra contracts:

    Extra 1 — the status is rendered ONLY from the real TradingState
              returned by the existing seam: the page never inspects
              cEtaval/cEtavalTitle (source inspection) and never maps
              raw broker fields in the UI.
    Extra 2 — a late state result for a replaced symbol can never
              become the new status (stale-query discard, deterministic).
    Extra 3 — no Order creation / submission / dispatch on the state
              path (OrderEngine/DispatchCore/BrokerManager-for-orders/
              AgaahBroker POST never touched).
    Extra 4 — the worker lifecycle (start → run → signal → cleanup →
              thread finished) leaves no lingering worker on any path.
    Extra 5 — MainWindow wiring: the REAL query seam is injected lazily
              (offline construction preserved) via the existing path
              (BrokerManager → TradingStateQuery).
    Extra 6 — full offline search+select flow: the state label starts
              as unknown/dash before any selection and reads only real
              state after selection.

Run:
    pytest -q test_ui3_2b_trading_state_display.py
"""

import os
import subprocess
import sys
import threading

import pytest

from PySide6.QtWidgets import QApplication

from models.instrument import Instrument
from models.trading_state import (
    UNVERIFIED,
    VERIFIED_BLOCKED,
    VERIFIED_TRADABLE,
    TradingState,
    TradingStateUnavailable,
)

from ui.account_store import AccountStore
from ui.order_configuration_page import (
    STATUS_LABEL_NOT_TRADABLE,
    STATUS_LABEL_TRADABLE,
    STATUS_LABEL_UNKNOWN,
    STATUS_PENDING_LABEL,
    OrderConfigurationPage,
)
from ui.trading_state_worker import TradingStateWorker


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

INSTRUMENT_AKOU = Instrument(
    symbol="آکو",
    name="آکو باتري ايرانيان",
    ins_code="60235881999727383",
    market="بورس",
)
INSTRUMENT_FOLAD = Instrument(
    symbol="فولاد",
    name="فولاد مبارکه اصفهان",
    ins_code="46348559193224090",
    market="بورس",
)

RESULT_AKOU = {
    "symbol": "آکو",
    "name": "آکو باتري ايرانيان",
    "ins_code": "60235881999727383",
    "flow": 0,
    "market": "بورس",
}
RESULT_FOLAD = {
    "symbol": "فولاد",
    "name": "فولاد مبارکه اصفهان",
    "ins_code": "46348559193224090",
    "flow": 0,
    "market": "بورس",
}

STATUS_LABELS = {STATUS_LABEL_TRADABLE, STATUS_LABEL_NOT_TRADABLE, STATUS_LABEL_UNKNOWN}


class StubQuery:
    """
    A stub mimicking the real ``TradingStateQuery`` surface
    (get_trading_state(ins_code)) without any network. The page cannot
    tell it apart from the real seam — that is the point of the seam.
    """

    def __init__(self, state=None, error=None):
        self.state = state
        self.error = error
        self.calls = []

    def get_trading_state(self, ins_code):
        self.calls.append(ins_code)
        if self.error is not None:
            raise self.error
        return self.state


class StubResolver:
    """Mimics the real SymbolResolver surface for search/resolve."""

    def __init__(self, results=None, instrument=None):
        self.results = list(results or [])
        self.instrument = instrument
        self.resolve_calls = []

    def search(self, text):
        return list(self.results)

    def resolve(self, result):
        self.resolve_calls.append(result)
        return self.instrument


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def store():
    return AccountStore()


def _wait_until(predicate, timeout_s=5.0):
    """Bounded deterministic wait for a worker-side side effect."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _drain(qapp, page):
    """
    Process queued signal deliveries, then wait for worker threads.

    A cross-thread signal is only QUEUED while the worker runs (the GUI
    thread is blocked inside ``thread.wait()``), and delivery can lag
    the join by a few event-loop wakeups. The event loop is therefore
    given a fixed set of bounded wakeups first — so queued search
    results and state results are actually delivered — and then, if a
    state query is still pending, it is spun on until the pending
    status label is replaced (or the bounded spin exhausts, in which
    case a test assertion on the label fails loudly rather than hangs).
    """
    import time

    qapp.processEvents()
    page.wait_for_workers(timeout_ms=10000)
    page.wait_for_trading_state_workers(timeout_ms=10000)
    for _ in range(30):  # fixed bounded wakeups for queued deliveries
        qapp.processEvents()
        time.sleep(0.005)
    pending = STATUS_PENDING_LABEL
    for _ in range(150):  # bounded wait for the state verdict
        if page.trading_state_label.text() != pending:
            break
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()  # deliver the finished-cleanup of the last worker


def _finish_debounce(qapp, page):
    """Fire the single-shot debounce timer deterministically."""
    deadline = 200
    while deadline > 0 and page._debounce_timer.isActive():
        qapp.processEvents()
        deadline -= 1
    if page._debounce_timer.isActive():
        page._debounce_timer.stop()
        page._start_symbol_search()
    qapp.processEvents()


def _select_symbol(qapp, page, text="آکو", results=(RESULT_AKOU,),
                   instrument=INSTRUMENT_AKOU):
    """Run the REAL UI-3.2A search+select flow (offline, stubbed)."""
    stub = StubResolver(results=results, instrument=instrument)
    page.set_resolver_factory(lambda: stub)
    page.symbol_input.setCurrentText(text)
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)
    assert page.config.selected_instrument is instrument
    assert _wait_until(
        lambda: page._trading_state_instrument in (instrument.ins_code, None)
    )
    return stub


def _state_text(page):
    return page.trading_state_label.text()


# ============================================================
# Test 1 — VERIFIED_TRADABLE → «قابل معامله»
# ============================================================


def test_1_verified_tradable_shown_as_tradable(qapp, store):
    page = OrderConfigurationPage(store)
    page.set_trading_state_query_factory(lambda: StubQuery(state=VERIFIED_TRADABLE))

    _select_symbol(qapp, page)

    assert _state_text(page) == STATUS_LABEL_TRADABLE
    assert STATUS_LABEL_TRADABLE == "قابل معامله"
    assert STATUS_LABEL_TRADABLE in _state_text(page)


# ============================================================
# Test 2 — VERIFIED_BLOCKED → clear NOT-tradable status
# ============================================================


def test_2_verified_blocked_shown_as_not_tradable(qapp, store):
    page = OrderConfigurationPage(store)
    page.set_trading_state_query_factory(lambda: StubQuery(state=VERIFIED_BLOCKED))

    _select_symbol(qapp, page)

    text = _state_text(page)
    assert text == STATUS_LABEL_NOT_TRADABLE
    assert STATUS_LABEL_NOT_TRADABLE == "غیرقابل معامله"
    # never shown as tradable
    assert "قابل معامله" not in text.replace("غیرقابل معامله", "")


# ============================================================
# Test 3 — UNVERIFIED → «نامشخص»
# ============================================================


def test_3_unverified_shown_as_unknown(qapp, store):
    page = OrderConfigurationPage(store)
    page.set_trading_state_query_factory(lambda: StubQuery(state=UNVERIFIED))

    _select_symbol(qapp, page)

    text = _state_text(page)
    assert text == STATUS_LABEL_UNKNOWN
    assert STATUS_LABEL_UNKNOWN == "نامشخص"
    assert "قابل معامله" not in text


# ============================================================
# Test 4 — TradingStateUnavailable → no crash, «نامشخص»
# ============================================================


def test_4_trading_state_unavailable_shows_unknown_no_crash(qapp, store):
    page = OrderConfigurationPage(store)
    page.set_trading_state_query_factory(
        lambda: StubQuery(error=TradingStateUnavailable("source down"))
    )

    _select_symbol(qapp, page)

    # the UI is alive and shows the unknown status — never a crash
    text = _state_text(page)
    assert text == STATUS_LABEL_UNKNOWN
    assert "قابل معامله" not in text

    # an arbitrary unexpected failure of the same seam behaves the same
    page2 = OrderConfigurationPage(store)
    page2.set_trading_state_query_factory(
        lambda: StubQuery(error=RuntimeError("boom"))
    )
    _select_symbol(qapp, page2)
    assert _state_text(page2) == STATUS_LABEL_UNKNOWN


# ============================================================
# Test 5 — second symbol selection: the first state does not survive
# ============================================================


def test_5_second_selection_replaces_previous_state(qapp, store):
    page = OrderConfigurationPage(store)
    states = {
        INSTRUMENT_AKOU.ins_code: VERIFIED_TRADABLE,
        INSTRUMENT_FOLAD.ins_code: VERIFIED_BLOCKED,
    }

    class DispatchingQuery:
        """Returns the state of whichever ins_code is queried."""

        def __init__(self):
            self.calls = []

        def get_trading_state(self, ins_code):
            self.calls.append(ins_code)
            return states[ins_code]

    query = DispatchingQuery()
    page.set_trading_state_query_factory(lambda: query)

    # 1. select symbol A → its state is displayed
    _select_symbol(qapp, page)
    assert _state_text(page) == STATUS_LABEL_TRADABLE

    # 2. select symbol B through the same real flow → A's state must
    #    not survive
    _select_symbol(
        qapp, page, text="فولاد", results=(RESULT_FOLAD,),
        instrument=INSTRUMENT_FOLAD,
    )
    assert page.config.selected_instrument is INSTRUMENT_FOLAD
    text = _state_text(page)
    assert text == STATUS_LABEL_NOT_TRADABLE
    assert query.calls[-1] == INSTRUMENT_FOLAD.ins_code
    assert INSTRUMENT_AKOU.ins_code not in text


# ============================================================
# Test 6 — changing / clearing the symbol text drops the old state
# ============================================================


def test_6_retyping_or_clearing_drops_previous_state(qapp, store):
    page = OrderConfigurationPage(store)
    page.set_trading_state_query_factory(lambda: StubQuery(state=VERIFIED_TRADABLE))

    _select_symbol(qapp, page)
    assert _state_text(page) == STATUS_LABEL_TRADABLE

    # 6a. typing new text: the old state must not be attributed to it
    page.symbol_input.setCurrentText("فولان")
    _drain(qapp, page)
    assert page.config.selected_instrument is None
    assert _state_text(page) == "—"
    assert "قابل معامله" not in _state_text(page)

    # 6b. a fresh selection rebuilds the state from the real seam
    _select_symbol(qapp, page)
    assert _state_text(page) == STATUS_LABEL_TRADABLE

    # 6c. clearing the input: no state may remain
    page.symbol_input.setCurrentText("")
    _drain(qapp, page)
    assert _state_text(page) == "—"
    assert page.config.selected_instrument is None
    assert "قابل معامله" not in _state_text(page)

    # 6d. whitespace-only input: same contract
    page.symbol_input.setCurrentText("آکو")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)
    assert "قابل معامله" in _state_text(page)
    page.symbol_input.setCurrentText("   ")
    _drain(qapp, page)
    assert _state_text(page) == "—"


# ============================================================
# Extra 1 — the UI renders only the seam's verdict: no raw broker
# status logic in the UI
# ============================================================


def test_extra_no_cetaval_logic_in_ui(qapp, store):
    """
    The status decision stays in the existing project path. The UI
    modules never mention the raw broker status fields (cEtaval /
    cEtavalTitle, checked byte-exact via escaped tokens) and render
    only what the returned TradingState already decided.
    """
    import inspect

    import ui.order_configuration_page as page_mod
    import ui.trading_state_worker as worker_mod

    for mod in (page_mod, worker_mod):
        src = inspect.getsource(mod)
        assert "cEtaval" not in src and "cEtavalTitle" not in src
        assert "CETAVAL" not in src

    # an unknown-source verified state and a custom state both follow
    # the same three-branch contract — nothing extra is invented
    page = OrderConfigurationPage(store)
    assert page._trading_state_text(VERIFIED_TRADABLE) == STATUS_LABEL_TRADABLE
    assert page._trading_state_text(VERIFIED_BLOCKED) == STATUS_LABEL_NOT_TRADABLE
    assert page._trading_state_text(UNVERIFIED) == STATUS_LABEL_UNKNOWN
    assert page._trading_state_text(
        TradingState(is_order_entry_allowed=True, is_verified=False,
                     source="tsetmc:cEtaval")
    ) == STATUS_LABEL_UNKNOWN
    assert page._trading_state_text("not a state") == STATUS_LABEL_UNKNOWN


# ============================================================
# Extra 2 — a late state result for a replaced symbol is discarded
# ============================================================


def test_extra_stale_state_result_never_becomes_new_status(qapp, store):
    """
    Select A → state query for A in flight → user retypes → the late
    result of A must never become the displayed status of the new text.
    """
    release = threading.Event()
    queries = []

    class GatedQuery:
        def get_trading_state(self, ins_code):
            queries.append(ins_code)
            release.wait(timeout=5)
            return VERIFIED_TRADABLE

    page = OrderConfigurationPage(store)
    page.set_trading_state_query_factory(lambda: GatedQuery())

    _select_symbol(qapp, page)
    assert queries == [INSTRUMENT_AKOU.ins_code]
    stale_ins_code = page._trading_state_instrument

    # the user types new text while the query is in flight
    page.symbol_input.setCurrentText("فولان")
    assert _state_text(page) == "—"
    assert page._trading_state_instrument is None  # A is no longer shown

    # the late result arrives — it must be discarded
    release.set()
    page.wait_for_trading_state_workers(timeout_ms=10000)
    qapp.processEvents()

    assert _state_text(page) == "—"
    assert "قابل معامله" not in _state_text(page)
    assert stale_ins_code not in _state_text(page)

    # determinism: same scenario again — identical outcome
    release2 = threading.Event()

    class GatedQuery2(GatedQuery):
        def get_trading_state(self, ins_code):
            queries.append(ins_code)
            release2.wait(timeout=5)
            return VERIFIED_TRADABLE

    page2 = OrderConfigurationPage(store)
    page2.set_trading_state_query_factory(lambda: GatedQuery2())
    _select_symbol(qapp, page2)
    page2.symbol_input.setCurrentText("فولان")
    release2.set()
    page2.wait_for_trading_state_workers(timeout_ms=10000)
    qapp.processEvents()
    assert _state_text(page2) == "—"


# ============================================================
# Extra 3 — the state path never creates/submits/dispatches an Order
# ============================================================


def test_extra_no_order_path_on_state_query(qapp, store):
    page = OrderConfigurationPage(store)
    page.set_trading_state_query_factory(lambda: StubQuery(state=VERIFIED_TRADABLE))

    _select_symbol(qapp, page)
    _drain(qapp, page)

    # no execution attribute exists anywhere on the page
    for attr in (
        "order_engine", "dispatch", "dispatch_core", "submit", "send",
        "broker_manager", "agaah_broker", "session", "place_order",
    ):
        assert not hasattr(page, attr), f"page has forbidden attribute: {attr}"

    # the config stays a pure UI state object: no Order, no payload
    from models.order import Order

    assert not isinstance(page.config, Order)
    assert not hasattr(page.config, "to_order")
    assert not hasattr(page.config, "to_payload")
    assert page.config.final_amount() is None  # no fee/final fabrication


# ============================================================
# Extra 4 — worker lifecycle: no lingering state worker on any path
# ============================================================


def test_extra_trading_state_worker_lifecycle(qapp, store):
    release = threading.Event()

    class BlockingQuery:
        def get_trading_state(self, ins_code):
            release.wait(timeout=5)
            return VERIFIED_TRADABLE

    page = OrderConfigurationPage(store)
    page.set_trading_state_query_factory(lambda: BlockingQuery())

    _select_symbol(qapp, page)

    # while running: exactly one live state worker
    assert page._trading_state_thread is not None
    assert not page._trading_state_thread.isFinished()

    release.set()
    page.wait_for_trading_state_workers(timeout_ms=10000)
    qapp.processEvents()

    # after completion: nothing lingers, and the status IS displayed
    assert page._trading_state_thread is None
    assert page._trading_state_worker is None
    assert _state_text(page) == STATUS_LABEL_TRADABLE

    # the failure path is reaped as well
    page2 = OrderConfigurationPage(store)
    page2.set_trading_state_query_factory(
        lambda: StubQuery(error=TradingStateUnavailable("down"))
    )
    _select_symbol(qapp, page2)
    page2.wait_for_trading_state_workers(timeout_ms=10000)
    qapp.processEvents()
    assert page2._trading_state_thread is None
    assert page2._trading_state_worker is None
    assert _state_text(page2) == STATUS_LABEL_UNKNOWN


# ============================================================
# Extra 5 — MainWindow wires the REAL seam lazily (offline build kept)
# ============================================================


def test_extra_main_window_lazy_real_query_factory(qapp):
    """
    Construction stays fully offline; the real query seam is built only
    when an actual status query runs, through the EXISTING path
    (BrokerManager → broker/provider → TradingStateQuery).
    """
    import subprocess as sp

    code = "\n".join(
        [
            "import sys",
            "import socket",
            "import urllib.request",
            "",
            "class _Boom:",
            "    def __init__(self, *a, **k):",
            "        raise AssertionError('network construct attempted')",
            "    def __getattr__(self, name):",
            "        raise AssertionError(f'network access attempted: {name}')",
            "",
            "socket.create_connection = _Boom",
            "socket.socket = _Boom",
            "socket.getaddrinfo = _Boom",
            "urllib.request.urlopen = _Boom",
            "",
            "import ui.app as ui_app",
            "from ui.main_window import MainWindow",
            "app = ui_app.create_app([])",
            "window = MainWindow()",
            "page = window.order_configuration_page",
            "# the factory is wired and callable, but nothing was built yet",
            "assert page._trading_state_factory is not None",
            "banned = ('brokers', 'market', 'core')",
            "leaked = sorted(m for m in sys.modules if m.split('.')[0] in banned)",
            "assert not leaked, f'UI construction imported trading modules: {leaked}'",
            "assert page.trading_state_label.text() == '\u2014'",
            "# the real factory builds the EXISTING seam",
            "query = window._real_trading_state_query()",
            "from core.trading_state_query import TradingStateQuery",
            "assert isinstance(query, TradingStateQuery)",
            "print('LAZY_QUERY_OK')",
        ]
    )
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "LAZY_QUERY_OK" in result.stdout


# ============================================================
# Extra 6 — full offline flow through the real UI-3.2A selection path
# ============================================================


def test_extra_full_flow_search_select_state_offline():
    """
    End-to-end in a clean subprocess: search → select → state display,
    all offline (sockets exploded), with stub factories only.
    """
    code = "\n".join(
        [
            "import sys",
            "import socket",
            "import time",
            "import urllib.request",
            "",
            "class _Boom:",
            "    def __init__(self, *a, **k):",
            "        raise AssertionError('network construct attempted')",
            "    def __getattr__(self, name):",
            "        raise AssertionError(f'network access attempted: {name}')",
            "",
            "socket.create_connection = _Boom",
            "socket.socket = _Boom",
            "socket.getaddrinfo = _Boom",
            "urllib.request.urlopen = _Boom",
            "",
            "from models.instrument import Instrument",
            "from models.trading_state import VERIFIED_TRADABLE",
            "from ui.account_store import AccountStore",
            "from ui.order_configuration_page import OrderConfigurationPage",
            "from PySide6.QtWidgets import QApplication",
            "",
            "app = QApplication([])",
            "store = AccountStore()",
            "page = OrderConfigurationPage(store)",
            "",
            "instrument = Instrument(symbol='آکو', name='آکو باتري ايرانيان',",
            "                        ins_code='60235881999727383', market='بورس')",
            "",
            "class _Resolver:",
            "    def search(self, text):",
            "        return [{'symbol': 'آکو', 'name': 'آکو باتري ايرانيان',",
            "                 'ins_code': '60235881999727383', 'flow': 0,",
            "                 'market': 'بورس'}]",
            "    def resolve(self, result):",
            "        return instrument",
            "",
            "class _Query:",
            "    def get_trading_state(self, ins_code):",
            "        assert ins_code == '60235881999727383'",
            "        return VERIFIED_TRADABLE",
            "",
            "page.set_resolver_factory(lambda: _Resolver())",
            "page.set_trading_state_query_factory(lambda: _Query())",
            "",
            "page.symbol_input.setCurrentText('آکو')",
            "page._debounce_timer.stop()",
            "page._start_symbol_search()",
            "page.wait_for_workers(10000)",
            "app.processEvents()",
            "page._on_result_selected(page.results_list.item(0))",
            "page.wait_for_workers(10000)",
            "page.wait_for_trading_state_workers(10000)",
            "for _ in range(30):",
            "    app.processEvents()",
            "    time.sleep(0.01)",
            "",
            "assert page.config.selected_instrument is instrument",
            "assert page.trading_state_label.text() == 'قابل معامله'",
            "print('FULL_FLOW_OK')",
        ]
    )
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "FULL_FLOW_OK" in result.stdout
