"""
test_ui3_2a_symbol_search.py

UI-3.2A Symbol Search & Instrument Selection tests (fully offline —
network is always stubbed; the REAL SymbolResolver seam is verified with
spy factories, never by hitting TSETMC).

Contract coverage:

    Test 1  — the Symbol input exists.
    Test 2  — typing (after debounce) triggers a real search.
    Test 3  — empty input never searches.
    Test 4  — whitespace-only input never searches.
    Test 5  — the search really goes through SymbolResolver.search()
              (called on the injected factory's resolver object).
    Test 6  — real results are displayed as SYMBOL — NAME.
    Test 7  — result identity is kept in item data (Qt.UserRole), never
              re-parsed from the display text.
    Test 8  — selecting a result calls SymbolResolver.resolve().
    Test 9  — the real Instrument lands in selected_instrument.
    Test 10 — a fake instrument can never be stored.
    Test 11 — on success, Symbol/Name come from the real Instrument.
    Test 12 — new typing never masquerades as the previous selection.
    Test 13 — a stale (older-sequence) result cannot overwrite the
              newer result (mandatory deterministic race scenario:
              A starts, B starts, B finishes first, A finishes later).
    Test 14 — search failure does not crash the UI.
    Test 15 — resolve failure stores nothing fabricated.
    Test 16 — the no-results state is shown explicitly.
    Test 17 — no real network is touched (socket silence, clean
              subprocess with a stub resolver injected).
    Test 18 — TSETMC trading-state is never called in this task.
    Test 19 — no BrokerManager/Broker/API object is created.
    Test 20 — no nsc_id is created or stored.
    Test 21 — no Order object is created.
    Test 22 — the active account still comes from the existing UI-2.1
              AccountStore (no fallback).
    Test 23 — prior contracts stay green (navigation/pages/mode,
              placeholders, legacy main.py isolation, AST seam check).

Run:
    pytest -q test_ui3_2a_symbol_search.py
"""

import os
import subprocess
import sys

import pytest

from PySide6.QtWidgets import QApplication

from models.instrument import Instrument

from ui.account_store import AccountStore
from ui.main_window import MainWindow
from ui.order_configuration_page import (
    RESULT_DATA_ROLE,
    RESULT_SEQUENCE_ROLE,
    SEARCH_STATE_NO_RESULTS,
    SEARCH_STATE_SEARCHING,
    OrderConfigurationPage,
)
from ui.symbol_search_worker import (
    SYMBOL_SEARCH_DEBOUNCE_MS,
    SymbolSearchWorker,
    SymbolResolveWorker,
)


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

# Deterministic fake resolver results — shaped EXACTLY like the real
# SymbolResolver.search() output (symbol/name/ins_code/flow/market).
RESULT_AKOU = {
    "symbol": "آکو",
    "name": "آکو باتري ايرانيان",
    "ins_code": "60235881999727383",
    "flow": 0,
    "market": "بورس",
}
RESULT_FOLAN = {
    "symbol": "فولاد",
    "name": "فولاد مبارکه اصفهان",
    "ins_code": "46348559193224090",
    "flow": 0,
    "market": "بورس",
}
RESULTS_AK = [RESULT_AKOU, RESULT_FOLAN]

INSTRUMENT_AKOU = Instrument(
    symbol="آکو",
    name="آکو باتري ايرانيان",
    ins_code="60235881999727383",
    market="بورس",
)


class StubResolver:
    """
    A stub that mimics the real SymbolResolver's surface (search /
    resolve) without any network. The page/pipeline code cannot tell it
    apart from the real resolver — that is the point of the seam.
    """

    def __init__(self, search_results=None, resolve_result=None,
                 search_error=None, resolve_error=None):
        self.search_results = (
            list(search_results) if search_results is not None else []
        )
        self.resolve_result = resolve_result
        self.search_error = search_error
        self.resolve_error = resolve_error
        self.search_calls = []
        self.resolve_calls = []

    def search(self, text):
        self.search_calls.append(text)
        if self.search_error is not None:
            raise self.search_error
        return list(self.search_results)

    def resolve(self, result):
        self.resolve_calls.append(result)
        if self.resolve_error is not None:
            raise self.resolve_error
        return self.resolve_result


@pytest.fixture(scope="module")
def qapp():
    """Reuse the process-wide QApplication if one exists, else create one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def store():
    return AccountStore()


def _page_with_resolver(store, **stub_kwargs):
    """Build a page whose searches run through a StubResolver."""
    page = OrderConfigurationPage(store)
    stub = StubResolver(**stub_kwargs)
    page.set_resolver_factory(lambda: stub)
    return page, stub


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
    """Process queued signal deliveries, then wait for worker threads."""
    qapp.processEvents()
    page.wait_for_workers(timeout_ms=10000)
    qapp.processEvents()


def _finish_debounce(qapp, page):
    """Fire the single-shot debounce timer deterministically."""
    deadline = 200  # 200 * 10ms = 2s worst case; the timer is 300ms
    while deadline > 0 and page._debounce_timer.isActive():
        qapp.processEvents()
        page._debounce_timer.start  # no-op attribute touch keeps linters calm
        page._debounce_timer.remainingTime()  # advances on processEvents only
        deadline -= 1
    # Single-shot QTimer with no running event loop fires on processEvents;
    # ensure it fired exactly once now.
    if page._debounce_timer.isActive():
        # Force-expire deterministically (no real sleeping):
        page._debounce_timer.stop()
        page._start_symbol_search()
    qapp.processEvents()


# ============================================================
# Test 1 — the Symbol input exists
# ============================================================


def test_1_symbol_input_exists(qapp, store):
    page = OrderConfigurationPage(store)

    assert page.symbol_input is not None
    assert page.symbol_input.isEditable()
    assert page.results_list is not None
    assert page.search_status_label is not None


# ============================================================
# Test 2 — typing (after debounce) triggers a real search
# ============================================================


def test_2_typing_triggers_debounced_search(qapp, store):
    page, stub = _page_with_resolver(store, search_results=RESULTS_AK)

    page.symbol_input.setCurrentText("آکو")
    _finish_debounce(qapp, page)
    _drain(qapp, page)

    assert stub.search_calls == ["آکو"]
    assert page.results_list.count() == len(RESULTS_AK)


# ============================================================
# Test 3 — empty input never searches
# ============================================================


def test_3_empty_input_never_searches(qapp, store):
    page, stub = _page_with_resolver(store, search_results=RESULTS_AK)

    page.symbol_input.setCurrentText("")
    _finish_debounce(qapp, page)
    _drain(qapp, page)

    assert stub.search_calls == []
    assert page.results_list.count() == 0
    # clearing the input clears previous results
    assert page.search_status_label.text() == ""


# ============================================================
# Test 4 — whitespace-only input never searches
# ============================================================


def test_4_whitespace_only_never_searches(qapp, store):
    page, stub = _page_with_resolver(store, search_results=RESULTS_AK)

    page.symbol_input.setCurrentText("   ")
    _finish_debounce(qapp, page)
    _drain(qapp, page)

    assert stub.search_calls == []
    assert page.results_list.count() == 0


# ============================================================
# Test 5 — search really goes through SymbolResolver.search()
# ============================================================


def test_5_search_uses_real_resolver_seam(qapp, store):
    page, stub = _page_with_resolver(store, search_results=RESULTS_AK)

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)

    # the call happened on the resolver object handed to the worker —
    # the real SymbolResolver API (search), not a UI-local copy
    assert len(stub.search_calls) == 1
    assert stub.search_calls[0] == "آک"
    # rapid typing → only the latest input is searched
    page.symbol_input.setCurrentText("آکو")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    assert stub.search_calls == ["آک", "آکو"]


# ============================================================
# Test 6 — real results shown as SYMBOL — NAME
# ============================================================


def test_6_results_displayed_symbol_dash_name(qapp, store):
    page, _ = _page_with_resolver(store, search_results=RESULTS_AK)

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)

    texts = [
        page.results_list.item(i).text()
        for i in range(page.results_list.count())
    ]
    assert texts[0].startswith("آکو")
    assert "آکو باتري ايرانيان" in texts[0]
    assert " \u2014 " in texts[0]  # SYMBOL — NAME separator
    assert texts[1].startswith("فولاد")


# ============================================================
# Test 7 — identity kept in item data, never re-parsed from display
# ============================================================


def test_7_identity_stored_in_item_data_not_parsed(qapp, store):
    page, _ = _page_with_resolver(store, search_results=RESULTS_AK)

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)

    item = page.results_list.item(0)
    # the item stores the index into the page's shared list of REAL
    # resolver results (Qt signals marshall payloads, so the object
    # itself must not travel through a signal)
    assert item.data(RESULT_DATA_ROLE) == 0
    stored = page._latest_results[item.data(RESULT_DATA_ROLE)]
    assert stored is RESULTS_AK[0]
    assert stored["ins_code"] == "60235881999727383"
    assert page._latest_results[1] is RESULTS_AK[1]

    # the display text is NOT the source of identity: splitting it can
    # never reconstruct a result (the page has no split-based parser)
    import inspect

    import ui.order_configuration_page as mod

    assert 'split("' not in inspect.getsource(mod)
    assert "split('" not in inspect.getsource(mod)


# ============================================================
# Test 8 — selecting a result calls SymbolResolver.resolve()
# ============================================================


def test_8_selection_calls_resolver_resolve(qapp, store):
    page, stub = _page_with_resolver(
        store, search_results=RESULTS_AK, resolve_result=INSTRUMENT_AKOU
    )

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)

    page.results_list.item(0).setSelected(True)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)

    assert len(stub.resolve_calls) == 1
    # the EXACT real result object (identity preserved via the shared
    # list — never a copy rebuilt from display text)
    assert stub.resolve_calls[0] is RESULTS_AK[0]


# ============================================================
# Test 9 — the real Instrument lands in selected_instrument
# ============================================================


def test_9_real_instrument_stored(qapp, store):
    page, _ = _page_with_resolver(
        store, search_results=RESULTS_AK, resolve_result=INSTRUMENT_AKOU
    )

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)

    assert page.config.selected_instrument is INSTRUMENT_AKOU
    from models.instrument import Instrument as RealInstrument

    assert isinstance(page.config.selected_instrument, RealInstrument)


# ============================================================
# Test 10 — a fake instrument can never be stored
# ============================================================


def test_10_fake_instrument_never_stored(qapp, store):
    class FakeInstrument:
        ins_code = "FAKE"

    page, _ = _page_with_resolver(
        store, search_results=RESULTS_AK, resolve_result=FakeInstrument()
    )

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)

    # fail-closed: the fake object never became the selection
    assert page.config.selected_instrument is None
    assert "Resolve failed" in page.search_status_label.text()


# ============================================================
# Test 11 — Symbol/Name displayed from the real Instrument
# ============================================================


def test_11_selected_instrument_display_from_real_object(qapp, store):
    page, _ = _page_with_resolver(
        store, search_results=RESULTS_AK, resolve_result=INSTRUMENT_AKOU
    )

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)

    text = page.symbol_name_label.text()
    assert "آکو" in text
    assert "آکو باتري ايرانيان" in text
    assert "بورس" in text  # market, from the model


# ============================================================
# Test 12 — new typing never masquerades as the previous selection
# ============================================================


def test_12_new_typing_drops_previous_selection(qapp, store):
    page, stub = _page_with_resolver(
        store, search_results=RESULTS_AK, resolve_result=INSTRUMENT_AKOU
    )

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)
    assert page.config.selected_instrument is INSTRUMENT_AKOU

    # the user types something new → the old selection must not be
    # attributed to the new text
    page.symbol_input.setCurrentText("فول")
    assert page.config.selected_instrument is None
    assert page.symbol_text == "فول"


# ============================================================
# Test 13 — stale result can NEVER overwrite the newer result
# (mandatory deterministic race: A starts, B starts, B finishes first,
#  A finishes later)
# ============================================================


def test_13_stale_result_discarded(qapp, store):
    page = OrderConfigurationPage(store)
    stub = StubResolver(search_results=RESULTS_AK)
    page.set_resolver_factory(lambda: stub)

    # Search A starts
    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    qapp.processEvents()
    page.wait_for_workers(timeout_ms=10000)
    qapp.processEvents()
    sequence_a = page._search_sequence

    # Search B starts (newer generation)
    page.symbol_input.setCurrentText("آکو")
    _finish_debounce(qapp, page)
    qapp.processEvents()
    page.wait_for_workers(timeout_ms=10000)
    qapp.processEvents()
    sequence_b = page._search_sequence
    # with the typing-bump guard every keystroke advances the
    # generation, so B only needs to be NEWER than A
    assert sequence_b > sequence_a

    # B's result is displayed: the exact real resolver objects
    displayed = list(page._latest_results)
    assert displayed == RESULTS_AK

    # A finishes LATER — its result must not replace B's
    stale_results = [{"symbol": "قدیمی", "name": "old", "ins_code": "0",
                      "flow": 0, "market": ""}]
    page._on_search_succeeded(sequence_a, stale_results)

    displayed = list(page._latest_results)
    assert displayed == RESULTS_AK  # B still shown; A discarded
    assert all(d["symbol"] != "قدیمی" for d in displayed)

    # deterministic: the sequence mechanism is a plain generation counter
    worker = SymbolSearchWorker("x", 1, resolver_factory=lambda: stub)
    assert worker.sequence == 1
    page._on_search_succeeded(page._search_sequence + 1, [])
    # an unknown-future sequence also never corrupts the current state
    assert page.results_list.count() == len(RESULTS_AK)


# ============================================================
# Test 14 — search failure does not crash the UI
# ============================================================


def test_14_search_failure_handled(qapp, store):
    page, stub = _page_with_resolver(
        store, search_error=RuntimeError("network down")
    )

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)

    # still alive, no crash, explicit user-facing message, no fake data
    assert page.results_list.count() == 0
    assert "Search failed" in page.search_status_label.text()

    # a LATER generation's failure must not clobber a newer state either
    page._on_search_failed(page._search_sequence - 1, "old boom")
    assert "Search failed" in page.search_status_label.text()


# ============================================================
# Test 15 — resolve failure stores nothing fabricated
# ============================================================


def test_15_resolve_failure_keeps_previous_selection(qapp, store):
    page, stub = _page_with_resolver(
        store, search_results=RESULTS_AK, resolve_error=RuntimeError("boom")
    )

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)

    assert page.config.selected_instrument is None
    assert "Resolve failed" in page.search_status_label.text()
    # no ins_code was guessed anywhere
    assert not hasattr(page.config, "nsc_id")


# ============================================================
# Test 16 — no-results state is shown explicitly
# ============================================================


def test_16_no_results_state(qapp, store):
    page, _ = _page_with_resolver(store, search_results=[])

    page.symbol_input.setCurrentText("ناموجود")
    _finish_debounce(qapp, page)
    _drain(qapp, page)

    assert page.results_list.count() == 0
    assert page.search_status_label.text() == SEARCH_STATE_NO_RESULTS == (
        "No symbols found"
    )
    assert page.config.selected_instrument is None


# ============================================================
# Test 17 — no real network (clean subprocess, stub injected)
# ============================================================


def test_17_no_real_network_in_tests_or_page():
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
            "from ui.account_store import AccountStore",
            "from ui.order_configuration_page import OrderConfigurationPage",
            "",
            "app = ui_app.create_app([])",
            "store = AccountStore()",
            "page = OrderConfigurationPage(store)",
            "",
            "class _Stub:",
            "    def search(self, text):",
            "        return [{'symbol': 'آکو', 'name': 'آکو باتري ايرانيان',",
            "                 'ins_code': '60235881999727383', 'flow': 0,",
            "                 'market': 'بورس'}]",
            "    def resolve(self, result):",
            "        from models.instrument import Instrument",
            "        return Instrument(symbol=result['symbol'],",
            "                          name=result['name'],",
            "                          ins_code=result['ins_code'])",
            "",
            # The instrument selection below also triggers the UI-3.2B
            # trading-state display path. TradingState is NOT what this
            # test is about — inject the page's EXISTING stub seam so the
            # selection starts a stub-backed TradingStateWorker (pure
            # in-memory, no Broker seam) instead of the real one. The
            # thread is still joined before the process exits, so shutdown
            # stays clean (0xC0000409 came from a live worker at exit).
            "class _StubQuery:",
            "    def get_trading_state(self, ins_code):",
            "        from models.trading_state import TradingStateUnavailable",
            "        raise TradingStateUnavailable('not part of test 17')",
            "",
            "page.set_resolver_factory(lambda: _Stub())",
            "page.set_trading_state_query_factory(lambda: _StubQuery())",
            "page.symbol_input.setCurrentText('آکو')",
            "page._debounce_timer.stop()",
            "page._start_symbol_search()",
            "page.wait_for_workers(10000)",
            "app.processEvents()",
            "assert page.results_list.count() == 1",
            "page._on_result_selected(page.results_list.item(0))",
            "page.wait_for_workers(10000)",
            # Join the stub-backed trading-state thread before exit so
            # the child never tears down a live QThread at shutdown.
            "page.wait_for_trading_state_workers(10000)",
            "app.processEvents()",
            "assert page.config.selected_instrument is not None",
            "assert page.config.selected_instrument.symbol == 'آکو'",
            # Deterministic Qt teardown BEFORE interpreter exit: finished
            # workers' deleteLater is processed and the page/app C++
            # objects are destroyed explicitly, so finalization never has
            # to destroy live/pending Qt objects (that race was the
            # source of the flaky 0xC0000409 at child shutdown).
            "page.deleteLater()",
            "app.processEvents()",
            "del page",
            "app.quit()",
            "del app",
            "import gc",
            "gc.collect()",
            "print('NO_NETWORK_OK')",
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
    assert "NO_NETWORK_OK" in result.stdout


# ============================================================
# Test 18 — TSETMC trading state is never called in this task
# ============================================================


def test_18_tsetmc_trading_state_never_called(qapp, store):
    page, _ = _page_with_resolver(
        store, search_results=RESULTS_AK, resolve_result=INSTRUMENT_AKOU
    )

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)

    # full search + selection flow done; status still fail-closed
    assert page.config.symbol_status() == "Not available"
    assert "Status: Not available" in page.symbol_status_label.text()
    assert "tradable" not in page.symbol_status_label.text().lower()
    # The UI never touches TSETMC itself: no import of market.tsetmc,
    # no code reference to it, and no mapping of the raw TSETMC fields
    # (cEtaval / cEtavalTitle). The ONLY trading-state path the page may
    # use is the EXISTING read-only TradingStateQuery seam via
    # TradingStateWorker (UI-3.2B) — so consuming TradingState /
    # TradingStateWorker / TradingStateQuery / get_trading_state is
    # allowed; the boundary tested here is ONLY direct TSETMC access
    # and direct raw-field mapping. The seam contract itself is
    # asserted in test_ui3_2b_trading_state_display.py.
    import ast
    import inspect

    import ui.order_configuration_page as mod

    src = inspect.getsource(mod)
    tree = ast.parse(src)

    # Docstrings are documentation (they legitimately describe the
    # boundary) — they are excluded; every real CODE reference counts.
    docstring_values = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstring_values.add(id(first.value))

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [
                f"import {alias.name}"
                for alias in node.names
                if "tsetmc" in alias.name.lower()
            ]
        elif isinstance(node, ast.ImportFrom):
            if "tsetmc" in (node.module or "").lower():
                offenders.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Attribute) and "tsetmc" in node.attr.lower():
            offenders.append(f"attribute .{node.attr}")
        elif isinstance(node, ast.Name) and "tsetmc" in node.id.lower():
            offenders.append(f"name {node.id}")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_values
            and "tsetmc" in node.value.lower()
        ):
            offenders.append(f"string {node.value!r}")

    assert not offenders, (
        "ui.order_configuration_page touches TSETMC directly: "
        + ", ".join(offenders)
    )

    # The raw TSETMC field mapping never leaks into the UI — the verdict
    # comes from the seam's TradingState, never from the broker's raw
    # payload fields.
    assert "cEtaval" not in src
    assert "cEtavalTitle" not in src


# ============================================================
# Test 19 — no BrokerManager/Broker/API object is created
# ============================================================


def test_19_no_broker_objects_created(qapp, store):
    page, _ = _page_with_resolver(store, search_results=RESULTS_AK)

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)

    for attr in (
        "broker_manager",
        "broker",
        "agaah_broker",
        "instrument_provider",
        "order_engine",
        "dispatch",
        "session",
        "token",
    ):
        assert not hasattr(page, attr), f"page has forbidden attribute: {attr}"


# ============================================================
# Test 20 — no nsc_id is created or stored
# ============================================================


def test_20_no_nsc_id_created(qapp, store):
    page, _ = _page_with_resolver(
        store, search_results=RESULTS_AK, resolve_result=INSTRUMENT_AKOU
    )

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)

    config = page.config
    assert not hasattr(config, "nsc_id")
    assert "nsc_id" not in vars(config)
    # the resolve worker never fabricates identity — resolve receives
    # the resolver's own result object
    worker = SymbolResolveWorker(RESULT_AKOU, 1)
    assert worker.result is RESULT_AKOU


# ============================================================
# Test 21 — no Order object is created
# ============================================================


def test_21_no_order_created(qapp, store):
    from models.order import Order

    page, _ = _page_with_resolver(
        store, search_results=RESULTS_AK, resolve_result=INSTRUMENT_AKOU
    )

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)

    assert not isinstance(page.config, Order)
    assert not hasattr(page, "to_order")
    assert not hasattr(page, "submit")


# ============================================================
# Test 22 — active account still comes from the UI-2.1 AccountStore
# ============================================================


def test_22_active_account_from_existing_store(qapp):
    window = MainWindow()

    assert window.order_configuration_page.store is window.account_store
    assert window.accounts_page.store is window.account_store

    window.account_store.add("ACC-001", "آگاه")
    # no fallback: without explicit activation nothing is shown
    window.order_configuration_page.refresh_active_account()
    assert "No active account" in (
        window.order_configuration_page.active_account_label.text()
    )

    window.account_store.set_active("ACC-001")
    window.order_configuration_page.refresh_active_account()
    assert "ACC-001" in (
        window.order_configuration_page.active_account_label.text()
    )


# ============================================================
# Test 23 — prior contracts stay green (structure + AST seam)
# ============================================================


def test_23_prior_ui_contracts_preserved(qapp):
    window = MainWindow()

    # UI-1/UI-2.1/UI-3.1 navigation and placeholders intact
    assert set(window.pages) == {
        "Home", "Accounts", "Order Configuration", "Settings",
    }
    assert set(window.placeholder_pages) == {"Home", "Settings"}
    from ui.main_window import ApplicationMode

    assert window.mode is ApplicationMode.NORMAL
    window.set_mode(ApplicationMode.DIAGNOSTIC)
    assert window.mode is ApplicationMode.DIAGNOSTIC

    # UI-3.1 amounts/status contracts intact on this page
    page = window.order_configuration_page
    assert page.fee_label.text() == "Not available"
    assert page.final_amount_label.text() == "Not available"
    assert "Status: Not available" in page.symbol_status_label.text()

    # the MainWindow seam is the only market import path: a lazy factory
    import ui.main_window as mw

    assert callable(mw.MainWindow._real_symbol_resolver)


# ============================================================
# Extra — debounce constant matches the legacy 300 ms pattern
# ============================================================


def test_extra_debounce_constant_matches_legacy_pattern():
    assert SYMBOL_SEARCH_DEBOUNCE_MS == 300


# ============================================================
# Extra — full worker lifecycle: start → run → signal → cleanup →
# thread finished; no worker/thread lingers on ANY path
# ============================================================


def test_extra_worker_lifecycle_no_leftovers_on_any_path(qapp, store):
    """
    The complete lifecycle for both search and resolve workers:

        start → run() → signal → cleanup → thread finished

    and after completion the page holds NO live worker/thread — on the
    success path, the resolve path AND the failure path.
    """
    import threading

    release = threading.Event()

    class BlockingResolver:
        """search() blocks until released — lets us observe the LIVE set."""

        def search(self, text):
            # bounded so a broken test can never hang forever
            release.wait(timeout=5)
            return [dict(RESULT_AKOU)]

        def resolve(self, result):
            return INSTRUMENT_AKOU

    page = OrderConfigurationPage(store)
    page.set_resolver_factory(lambda: BlockingResolver())

    # ---- search worker: alive while running, gone after finish ----
    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    qapp.processEvents()

    assert page._search_thread is not None
    assert page._search_worker is not None
    assert len(page._active_search_threads) == 1  # the live worker
    assert not page._search_thread.isFinished()

    release.set()
    page.wait_for_workers(timeout_ms=10000)  # run() returned → finished
    qapp.processEvents()  # deliver the finished-signal cleanup

    assert page._search_thread is None
    assert page._search_worker is None
    assert page._active_search_threads == []  # nothing lingers
    assert page.results_list.count() == 1

    # ---- resolve worker: same lifecycle ----
    page._on_result_selected(page.results_list.item(0))
    qapp.processEvents()

    assert page._resolve_thread is not None
    assert page._resolve_worker is not None
    assert len(page._active_search_threads) == 1

    page.wait_for_workers(timeout_ms=10000)
    qapp.processEvents()

    assert page._resolve_thread is None
    assert page._resolve_worker is None
    assert page._active_search_threads == []  # nothing lingers
    assert page.config.selected_instrument is INSTRUMENT_AKOU


def test_extra_worker_lifecycle_cleanup_on_failure_path(qapp, store):
    """A failing worker is also fully reaped (no lingering thread)."""
    page, _ = _page_with_resolver(
        store, search_results=RESULTS_AK, resolve_error=RuntimeError("boom")
    )

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    assert page._active_search_threads == []  # search worker reaped

    page._on_result_selected(page.results_list.item(0))
    _drain(qapp, page)

    assert page._resolve_thread is None
    assert page._resolve_worker is None
    assert page._active_search_threads == []  # resolve worker reaped
    assert "Resolve failed" in page.search_status_label.text()


# ============================================================
# Extra — resolve stale-result race (mandatory scenario):
# Search A → select result A (resolve A starts) → user types B →
# selection cleared → resolve A returns LATE → must NOT re-set the
# selection.
# ============================================================


def test_extra_stale_resolve_race_never_restores_selection(qapp, store):
    """
    Search A
      → pick result A → resolve A starts
      → user types new text B → previous selection cleared, generation
        bumped
      → resolve A returns LATE
    → the late resolve may NOT set selected_instrument again.
    """
    import threading

    release_resolve = threading.Event()

    class GatedResolver:
        """search returns instantly; resolve blocks until released."""

        def __init__(self):
            self.resolve_calls = []

        def search(self, text):
            return [dict(RESULT_AKOU)]

        def resolve(self, result):
            self.resolve_calls.append(result)
            release_resolve.wait(timeout=5)
            return INSTRUMENT_AKOU

    resolver = GatedResolver()
    page = OrderConfigurationPage(store)
    page.set_resolver_factory(lambda: resolver)

    # 1. Search A (instant)
    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    assert page.results_list.count() == 1

    # 2. Select result A → resolve A starts and BLOCKS
    page._on_result_selected(page.results_list.item(0))
    qapp.processEvents()
    assert _wait_until(lambda: len(resolver.resolve_calls) == 1)
    resolve_sequence = page._search_sequence

    # 3. The user types new text B while resolve A is in flight:
    #    selection cleared AND generation bumped immediately.
    page.symbol_input.setCurrentText("فولان")
    assert page.config.selected_instrument is None  # cleared on typing
    assert page._search_sequence > resolve_sequence  # A is now stale

    # 4. resolve A returns LATE
    release_resolve.set()
    page.wait_for_workers(timeout_ms=10000)
    qapp.processEvents()

    # 5. The late resolve must NOT (re)set the selection
    assert page.config.selected_instrument is None
    assert page.symbol_text == "فولان"
    # and the late worker is fully reaped too
    assert page._active_search_threads == []
    assert page._resolve_thread is None

    # Determinism: run the same scenario again — identical outcome.
    release_resolve.clear()
    resolver2 = GatedResolver()
    page2 = OrderConfigurationPage(store)
    page2.set_resolver_factory(lambda: resolver2)

    page2.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page2)
    _drain(qapp, page2)
    page2._on_result_selected(page2.results_list.item(0))
    qapp.processEvents()
    page2.symbol_input.setCurrentText("فولان")
    release_resolve.set()
    page2.wait_for_workers(timeout_ms=10000)
    qapp.processEvents()

    assert page2.config.selected_instrument is None
    assert page2.symbol_text == "فولان"


# ============================================================
# Extra — retyping revokes the old results (mandatory scenario):
# Search A → A results displayed → type B → clicking the OLD A row
# must resolve NOTHING and the selection must stay None.
# ============================================================


def test_extra_old_result_row_not_resolvable_after_retype(qapp, store):
    from PySide6.QtWidgets import QListWidgetItem as Item

    """
    Search A → results shown → user types B (selection cleared) →
    clicking the OLD A row must not resolve and must never (re)store
    an instrument — typed text != selected instrument.
    """
    import threading

    release_resolve = threading.Event()

    class GatedResolver:
        """search instant; resolve blocked until released."""

        def __init__(self):
            self.search_calls = []
            self.resolve_calls = []

        def search(self, text):
            self.search_calls.append(text)
            return [dict(RESULT_AKOU)]

        def resolve(self, result):
            self.resolve_calls.append(result)
            release_resolve.wait(timeout=5)
            return INSTRUMENT_AKOU

    resolver = GatedResolver()
    page = OrderConfigurationPage(store)
    page.set_resolver_factory(lambda: resolver)

    # 1. Search A → results displayed
    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    assert page.results_list.count() == 1
    old_row_sequence = page.results_list.item(0).data(RESULT_SEQUENCE_ROLE)
    # a detached copy of the old row's payload (the click may deliver an
    # item whose C++ object was deleted with the list)
    old_item = Item()
    old_item.setData(RESULT_DATA_ROLE, 0)
    old_item.setData(RESULT_SEQUENCE_ROLE, old_row_sequence)

    # 2. User types B → selection cleared AND old results revoked
    page.symbol_input.setCurrentText("فولان")
    assert page.config.selected_instrument is None
    assert page.results_list.count() == 0        # old rows gone from the UI
    assert page._latest_results == []            # old identity list dropped

    # 3. Even if a stale reference to the old row survives (a click
    #    already in flight, an external holder, …) the row belongs to a
    #    superseded generation → never resolved, never selected.
    assert old_row_sequence != page._search_sequence
    page._on_result_selected(old_item)
    page.wait_for_workers(timeout_ms=10000)
    qapp.processEvents()
    assert resolver.resolve_calls == []           # NO resolve started
    assert page.config.selected_instrument is None

    # 4. Determinism: same scenario again — identical outcome.
    release_resolve.set()
    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)
    assert page.results_list.count() == 1
    stale_row_sequence = (
        page.results_list.item(0).data(RESULT_SEQUENCE_ROLE)
    )
    stale_item = Item()
    stale_item.setData(RESULT_DATA_ROLE, 0)
    stale_item.setData(RESULT_SEQUENCE_ROLE, stale_row_sequence)
    page.symbol_input.setCurrentText("فولان")
    page._on_result_selected(stale_item)
    page.wait_for_workers(timeout_ms=10000)
    qapp.processEvents()
    assert resolver.resolve_calls == []
    assert page.config.selected_instrument is None


# ============================================================
# Extra — itemClicked + itemActivated of ONE interaction must
# collapse into exactly ONE resolve worker (no duplicate resolve).
# ============================================================


def test_extra_one_interaction_yields_exactly_one_resolve(qapp, store):
    """
    A single activation (double-click fires itemClicked twice AND
    itemActivated once) must start exactly ONE resolve worker — the
    second delivery finds a resolve already in flight and is ignored.
    """
    import threading

    release_resolve = threading.Event()

    class GatedResolver:
        def __init__(self):
            self.resolve_calls = []

        def search(self, text):
            return [dict(RESULT_AKOU)]

        def resolve(self, result):
            self.resolve_calls.append(result)
            release_resolve.wait(timeout=5)
            return INSTRUMENT_AKOU

    resolver = GatedResolver()
    page = OrderConfigurationPage(store)
    page.set_resolver_factory(lambda: resolver)

    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    _drain(qapp, page)

    item = page.results_list.item(0)
    # Simulate the triple delivery of one double-click while the first
    # resolve is still in flight:
    page._on_result_selected(item)  # itemClicked (1st)
    page._on_result_selected(item)  # itemClicked (2nd, same click)
    page._on_result_selected(item)  # itemActivated

    # exactly ONE worker was created and it is still running
    assert _wait_until(lambda: len(resolver.resolve_calls) == 1)
    assert page._resolve_thread is not None
    assert len(page._active_search_threads) == 1

    # after completion, a NEW genuine interaction resolves again
    release_resolve.set()
    page.wait_for_workers(timeout_ms=10000)
    qapp.processEvents()
    page._on_result_selected(item)   # itemActivated (same row, still shown)
    page.wait_for_workers(timeout_ms=10000)
    qapp.processEvents()
    assert len(resolver.resolve_calls) == 2


# ============================================================
# Extra — REAL stale-search race (not a manually invoked callback):
# A actually starts and stays running; B actually starts later and
# finishes first; A finishes last — A must not touch the UI.
# ============================================================


def test_extra_real_stale_search_race(qapp, store):
    """Search A really starts; search B really starts later, finishes
    first; A finishes last — A's result must not update the UI."""
    import threading

    release_a = threading.Event()
    release_b = threading.Event()

    class GatedResolver:
        def __init__(self):
            self.calls = []

        def search(self, text):
            self.calls.append(text)
            # A blocks until B has finished; B finishes immediately.
            (release_a if text == "آک" else release_b).wait(timeout=5)
            return [
                dict(RESULT_AKOU)
                if text == "آک"
                else dict(RESULT_FOLAN)
            ]

        def resolve(self, result):
            return INSTRUMENT_AKOU

    resolver = GatedResolver()
    page = OrderConfigurationPage(store)
    page.set_resolver_factory(lambda: resolver)

    # Search A starts and stays running.
    page.symbol_input.setCurrentText("آک")
    _finish_debounce(qapp, page)
    qapp.processEvents()
    assert _wait_until(lambda: resolver.calls == ["آک"])
    thread_a = page._search_thread
    assert thread_a is not None and not thread_a.isFinished()

    # Search B starts (A still running) and finishes first.
    page.symbol_input.setCurrentText("آکو")
    _finish_debounce(qapp, page)
    qapp.processEvents()
    assert _wait_until(lambda: resolver.calls == ["آک", "آکو"])
    release_b.set()
    assert _wait_until(lambda: page._search_thread is not thread_a)
    _drain(qapp, page)
    # B's result is displayed
    assert [r["symbol"] for r in page._latest_results] == ["فولاد"]

    # A finishes LAST — its result must not update the UI.
    release_a.set()
    page.wait_for_workers(timeout_ms=10000)
    qapp.processEvents()
    assert [r["symbol"] for r in page._latest_results] == ["فولاد"]
    assert page.results_list.count() == 1
    assert all(
        page.results_list.item(i).data(RESULT_SEQUENCE_ROLE)
        == page._search_sequence
        for i in range(page.results_list.count())
    )  # the only visible rows belong to the current generation

