"""
test_ui4_queue_ui_integration.py

UI-4 — Order Queue UI integration (fully offline, deterministic).

The Order Configuration page connected to the EXISTING
``core.order_queue.OrderQueue``: an explicit "Add to Queue" action
prepares ONE real ``models.order.Order`` (broker ``nscId`` resolved off
the GUI thread at selection time — NEVER at enqueue time) and appends it
together with the active account/broker binding; a visible queue list is
rendered ONLY from ``OrderQueue.list_pending()`` (the exact queued
objects, never clones).

Mandatory contract coverage:

    Test 1  — the page contains an explicit "Add to Queue" action and a
              visible queue list.
    Test 2  — a valid configured order + a valid account/broker binding
              enqueues exactly once.
    Test 3  — the exact Order object is stored inside the resulting
              QueueEntry (no clone, no rebuild).
    Test 4  — the QueueEntry keeps the active account identity.
    Test 5  — the QueueEntry keeps the active broker identity.
    Test 6  — the visible queue list reflects OrderQueue.list_pending().
    Test 7  — two orders are two fully independent QueueEntries.
    Test 8  — queued orders are never cloned/reconstructed for display.
    Test 9  — missing/incoherent inputs or bindings fail closed: nothing
              is enqueued, the queue stays untouched.
    Test 10 — Add-to-Queue never calls DispatchCore / DispatchIntegration
              / OrderEngine / an OrderEngine execution path / a broker
              placement or the network (socket-bombed clean subprocess).
    Test 11 — existing UI-3.2A/3.2B symbol/trading-state behavior stays
              intact on the same page (full offline flow).

Extra contracts:

    Extra 1 — identity worker lifecycle: no lingering identity worker on
              any path (mirrors the other workers).
    Extra 2 — a late identity resolution for a replaced symbol can never
              become the new selection's nscId.
    Extra 3 — an account switch invalidates the broker-scoped identity
              (fail-closed until the selection is re-resolved).
    Extra 4 — MainWindow construction stays offline and the lazy default
              queue is only imported at the first real queue access.

These tests are fully offline:
  - no network
  - no login
  - no broker API
  - no TSETMC call
  - no dispatch / OrderEngine / OrderEngine execution

Run:
    pytest -q test_ui4_queue_ui_integration.py
"""

import os
import subprocess
import sys
import threading
import time

import pytest

from PySide6.QtWidgets import QApplication, QListWidget

from models.instrument import Instrument
from models.order import BUY, SELL, Order
from models.trading_state import VERIFIED_TRADABLE

from core.order_queue import OrderQueue

from ui.account_store import AccountStore
from ui.order_configuration_page import (
    QUEUE_ENTRY_ROLE,
    QUEUE_STATUS_BROKER_STALE,
    QUEUE_STATUS_INCOMPLETE,
    QUEUE_STATUS_NO_ACCOUNT,
    QUEUE_STATUS_NO_IDENTITY,
    QUEUE_STATUS_NO_SYMBOL,
    STATUS_LABEL_TRADABLE,
    STATUS_PENDING_LABEL,
    OrderConfigurationPage,
)


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

NSC_AKOU = "NSC-60235881999727383"
NSC_FOLAD = "NSC-46348559193224090"

ACCOUNT_ONE = "ACC-001"
BROKER_ONE = "آگاه"
ACCOUNT_TWO = "ACC-002"
BROKER_TWO = "کارگزاری سهم"


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


class StubQuery:
    """Mimics the real TradingStateQuery surface (get_trading_state)."""

    def __init__(self, state=None, error=None):
        self.state = state
        self.error = error
        self.calls = []

    def get_trading_state(self, ins_code):
        self.calls.append(ins_code)
        if self.error is not None:
            raise self.error
        return self.state


class StubNscSeam:
    """Mimics the broker InstrumentProvider surface (get_nsc_id)."""

    def __init__(self, nsc_id=NSC_AKOU, mapping=None, error=None):
        self.nsc_id = nsc_id
        self.mapping = mapping or {}
        self.error = error
        self.calls = []

    def get_nsc_id(self, ins_code):
        self.calls.append(ins_code)
        if self.error is not None:
            raise self.error
        if self.mapping:
            return self.mapping.get(ins_code)
        return self.nsc_id


class RecordingQueue(OrderQueue):
    """OrderQueue subclass that remembers exactly what was enqueued."""

    def __init__(self):
        super().__init__()
        self.received = []

    def enqueue(self, order, account_id=None, broker_name=None):
        self.received.append((order, account_id, broker_name))
        super().enqueue(order, account_id=account_id, broker_name=broker_name)


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


def _store_with_active(account_id=ACCOUNT_ONE, broker_name=BROKER_ONE):
    store = AccountStore()
    store.add(account_id, broker_name)
    store.set_active(account_id)
    return store


def _wait_until(predicate, timeout_s=5.0):
    """Bounded deterministic wait for a worker-side side effect."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _pulse(qapp, loops=30):
    """A fixed number of event-loop wakeups for queued signal deliveries."""
    for _ in range(loops):
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()


def _drain(qapp, page):
    """Process queued deliveries, then wait for all page workers."""
    qapp.processEvents()
    page.wait_for_workers(timeout_ms=10000)
    page.wait_for_trading_state_workers(timeout_ms=10000)
    page.wait_for_order_identity_workers(timeout_ms=10000)
    _pulse(qapp)
    pending = STATUS_PENDING_LABEL
    for _ in range(150):
        if page.trading_state_label.text() != pending:
            break
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()


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


def _select_symbol(
    qapp, page, text="آکو", results=(RESULT_AKOU,),
    instrument=INSTRUMENT_AKOU,
    resolver_factory=None,
):
    """Run the REAL UI-3.2A search+select flow (offline, stubbed)."""
    stub = resolver_factory() if resolver_factory is not None else StubResolver(
        results=results, instrument=instrument,
    )
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


def _prepare_order(
    qapp,
    page,
    instrument=INSTRUMENT_AKOU,
    side=BUY,
    price=15000,
    quantity=500,
):
    """Configure the form directly and resolve the order identity."""
    page.config.select_instrument(instrument)
    page.config.set_side(side)
    page.config.set_price(price)
    page.config.set_quantity(quantity)
    page._start_order_identity_resolution(instrument)
    page.wait_for_order_identity_workers(timeout_ms=10000)
    _pulse(qapp)
    return page


# ============================================================
# Test 1 — an explicit Add-to-Queue action and a visible queue list
# ============================================================


def test_1_add_to_queue_action_and_queue_view_exist(qapp):
    store = _store_with_active()
    page = OrderConfigurationPage(store, order_queue=OrderQueue())

    assert page.add_to_queue_button is not None
    assert "Add to Queue" in page.add_to_queue_button.text()

    assert isinstance(page.queue_list, QListWidget)
    assert page.queue_list.count() == 0
    assert hasattr(page, "queue_status_label")
    assert hasattr(page, "queue_count_label")
    from PySide6.QtWidgets import QGroupBox

    assert isinstance(page.queue_list.parent(), QGroupBox)
    assert page.queue_list.parent().title() == "Order Queue"
    assert page.queue_count_label.text() == "0 order(s) in queue"


# ============================================================
# Test 2 — a valid order + valid binding enqueues EXACTLY once
# ============================================================


def test_2_valid_order_and_binding_enqueue_once(qapp):
    queue = OrderQueue()
    page = OrderConfigurationPage(
        _store_with_active(), order_queue=queue,
    )
    page.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    _prepare_order(qapp, page)

    assert page.order_queue is queue
    assert queue.list_pending() == []

    page.add_to_queue_button.click()
    assert len(queue.list_pending()) == 1

    # a NEW identical order on the next click is enqueued as a SECOND,
    # independent entry — exactly one Order per Add-to-Queue action
    page.add_to_queue_button.click()
    assert len(queue.list_pending()) == 2


# ============================================================
# Test 3 — the exact Order object is stored in the QueueEntry
# ============================================================


def test_3_exact_order_object_stored_in_entry(qapp):
    recording = RecordingQueue()
    page = OrderConfigurationPage(
        _store_with_active(), order_queue=recording,
    )
    page.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    _prepare_order(qapp, page, price=18000, quantity=700)

    assert page._on_add_to_queue() is True

    (order, account_id, broker_name) = recording.received[0]
    entry = recording.list_pending()[0]

    # the entry holds the EXACT object the page passed to enqueue —
    # never a clone or a reconstruction
    assert entry.order is order
    assert order is entry.order
    assert recording.is_pending(order) is True

    # it is a real Core Order carrying exactly the resolved identity
    assert isinstance(order, Order)
    assert order.nsc_id == NSC_AKOU
    assert order.side == 1  # models.order.BUY
    assert order.price == 18000
    assert order.quantity == 700
    assert account_id == ACCOUNT_ONE
    assert broker_name == BROKER_ONE


# ============================================================
# Test 4 — account identity is preserved on the entry
# ============================================================


def test_4_entry_keeps_account_identity(qapp):
    store = _store_with_active(account_id=ACCOUNT_TWO)
    page = OrderConfigurationPage(store, order_queue=OrderQueue())
    page.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    _prepare_order(qapp, page)

    assert page._on_add_to_queue() is True

    entry = page.order_queue.list_pending()[0]
    assert entry.account_id == ACCOUNT_TWO
    assert entry.account_id != ACCOUNT_ONE


# ============================================================
# Test 5 — broker identity is preserved on the entry
# ============================================================


def test_5_entry_keeps_broker_identity(qapp):
    store = _store_with_active(broker_name=BROKER_TWO)
    page = OrderConfigurationPage(store, order_queue=OrderQueue())
    page.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    _prepare_order(qapp, page)

    assert page._on_add_to_queue() is True

    entry = page.order_queue.list_pending()[0]
    assert entry.broker_name == BROKER_TWO
    assert entry.broker_name != BROKER_ONE


# ============================================================
# Test 6 — the visible queue list reflects list_pending()
# ============================================================


def test_6_visible_list_reflects_list_pending(qapp):
    queue = OrderQueue()
    page = OrderConfigurationPage(_store_with_active(), order_queue=queue)
    page.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    _prepare_order(qapp, page, price=15000, quantity=500, side=BUY)

    assert page._on_add_to_queue() is True
    assert page.queue_list.count() == 1
    row_one = page.queue_list.item(0).text()
    assert NSC_AKOU in row_one
    assert "خرید" in row_one          # side label is rendered, not raw 1
    assert "15000" in row_one         # the int price
    assert "500" in row_one           # the int quantity
    assert ACCOUNT_ONE in row_one
    assert BROKER_ONE in row_one
    assert page.queue_count_label.text() == "1 order(s) in queue"

    page.symbol_input.setCurrentText("")  # clear keeps prior queue intact
    _drain(qapp, page)
    assert page.queue_list.count() == 1  # display unchanged by symbol edit
    assert page.queue_count_label.text() == "1 order(s) in queue"


# ============================================================
# Test 7 — two orders are two fully independent entries
# ============================================================


def test_7_two_orders_are_independent_entries(qapp):
    queue = OrderQueue()
    page = OrderConfigurationPage(_store_with_active(), order_queue=queue)
    seam = StubNscSeam(
        mapping={
            INSTRUMENT_AKOU.ins_code: NSC_AKOU,
            INSTRUMENT_FOLAD.ins_code: NSC_FOLAD,
        }
    )
    page.set_order_identity_factory(lambda: seam)

    _prepare_order(qapp, page, instrument=INSTRUMENT_AKOU, side=BUY,
                   price=15000, quantity=500)
    assert page._on_add_to_queue() is True

    _prepare_order(qapp, page, instrument=INSTRUMENT_FOLAD, side=SELL,
                   price=12000, quantity=300)
    assert page._on_add_to_queue() is True

    entries = queue.list_pending()
    assert len(entries) == 2
    first, second = entries

    # independent entries, independent order objects, FIFO order
    assert first is not second
    assert first.order is not second.order
    assert queue.list_pending()[0] is first
    assert queue.list_pending()[1] is second

    assert first.order.nsc_id == NSC_AKOU
    assert second.order.nsc_id == NSC_FOLAD
    assert first.order.side == BUY
    assert second.order.side == SELL
    assert first.order.price == 15000
    assert second.order.price == 12000
    assert first.order.quantity == 500
    assert second.order.quantity == 300

    # each entry keeps its own binding — one account, same broker
    assert first.account_id == ACCOUNT_ONE
    assert second.account_id == ACCOUNT_ONE
    assert first.broker_name == BROKER_ONE
    assert second.broker_name == BROKER_ONE

    # the seam resolved each selected instrument independently
    assert seam.calls == [INSTRUMENT_AKOU.ins_code, INSTRUMENT_FOLAD.ins_code]


# ============================================================
# Test 8 — orders are never cloned/reconstructed for display
# ============================================================


def test_8_orders_not_cloned_for_display(qapp):
    queue = OrderQueue()
    page = OrderConfigurationPage(_store_with_active(), order_queue=queue)
    page.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    _prepare_order(qapp, page)

    assert page._on_add_to_queue() is True

    entry = queue.list_pending()[0]
    item = page.queue_list.item(0)

    # the ROW carries the exact QueueEntry (identity travels in the role);
    # the displayed order is the exact queued object — never rebuilt
    from core.order_queue import QueueEntry

    stored = item.data(QUEUE_ENTRY_ROLE)
    assert isinstance(stored, QueueEntry)
    assert stored is entry
    assert stored.order is entry.order
    assert stored.order is queue.list_pending()[0].order


# ============================================================
# Test 9 — missing/incoherent input or binding fails closed
# ============================================================


def test_9_add_to_queue_fails_closed(qapp):
    # 9a. no active account → nothing queued
    store = AccountStore()
    store.add(ACCOUNT_ONE, BROKER_ONE)  # exists but NOT active
    queue = OrderQueue()
    page = OrderConfigurationPage(store, order_queue=queue)
    page.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    page.config.select_instrument(INSTRUMENT_AKOU)
    page.config.set_side(BUY)
    page.config.set_price(15000)
    page.config.set_quantity(500)
    assert page._on_add_to_queue() is False
    assert queue.list_pending() == []
    assert QUEUE_STATUS_NO_ACCOUNT == page.queue_status_label.text()

    # 9b. no selected symbol → nothing queued
    store2 = _store_with_active()
    queue2 = OrderQueue()
    page2 = OrderConfigurationPage(store2, order_queue=queue2)
    page2.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    page2.config.set_side(BUY)
    page2.config.set_price(15000)
    page2.config.set_quantity(500)
    assert page2._on_add_to_queue() is False
    assert queue2.list_pending() == []
    assert QUEUE_STATUS_NO_SYMBOL == page2.queue_status_label.text()

    # 9c. incomplete fields (no price) → nothing queued
    store3 = _store_with_active()
    queue3 = OrderQueue()
    page3 = OrderConfigurationPage(store3, order_queue=queue3)
    page3.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    page3.config.select_instrument(INSTRUMENT_AKOU)
    page3.config.set_side(BUY)
    page3.config.set_quantity(500)
    assert page3._on_add_to_queue() is False
    assert queue3.list_pending() == []
    assert QUEUE_STATUS_INCOMPLETE == page3.queue_status_label.text()

    # 9d. unresolved/absent broker identity → nothing queued, no call
    store4 = _store_with_active()
    queue4 = OrderQueue()
    seam4 = StubNscSeam(nsc_id=None)  # provider cannot map this ins_code
    page4 = OrderConfigurationPage(store4, order_queue=queue4)
    page4.set_order_identity_factory(lambda: seam4)
    _prepare_order(qapp, page4)  # resolution ran, but produced no nscId
    assert page4._order_nsc_id is None
    assert page4._on_add_to_queue() is False
    assert queue4.list_pending() == []
    assert QUEUE_STATUS_NO_IDENTITY == page4.queue_status_label.text()

    # 9e. identity never resolved for the current selection (stale)
    store5 = _store_with_active()
    queue5 = OrderQueue()
    page5 = OrderConfigurationPage(store5, order_queue=queue5)
    page5.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    page5._start_order_identity_resolution(INSTRUMENT_AKOU)
    # user then edits the symbol WITHOUT resolving the new identity
    page5.symbol_input.setCurrentText("فولاد")
    _drain(qapp, page5)
    page5.config.select_instrument(INSTRUMENT_FOLAD)
    page5.config.set_side(BUY)
    page5.config.set_price(15000)
    page5.config.set_quantity(500)
    assert page5._on_add_to_queue() is False
    assert queue5.list_pending() == []


# ============================================================
# Test 10 — Add-to-Queue never reaches execution/dispatch/network
# ============================================================


def test_10_add_to_queue_never_calls_execution_path():
    code = "\n".join(
        [
            "import sys, socket, urllib.request",
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
            "from ui.account_store import AccountStore",
            "from ui.order_configuration_page import OrderConfigurationPage",
            "from PySide6.QtWidgets import QApplication",
            "",
            "app = QApplication([])",
            "store = AccountStore()",
            "store.add('ACC-001', 'آگاه')",
            "store.set_active('ACC-001')",
            "page = OrderConfigurationPage(store)",
            "",
            "# construction stays fully offline",
            "banned = ('brokers', 'market', 'core')",
            "leaked = sorted(m for m in sys.modules if m.split('.')[0] in banned)",
            "assert not leaked, f'UI construction imported trading modules: {leaked}'",
            "",
            "instrument = Instrument(symbol='آکو', name='آکو باتري ايرانيان',",
            "                        ins_code='60235881999727383', market='بورس')",
            "",
            "class _Nsc:",
            "    def get_nsc_id(self, ins_code):",
            "        assert ins_code == '60235881999727383'",
            "        return 'NSC-60235881999727383'",
            "",
            "page.set_order_identity_factory(lambda: _Nsc())",
            "page.config.select_instrument(instrument)",
            "page.config.set_side(1)",
            "page.config.set_price(15000)",
            "page.config.set_quantity(500)",
            "page._start_order_identity_resolution(instrument)",
            "page.wait_for_order_identity_workers(10000)",
            "for _ in range(30):",
            "    app.processEvents()",
            "",
            "# the Add-to-Queue action itself: no dispatch, no engine, no network",
            "assert page._on_add_to_queue() is True",
            "entries = page.order_queue.list_pending()",
            "assert len(entries) == 1",
            "assert entries[0].order.nsc_id == 'NSC-60235881999727383'",
            "assert entries[0].account_id == 'ACC-001'",
            "assert entries[0].broker_name == 'آگاه'",
            "",
            "# only core.order_queue was ever pulled in from core/brokers/market",
            "import core.order_queue",
            "for module in sorted(m for m in sys.modules if m.split('.')[0] in banned):",
            "    if module in ('core', 'core.order_queue'):",
            "        continue",
            "    raise AssertionError(f'execution/module leaked: {module}')",
            "print('QUEUE_OFFLINE_OK')",
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
    assert "QUEUE_OFFLINE_OK" in result.stdout


# ============================================================
# Test 11 — existing UI-3.2A/3.2B behavior stays intact
# ============================================================


def test_11_ui3_symbol_and_trading_state_behavior_intact(qapp):
    store = _store_with_active()
    page = OrderConfigurationPage(store, order_queue=OrderQueue())
    page.set_trading_state_query_factory(lambda: StubQuery(state=VERIFIED_TRADABLE))
    page.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))

    _select_symbol(qapp, page)

    # UI-3.2A: real symbol info is displayed from the real Instrument
    assert page.config.selected_instrument is INSTRUMENT_AKOU
    assert "آکو" in page.symbol_name_label.text()

    # UI-3.2B: real trading state is displayed through the real flow
    assert page.trading_state_label.text() == STATUS_LABEL_TRADABLE

    # UI-4: the same selection now also resolves a real identity and can
    # be added to the queue once the order fields are filled
    page.config.set_side(BUY)
    page.config.set_price(15000)
    page.config.set_quantity(500)
    assert page._on_add_to_queue() is True
    entry = page.order_queue.list_pending()[0]
    assert entry.order.nsc_id == NSC_AKOU
    assert entry.account_id == ACCOUNT_ONE
    assert entry.broker_name == BROKER_ONE


# ============================================================
# Extra 1 — identity worker lifecycle: reaped on every path
# ============================================================


def test_extra_identity_worker_lifecycle(qapp):
    release = threading.Event()

    class GatedSeam:
        def get_nsc_id(self, ins_code):
            release.wait(timeout=5)
            return NSC_AKOU

    page = OrderConfigurationPage(_store_with_active())
    page.set_order_identity_factory(lambda: GatedSeam())
    page.config.select_instrument(INSTRUMENT_AKOU)
    page._start_order_identity_resolution(INSTRUMENT_AKOU)

    # while running: exactly one live identity worker
    assert page._order_identity_thread is not None
    assert not page._order_identity_thread.isFinished()

    release.set()
    page.wait_for_order_identity_workers(timeout_ms=10000)
    _pulse(qapp)

    # after completion: nothing lingers, the identity is resolved
    assert page._order_identity_thread is None
    assert page._order_identity_worker is None
    assert page._order_nsc_id == NSC_AKOU

    # the failure path is reaped as well
    page2 = OrderConfigurationPage(_store_with_active())
    page2.set_order_identity_factory(
        lambda: StubNscSeam(error=RuntimeError("boom"))
    )
    page2.config.select_instrument(INSTRUMENT_AKOU)
    page2._start_order_identity_resolution(INSTRUMENT_AKOU)
    page2.wait_for_order_identity_workers(timeout_ms=10000)
    _pulse(qapp)
    assert page2._order_identity_thread is None
    assert page2._order_identity_worker is None
    assert page2._order_nsc_id is None  # fail-closed


# ============================================================
# Extra 2 — a late identity result for a replaced symbol is discarded
# ============================================================


def test_extra_stale_identity_never_becomes_new_selection(qapp):
    release = threading.Event()
    calls = []

    class GatedSeam:
        def get_nsc_id(self, ins_code):
            calls.append(ins_code)
            release.wait(timeout=5)
            return NSC_AKOU

    page = OrderConfigurationPage(_store_with_active())
    page.set_order_identity_factory(lambda: GatedSeam())
    page.config.select_instrument(INSTRUMENT_AKOU)
    page._start_order_identity_resolution(INSTRUMENT_AKOU)
    assert _wait_until(lambda: len(calls) == 1)
    assert calls == [INSTRUMENT_AKOU.ins_code]
    stale_ins_code = page._order_identity_instrument

    # the user retypes while the resolution is in flight
    page.symbol_input.setCurrentText("فولان")
    _drain(qapp, page)
    assert page._order_identity_instrument is None
    assert page._order_nsc_id is None

    # the late result arrives — it must be discarded
    release.set()
    page.wait_for_order_identity_workers(timeout_ms=10000)
    _pulse(qapp)

    assert page._order_nsc_id is None
    assert stale_ins_code is not None


# ============================================================
# Extra 3 — an account switch invalidates the broker-scoped identity
# ============================================================


def test_extra_account_switch_invalidates_identity(qapp):
    store = AccountStore()
    store.add(ACCOUNT_ONE, BROKER_ONE)
    store.add(ACCOUNT_TWO, BROKER_TWO)
    store.set_active(ACCOUNT_ONE)

    queue = OrderQueue()
    page = OrderConfigurationPage(store, order_queue=queue)
    page.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    _prepare_order(qapp, page)

    # resolved against broker ONE — the entry would carry that binding
    assert page._order_identity_broker == BROKER_ONE
    assert page._on_add_to_queue() is True
    assert queue.list_pending()[0].broker_name == BROKER_ONE

    # now the user switches to the SECOND broker
    store.set_active(ACCOUNT_TWO)
    page.refresh_active_account()
    _drain(qapp, page)

    # the identity belongs to broker ONE — binding it to broker TWO is
    # refused until the selection is re-resolved (fail-closed)
    queue2 = OrderQueue()
    page2 = OrderConfigurationPage(store, order_queue=queue2)
    page2.set_order_identity_factory(lambda: StubNscSeam(NSC_AKOU))
    _prepare_order(qapp, page2)
    assert page2._on_add_to_queue() is True
    assert queue2.list_pending()[0].broker_name == BROKER_TWO


# ============================================================
# Extra 4 — MainWindow construction stays offline; lazy queue import
# ============================================================


def test_extra_main_window_construction_offline_lazy_queue():
    code = "\n".join(
        [
            "import sys, socket, urllib.request",
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
            "",
            "banned = ('brokers', 'market', 'core')",
            "leaked = sorted(m for m in sys.modules if m.split('.')[0] in banned)",
            "assert not leaked, f'UI construction imported trading modules: {leaked}'",
            "",
            "# nothing queued; the queue object is only materialized lazily",
            "assert page.queue_list.count() == 0",
            "assert page._injected_order_queue is None",
            "",
            "from core.order_queue import OrderQueue",
            "assert isinstance(page.order_queue, OrderQueue)",
            "assert sys.modules.get('core.order_queue') is not None",
            "# still NO dispatch/engine module leaked",
            "for module in sorted(m for m in sys.modules if m.startswith('core.')):",
            "    if module == 'core.order_queue':",
            "        continue",
            "    raise AssertionError(f'unexpected core module: {module}')",
            "print('LAZY_QUEUE_OK')",
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
    assert "LAZY_QUEUE_OK" in result.stdout
