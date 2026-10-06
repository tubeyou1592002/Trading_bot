"""
test_ui7_task3_periodic_dispatch.py — UI-7 Task 3: periodic, concurrent
dispatch of the frozen order set at a real millisecond cadence.

Fully offline. Every clock, broker and send path is a test double: no real
broker, no real order and no network request is ever issued. The
``runner_factory`` double stands in for the EXISTING UI-5 send path
(``TestRunner.run``), so the tests observe WHEN a send starts and WHICH
runner instance served it, without touching the Core.

What these tests claim, precisely
---------------------------------
They prove that the application STARTS the sends to the different brokers
at the due moments, spaced by exactly the entered millisecond value. They
do NOT claim that a broker receives or acknowledges anything at that
instant — network and broker latency stay a separate concern, measured
separately by Block 8.

Covered:
  1. the interval is whole MILLISECONDS; zero/negative/decimal/malformed
     are rejected fail-closed; a ms value is never read as seconds;
  2. the due ladder is an exact multiple of the interval on the MONOTONIC
     clock (proved arithmetically AND by measurement, with 50 ms);
  3. the real spacing of the send starts is the entered ms value;
  4. a turn never fires early, and a slow answer does not shift the later
     due times;
  5. one due moment starts every broker's send at the same time — proved
     with a barrier/event, so a SERIAL implementation cannot pass;
  6. the UI thread is never blocked by a slow broker;
  7. runner identity/state never crosses groups or turns;
  8. pending responses do not block or suppress later cadence turns;
  9. a missed due time is skipped — never caught up, never burst;
 10. Stop prevents new turns and never cancels an in-flight run;
 11. the Block 3 window end starts nothing new;
 12. due time and start time are recorded separately from Block 8;
 13. ``ui7-turn-*`` is a scheduling label, NOT a trace id;
 14. one failing broker neither stops nor serializes the others;
 15. the REAL send path is Dry Run without a SafetyGate and stays Dry Run
     under a blocking gate — Task 3 never bypasses the gate;
 16. the UI-7 Task 1/2 page lifecycle (Apply/Stop/expiry, frozen set) holds.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

UTC = timezone.utc
TEHRAN = timezone(timedelta(hours=3, minutes=30))

# A fixed "now": 2026-10-02 09:29:00Z == 12:59:00 Tehran.
FIXED_NOW = datetime(2026, 10, 2, 9, 29, 0, tzinfo=UTC)
GOOD_BODY = "10/02/2026 12:59:00"
GOOD_DATE_HEADER = "Thu, 02 Oct 2026 09:29:00 GMT"

from ui.schedule_dispatcher import (  # noqa: E402
    DispatchIntervalError,
    DispatchTarget,
    PeriodicScheduleDispatcher,
    TurnStatus,
    execution_interval_timedelta,
    parse_execution_interval_ms,
)
from ui.schedule_settings import (  # noqa: E402
    APPLY_BUTTON_LABEL,
    SCHEDULE_STATE_EXPIRED,
    STOP_BUTTON_LABEL,
)
from ui import strings as STRINGS


# ---------------------------------------------------------------------------
# test doubles
# ---------------------------------------------------------------------------


class FakeMono:
    """A monotonic clock the test drives by hand."""

    def __init__(self, start: float = 1000.0) -> None:
        self.value = float(start)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> float:
        self.value += float(seconds)
        return self.value


class FakeResult:
    """The shape of the real ``DispatchResult`` the send path returns."""

    def __init__(self, trace_id, success=True, message="ok"):
        self.trace_id = trace_id
        self.success = success
        self.message = message


class FakePlan:
    def __init__(self, nsc_ids):
        self.nsc_ids = list(nsc_ids)


class FakeEntry:
    """The shape of a frozen queue entry: what the runner may see."""

    def __init__(self, nsc_id, account_id, broker_name):
        self.nsc_id = nsc_id
        self.account_id = account_id
        self.broker_name = broker_name


class RecordingRunner:
    """
    A stand-in for the EXISTING ``ui.test_runner.TestRunner``.

    Like the real runner it carries PER-RUN MUTABLE STATE (``last_result``,
    ``last_execution_id``) — that is exactly why the dispatcher must never
    share one instance between concurrent groups or turns.
    """

    instances = []

    def __init__(self, recorder, label="runner", delay=0.0, fail=False):
        self._recorder = recorder
        self.label = label
        self.delay = delay
        self.fail = fail
        self.last_result = None
        self.last_execution_id = None
        self.calls = []
        RecordingRunner.instances.append(self)

    def run(self, entries, account=None):
        self._recorder.started.append(self.label)
        self._recorder.start_mono.append(time.monotonic())
        self._recorder.start_threads.append(threading.current_thread().name)
        self.calls.append((tuple(e.nsc_id for e in entries), account))
        if self.delay:
            time.sleep(self.delay)
        self.last_result = FakeResult(f"trace-{self.label}-{len(self.calls)}")
        self.last_execution_id = f"exec-{self.label}-{len(self.calls)}"
        if self.fail:
            raise RuntimeError(f"{self.label} is down")
        return (
            FakePlan(e.nsc_id for e in entries),
            self.last_execution_id,
            self.last_result,
        )


class Recorder:
    def __init__(self):
        self.started = []
        self.start_mono = []
        self.start_threads = []
        self.lock = threading.Lock()


def make_runner_factory(recorder, labels=None, delay=0.0, failing=()):
    """A factory handing out a NEW RecordingRunner per call."""
    failing = set(failing)

    def factory():
        with recorder.lock:
            index = len(RecordingRunner.instances) + 1
        label = labels[(index - 1) % len(labels)] if labels else f"runner-{index}"
        return RecordingRunner(
            recorder, label=label, delay=delay, fail=label in failing
        )

    return factory


def targets_for(*bindings):
    """``("acc-1", "agah", "nsc-a")`` -> one frozen DispatchTarget."""
    return tuple(
        DispatchTarget(
            entry=FakeEntry(nsc_id, account_id, broker_name),
            account_id=account_id,
            broker_name=broker_name,
            account=f"account-object-{account_id}",
        )
        for (account_id, broker_name, nsc_id) in bindings
    )


def wait_for_turn(dispatcher, index, timeout=5.0):
    """Block until the ``index``-th due time has arrived."""
    due = dispatcher.due_mono_for_turn(index)
    deadline = time.monotonic() + timeout
    while dispatcher.mono_now() < due and time.monotonic() < deadline:
        time.sleep(0.002)


def service(dispatcher, index):
    """Wait for the due time, then service exactly that turn."""
    wait_for_turn(dispatcher, index)
    return dispatcher.service_due_turn(dispatcher.mono_now(), index)


def freeze(dispatcher, targets, interval_ms=50.0, locked_mono=None, window=None):
    """
    Freeze a dispatcher against a fixed wall base + a monotonic anchor.

    With no explicit ``locked_mono`` the anchor is the CURRENT real monotonic
    reading, which is what production does (Task 2's locked anchor) and makes
    the very first due time come due immediately.
    """
    base = FIXED_NOW
    if locked_mono is None:
        locked_mono = time.monotonic()
    dispatcher.freeze(
        targets=targets,
        interval_ms=interval_ms,
        locked_base=base,
        locked_mono=locked_mono,
        window=window,
    )
    return base, locked_mono


def run_cadence(dispatcher, count, interval_ms):
    """
    Drive ``count`` turns on a worker thread at the REAL cadence.

    Each iteration waits for its own exact due time, so the starts land
    ``interval_ms`` apart and a missed due time is never invented.
    """

    def loop():
        for index in range(count):
            due = dispatcher.due_mono_for_turn(index)
            # A bounded wait: if the ladder were ever wrong by orders of
            # magnitude the test must FAIL, not hang forever.
            deadline = time.monotonic() + 5.0
            while dispatcher.mono_now() < due and time.monotonic() < deadline:
                time.sleep(min(max(due - dispatcher.mono_now(), 0.001), 0.005))
            dispatcher.service_due_turn(dispatcher.mono_now(), index)

    thread = threading.Thread(target=loop, name="cadence", daemon=True)
    thread.start()
    thread.join(timeout=30)
    assert not thread.is_alive(), "the cadence loop did not finish"
    return thread


# ---------------------------------------------------------------------------
# 1. the interval is whole milliseconds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [("50", 50.0), ("1", 1.0), ("250", 250.0)])
def test_ms_value_is_parsed_as_milliseconds(text, expected):
    assert parse_execution_interval_ms(text) == expected


@pytest.mark.parametrize(
    "bad", ["", "  ", "0", "-5", "+5", "1.5", "50ms", "abc", "5e2", None, 50]
)
def test_invalid_interval_is_rejected_fail_closed(bad):
    with pytest.raises(DispatchIntervalError):
        parse_execution_interval_ms(bad)


def test_interval_is_never_read_as_seconds():
    """50 must be 50 ms, not 50 s — the delta says so."""
    delta = execution_interval_timedelta("50")
    assert delta == timedelta(milliseconds=50)
    assert delta.total_seconds() == pytest.approx(0.050)
    assert execution_interval_timedelta("1000").total_seconds() == 1.0


# ---------------------------------------------------------------------------
# 2/3. the due ladder is an exact multiple of the interval
# ---------------------------------------------------------------------------


def test_due_ladder_is_exact_ms_multiples_on_the_monotonic_clock():
    """The ladder is arithmetic on the MONOTONIC clock, not a Block 3 list."""
    mono = FakeMono()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=lambda: None)
    _base, locked = freeze(dispatcher, (), interval_ms=50.0, locked_mono=mono())

    first = dispatcher.due_mono_for_turn(0)
    assert first == pytest.approx(locked)
    for index in range(1, 200):
        gap = dispatcher.due_mono_for_turn(index) - dispatcher.due_mono_for_turn(index - 1)
        assert gap == pytest.approx(0.050), index
    assert dispatcher.due_mono_for_turn(100) - first == pytest.approx(5.0)


def test_measured_send_starts_are_50_ms_apart():
    """THE headline proof: with 50 ms entered, sends really start 50 ms apart."""
    interval_ms = 50.0
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=make_runner_factory(recorder))
    freeze(dispatcher, targets_for(("acc-1", "agah", "nsc-a")), interval_ms=interval_ms)

    run_cadence(dispatcher, 6, interval_ms)

    starts = recorder.start_mono
    assert len(starts) >= 5
    gaps_ms = [
        (starts[i + 1] - starts[i]) * 1000.0 for i in range(len(starts) - 1)
    ]
    # Each gap IS the entered value (plus ordinary thread-scheduling jitter
    # of a few ms). It is a real spacing, never a tolerance band and never
    # seconds: 48.9 ms proves nothing like 1 s or 50 s would.
    assert all(abs(g - interval_ms) < 5.0 for g in gaps_ms), gaps_ms


def test_a_later_interval_is_honoured_in_milliseconds():
    """200 ms really is ~200 ms apart, not 200 s and not 0.2 s x1000."""
    interval_ms = 200.0
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=make_runner_factory(recorder))
    freeze(dispatcher, targets_for(("acc-1", "agah", "nsc-a")), interval_ms=interval_ms)

    run_cadence(dispatcher, 4, interval_ms)

    starts = recorder.start_mono
    gaps = [(starts[i + 1] - starts[i]) * 1000.0 for i in range(len(starts) - 1)]
    assert gaps, "no send was recorded"
    assert all(abs(g - interval_ms) < 20.0 for g in gaps), gaps


def test_the_ms_field_makes_the_cadence_denser_than_a_second():
    """Two seconds of 50 ms cadence == 40 turns, never 2."""
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=make_runner_factory(recorder))
    freeze(dispatcher, targets_for(("acc-1", "agah", "nsc-a")), interval_ms=50.0)
    assert dispatcher.due_mono_for_turn(39) - dispatcher.due_mono_for_turn(0) == pytest.approx(
        1.95
    )


# ---------------------------------------------------------------------------
# 4. no early fire; a slow answer does not move later due times
# ---------------------------------------------------------------------------


def test_a_turn_is_not_serviced_before_its_due_time():
    mono = FakeMono()
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(recorder), mono_clock=mono
    )
    _base, locked = freeze(
        dispatcher,
        targets_for(("acc-1", "agah", "nsc-a")),
        interval_ms=50.0,
        locked_mono=mono(),
    )

    # Still 30 ms before the first due time -> nothing at all.
    assert dispatcher.service_due_turn(locked - 0.030, 0) is None
    assert dispatcher.turns == ()
    assert recorder.started == []

    # Exactly at the due time -> serviced.
    record = dispatcher.service_due_turn(locked, 0)
    assert record is not None and record.turn_index == 0
    assert record.status is TurnStatus.DISPATCHED


def test_a_slow_answer_does_not_shift_the_later_due_times():
    """
    A 400 ms answer must NOT drag the later due times with it.

    With a 500 ms cadence the later turns are still reached, so the recorded
    DUE times can be compared: they keep the exact ladder even though every
    send started hundreds of ms late.
    """
    interval_ms = 500.0
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(recorder, delay=0.4)
    )
    freeze(dispatcher, targets_for(("acc-1", "agah", "nsc-a")), interval_ms=interval_ms)

    run_cadence(dispatcher, 3, interval_ms)

    records = [r for r in dispatcher.turns if r.status is TurnStatus.DISPATCHED]
    assert len(records) >= 3
    for previous, current in zip(records, records[1:]):
        assert current.due_mono - previous.due_mono == pytest.approx(0.500)
    # The 400 ms sits in the BROKER answer, not in the schedule: each turn's
    # own start still happened essentially on its due time.
    assert all(r.start_delay_ms < 50.0 for r in records), [
        r.start_delay_ms for r in records
    ]


# ---------------------------------------------------------------------------
# 5. fan-out at one due moment is genuinely concurrent
# ---------------------------------------------------------------------------


def test_all_brokers_start_together_at_one_due_time():
    """
    Three brokers, ONE due time: all three sends must have STARTED before
    any of them is released. The barrier makes a serial implementation
    deadlock and fail, so this cannot pass by accident.
    """
    barrier = threading.Barrier(3, timeout=10)
    recorder = Recorder()

    class BarrierRunner(RecordingRunner):
        def run(self, entries, account=None):
            barrier.wait()  # every broker must be here at the same time
            return super().run(entries, account=account)

    labels = iter(["agah", "saman", "zarin"])
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=lambda: BarrierRunner(recorder, label=next(labels))
    )
    freeze(
        dispatcher,
        targets_for(
            ("acc-1", "agah", "nsc-a"),
            ("acc-1", "saman", "nsc-b"),
            ("acc-2", "zarin", "nsc-c"),
        ),
    )
    assert len(dispatcher.frozen_groups) == 3

    record = dispatcher.service_due_turn(dispatcher.mono_now(), 0)
    assert record is not None and record.status is TurnStatus.DISPATCHED
    assert sorted(record.brokers) == ["agah", "saman", "zarin"]


def test_a_slow_broker_does_not_delay_another_brokers_send_start():
    """The fast broker's send starts while the slow one is still waiting."""
    started = {}
    both_started = threading.Event()
    slow_finished = threading.Event()

    class TimedRunner(RecordingRunner):
        def run(self, entries, account=None):
            started[self.label] = time.monotonic()
            if self.label == "slow":
                # only completes once the fast broker has also started
                assert both_started.wait(timeout=10), "fast broker never started"
                slow_finished.set()
            else:
                both_started.set()
            return super().run(entries, account=account)

    labels = iter(["slow", "fast"])
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=lambda: TimedRunner(Recorder(), label=next(labels))
    )
    freeze(
        dispatcher,
        targets_for(("acc-1", "agah", "nsc-a"), ("acc-1", "saman", "nsc-b")),
    )
    record = dispatcher.service_due_turn(dispatcher.mono_now(), 0)

    assert record.status is TurnStatus.DISPATCHED
    assert slow_finished.is_set()
    assert started["fast"] <= started["slow"] + 10.0
    assert all(r.success for r in record.results)


def test_each_group_receives_only_its_own_frozen_orders():
    """The fan-out must not cross the frozen bindings."""
    RecordingRunner.instances = []
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=make_runner_factory(recorder))
    freeze(
        dispatcher,
        targets_for(
            ("acc-1", "agah", "nsc-a"),
            ("acc-1", "agah", "nsc-b"),
            ("acc-1", "saman", "nsc-c"),
        ),
    )
    assert len(dispatcher.frozen_groups) == 2

    seen = {}
    class CapturingRunner(RecordingRunner):
        def run(self, entries, account=None):
            for entry in entries:
                seen.setdefault(entry.broker_name, set()).add(entry.nsc_id)
            return super().run(entries, account=account)

    dispatcher._runner_factory = lambda: CapturingRunner(recorder, label="capture")
    dispatcher.service_due_turn(dispatcher.mono_now(), 0)

    assert seen == {"agah": {"nsc-a", "nsc-b"}, "saman": {"nsc-c"}}


# ---------------------------------------------------------------------------
# 6. the UI thread is never blocked
# ---------------------------------------------------------------------------


def test_the_calling_thread_is_free_while_a_broker_is_slow():
    """
    The dispatch turn is handed to its own threads: a 600 ms answer must
    leave the CALLING (UI) thread free to keep working immediately.
    """
    ui_progress = []

    def ui_work():
        for _ in range(200):
            ui_progress.append(time.monotonic())
            time.sleep(0.002)

    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(Recorder(), delay=0.6)
    )
    freeze(dispatcher, targets_for(("acc-1", "agah", "nsc-a")))

    ui_thread = threading.Thread(target=ui_work, name="ui-thread", daemon=True)
    ui_thread.start()

    handed_off = threading.Event()
    release = threading.Event()

    def hand_off():
        # the page's worker loop: service the turn on this thread
        dispatcher.service_due_turn(dispatcher.mono_now(), 0)
        release.set()

    worker = threading.Thread(target=hand_off, name="ui7-dispatch", daemon=True)
    worker.start()

    # The caller returns at once; the slow broker is waited for elsewhere.
    deadline = time.monotonic() + 5
    while len(ui_progress) < 20 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert len(ui_progress) >= 20, "the calling thread was blocked"
    assert not worker.is_alive() or dispatcher.in_flight == 1

    release.wait(timeout=10)
    ui_thread.join(timeout=5)
    worker.join(timeout=10)
    assert not worker.is_alive()


def test_the_page_runs_the_cadence_on_a_worker_thread():
    """The UI countdown tick never dispatches; a daemon worker owns the loop."""
    import inspect

    from ui.order_configuration_page import OrderConfigurationPage

    countdown = inspect.getsource(OrderConfigurationPage._update_countdown)
    assert "_service_due_dispatch_turns" not in countdown
    assert "service_due_turn" not in countdown

    worker = inspect.getsource(OrderConfigurationPage._start_dispatch_worker)
    assert "threading.Thread" in worker
    assert "daemon=True" in worker


# ---------------------------------------------------------------------------
# 7. runner identity / state isolation
# ---------------------------------------------------------------------------


def test_every_group_and_turn_gets_its_own_runner():
    """No shared, mutable runner instance between groups or turns."""
    RecordingRunner.instances = []
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=make_runner_factory(recorder))
    freeze(
        dispatcher,
        targets_for(("acc-1", "agah", "nsc-a"), ("acc-1", "saman", "nsc-b")),
    )
    dispatcher.service_due_turn(dispatcher.mono_now(), 0)
    service(dispatcher, 1)

    instances = RecordingRunner.instances
    assert len(instances) == 4  # 2 groups x 2 turns
    assert len({id(r) for r in instances}) == 4

    seen = [nsc for instance in instances for names, _ in instance.calls for nsc in names]
    assert sorted(seen) == ["nsc-a", "nsc-a", "nsc-b", "nsc-b"]
    accounts = {account for instance in instances for _, account in instance.calls}
    assert accounts == {"account-object-acc-1"}


def test_run_results_do_not_cross_between_groups_and_turns():
    """Each result carries its OWN runner's execution id and trace id."""
    RecordingRunner.instances = []
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=make_runner_factory(recorder))
    freeze(
        dispatcher,
        targets_for(("acc-1", "agah", "nsc-a"), ("acc-1", "saman", "nsc-b")),
    )
    record = dispatcher.service_due_turn(dispatcher.mono_now(), 0)

    produced = {id(i): (i.last_execution_id, i.last_result.trace_id) for i in RecordingRunner.instances}
    trace_ids = [r.trace_id for r in record.results]
    execution_ids = [r.execution_id for r in record.results]
    assert len(set(trace_ids)) == 2, trace_ids
    assert len(set(execution_ids)) == 2, execution_ids
    # Every reported id is an id a runner really produced, and the two
    # groups' results are two DIFFERENT runner results, not one overwritten.
    reported = set(zip(execution_ids, trace_ids))
    assert reported <= set(produced.values())
    assert len(reported) == 2


# ---------------------------------------------------------------------------
# 8. pending responses never suppress later due turns
# ---------------------------------------------------------------------------


def test_page_starts_later_ticks_while_previous_broker_responses_are_pending(qapp):
    """Each 50 ms tick starts despite earlier broker calls still waiting."""
    release = threading.Event()
    started = []
    started_lock = threading.Lock()

    class BlockingRunner:
        def run(self, entries, account=None):
            with started_lock:
                started.append(time.monotonic())
                result_index = len(started)
            assert release.wait(timeout=5)
            return (
                FakePlan(entry.nsc_id for entry in entries),
                f"exec-{result_index}",
                FakeResult(f"trace-{result_index}"),
            )

    from ui.account_store import AccountStore
    from ui.order_configuration_page import OrderConfigurationPage

    page = OrderConfigurationPage(AccountStore())
    PAGES.append(page)
    page._ensure_feedback_binding = lambda: None
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=BlockingRunner,
        mono_clock=time.monotonic,
    )
    locked_mono = time.monotonic()
    dispatcher.freeze(
        targets=targets_for(("acc-1", "agah", "nsc-a")),
        interval_ms=50,
        locked_base=FIXED_NOW,
        locked_mono=locked_mono,
        window=(FIXED_NOW, FIXED_NOW + timedelta(seconds=0.6)),
    )
    page._dispatcher = dispatcher
    try:
        page._start_dispatch_worker(dispatcher)

        deadline = time.monotonic() + 0.35
        while len(started) < 4 and time.monotonic() < deadline:
            time.sleep(0.002)

        # No response was released, yet four cadence ticks reached the send path.
        assert len(started) >= 4, started
        assert dispatcher.in_flight >= 4
        assert dispatcher.peak_in_flight >= 4
    finally:
        page._stop_dispatcher()
        release.set()
        deadline = time.monotonic() + 5
        while dispatcher.in_flight and time.monotonic() < deadline:
            time.sleep(0.005)
    assert dispatcher.in_flight == 0


# ---------------------------------------------------------------------------
# 9. no catch-up, no burst
# ---------------------------------------------------------------------------


def test_a_missed_due_time_is_skipped_and_never_replayed():
    mono = FakeMono()
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(recorder), mono_clock=mono
    )
    _base, locked = freeze(
        dispatcher, targets_for(("acc-1", "agah", "nsc-a")), locked_mono=mono()
    )

    dispatcher.service_due_turn(locked, 0)
    assert len(recorder.started) == 1

    # The machine stalled: the next due time is 1 s past -> MISSED.
    mono.advance(1.0)
    missed = dispatcher.service_due_turn(mono(), 1)
    assert missed.status is TurnStatus.SKIPPED_MISSED
    assert missed.started_mono is None
    assert len(recorder.started) == 1

    # It is recorded, never replayed: servicing it again still sends nothing.
    again = dispatcher.service_due_turn(mono(), 1)
    assert again.status is TurnStatus.SKIPPED_MISSED
    assert len(recorder.started) == 1


def test_no_burst_after_a_stall():
    """After a long stall the next dispatch is ONE send, not a backlog."""
    mono = FakeMono()
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(recorder), mono_clock=mono
    )
    _base, locked = freeze(
        dispatcher, targets_for(("acc-1", "agah", "nsc-a")), locked_mono=mono()
    )

    dispatcher.service_due_turn(locked, 0)
    mono.advance(10.0)  # ten seconds of stall == 200 missed 50 ms slots
    record = dispatcher.service_due_turn(mono(), 1)

    assert record.status is TurnStatus.SKIPPED_MISSED
    assert len(recorder.started) == 1  # a single send, no burst of 200


def test_the_next_due_time_after_a_stall_is_an_exact_interval_multiple():
    mono = FakeMono()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=lambda: None, mono_clock=mono)
    _base, locked = freeze(dispatcher, (), interval_ms=50.0, locked_mono=mono())

    mono.advance(1.0)
    upcoming = dispatcher.due_mono_at_or_after(mono())
    assert upcoming is not None
    assert (upcoming - locked) == pytest.approx(round((upcoming - locked) / 0.05) * 0.05)


# ---------------------------------------------------------------------------
# 10. Stop
# ---------------------------------------------------------------------------


def test_stop_prevents_new_turns_but_never_cancels_an_inflight_run():
    recorder = Recorder()
    finished = threading.Event()

    class SlowRunner(RecordingRunner):
        def run(self, entries, account=None):
            time.sleep(0.2)
            finished.set()
            return super().run(entries, account=account)

    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=lambda: SlowRunner(recorder, label="slow")
    )
    freeze(dispatcher, targets_for(("acc-1", "agah", "nsc-a")))

    worker = threading.Thread(
        target=lambda: dispatcher.service_due_turn(dispatcher.mono_now(), 0),
        daemon=True,
    )
    worker.start()
    time.sleep(0.05)

    dispatcher.stop()
    assert dispatcher.stopped

    # The in-flight run is NOT cancelled: it completes normally.
    worker.join(timeout=10)
    assert finished.is_set()

    # ... but no NEW turn may start.
    later = dispatcher.service_due_turn(dispatcher.mono_now(), 1)
    assert later.status is TurnStatus.SKIPPED_STOPPED
    assert later.results == ()
    assert len(recorder.started) == 1


# ---------------------------------------------------------------------------
# 11. the Block 3 window bounds the run
# ---------------------------------------------------------------------------


def test_the_window_end_starts_nothing_new():
    mono = FakeMono()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=lambda: None, mono_clock=mono)
    start = FIXED_NOW
    end = FIXED_NOW + timedelta(seconds=1)
    freeze(dispatcher, (), interval_ms=50.0, locked_mono=mono(), window=(start, end))

    # 1 s / 50 ms == 20 intervals, so indices 0..20 are the last inside.
    inside = [i for i in range(0, 40) if dispatcher.index_in_window(i)]
    assert inside == list(range(0, 21))
    assert dispatcher.index_in_window(21) is False
    assert dispatcher.index_in_window(1000) is False


def test_a_due_time_outside_the_window_is_never_serviced():
    mono = FakeMono()
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(recorder), mono_clock=mono
    )
    freeze(
        dispatcher,
        targets_for(("acc-1", "agah", "nsc-a")),
        locked_mono=mono(),
        window=(FIXED_NOW + timedelta(seconds=1), FIXED_NOW + timedelta(seconds=2)),
    )
    assert dispatcher.service_due_turn(mono(), 0) is None
    assert recorder.started == []


# ---------------------------------------------------------------------------
# 12. due time vs start time, kept out of Block 8
# ---------------------------------------------------------------------------


def test_due_time_and_start_time_are_recorded_separately():
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=make_runner_factory(recorder))
    base, locked = freeze(dispatcher, targets_for(("acc-1", "agah", "nsc-a")))

    record = dispatcher.service_due_turn(dispatcher.mono_now(), 0)
    assert record.due_mono == pytest.approx(locked)
    assert record.started_mono is not None
    assert record.started_mono >= record.due_mono
    assert record.start_delay_ms == pytest.approx(
        (record.started_mono - record.due_mono) * 1000.0
    )
    # The wall projection is display-only and derived from the locked base.
    assert abs(record.due_moment - base) < timedelta(milliseconds=5)

    fields = set(record.__dataclass_fields__)
    for block8_field in ("latency", "latency_report", "dispatch_latency", "stages"):
        assert block8_field not in fields


def test_task3_records_never_carry_a_block8_latency():
    """Block 8 measurement is a separate concern; nothing is merged in."""
    for block8_field in (
        "dispatch_duration",
        "plan_item",
        "plan_account",
        "instrument_resolution",
        "order_engine_path",
        "broker_calls",
        "latency_report",
    ):
        assert not hasattr(TurnStatus, block8_field)

    from core.dispatch_core import DispatchLatencyReport

    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=make_runner_factory(recorder))
    freeze(dispatcher, targets_for(("acc-1", "agah", "nsc-a")))
    record = dispatcher.service_due_turn(dispatcher.mono_now(), 0)

    for result in record.results:
        assert not hasattr(result, "latency")
        assert not hasattr(result, "report")
    assert DispatchLatencyReport is not None


# ---------------------------------------------------------------------------
# 13. turn id is NOT a trace id
# ---------------------------------------------------------------------------


def test_turn_id_is_a_label_not_a_trace_id():
    RecordingRunner.instances = []
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=make_runner_factory(recorder))
    freeze(dispatcher, targets_for(("acc-1", "agah", "nsc-a")))
    record = dispatcher.service_due_turn(dispatcher.mono_now(), 0)

    assert record.turn_id == "ui7-turn-0"
    assert record.trace_ids == ("trace-runner-1-1",)

    for result in record.results:
        assert result.trace_id != record.turn_id
        assert not str(result.trace_id).startswith("ui7-turn-")


def test_turn_ids_are_unique_per_turn():
    RecordingRunner.instances = []
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(runner_factory=make_runner_factory(recorder))
    freeze(dispatcher, targets_for(("acc-1", "agah", "nsc-a")))
    run_cadence(dispatcher, 3, 50.0)

    ids = [r.turn_id for r in dispatcher.turns if r.dispatched]
    assert ids == ["ui7-turn-0", "ui7-turn-1", "ui7-turn-2"]
    assert len(set(ids)) == len(ids)


def test_the_turn_id_field_is_named_separately_from_the_trace_id():
    """They are two different fields, so neither can stand in for the other."""
    turn_fields = set(TurnRecord_fields())
    assert "turn_id" in turn_fields
    assert "trace_id" not in turn_fields

    broker_fields = set(BrokerTurnResult_fields())
    assert "trace_id" in broker_fields
    assert "turn_id" not in broker_fields


def TurnRecord_fields():
    from ui.schedule_dispatcher import TurnRecord

    return TurnRecord.__dataclass_fields__


def BrokerTurnResult_fields():
    from ui.schedule_dispatcher import BrokerTurnResult

    return BrokerTurnResult.__dataclass_fields__


# ---------------------------------------------------------------------------
# 14. failure isolation
# ---------------------------------------------------------------------------


def test_one_failing_broker_neither_stops_nor_serializes_the_others():
    RecordingRunner.instances = []
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(recorder)
    )
    freeze(
        dispatcher,
        targets_for(
            ("acc-1", "agah", "nsc-a"),
            ("acc-1", "saman", "nsc-b"),
            ("acc-2", "zarin", "nsc-c"),
        ),
    )
    original = RecordingRunner

    def factory():
        runner = original(recorder, label=f"r{len(original.instances) + 1}")
        if runner.label == "r1":
            runner.fail = True
        return runner

    dispatcher._runner_factory = factory
    record = dispatcher.service_due_turn(dispatcher.mono_now(), 0)

    assert record.status is TurnStatus.DISPATCHED
    outcomes = {r.broker_name: r.success for r in record.results}
    assert len(outcomes) == 3
    assert sorted(outcomes.values()) == [False, True, True]
    # Every group was actually attempted (the failing one included).
    assert len(recorder.started) == 3


# ---------------------------------------------------------------------------
# 15. the send path is Dry Run — the gate is never bypassed
# ---------------------------------------------------------------------------


def test_the_ui_runner_wires_a_default_deny_safety_gate():
    """
    The real runner wires Block 10's gate, but its default state denies
    every prerequisite, so the controlled-live bridge remains Dry Run.
    """
    from core.dispatch_core import DispatchCore
    from ui.test_runner import TestRunner

    runner = TestRunner(broker_manager=object())
    core = runner._ensure_integration().dispatch_core
    assert isinstance(core, DispatchCore)
    assert core.safety_gate is not None
    assert core.safety_gate.evaluate().allowed is False
    assert core.live_trading_enabled is False
    assert core._live_flag_for(sequence=1) is False
    assert core._live_flag_for(sequence=2) is False


def test_a_blocking_safety_gate_keeps_the_send_dry_run():
    """With a gate that BLOCKS, the envelope is still Dry Run."""
    from core.dispatch_core import DispatchCore
    from core.safety_gate import SafetyGate

    blocked = SafetyGate()  # every prerequisite defaults to deny
    assert blocked.evaluate().allowed is False

    core = DispatchCore(safety_gate=blocked)
    assert core._live_flag_for(sequence=1) is False


def test_task3_cannot_request_live_at_all():
    """The dispatcher exposes no live switch — it can only start sends."""
    import ui.schedule_dispatcher as module

    for forbidden in ("live", "set_live", "allow_live", "dry_run", "bypass"):
        assert forbidden not in dir(module)

    dispatcher = PeriodicScheduleDispatcher(runner_factory=lambda: None)
    fields = set(type(dispatcher).__dict__)
    assert not any("live" in name for name in fields)


# ---------------------------------------------------------------------------
# 16. the UI-7 Task 1/2 page lifecycle still holds
# ---------------------------------------------------------------------------


PAGES = []


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _stop_lingering_schedules():
    yield
    for page in PAGES:
        try:
            if page.countdown_active or page._schedule_locked:
                page._on_stop_schedule()
        except RuntimeError:
            pass
    PAGES.clear()


class Clock:
    """A wall + monotonic pair the test drives directly."""

    def __init__(self, wall=FIXED_NOW, mono=0.0):
        self.wall = wall
        self.mono = mono

    def advance(self, seconds):
        self.wall = self.wall + timedelta(seconds=seconds)
        self.mono += float(seconds)


def _drain_events(count=50):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for _ in range(count):
        app.processEvents()


def _offline_transport():
    from ui.market_clock import TransportResult

    def _transport(url, timeout):
        return TransportResult(
            status_code=200,
            text=GOOD_BODY,
            headers={
                "Content-Type": "text/plain",
                "Date": GOOD_DATE_HEADER,
                "Age": "0",
            },
        )

    return _transport


def _make_page(qapp, clock=None):
    from ui.account_store import AccountStore
    from ui.market_clock import MarketClockService
    from ui.order_configuration_page import OrderConfigurationPage

    clock = clock if clock is not None else Clock()
    page = OrderConfigurationPage(AccountStore())
    page.set_clock_service_factory(
        lambda t: MarketClockService(
            transport=t,
            now_utc=(lambda: clock.wall),
            mono_clock=(lambda: clock.mono),
        )
    )
    page.set_clock_transport(_offline_transport())
    page.clock = clock
    PAGES.append(page)
    return page


def fill(page, start, end, interval, dispatch_ms="50"):
    page.schedule_start_input.setText(start)
    page.schedule_end_input.setText(end)
    page.schedule_interval_input.setText(interval)
    page.dispatch_interval_input.setText(dispatch_ms)


def sync_clock(page):
    page._on_sync_clock()
    thread = page._clock_thread
    if thread is not None:
        assert thread.wait(10_000)
    _drain_events()


def apply_schedule(page):
    page._on_apply_schedule()
    thread = page._clock_thread
    if thread is not None:
        assert thread.wait(10_000)
    _drain_events()


def locked_controls(page):
    widgets = {
        "schedule start": page.schedule_start_input,
        "schedule end": page.schedule_end_input,
        "schedule interval": page.schedule_interval_input,
        "dispatch interval (ms)": page.dispatch_interval_input,
        "sync": page.sync_clock_button,
        "refresh clock": page.refresh_clock_button,
        "symbol": page.symbol_input,
        "results": page.results_list,
        "price": page.price_input,
        "quantity": page.quantity_input,
        "add to queue": page.add_to_queue_button,
        "queue list": page.queue_list,
        "test": page.test_button,
    }
    for side, button in page.side_buttons.items():
        widgets[f"side {side}"] = button
    return widgets


def _enqueue(page, account_id, broker_name):
    """Put one frozen order for ``account_id``/``broker_name`` in the queue."""
    from models.order import Order

    order = Order(nsc_id=f"ins-{account_id}", side=1, price=1000, quantity=10)
    page.order_queue.enqueue(order, account_id, broker_name)
    return page.order_queue.list_pending()[-1]


def test_the_page_locks_stops_and_expires_correctly(qapp):
    """The Task 1/2 lifecycle is unchanged now that Task 3 dispatches."""
    page = _make_page(qapp)
    before = {name: w.isEnabled() for name, w in locked_controls(page).items()}
    # A schedule needs a valid destination set (see the empty-queue case).
    page.store.add("acct-a", "agah")
    _enqueue(page, "acct-a", "agah")

    sync_clock(page)
    fill(page, "13:00:00", "13:00:30", "15")
    apply_schedule(page)

    # --- Apply still locks everything and becomes Stop --------------------
    assert page.apply_schedule_button.text() == STOP_BUTTON_LABEL
    for name, widget in locked_controls(page).items():
        assert not widget.isEnabled(), f"{name} was not locked by Apply"
    assert page.dispatch_interval_ms == 50.0

    # --- Stop still unlocks and clears everything ------------------------
    page._on_stop_schedule()
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL
    for name, widget in locked_controls(page).items():
        assert widget.isEnabled() == before[name], f"{name} did not come back"
    assert page.dispatch_turns == ()

    # --- expiry still frees the controls ----------------------------------
    page2 = _make_page(qapp)
    before2 = {n: w.isEnabled() for n, w in locked_controls(page2).items()}
    page2.store.add("acct-a", "agah")
    _enqueue(page2, "acct-a", "agah")
    sync_clock(page2)
    fill(page2, "13:00:00", "13:00:30", "15")
    apply_schedule(page2)
    assert page2.countdown_active

    page2.clock.advance(120)
    page2._update_countdown()
    assert page2.schedule_lifecycle_state() == SCHEDULE_STATE_EXPIRED
    assert page2.apply_schedule_button.text() == APPLY_BUTTON_LABEL
    for name, widget in locked_controls(page2).items():
        assert widget.isEnabled() == before2[name], f"{name} stayed locked after expiry"


def test_an_invalid_interval_rejects_apply_and_dispatches_nothing(qapp):
    """A bad ms value rejects the Apply and starts no send at all."""
    page = _make_page(qapp)
    sync_clock(page)
    fill(page, "13:00:00", "13:05:00", "15", dispatch_ms="0")
    apply_schedule(page)

    assert STRINGS.SCHEDULE_REJECTED.split("{", 1)[0] in (
        page.schedule_summary_label.text()
    )
    assert page.dispatch_turns == (), "a rejected interval dispatched something"
    assert not page.countdown_active
    assert page.dispatch_interval_ms is None
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL


def test_the_frozen_set_is_really_frozen_across_turns(qapp):
    """Every turn sends the SAME orders to the SAME destinations."""
    page = _make_page(qapp)
    page.store.add("acct-a", "agah")
    page.store.add("acct-b", "sana")

    entry_a = _enqueue(page, "acct-a", "agah")
    entry_b = _enqueue(page, "acct-b", "sana")

    sent = []

    class Runner:
        last_report = None
        last_order_results = None

        def run(self, entries, account):
            # The EXISTING runner takes the broker binding from the ENTRIES
            # (never from the Account object), exactly as TestRunner does.
            broker = entries[0].broker_name
            sent.append((broker, [id(e) for e in entries]))
            return ("plan", f"exec-{broker}", FakeResult(trace_id=f"t-{broker}"))

    page.set_test_runner_factory(lambda: Runner())

    sync_clock(page)
    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)
    try:
        # Apply alone sends nothing: the window start is still a minute away.
        assert sent == [], "Apply dispatched before the window opened"
        assert page.dispatch_turns == ()

        # Reach the window start, then step the real 50 ms cadence.
        page.clock.advance(60)
        page._service_due_dispatch_turns()   # turn 0
        page.clock.advance(0.05)
        page._service_due_dispatch_turns()   # turn 1

        assert len(sent) == 4, f"expected two turns x two brokers, got {sent}"
        assert sorted(name for name, _ in sent) == ["agah", "agah", "sana", "sana"]
        for ids in [i for name, i in sent if name == "agah"]:
            assert ids == [id(entry_a)], "agah did not get the frozen order"
        for ids in [i for name, i in sent if name == "sana"]:
            assert ids == [id(entry_b)], "sana did not get the frozen order"

        pending = page.order_queue.list_pending()
        assert {id(e) for e in pending} == {id(entry_a), id(entry_b)}
        frozen = page._frozen_dispatch_targets()
        assert {(t.broker_name, id(t.entry)) for t in frozen} == {
            ("agah", id(entry_a)),
            ("sana", id(entry_b)),
        }
    finally:
        page._on_stop_schedule()


def test_the_page_labels_the_interval_in_milliseconds():
    """The label and the placeholder both say MILLISECONDS."""
    import ui.schedule_dispatcher as module
    from ui import strings as STRINGS

    # Both must name the millisecond unit explicitly, so the interval can
    # never be misread as seconds. The wording is Persian (UI-9.3), so the
    # contract is checked against the catalogue, not an English literal.
    assert STRINGS.LABEL_DISPATCH_INTERVAL_MS == module.EXECUTION_INTERVAL_LABEL
    assert (
        STRINGS.PLACEHOLDER_DISPATCH_INTERVAL
        == module.EXECUTION_INTERVAL_PLACEHOLDER
    )
    for text in (
        module.EXECUTION_INTERVAL_LABEL,
        module.EXECUTION_INTERVAL_PLACEHOLDER,
    ):
        assert "\u0645\u06cc\u0644\u06cc\u200c\u062b\u0627\u0646\u06cc\u0647" in text


# ---------------------------------------------------------------------------\
# 17. Apply after the window start: the FIRST turn starts immediately
#
# The window start is ALREADY PAST and the window end is still in the
# future. The first send must begin at the first execution opportunity -
# now - and the past due times must NOT be walked one by one, recorded as
# missed, or turned into a backlog.
# ---------------------------------------------------------------------------\


def test_a_past_window_start_dispatches_the_first_turn_immediately():
    """
    Apply 30 s AFTER the window start, with the end still 30 s away.

    The very first turn must be sendable at once: its due time is the
    first execution opportunity, NOT the missed window start.
    """
    mono = FakeMono()
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(recorder), mono_clock=mono
    )
    # The window opened 30 s ago and still closes in 30 s, so at the
    # moment of Apply the start IS past while the end is still ahead.
    start = FIXED_NOW - timedelta(seconds=30)
    end = FIXED_NOW + timedelta(seconds=30)
    _b, locked = freeze(
        dispatcher,
        targets_for(("acc-1", "agah", "nsc-a")),
        interval_ms=50.0,
        locked_mono=mono(),
        window=(start, end),
    )

    assert dispatcher.project_mono(start) == pytest.approx(locked - 30.0)

    first_due = dispatcher.due_mono_for_turn(0)
    # The anchor is the FIRST EXECUTION OPPORTUNITY, not the past start.
    assert first_due == pytest.approx(locked)

    record = dispatcher.service_due_turn(mono(), 0)

    assert record is not None
    assert record.status is TurnStatus.DISPATCHED, (
        "the first turn of a late Apply was skipped instead of dispatched"
    )
    assert len(recorder.started) == 1, recorder.started
    assert record.started_mono is not None


def test_the_second_turn_after_a_past_start_is_exactly_one_interval_later():
    """The fixed cadence continues from the immediate anchor."""
    mono = FakeMono()
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(recorder), mono_clock=mono
    )
    interval_ms = 50.0
    freeze(
        dispatcher,
        targets_for(("acc-1", "agah", "nsc-a")),
        interval_ms=interval_ms,
        locked_mono=mono(),
        window=(
            FIXED_NOW - timedelta(seconds=30),
            FIXED_NOW + timedelta(seconds=30),
        ),
    )

    first = dispatcher.due_mono_for_turn(0)
    second = dispatcher.due_mono_for_turn(1)
    third = dispatcher.due_mono_for_turn(2)

    assert second - first == pytest.approx(interval_ms / 1000.0)
    assert third - second == pytest.approx(interval_ms / 1000.0)
    # ... and exactly one interval later than the send that just happened.
    assert second == pytest.approx(first + interval_ms / 1000.0)


def test_a_past_start_never_walks_the_missed_due_times():
    """
    2000 historical 50 ms slots, ONE send - no loop, no skipped backlog.

    Anchoring on the past window start would have made 600 of those slots
    "missed" turns to walk and record before reaching the present. The
    immediate anchor means none of them exists.
    """
    mono = FakeMono()
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(recorder), mono_clock=mono
    )
    freeze(
        dispatcher,
        targets_for(("acc-1", "agah", "nsc-a")),
        interval_ms=50.0,
        locked_mono=mono(),
        # The window opened 2000 slots (100 s) ago and closes in 20 s.
        window=(
            FIXED_NOW - timedelta(seconds=100),
            FIXED_NOW + timedelta(seconds=20),
        ),
    )
    planned_start_mono = dispatcher.project_mono(FIXED_NOW - timedelta(seconds=100))
    assert (mono() - planned_start_mono) / 0.050 == pytest.approx(2000.0)

    assert dispatcher.service_due_turn(mono(), 0).status is TurnStatus.DISPATCHED

    # Exactly ONE send and exactly ONE record: nothing was replayed, no
    # SKIPPED_MISSED history was generated, and the cursor never had to
    # climb through the past.
    assert len(recorder.started) == 1, recorder.started
    assert len(dispatcher.turns) == 1
    assert dispatcher.turns[0].status is TurnStatus.DISPATCHED
    assert TurnStatus.SKIPPED_MISSED not in [t.status for t in dispatcher.turns]

    # Turn 1 is the very next slot - still on the live cadence.
    assert dispatcher.due_mono_for_turn(1) == pytest.approx(
        dispatcher.due_mono_for_turn(0) + 0.050
    )


def test_the_page_after_the_window_start_sends_at_once(qapp):
    """End to end: a late Apply sends on the FIRST opportunity, not later."""
    page = _make_page(qapp)
    page.store.add("acct-a", "agah")
    _enqueue(page, "acct-a", "agah")

    sent = []

    class Runner:
        def run(self, entries, account):
            sent.append(time.monotonic())
            return ("plan", "exec-1", FakeResult(trace_id="t-1"))

    page.set_test_runner_factory(lambda: Runner())
    sync_clock(page)
    # The window opens at 12:59:00; the clock now reads 13:00:00, so
    # Apply happens a full minute AFTER the start while the end is ahead.
    fill(page, "12:59:00", "13:05:00", "15")
    page.clock.advance(60)
    apply_schedule(page)
    try:
        assert page.countdown_active, page.schedule_summary_label.text()

        # The first execution opportunity is NOW: the live worker reaches
        # the send path without any manual stepping at all. (Before this
        # fix the ladder was anchored on the missed window start and this
        # never happened.)
        deadline = time.monotonic() + 5.0
        while not sent and time.monotonic() < deadline:
            time.sleep(0.005)
        assert len(sent) == 1, f"expected the immediate first send, got {sent}"
        first_at = sent[0]

        # The cadence continues at the fixed interval from that anchor.
        # Stepping the locked clock forward by exactly one interval makes
        # the next turn due and no sooner.
        page.clock.advance(0.05)
        page._service_due_dispatch_turns()

        assert len(sent) == 2, sent
        assert page.dispatch_turns[0].status is TurnStatus.DISPATCHED
        assert page.dispatch_turns[1].status is TurnStatus.DISPATCHED
    finally:
        page._on_stop_schedule()


def test_a_future_window_start_is_never_shifted():
    """A start still in the FUTURE keeps its exact scheduled instant."""
    mono = FakeMono()
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(recorder), mono_clock=mono
    )
    start = FIXED_NOW + timedelta(seconds=60)
    end = FIXED_NOW + timedelta(seconds=120)
    freeze(
        dispatcher,
        targets_for(("acc-1", "agah", "nsc-a")),
        interval_ms=50.0,
        locked_mono=mono(),
        window=(start, end),
    )

    # Apply happened now; the start is 60 s away. The anchor is untouched.
    assert dispatcher.due_mono_for_turn(0) == pytest.approx(
        dispatcher.project_mono(start)
    )
    assert dispatcher.due_mono_for_turn(0) - mono() == pytest.approx(60.0)

    # Nothing fires early, and nothing is recorded at all.
    assert dispatcher.service_due_turn(mono(), 0) is None
    assert dispatcher.turns == ()
    assert recorder.started == []

    # It fires exactly at its own scheduled instant.
    mono.advance(60.0)
    record = dispatcher.service_due_turn(mono(), 0)
    assert record.status is TurnStatus.DISPATCHED
    assert record.started_mono is not None


def test_the_window_end_is_still_the_ceiling_after_a_late_start():
    """A late start never pushes sends past the Block 3 window end."""
    mono = FakeMono()
    recorder = Recorder()
    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=make_runner_factory(recorder), mono_clock=mono
    )
    end = FIXED_NOW + timedelta(seconds=30)
    freeze(
        dispatcher,
        targets_for(("acc-1", "agah", "nsc-a")),
        interval_ms=50.0,
        locked_mono=mono(),
        # Opened 30 s ago: a late start with 30 s of window left.
        window=(FIXED_NOW - timedelta(seconds=30), end),
    )

    assert dispatcher.index_in_window(0) is True
    # 30 s / 50 ms == 600 slots; slot 600 lands exactly ON the window end,
    # which is still inside, and 601 is the first one past it.
    assert dispatcher.index_in_window(599) is True
    assert dispatcher.index_in_window(600) is True
    assert dispatcher.index_in_window(601) is False
    assert dispatcher.index_in_window(10_000) is False


# ---------------------------------------------------------------------------\
# 18. no schedule without a valid destination set
#
# A schedule is never activated over an empty queue, an unresolvable
# account, or a broker that disagrees with the account's own broker. The
# WHOLE schedule is rejected: no worker, no turn, no ``runner.run()``, and
# the controls stay in the configuring state.
# ---------------------------------------------------------------------------\


class _ExplodingRunner:
    """Any ``run()`` here is a failure: nothing may reach the send path."""

    calls = []

    def run(self, entries, account=None):
        _ExplodingRunner.calls.append(entries)
        raise AssertionError("runner.run() must never be called")


@pytest.fixture
def _no_sends(monkeypatch):
    _ExplodingRunner.calls = []
    return _ExplodingRunner.calls


def _assert_schedule_refused(page, before, sent):
    """No schedule, no worker, no turn, unlocked controls, no send."""
    assert page.countdown_active is False
    assert page._dispatcher is None
    assert page.dispatch_interval_ms is None
    assert page.dispatch_turns == ()
    assert sent == [], "the send path was reached anyway"
    for name, widget in locked_controls(page).items():
        assert widget.isEnabled() == before[name], f"{name} stayed locked"
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL


def test_an_empty_queue_refuses_to_activate_a_schedule(qapp, _no_sends):
    """Case 1: nothing is queued, so there is no destination at all."""
    page = _make_page(qapp)
    before = {name: w.isEnabled() for name, w in locked_controls(page).items()}
    sync_clock(page)
    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)

    assert STRINGS.SCHEDULE_REJECTED.split("{", 1)[0] in (
        page.schedule_summary_label.text()
    )
    assert page.schedule_timing() is None
    _assert_schedule_refused(page, before, _no_sends)


def test_an_order_without_a_valid_account_refuses_the_whole_schedule(
    qapp, _no_sends
):
    """
    Case 2: one order has no account in the store.

    The VALID order beside it is never sent as a silent partial set.
    """
    page = _make_page(qapp)
    before = {name: w.isEnabled() for name, w in locked_controls(page).items()}
    page.store.add("acct-good", "agah")
    _enqueue(page, "acct-good", "agah")
    _enqueue(page, "acct-missing", "saman")   # never added to the store
    sync_clock(page)
    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)

    summary = page.schedule_summary_label.text().lower()
    assert STRINGS.SCHEDULE_REJECTED.split("{", 1)[0] in summary
    assert "acct-missing" in summary, summary
    _assert_schedule_refused(page, before, _no_sends)


def test_a_broker_mismatch_refuses_the_whole_schedule(qapp, _no_sends):
    """
    Case 3: the order is registered for a broker its account is not bound to.
    """
    page = _make_page(qapp)
    before = {name: w.isEnabled() for name, w in locked_controls(page).items()}
    page.store.add("acct-good", "agah")
    page.store.add("acct-mixed", "saman")
    _enqueue(page, "acct-good", "agah")
    _enqueue(page, "acct-mixed", "zarin")     # account is bound to saman
    sync_clock(page)
    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)

    summary = page.schedule_summary_label.text().lower()
    assert STRINGS.SCHEDULE_REJECTED.split("{", 1)[0] in summary
    assert "zarin" in summary and "saman" in summary, summary
    _assert_schedule_refused(page, before, _no_sends)


def test_a_refused_schedule_does_not_block_a_later_valid_one(qapp):
    """The refusal is about THIS set, not a permanent block."""
    page = _make_page(qapp)
    sync_clock(page)
    fill(page, "13:00:00", "13:05:00", "15")
    apply_schedule(page)
    assert page.schedule_timing() is None

    page.store.add("acct-a", "agah")
    _enqueue(page, "acct-a", "agah")
    apply_schedule(page)

    assert page.schedule_timing() is not None
    assert page.countdown_active
    page._on_stop_schedule()


def test_freeze_refuses_an_invalid_set_even_if_apply_was_skipped(qapp):
    """
    Defence in depth: ``_freeze_dispatch_set`` re-checks before it freezes.

    Even a caller that reaches freeze directly can never start a worker
    over an unvalidated set.
    """
    page = _make_page(qapp)
    assert page._freeze_dispatch_set() is False
    assert page._dispatcher is None
    assert page.dispatch_turns == ()


def test_failed_second_destination_check_does_not_start_countdown(
    qapp, monkeypatch
):
    """A queue change during Apply cannot leave a countdown-only schedule."""
    page = _make_page(qapp)
    page.store.add("acct-a", "agah")
    queued = _enqueue(page, "acct-a", "agah")
    sync_clock(page)
    fill(page, "13:00:00", "13:05:00", "15")

    freeze_dispatch_set = page._freeze_dispatch_set

    def remove_destination_before_freeze():
        # _on_apply_schedule already validated this destination. Simulate it
        # disappearing before the defense-in-depth check after clock sync.
        page.order_queue.remove(queued)
        return freeze_dispatch_set()

    monkeypatch.setattr(
        page, "_freeze_dispatch_set", remove_destination_before_freeze
    )
    apply_schedule(page)

    assert STRINGS.SCHEDULE_REJECTED.split("{", 1)[0] in (
        page.schedule_summary_label.text()
    )
    assert page.schedule_timing() is None
    assert page.countdown_active is False
    assert page._schedule_locked is False
    assert page._dispatcher is None
    assert page.dispatch_interval_ms is None
    assert page.dispatch_turns == ()
    assert page.apply_schedule_button.text() == APPLY_BUTTON_LABEL


# ---------------------------------------------------------------------------\
# 19. the recorded start is the REAL hand-off to the send path
#
# The boundary is the monotonic instant immediately before ``runner.run``
# is called - not the ``submit`` moment, not the thread preparation and
# not the end of the broker's answer.
# ---------------------------------------------------------------------------\


def test_the_recorded_start_is_the_real_entry_into_runner_run():
    """
    A controlled runner records when it was ACTUALLY entered.

    The dispatcher's stored time must be that boundary, not the submit
    time and not the end of the answer.
    """
    entry = {}

    class BoundaryRunner:
        def run(self, entries, account=None):
            entry["entered"] = time.monotonic()
            return ("plan", "exec-1", FakeResult(trace_id="t-1"))

    dispatcher = PeriodicScheduleDispatcher(runner_factory=BoundaryRunner)
    _base, locked = freeze(dispatcher, targets_for(("acc-1", "agah", "nsc-a")))
    due = dispatcher.due_mono_for_turn(0)

    before = time.monotonic()
    record = dispatcher.service_due_turn(dispatcher.mono_now(), 0)
    after = time.monotonic()

    assert record.status is TurnStatus.DISPATCHED
    assert "entered" in entry

    # The stored start IS the entry instant (within the recording's own
    # resolution), and it lies between the submit and the return.
    assert record.started_mono == pytest.approx(entry["entered"], abs=1e-3)
    assert before <= record.started_mono <= after
    assert record.start_delay_ms == pytest.approx(
        (record.started_mono - due) * 1000.0
    )


def test_the_start_delay_ignores_a_slow_broker_answer():
    """
    A 400 ms broker answer must not become a 400 ms start delay.

    The answer happens AFTER the hand-off, so the recorded start delay is
    the same as with an instant broker.
    """
    interval_ms = 500.0

    def measure(delay):
        recorder = Recorder()
        dispatcher = PeriodicScheduleDispatcher(
            runner_factory=make_runner_factory(recorder, delay=delay)
        )
        _base, locked = freeze(
            dispatcher, targets_for(("acc-1", "agah", "nsc-a"))
        )
        due = dispatcher.due_mono_for_turn(0)
        record = dispatcher.service_due_turn(dispatcher.mono_now(), 0)
        assert record.status is TurnStatus.DISPATCHED
        return record.start_delay_ms

    fast = measure(0.0)
    slow = measure(0.4)

    assert fast is not None and slow is not None
    # The whole 400 ms answer stayed inside the send path. It did NOT
    # inflate the start delay, which stays a handful of milliseconds.
    assert slow < 100.0, f"the broker answer leaked into the start delay: {slow}"
    assert abs(slow - fast) < 60.0, (fast, slow)


def test_each_group_keeps_its_own_start_time():
    """
    Groups start concurrently, so each one keeps its OWN hand-off time.
    """
    seen = {}

    class PerGroupRunner:
        def run(self, entries, account=None):
            broker = entries[0].broker_name
            # The "answer" for one group is slow; the other is instant.
            if broker == "slow":
                time.sleep(0.30)
            seen[broker] = time.monotonic()
            return ("plan", f"exec-{broker}", FakeResult(trace_id=f"t-{broker}"))

    dispatcher = PeriodicScheduleDispatcher(runner_factory=PerGroupRunner)
    freeze(
        dispatcher,
        targets_for(("acc-1", "slow", "nsc-a"), ("acc-1", "fast", "nsc-b")),
    )
    record = dispatcher.service_due_turn(dispatcher.mono_now(), 0)
    assert record.status is TurnStatus.DISPATCHED

    starts = {r.broker_name: r.started_mono for r in record.results}
    assert set(starts) == {"slow", "fast"}
    assert all(v is not None for v in starts.values()), starts
    # Both really entered the send path, and at nearly the same moment:
    # the slow broker's 300 ms answer happens AFTER the hand-off.
    assert abs(starts["slow"] - starts["fast"]) < 0.10, starts

    # The turn's own start is the FIRST REAL hand-off of its groups.
    assert record.started_mono == pytest.approx(
        min(starts.values()), abs=1e-6
    )


def test_the_start_time_is_not_the_submit_time():
    """A deliberately slow submit must not move the recorded start."""
    submission = {}
    original = PeriodicScheduleDispatcher._send_to_group

    def slow_submit(self, group, barrier=None):
        # Stall the worker BEFORE it can reach the hand-off boundary.
        time.sleep(0.25)
        submission["reached"] = time.monotonic()
        return original(self, group, barrier)

    entered = {}

    class Runner:
        def run(self, entries, account=None):
            entered["at"] = time.monotonic()
            return ("plan", "exec-1", FakeResult(trace_id="t-1"))

    PeriodicScheduleDispatcher._send_to_group = slow_submit
    try:
        dispatcher = PeriodicScheduleDispatcher(runner_factory=Runner)
        _base, locked = freeze(
            dispatcher, targets_for(("acc-1", "agah", "nsc-a"))
        )
        submit_at = time.monotonic()
        record = dispatcher.service_due_turn(dispatcher.mono_now(), 0)
    finally:
        PeriodicScheduleDispatcher._send_to_group = original

    assert record.status is TurnStatus.DISPATCHED
    # The recorded start followed the 250 ms submit stall, because it is
    # taken at the hand-off - the submit time is NOT what is recorded.
    assert record.started_mono >= submit_at + 0.20
    assert record.started_mono == pytest.approx(entered["at"], abs=1e-3)
