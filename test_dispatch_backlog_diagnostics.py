"""Offline proof of the UI-7 backlog counter and per-turn resend semantics.

These tests only EXERCISE the existing dispatcher. They do not change the
cadence, the concurrency policy or any safety gate.
"""

import logging
import threading
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from ui.schedule_dispatcher import (
    OUTSTANDING_TURN_WARNING_THRESHOLD,
    DispatchTarget,
    PeriodicScheduleDispatcher,
)


LOGGER_NAME = "ui.schedule_dispatcher"


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


def _targets(count=2):
    return [
        DispatchTarget(
            entry=SimpleNamespace(entry_id=f"entry-{index}"),
            account_id="ACC-1",
            broker_name="BROKER-1",
            account=SimpleNamespace(account_id="ACC-1"),
        )
        for index in range(count)
    ]


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_backlog_counts_turns_and_every_turn_resends_all_frozen_orders(caplog):
    clock = FakeClock()
    release = threading.Event()
    calls = []
    calls_lock = threading.Lock()

    class BlockingRunner:
        def run(self, entries, account=None):
            with calls_lock:
                calls.append(tuple(id(entry) for entry in entries))
            if not release.wait(5):
                raise TimeoutError("test runner was not released")
            return None, "exec-id", SimpleNamespace(
                success=True, message="", trace_id=None
            )

    dispatcher = PeriodicScheduleDispatcher(
        runner_factory=BlockingRunner,
        mono_clock=clock,
    )
    dispatcher.freeze(
        targets=_targets(2),
        interval_ms=100.0,
        locked_base=datetime(2026, 10, 23, 9, 0, 0),
        locked_mono=clock.value,
        window=None,
    )

    assert dispatcher.frozen_order_count == 2

    threads = []
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        try:
            for turn_index in range(
                OUTSTANDING_TURN_WARNING_THRESHOLD + 1
            ):
                thread = threading.Thread(
                    target=dispatcher.service_due_turn,
                    args=(
                        dispatcher.due_mono_for_turn(turn_index),
                        turn_index,
                    ),
                )
                thread.start()
                threads.append(thread)

            assert _wait_until(
                lambda: dispatcher.in_flight
                == OUTSTANDING_TURN_WARNING_THRESHOLD + 1
            )
            # in_flight counts TURNS (each carrying the whole frozen set),
            # not individual orders.
            assert dispatcher.in_flight == 3
            assert dispatcher.peak_in_flight == 3
            assert dispatcher.frozen_order_count == 2
        finally:
            release.set()
            for thread in threads:
                thread.join(timeout=5)

    assert dispatcher.in_flight == 0
    assert len(calls) == OUTSTANDING_TURN_WARNING_THRESHOLD + 1
    # Every turn received the SAME two orders: no consumption, no dedup.
    assert all(call == calls[0] for call in calls)
    assert all(len(call) == 2 for call in calls)

    text = caplog.text
    assert "3 open/in-progress dispatch turn(s)" in text
    assert "not broker-unconfirmed orders" in text
    assert "same 2 frozen order(s)" in text
