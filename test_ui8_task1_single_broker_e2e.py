"""
test_ui8_task1_single_broker_e2e.py

UI-8 Task 1 — ONE order / ONE account / ONE broker, end to end, offline.

Why this file exists (UI-5 coverage review):

  * ``test_ui5_task2_dry_run_execution.py`` proves the RUNNER reaches the
    simulation broker when the runner is called directly, and proves the
    PAGE wiring only with duck-typed stub runners (no real core, no broker).
  * ``test_ui5_task3_order_results.py`` proves the real page -> real
    ``TestRunner`` -> ``SimulationHarness`` core -> result-row rendering,
    but spreads the evidence over several tests, uses an injected
    ``dispatch_core``, and never pins the whole single-order flow
    (single add, single Test click, one ``live=False`` broker call, one
    visible result row, no real broker / no parallel path) in one run, and
    never asserts the absence of network access or of the production
    ``BrokerManager``/``AgaahBroker`` binding on that flow.

  None of those tests covers the full Task 1 acceptance list in a single
  offline pass, so this file adds exactly ONE targeted test that does.

Path under test (nothing stubbed except the symbol-information seam and the
broker pair of the offline ``SimulationHarness``):

    real page form -> real Add-to-Queue (``_on_add_to_queue``)
        -> real ``TestRunner.run(entries, account=...)``   (built with the
           SAME production shape MainWindow uses: ``broker_manager`` only,
           no injected Dispatch Core, so the runner builds the real
           ``DispatchCore`` itself)
        -> real ``DispatchIntegration`` / ``DispatchCore`` /
           ``core.order_engine.OrderEngine`` (M6-A ... M6-E untouched)
        -> ``SimulationBroker.place_order(order, live=False)``
        -> per-order ``OrderExecutionResult`` of THIS dispatch
        -> the page's real Test Results display.

No network, no credentials, no real account, no live send: the whole flow
runs while sockets, ``urllib``, the production ``BrokerManager``
construction path and ``AgaahBroker`` construction are all booby-trapped.

Safety is proven from the OBSERVABLE contract of this run only — exactly
one ``SimulationBroker.place_order`` call carrying ``live=False``, a
dispatch result and a per-order result that both report a dry run, and the
simulated broker's own fail-closed refusal of any ``live=True`` call. This
test makes NO assumption about how ``TestRunner`` builds its Dispatch Core
(it does not require a ``SafetyGate`` to exist, be attached, or be
evaluated), so it holds for any committed revision of ``ui/test_runner.py``.

Run:
    pytest -q test_ui8_task1_single_broker_e2e.py
"""

import inspect
import socket
import urllib.request
from unittest.mock import patch

import pytest

from PySide6.QtWidgets import QApplication

from brokers.manager import BrokerManager
from core.dispatch_contracts import DispatchResult
from core.dispatch_core import DispatchCore
from core.order_queue import OrderQueue
from core.simulation_harness import (
    SimulationBroker,
    SimulationHarness,
    SimulationInstrumentProvider,
    build_simulation_catalog,
    make_simulation_order,
)
from models.instrument import Instrument
from models.order import SELL

from ui.account_store import AccountStore
from ui.order_configuration_page import (
    RESULT_STATUS_SUCCESS,
    OrderConfigurationPage,
)
from ui.test_runner import TestRunner


BROKER = "SIM"
ACCOUNT_ID = "ACC-UI8-1"
INS_CODE = "INS-SIM-1"
INSTRUMENT = Instrument(
    symbol="\u0622\u06a9\u0648", name="SSIM \u0622\u06a9\u0648", ins_code=INS_CODE
)


@pytest.fixture(scope="module")
def qapp():
    """Reuse the process-wide QApplication if one exists, else create one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def no_real_broker_or_network():
    """
    Make every real-broker / network entry point fail loudly for the whole
    test. Nothing in this module may construct an HTTP session, open a
    socket, resolve a host, or build the production broker binding; if the
    UI path ever reached one, the test would error instead of passing.
    """

    def _boom(*args, **kwargs):
        raise AssertionError("real broker / network access attempted")

    with patch.object(socket, "socket", _boom), patch.object(
        socket, "create_connection", _boom
    ), patch.object(socket, "getaddrinfo", _boom), patch.object(
        urllib.request, "urlopen", _boom
    ), patch.object(
        # The harness builds its private manager with
        # ``BrokerManager.__new__`` on purpose: the production ``__init__``
        # binding (which is what creates the real AgaahBroker) must never
        # run on this offline flow.
        BrokerManager,
        "__init__",
        _boom,
    ):
        from brokers.agaah.broker import AgaahBroker

        with patch.object(AgaahBroker, "__init__", _boom):
            yield


class OfflineNscSeam:
    """
    Offline stand-in for the broker ``InstrumentProvider`` symbol seam
    (``get_nsc_id``), exactly as the UI-5 tests use it: it supplies the
    symbol information the Add-to-Queue action needs, without any broker,
    session or network call.
    """

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls = []

    def get_nsc_id(self, ins_code):
        self.calls.append(ins_code)
        return self.mapping.get(ins_code)


def _pulse(qapp, loops=30):
    """A fixed number of event-loop wakeups for the queued off-thread signal."""
    for _ in range(loops):
        qapp.processEvents()
    qapp.processEvents()


def _add_order_via_real_ui(qapp, page, seam):
    """
    Drive the REAL UI order flow: select the instrument and the order
    fields, resolve the broker nscId off-thread through the offline seam,
    then press Add-to-Queue. Returns the exact ``QueueEntry`` the page
    created.
    """
    page.set_order_identity_factory(lambda: seam)
    page.config.select_instrument(INSTRUMENT)
    page.config.set_side(SELL)
    page.config.set_price(10_000)
    page.config.set_quantity(10)
    page._start_order_identity_resolution(INSTRUMENT)
    page.wait_for_order_identity_workers(timeout_ms=10_000)
    _pulse(qapp)
    assert page._on_add_to_queue() is True
    return page.order_queue.list_pending()[-1]


def _watch_place_order(broker):
    """
    Wrap the simulation broker's ``place_order`` with an instance-level
    recorder (the Core still calls the very same method through the real
    engine). Records every call's ``(order, live)`` plus the module names of
    the calling frames, so the test can prove the call arrived through the
    real Core/OrderEngine path and not through a parallel direct path.
    """
    original = broker.place_order
    calls = []

    def recording_place_order(order, live=False):
        frames = [
            frame_info.frame.f_globals.get("__name__", "")
            for frame_info in inspect.stack()[1:]
        ]
        calls.append((order, live, frames))
        return original(order, live=live)

    broker.place_order = recording_place_order
    return calls


def test_ui8_task1_single_order_single_account_single_broker_end_to_end(
    qapp, no_real_broker_or_network
):
    """
    ONE order, ONE account, ONE broker: from the real order page through
    the real Test action and the real Core/OrderEngine to the simulated
    broker — and the result of THAT order back on screen.
    """
    harness = SimulationHarness(
        broker_name=BROKER,
        catalog=build_simulation_catalog(ins_codes=(INS_CODE,)),
    )
    place_order_calls = _watch_place_order(harness.broker)

    # Exactly one account, one broker, one queue — the single-batch case.
    store = AccountStore()
    store.add(ACCOUNT_ID, BROKER, ACCOUNT_ID)
    store.set_active(ACCOUNT_ID)
    queue = OrderQueue()
    page = OrderConfigurationPage(store, order_queue=queue)
    # Production wiring shape (MainWindow): the shared BrokerManager only,
    # no injected Dispatch Core — so the runner itself builds the REAL
    # DispatchCore around the simulation pair (how it configures that core
    # internally is not this test's concern).
    runner = TestRunner(broker_manager=harness.manager)
    page.set_test_runner_factory(lambda: runner)

    # ---- Real Add-to-Queue (no stubbed page action) ----------------------
    seam = OfflineNscSeam({INS_CODE: INS_CODE})
    entry = _add_order_via_real_ui(qapp, page, seam)
    record = store.get(ACCOUNT_ID)

    # (1) exactly ONE order is queued, bound to ONE account / ONE broker.
    pending = queue.list_pending()
    assert len(pending) == 1
    assert len(store.all_accounts()) == 1
    assert set(harness.manager.brokers) == {BROKER}
    assert pending[0] is entry
    assert entry.account_id == ACCOUNT_ID == record.account_id
    assert entry.broker_name == BROKER == record.broker_name
    assert page.test_button.isEnabled()
    # symbol information came from the offline seam only, never a broker.
    assert seam.calls == [INS_CODE]
    # nothing was sent before the Test action.
    assert place_order_calls == []
    assert page.result_list.count() == 0

    # ---- ONE Test press -> ONE real execution ----------------------------
    dispatch_counts = {"measured": 0, "plain": 0}
    real_measured = DispatchCore.dispatch_with_latency
    real_dispatch = DispatchCore.dispatch

    def counting_measured(self, plan):
        dispatch_counts["measured"] += 1
        return real_measured(self, plan)

    def counting_plain(self, plan):
        dispatch_counts["plain"] += 1
        return real_dispatch(self, plan)

    with patch.object(
        DispatchCore, "dispatch_with_latency", counting_measured
    ), patch.object(DispatchCore, "dispatch", counting_plain):
        page.test_button.click()

    assert page._test_mode is True
    assert page._last_test_error is None

    # (3) exactly ONE dispatch of this one click, through the existing
    # measured contract — never the plain entry point, never a re-execution.
    assert dispatch_counts == {"measured": 1, "plain": 0}

    # The runner really built the production core itself, around the shared
    # simulation manager. Nothing about how it configures that core (a
    # Safety Gate being attached or not) is assumed here.
    assert isinstance(runner._dispatch_core, DispatchCore)
    assert runner._integration.dispatch_core is runner._dispatch_core

    # (2) the SAME order and the SAME account/broker identity survived the
    # real execution path, by object identity (never cloned, never rebuilt).
    plan, execution_id, result = page._last_test_run
    assert plan.orders == [entry.order]
    assert plan.orders[0] is entry.order
    assert plan.accounts == [record.account]
    assert plan.accounts[0] is record.account
    assert plan.account_routes == {ACCOUNT_ID: BROKER}
    assert plan.conditions["binding"][0]["account_id"] == ACCOUNT_ID
    assert plan.conditions["binding"][0]["broker_name"] == BROKER
    assert execution_id == runner.last_execution_id
    assert execution_id != plan.plan_id

    # (3) exactly ONE call reached the simulated broker for that one click.
    assert len(place_order_calls) == 1
    assert len(harness.broker.place_order_calls) == 1

    # (4) that call was the dry-run submission of THIS order: live=False, and
    # nothing anywhere reports a live send.
    submitted_order, live_flag, frames = place_order_calls[0]
    assert submitted_order is entry.order
    assert live_flag is False
    assert harness.broker.place_order_calls == [(entry.order, False)]
    assert all(live is False for _, live in harness.broker.place_order_calls)
    assert isinstance(result, DispatchResult)
    assert result.sent is False
    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert result.order_count == 1
    per_order = page._last_order_results[0]
    assert per_order.sent is False
    assert per_order.success is True
    assert per_order.mode == "DRY_RUN"
    assert per_order.order is entry.order
    assert runner._dispatch_core.live_trading_enabled is False
    assert harness.broker.live_trading_enabled is False
    assert per_order.response["mode"] == "DRY_RUN"
    assert per_order.response["sent"] is False

    # Any live path in the simulated broker is still refused, independently
    # of the dry-run call above: a separate broker instance (never the one
    # under test, never reached from the UI) raises fail-closed on
    # live=True, so a live submission has no working path here at all.
    guard_broker = SimulationBroker(
        name="SIM-GUARD", catalog=build_simulation_catalog(ins_codes=(INS_CODE,))
    )
    guard_order = make_simulation_order(ins_code=INS_CODE)
    with pytest.raises(RuntimeError):
        guard_broker.place_order(guard_order, live=True)
    assert guard_broker.place_order_calls == [(guard_order, True)]

    # (5) the result of THAT order came back from the real execution path
    # and is visible in the Test Results display.
    assert page._last_test_entries == [entry]
    assert page.result_list.count() == 1
    row = page.result_list.item(0).text()
    assert row == (
        f"حساب {ACCOUNT_ID} | آکو | فروش | "
        f"{RESULT_STATUS_SUCCESS} | سفارش با موفقیت شبیه‌سازی شد"
    )
    assert page.result_status_label.text() == "1 result(s)"
    assert page._last_order_results[0] is per_order
    assert per_order.order is page._last_test_entries[0].order

    # (6) no real broker API and no parallel/direct path out of the UI: the
    # single broker call came through the real Core and OrderEngine frames
    # (below the UI frame, above the broker), and only the simulated pair is
    # registered on the manager the runner dispatched with.
    ui_frame = next(
        index
        for index, name in enumerate(frames)
        if name == "ui.order_configuration_page"
    )
    # ``inspect.stack()`` is innermost-first and the recorder itself is
    # skipped: the immediate caller of ``place_order`` is the real
    # OrderEngine, then the real DispatchCore, and only above them the UI
    # frame that pressed Test. A direct UI->broker call would carry no
    # core/engine frames at all.
    engine_frame = frames.index("core.order_engine")
    core_frame = frames.index("core.dispatch_core")
    assert engine_frame == 0
    assert engine_frame < core_frame < ui_frame
    assert isinstance(harness.broker, SimulationBroker)
    assert set(harness.manager.brokers) == {BROKER}
    assert isinstance(harness.manager.get(BROKER), SimulationBroker)
    # the provider resolved on the dispatch path is the harness's own
    # simulated one — not a real-broker provider of any kind.
    assert isinstance(
        harness.manager.get_instrument_provider(BROKER),
        SimulationInstrumentProvider,
    )
    assert harness.manager.get_instrument_provider(BROKER) is harness.provider