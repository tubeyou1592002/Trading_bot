"""
Block 9 — Task 9.3: Severe Burst simulation tests.

Extends the Task 9.1 harness and the Task 9.2 volume machinery with ONE
Severe Burst scenario on the SAME real dispatch path — no new architecture,
no bypass, no concurrency:

    ExecutionPlanner → ExecutionPlan → DispatchCore.dispatch()
        → BrokerManager → OrderEngine → SimulationBroker → DispatchResult

Burst definition (Task 9.3): severity, NOT concurrency. A burst is a large
number of executions (BurstVolume > every Task 9.2 volume) compressed into
ONE ExecutionPlan and executed strictly sequentially by the real engine
inside a single dispatch() call. No queue, no threading, no batching.

This file proves, for the burst:

  * the burst volume is deterministic and larger than Task 9.2's volumes;
  * all sequences arrive and are processed (none lost, none duplicated,
    none executed twice);
  * every execution result belongs to its own sequence (identity +
    fingerprint); order identity / instrument / account / broker are not
    cross-contaminated;
  * the place_order call count is exactly the dispatchable order count;
  * execution state is not contaminated between two consecutive bursts;
  * re-running the same burst is deterministic (the random per-dispatch
    ``trace_id`` is explicitly excluded from the comparison);
  * live trading is never enabled and no network / real broker is used.

Everything is fully offline and deterministic.
"""

import socket
from unittest.mock import MagicMock, patch

from core.simulation_harness import SimulationHarness


# ---------------------------------------------------------------------------
# Scenario under test
# ---------------------------------------------------------------------------


BURST_VOLUME = SimulationHarness.DEFAULT_BURST_VOLUME
TASK_9_2_VOLUMES = (10, 50, 100)


# ---------------------------------------------------------------------------
# Shared burst invariants
# ---------------------------------------------------------------------------


def assert_burst_invariants(harness, run, volume):
    """Check every mandated invariant for one completed burst run."""
    plan = run.plan
    result = run.dispatch_result

    # --- Input plan shape ---------------------------------------------------
    assert len(plan.orders) == volume
    assert plan.execution_order == list(range(1, volume + 1))

    # --- Sequences complete, unique, none lost, none duplicated -------------
    sequences = plan.execution_order
    assert len(set(sequences)) == volume
    assert sorted(sequences) == list(range(1, volume + 1))

    # --- Every sequence bound to its OWN expected order ----------------------
    binding = plan.conditions["binding"]
    fingerprint = {}
    for sequence in range(1, volume + 1):
        expected_ins, expected_price, expected_qty = harness.volume_order_fields(
            sequence
        )
        assert binding[sequence]["account_id"] == "ACC-SIM-1"
        assert binding[sequence]["broker_name"] == harness.broker_name

        order = plan.orders[sequence - 1]  # planner sorts by ascending sequence
        assert order.nsc_id == expected_ins
        assert order.price == expected_price
        assert order.quantity == expected_qty
        fingerprint[sequence] = (order.nsc_id, order.price, order.quantity)

    # No two sequences share the same fingerprint (distinct prices).
    assert len(set(fingerprint.values())) == volume

    # --- Broker received exactly the burst orders, in sequence order --------
    calls = run.broker.place_order_calls
    assert len(calls) == volume

    for index, (order, live) in enumerate(calls, start=1):
        assert live is False  # live trading never enabled
        assert (order.nsc_id, order.price, order.quantity) == fingerprint[index], (
            f"sequence {index} received a foreign/mismatched order"
        )
        assert order is plan.orders[index - 1]  # identity integrity

    # No duplicated order object reached the broker.
    assert len({id(order) for order, _ in calls}) == volume

    # Broker-level operation trail: exactly volume place_order calls.
    place_ops = [c for c in run.broker.calls if c.op == "place_order"]
    assert len(place_ops) == volume
    placed_prices = sorted(c.payload["price"] for c in place_ops)
    assert placed_prices == sorted(fp[1] for fp in fingerprint.values())

    # --- DispatchResult consistent with the real executions ------------------
    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert result.sent is False
    assert result.order_count == volume
    assert result.trace_id is not None

    # --- Live trading stays off everywhere ------------------------------------
    assert harness.broker.live_trading_enabled is False
    assert harness.dispatch_core.live_trading_enabled is False


# ---------------------------------------------------------------------------
# Burst volume: deterministic and more severe than Task 9.2
# ---------------------------------------------------------------------------


def test_burst_volume_is_deterministic_and_exceeds_task92_volumes():
    assert BURST_VOLUME > max(TASK_9_2_VOLUMES)

    # Same volume -> byte-identical plan input, every time.
    a = SimulationHarness().build_volume_plan(BURST_VOLUME)
    b = SimulationHarness().build_volume_plan(BURST_VOLUME)
    assert a.execution_order == b.execution_order == list(range(1, BURST_VOLUME + 1))
    assert [
        (o.nsc_id, o.price, o.quantity) for o in a.orders
    ] == [(o.nsc_id, o.price, o.quantity) for o in b.orders]


def test_severe_burst_at_default_volume():
    harness = SimulationHarness()
    run = harness.run_burst_scenario()

    assert_burst_invariants(harness, run, BURST_VOLUME)


# ---------------------------------------------------------------------------
# Sequence completeness / uniqueness / no loss / no duplication
# ---------------------------------------------------------------------------


def test_burst_sequence_completeness_and_uniqueness():
    harness = SimulationHarness()
    run = harness.run_burst_scenario()

    sequences = run.plan.execution_order
    assert sequences == list(range(1, BURST_VOLUME + 1))  # none missing
    assert len(set(sequences)) == BURST_VOLUME  # none duplicated


def test_burst_no_lost_or_duplicated_execution():
    harness = SimulationHarness()
    run = harness.run_burst_scenario()

    calls = run.broker.place_order_calls
    # Nothing lost: every dispatchable order was placed exactly once.
    assert len(calls) == BURST_VOLUME
    # Nothing duplicated: each expected fingerprint appears exactly once.
    expected_prices = sorted(
        harness.volume_order_fields(s)[1] for s in range(1, BURST_VOLUME + 1)
    )
    assert sorted(c[0].price for c in calls) == expected_prices
    assert len({id(order) for order, _ in calls}) == BURST_VOLUME


# ---------------------------------------------------------------------------
# Result/order identity integrity
# ---------------------------------------------------------------------------


def test_burst_result_order_identity_integrity():
    harness = SimulationHarness()
    run = harness.run_burst_scenario()

    for index, (order, live) in enumerate(run.broker.place_order_calls, start=1):
        # The broker call is identity-equal to the plan's own order object.
        assert order is run.plan.orders[index - 1]
        assert live is False
    assert run.dispatch_result.order_count == BURST_VOLUME
    assert run.dispatch_result.mode == "ALL_PROCESSED"


def test_burst_exact_place_order_count():
    harness = SimulationHarness()
    run = harness.run_burst_scenario()

    assert len(run.broker.place_order_calls) == BURST_VOLUME
    ops = [c.op for c in run.broker.calls]
    assert ops.count("place_order") == BURST_VOLUME
    # Each placed order's price fingerprint appears exactly once.
    prices = sorted(c.payload["price"] for c in run.broker.calls
                    if c.op == "place_order")
    assert prices == [1000 + s for s in range(1, BURST_VOLUME + 1)]


# ---------------------------------------------------------------------------
# Account / broker / instrument isolation inside the burst
# ---------------------------------------------------------------------------


def test_burst_account_broker_instrument_isolation():
    harness = SimulationHarness()
    run = harness.run_burst_scenario()

    # One account, one broker, one instrument — no cross-contamination.
    assert len(run.plan.accounts) == 1
    assert run.plan.accounts[0].account_id == "ACC-SIM-1"
    binding = run.plan.conditions["binding"]
    assert {b["account_id"] for b in binding.values()} == {"ACC-SIM-1"}
    assert {b["broker_name"] for b in binding.values()} == {harness.broker_name}
    assert {o.nsc_id for o in run.plan.orders} == {"INS-SIM-1"}
    assert {c[0].nsc_id for c in run.broker.place_order_calls} == {"INS-SIM-1"}
    # Every sequence is routed to the one registered SIM broker via the
    # plan binding (real core behavior: DispatchResult.broker_name stays
    # unset for the ALL_PROCESSED path — routing is per-sequence).

    # The provider path resolved ONLY the simulation instrument.
    resolved = {c.split(":", 1)[1] for c in run.provider.calls if ":" in c}
    assert resolved == {"INS-SIM-1"}
    # A foreign instrument cannot even exist in this broker's catalog.
    assert set(harness.broker.catalog) == {"INS-SIM-1"}


# ---------------------------------------------------------------------------
# State isolation between two consecutive bursts
# ---------------------------------------------------------------------------


def test_burst_state_isolated_across_consecutive_bursts():
    harness = SimulationHarness()

    run_a = harness.run_burst_scenario(plan_id="burst-a")
    # Snapshot the broker trail right after the first burst (the run record
    # references the harness's one shared simulation broker).
    trail_after_a = list(harness.broker.place_order_calls)
    assert len(trail_after_a) == BURST_VOLUME

    run_b = harness.run_burst_scenario(plan_id="burst-b")

    # The second burst added exactly its own volume — no loss, no
    # duplication, no replay of the first burst's executions.
    new_calls = harness.broker.place_order_calls[len(trail_after_a):]
    assert len(new_calls) == BURST_VOLUME
    assert len(harness.broker.place_order_calls) == 2 * BURST_VOLUME

    # Each new execution belongs to burst B's own order objects.
    ids_a = {id(o) for o in run_a.plan.orders}
    for index, (order, live) in enumerate(new_calls, start=1):
        assert live is False
        assert order is run_b.plan.orders[index - 1]
        assert id(order) not in ids_a  # burst A orders were never re-executed

    assert run_b.dispatch_result.mode == "ALL_PROCESSED"
    assert run_b.dispatch_result.order_count == BURST_VOLUME


# ---------------------------------------------------------------------------
# Deterministic rerun (random per-dispatch trace_id excluded)
# ---------------------------------------------------------------------------


def test_burst_deterministic_rerun_ignoring_trace_id():
    a = SimulationHarness().run_burst_scenario()
    b = SimulationHarness().run_burst_scenario()

    # --- Plans are identical -------------------------------------------------
    assert a.plan.plan_id == b.plan.plan_id
    assert a.plan.execution_order == b.plan.execution_order
    assert a.plan.account_routes == b.plan.account_routes
    assert a.plan.conditions["binding"] == b.plan.conditions["binding"]
    assert [(o.nsc_id, o.price, o.quantity) for o in a.plan.orders] == [
        (o.nsc_id, o.price, o.quantity) for o in b.plan.orders
    ]

    # --- DispatchResults match on every field EXCEPT the random trace_id -----
    # DispatchCore generates ``trace_id = str(uuid4())`` per dispatch; it is
    # intentionally excluded from the deterministic comparison.
    a_fields = {
        k: v for k, v in a.dispatch_result.__dict__.items() if k != "trace_id"
    }
    b_fields = {
        k: v for k, v in b.dispatch_result.__dict__.items() if k != "trace_id"
    }
    assert a_fields == b_fields
    # The excluded field exists on both runs (it is only non-deterministic,
    # never missing).
    assert a.dispatch_result.trace_id is not None
    assert b.dispatch_result.trace_id is not None

    # --- Real execution trails are identical ---------------------------------
    # ``creationDate`` is wall-clock stamped per real Order (models/order.py
    # defaults creation_date to ``datetime.now()``); like the random
    # per-dispatch trace_id it is excluded from the deterministic comparison.
    def comparable(payload):
        if isinstance(payload, dict):
            return {k: v for k, v in payload.items() if k != "creationDate"}
        return payload  # non-dict payloads (e.g. nsc_id strings) as-is

    assert [
        (c.op, comparable(c.payload)) for c in a.broker.calls
    ] == [(c.op, comparable(c.payload)) for c in b.broker.calls]
    assert [
        (o.nsc_id, o.price, o.quantity, live)
        for o, live in a.broker.place_order_calls
    ] == [
        (o.nsc_id, o.price, o.quantity, live)
        for o, live in b.broker.place_order_calls
    ]
    assert a.provider.calls == b.provider.calls


# ---------------------------------------------------------------------------
# Offline / live-trading guard (same guards as Tasks 9.1 and 9.2)
# ---------------------------------------------------------------------------


def test_burst_uses_no_network_and_no_real_broker():
    # Guard 1: the production Agaah binding is never constructed.
    with patch("brokers.manager.AgaahBroker") as agaah_spy, patch(
        "brokers.manager.AgaahInstrumentProvider"
    ) as provider_spy:
        harness = SimulationHarness()
        run = harness.run_burst_scenario()
        agaah_spy.assert_not_called()
        provider_spy.assert_not_called()

    assert run.dispatch_result.mode == "ALL_PROCESSED"

    # Guard 2: any socket open attempt fails the burst instantly.
    def forbidden_socket(*args, **kwargs):
        raise AssertionError("Network access attempted during burst run")

    with patch(f"{socket.socket.__module__}.socket", forbidden_socket):
        harness2 = SimulationHarness()
        run2 = harness2.run_burst_scenario()

    assert run2.dispatch_result.mode == "ALL_PROCESSED"
    assert len(run2.broker.place_order_calls) == BURST_VOLUME
    assert all(live is False for _, live in run2.broker.place_order_calls)
    assert harness2.broker.live_trading_enabled is False
    assert harness2.dispatch_core.live_trading_enabled is False
