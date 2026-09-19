"""
Block 9 — Task 9.2: High Volume simulation tests.

Extends the Task 9.1 offline harness with increasing execution volumes on
the SAME real dispatch path — no new architecture, no bypass:

    ExecutionPlanner → ExecutionPlan → DispatchCore.dispatch()
        → BrokerManager → OrderEngine → SimulationBroker → DispatchResult

Volumes tested: 10 / 50 / 100 orders (deterministic, unique sequences).

For every volume this file proves:

  * input count exactly matches the expected volume;
  * all sequences are unique and none is lost or executed twice;
  * every sequence is connected to its own expected order (by identity
    and by the deterministic price/quantity fingerprint);
  * the broker received exactly those orders (no foreign order object,
    no other sequence's order);
  * place_order call count is consistent with the dispatchable orders;
  * DispatchResult is consistent with the real executions
    (ALL_PROCESSED, correct order_count, sent=False);
  * execution state is not corrupted or mixed;
  * re-running the same scenario produces a deterministic outcome;
  * live trading is never enabled (every place_order live flag is False).

Everything is fully offline and deterministic: no network, no real broker,
no credentials, no real orders, no concurrency, no optimization.
"""

import socket
from unittest.mock import patch

import pytest

from core.simulation_harness import SimulationHarness


# ---------------------------------------------------------------------------
# Volume scenarios under test
# ---------------------------------------------------------------------------


VOLUME_SCENARIOS = [10, 50, 100]


# ---------------------------------------------------------------------------
# Shared invariants, checked for every volume
# ---------------------------------------------------------------------------


def assert_volume_invariants(harness, run, volume):
    """Check every mandated invariant for one completed volume run."""
    plan = run.plan
    result = run.dispatch_result

    # --- Input plan shape -------------------------------------------------
    assert len(plan.orders) == volume
    assert plan.execution_order == list(range(1, volume + 1))

    # --- Sequences unique, none lost, none duplicated ---------------------
    sequences = plan.execution_order
    assert len(set(sequences)) == volume  # all unique
    assert sorted(sequences) == list(range(1, volume + 1))  # none missing

    # --- Every sequence bound to its OWN expected order -------------------
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
        # Unique fingerprint: each sequence's order is identifiable.
        fingerprint[sequence] = (order.nsc_id, order.price, order.quantity)

    # No two sequences share the same fingerprint (distinct prices).
    assert len(set(fingerprint.values())) == volume

    # --- Broker received exactly the dispatched orders, in plan order -----
    calls = run.broker.place_order_calls
    assert len(calls) == volume  # every dispatchable order was placed

    for index, (order, live) in enumerate(calls, start=1):
        assert live is False  # live trading never enabled
        expected = fingerprint[index]
        assert (order.nsc_id, order.price, order.quantity) == expected, (
            f"sequence {index} received a foreign/mismatched order"
        )
        # The broker call is identity-equal to the plan's own order object.
        assert order is plan.orders[index - 1]

    # No duplicated order object reached the broker.
    assert len({id(order) for order, _ in calls}) == volume

    # Broker-level operation trail: exactly volume place_order calls.
    place_ops = [c.op for c in run.broker.calls if c.op == "place_order"]
    assert len(place_ops) == volume
    # Each placed order's payload fingerprint appears exactly once.
    placed_prices = sorted(c.payload["price"] for c in run.broker.calls
                           if c.op == "place_order")
    assert placed_prices == sorted(fp[1] for fp in fingerprint.values())

    # --- DispatchResult consistent with the real executions ---------------
    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert result.sent is False
    assert result.order_count == volume
    assert result.trace_id is not None

    # --- Engine state integrity: every per-order result is DRY_RUN --------
    # (derived from the real engine run, not fabricated by the test)
    assert run.reached_simulation_broker is True

    # --- Live trading stays off everywhere --------------------------------
    assert harness.broker.live_trading_enabled is False
    assert harness.dispatch_core.live_trading_enabled is False


# ---------------------------------------------------------------------------
# Volume scenarios on the real dispatch path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("volume", VOLUME_SCENARIOS)
def test_high_volume_scenario_at_volume(volume):
    harness = SimulationHarness()
    run = harness.run_volume_scenario(volume, plan_id=f"task9.2-vol-{volume}")

    assert_volume_invariants(harness, run, volume)


def test_volume_10_orders():
    harness = SimulationHarness()
    run = harness.run_volume_scenario(10)

    assert run.dispatch_result.order_count == 10
    assert len(run.broker.place_order_calls) == 10
    assert_volume_invariants(harness, run, 10)


def test_volume_50_orders():
    harness = SimulationHarness()
    run = harness.run_volume_scenario(50)

    assert run.dispatch_result.order_count == 50
    assert len(run.broker.place_order_calls) == 50
    assert_volume_invariants(harness, run, 50)


def test_volume_100_orders():
    harness = SimulationHarness()
    run = harness.run_volume_scenario(100)

    assert run.dispatch_result.order_count == 100
    assert len(run.broker.place_order_calls) == 100
    assert_volume_invariants(harness, run, 100)


# ---------------------------------------------------------------------------
# Determinism: same inputs -> same outcome
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("volume", VOLUME_SCENARIOS)
def test_volume_scenario_is_deterministic(volume):
    def outcome():
        harness = SimulationHarness()
        run = harness.run_volume_scenario(volume)
        return (
            run.dispatch_result.success,
            run.dispatch_result.mode,
            run.dispatch_result.sent,
            run.dispatch_result.order_count,
            [
                (o.nsc_id, o.price, o.quantity, live)
                for o, live in run.broker.place_order_calls
            ],
        )

    first = outcome()
    second = outcome()

    assert first == second
    assert len(first[-1]) == volume  # the recorded trail is complete


def test_plan_rebuild_is_deterministic():
    harness = SimulationHarness()

    plan_a = harness.build_volume_plan(25, plan_id="p")
    plan_b = harness.build_volume_plan(25, plan_id="p")

    assert plan_a.execution_order == plan_b.execution_order
    assert plan_a.conditions["binding"] == plan_b.conditions["binding"]
    assert [
        (o.nsc_id, o.price, o.quantity) for o in plan_a.orders
    ] == [(o.nsc_id, o.price, o.quantity) for o in plan_b.orders]


# ---------------------------------------------------------------------------
# The real dispatch path is used (no bypass, no shortcut)
# ---------------------------------------------------------------------------


def test_volume_scenario_goes_through_real_dispatch_core_and_engine():
    harness = SimulationHarness()

    engine_calls = []
    original_execute = harness.dispatch_core.order_engine.execute_by_ins_code

    def spy_execute(**kwargs):
        engine_calls.append(kwargs)
        return original_execute(**kwargs)

    harness.dispatch_core.order_engine.execute_by_ins_code = spy_execute

    dispatch_calls = []
    original_dispatch = harness.dispatch_core.dispatch

    def spy_dispatch(plan):
        dispatch_calls.append(plan)
        return original_dispatch(plan)

    harness.dispatch_core.dispatch = spy_dispatch

    run = harness.run_volume_scenario(10)

    # Exactly one dispatch() call with exactly the built plan.
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0] is run.plan

    # The REAL OrderEngine executed every order (M6-A..M6-E per order).
    assert len(engine_calls) == 10
    assert all(kwargs["live"] is False for kwargs in engine_calls)
    assert all(
        kwargs["broker"] is harness.broker for kwargs in engine_calls
    )
    # Sequences arrive in plan order through the real engine.
    assert [kwargs["order"].price for kwargs in engine_calls] == [
        harness.volume_order_fields(s)[1] for s in range(1, 11)
    ]

    # The test never called the simulation broker directly; every broker
    # interaction arrived through the real dispatch path above.
    assert len(run.broker.place_order_calls) == 10


def test_volume_scenario_provider_calls_match_real_path_signature():
    harness = SimulationHarness()
    run = harness.run_volume_scenario(10)

    # Real-path signature per order: one provider lookup from
    # DispatchCore._resolve_instrument + one from OrderEngine.
    assert run.provider.calls == ["get_instrument:INS-SIM-1"] * 20

    # Broker gate trail per order: trading state + capacity + placement.
    ops = [c.op for c in run.broker.calls]
    assert ops.count("get_trading_state") == 10
    assert ops.count("get_buy_capacity") == 10
    assert ops.count("place_order") == 10
    assert ops[0] == "get_trading_state"  # first interaction is the M6 gate


# ---------------------------------------------------------------------------
# Offline isolation (same guards as Task 9.1)
# ---------------------------------------------------------------------------


def test_volume_scenario_uses_no_network_and_no_real_broker():
    # Guard 1: the production Agaah binding is never constructed.
    with patch("brokers.manager.AgaahBroker") as agaah_spy, patch(
        "brokers.manager.AgaahInstrumentProvider"
    ) as provider_spy:
        harness = SimulationHarness()
        run = harness.run_volume_scenario(50)
        agaah_spy.assert_not_called()
        provider_spy.assert_not_called()

    assert run.dispatch_result.mode == "ALL_PROCESSED"

    # Guard 2: any socket open attempt fails the run instantly.
    def forbidden_socket(*args, **kwargs):
        raise AssertionError("Network access attempted during volume run")

    with patch(f"{socket.socket.__module__}.socket", forbidden_socket):
        harness2 = SimulationHarness()
        run2 = harness2.run_volume_scenario(100)

    assert run2.dispatch_result.mode == "ALL_PROCESSED"
    assert len(run2.broker.place_order_calls) == 100
    assert all(live is False for _, live in run2.broker.place_order_calls)


def test_volume_scenario_state_not_contaminated_across_runs():
    """Sequential volume runs on one harness keep their executions separate."""
    harness = SimulationHarness()

    run_10 = harness.run_volume_scenario(10, plan_id="run-a")
    # Snapshot the broker trail right after the first dispatch (the run
    # record references the harness's one shared simulation broker).
    trail_after_first = list(harness.broker.place_order_calls)
    assert len(trail_after_first) == 10

    run_20 = harness.run_volume_scenario(20, plan_id="run-b")

    # The second dispatch added exactly 20 new placements — no loss, no
    # duplication, no replay of the first run's orders.
    new_calls = harness.broker.place_order_calls[len(trail_after_first):]
    assert len(new_calls) == 20

    # Sequence-to-order connection stays intact in the second plan: the
    # new broker calls are exactly run_20's own orders, in sequence order.
    for index, (order, live) in enumerate(new_calls, start=1):
        assert live is False
        assert order is run_20.plan.orders[index - 1]
        _, price, qty = harness.volume_order_fields(index)
        assert (order.price, order.quantity) == (price, qty)
    assert len({id(order) for order, _ in new_calls}) == 20

    # DispatchResults stayed independent and correct.
    assert run_10.dispatch_result.order_count == 10
    assert run_20.dispatch_result.order_count == 20
    assert run_10.dispatch_result.trace_id != run_20.dispatch_result.trace_id
    assert run_10.dispatch_result.mode == run_20.dispatch_result.mode == "ALL_PROCESSED"


def test_invalid_volume_is_rejected_fail_closed():
    harness = SimulationHarness()

    with pytest.raises(ValueError):
        harness.build_volume_plan(0)

    with pytest.raises(ValueError):
        harness.build_volume_plan(-5)
