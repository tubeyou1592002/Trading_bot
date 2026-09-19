"""
Block 9 — Task 9.6: Failure Injection simulation tests.

Injects controlled, deterministic failures at the ONLY permitted seam — the
simulation broker's ``place_order`` — and proves the REAL dispatch path's
existing behavior around them:

    ExecutionPlanner → ExecutionPlan → DispatchCore.dispatch()
        → BrokerManager → OrderEngine → SimulationBroker → DispatchResult

Nothing production changes: the engine's own handling turns the injected
failure into the per-order outcome the current architecture defines
(place_order exception -> per-order ERROR result -> aggregate fail-closed
BLOCKED verdict; the loop keeps executing the remaining independent orders),
and the harness adds no retry / failover / queue / circuit breaker.

Scenario under test (8 orders, ONE plan, ONE dispatch call, interleaved):

    seq % 4 == 1 -> ACC-SIM-1 → SIM-A → STOCK-A   (always healthy)
    seq % 4 == 3 -> ACC-SIM-1 → SIM-A → STOCK-C   (always healthy)
    seq % 2 == 0 -> ACC-SIM-2 → SIM-B → STOCK-B   (failure armed here)

Distinct balances / prices / quantities make any identity swap detectable
from the real trails alone (M6-D passes account.tradable_balance_t1 as fund).

Failures actually implemented (Task 9.6 scope):
    A) exception        — broker raises a controlled RuntimeError inside
                          the real engine's place_order call
    B) failed_response  — broker returns a failure envelope in the same
                          shape the real dry-run path already carries
    C) timeout          — a fully simulated TimeoutError (no socket,
                          no real network, no sleep)
    D) missing response — NOT implementable without inventing protocol or
                          state the current contract has no place for
                          (documented in the final report; see the report
                          and the 'not implemented' note below).

Everything is fully offline and deterministic; only the inherently random
per-dispatch ``trace_id`` and the wall-clock ``creationDate`` order stamp
are excluded from deterministic comparisons (each with a documented reason).
"""

import socket
from unittest.mock import patch

from core.simulation_harness import (
    SimulationHarness,
    build_dual_broker_harness,
    build_simulation_catalog,
)

ACC1, ACC2 = "ACC-SIM-1", "ACC-SIM-2"
STOCK_A, STOCK_B, STOCK_C = "STOCK-A", "STOCK-B", "STOCK-C"
SIM_A, SIM_B = "SIM-A", "SIM-B"
BALANCE_1, BALANCE_2 = 1_000_000_000, 2_000_000_000
VOLUME = 8

SIM_A_SEQS = (1, 3, 5, 7)  # SIM-A's arrivals, in ascending plan order
B_SEQS = (2, 4, 6, 8)      # SIM-B's arrivals (ACC-SIM-2 → STOCK-B)
STOCK_A_SEQS = (1, 5)      # ACC-SIM-1 → STOCK-A
STOCK_C_SEQS = (3, 7)      # ACC-SIM-1 → STOCK-C


def make_harness():
    """Task 9.6 environment: two brokers, three instruments."""
    return build_dual_broker_harness(
        broker_a_name=SIM_A,
        broker_b_name=SIM_B,
        ins_codes=(STOCK_A, STOCK_B, STOCK_C),
    )


def expected_row(sequence):
    """The ONLY allowed (account, broker, instrument, balance, price, qty)."""
    if sequence % 4 == 1:
        return ACC1, SIM_A, STOCK_A, BALANCE_1, 10_000 + sequence, 100 + sequence
    if sequence % 4 == 3:
        return ACC1, SIM_A, STOCK_C, BALANCE_1, 30_000 + sequence, 300 + sequence
    return ACC2, SIM_B, STOCK_B, BALANCE_2, 20_000 + sequence, 200 + sequence


def trail_orders(broker):
    return [o for o, _ in broker.place_order_calls]


def injected_kinds(broker):
    return [
        c.payload["kind"] for c in broker.calls if c.op == "injected_failure"
    ]


def assert_healthy_chain(run, harness):
    """Every identity invariant that must hold despite any injected failure."""
    plan = run.plan

    # --- Plan shape: interleaved, complete, unique, unchanged ----------------
    assert len(plan.orders) == VOLUME
    assert plan.execution_order == list(range(1, VOLUME + 1))
    binding = plan.conditions["binding"]
    # Task 9.6 isolation mandate: the failure must not alter the binding.
    for sequence in range(1, VOLUME + 1):
        acc, broker, _ins, _bal, _price, _qty = expected_row(sequence)
        assert binding[sequence]["account_id"] == acc
        assert binding[sequence]["broker_name"] == broker
    assert plan.account_routes == {ACC1: SIM_A, ACC2: SIM_B}

    # --- Every order still reached exactly ONE broker, exactly once ----------
    trail_a = run.brokers[SIM_A].place_order_calls
    trail_b = run.brokers[SIM_B].place_order_calls
    assert len(trail_a) == VOLUME // 2
    assert len(trail_b) == VOLUME // 2
    placed = [o for o, _ in trail_a + trail_b]
    assert len(placed) == VOLUME
    assert len({id(o) for o in placed}) == VOLUME  # no duplicate execution
    for offset, sequence in enumerate(SIM_A_SEQS):
        order, live = trail_a[offset]
        acc, _b, ins, _bal, price, qty = expected_row(sequence)
        assert live is False
        assert order is plan.orders[sequence - 1]
        assert (order.nsc_id, order.price, order.quantity) == (ins, price, qty)
    for offset, sequence in enumerate(B_SEQS):
        order, live = trail_b[offset]
        acc, _b, ins, _bal, price, qty = expected_row(sequence)
        assert live is False
        assert order is plan.orders[sequence - 1]
        assert (order.nsc_id, order.price, order.quantity) == (ins, price, qty)

    # --- Broker identity: SIM-B saw ONLY Account 2 / Stock B ------------------
    assert {o.nsc_id for o in trail_orders(run.brokers[SIM_B])} == {STOCK_B}
    assert {
        c.payload["fund"] for c in run.brokers[SIM_B].calls
        if c.op == "get_buy_capacity"
    } == {BALANCE_2}
    # --- Broker identity: SIM-A saw ONLY Account 1 funds / its own stocks -----
    assert {o.nsc_id for o in trail_orders(run.brokers[SIM_A])} == {
        STOCK_A, STOCK_C
    }
    assert {
        c.payload["fund"] for c in run.brokers[SIM_A].calls
        if c.op == "get_buy_capacity"
    } == {BALANCE_1}

    # --- Live trading stays off everywhere ------------------------------------
    assert run.brokers[SIM_A].live_trading_enabled is False
    assert run.brokers[SIM_B].live_trading_enabled is False
    assert harness.dispatch_core.live_trading_enabled is False


# ---------------------------------------------------------------------------
# A) Exception injection
# ---------------------------------------------------------------------------


def test_exception_failure_hits_real_path_and_blocks_only_target():
    harness = make_harness()
    run = harness.run_failure_scenario(fail_nsc_id=STOCK_B)

    # The failure REALLY happened inside the real dispatch path, on the
    # right broker, at the right point (after the M6 gates: get_trading_state
    # and get_buy_capacity ran for that order first).
    kinds = injected_kinds(run.brokers[SIM_B])
    assert kinds == ["exception"]  # exactly one, one-shot, disarmed after
    ops = [c.op for c in run.brokers[SIM_B].calls]
    assert ops.count("get_trading_state") == VOLUME // 2
    assert ops.count("get_buy_capacity") == VOLUME // 2
    assert ops.count("place_order") == VOLUME // 2
    # M6 gates precede the injected point on the failing broker's trail.
    first_place = ops.index("place_order")
    assert ops.index("get_trading_state") < first_place
    assert ops.index("get_buy_capacity") < first_place

    # Aggregate result: fail-closed BLOCKED (current architecture contract).
    result = run.dispatch_result
    assert result.success is False
    assert result.mode == "BLOCKED"
    assert result.sent is False
    assert result.order_count == VOLUME
    assert result.trace_id is not None
    assert "بلاک" in result.message or "blocked" in result.message.lower()

    assert_healthy_chain(run, harness)


def test_exception_failure_isolates_all_other_executions():
    harness = make_harness()
    run = harness.run_failure_scenario(fail_nsc_id=STOCK_B)

    trail_a = run.brokers[SIM_A].place_order_calls
    trail_b = run.brokers[SIM_B].place_order_calls

    # The failure did NOT leak to SIM-A: its whole trail stayed healthy —
    # same orders, same identities, same order as the failure-free plan.
    assert [o for o, _ in trail_a] == [
        run.plan.orders[s - 1] for s in SIM_A_SEQS
    ]
    assert all(live is False for _, live in trail_a)
    assert injected_kinds(run.brokers[SIM_A]) == []  # no failure reached A

    # On SIM-B, the OTHER (healthy) Account-2 executions were untouched:
    # every Stock-B order was still attempted exactly once and in order.
    assert [o for o, _ in trail_b] == [
        run.plan.orders[s - 1] for s in B_SEQS
    ]
    # Account-1 → Broker-B never happened; Account-2 → Broker-A never happened.
    acc1_orders = [
        run.plan.orders[s - 1] for s in range(1, VOLUME + 1)
        if run.plan.conditions["binding"][s]["account_id"] == ACC1
    ]
    assert {id(o) for o in acc1_orders}.isdisjoint(
        {id(o) for o in trail_orders(run.brokers[SIM_B])}
    )
    # Result/result pairing stayed with its own plan slot (identity proof).
    assert [id(o) for o, _ in trail_b] == [
        id(run.plan.orders[s - 1]) for s in B_SEQS
    ]

    assert_healthy_chain(run, harness)


# ---------------------------------------------------------------------------
# B) Failed response injection
# ---------------------------------------------------------------------------


def test_failed_response_returns_failure_envelope_through_real_path():
    harness = make_harness()
    custom = {
        "mode": "FAILED",
        "sent": False,
        "success": False,
        "error": "SIM: custom broker rejection",
        "order_id": "SIM-STOCK-B",
    }
    run = harness.run_failure_scenario(
        fail_nsc_id=STOCK_B, fail_mode="failed_response", fail_response=custom
    )

    # The broker DID produce exactly one failed_response at the injected
    # point (one-shot, disarmed afterwards).
    injected = [
        c for c in run.brokers[SIM_B].calls if c.op == "injected_failure"
    ]
    assert len(injected) == 1
    assert injected[0].payload["kind"] == "failed_response"
    assert injected[0].payload["response"] == custom

    # Current engine contract (order_engine.py): a non-exception broker
    # response flows through as the per-order dry-run ``response`` — the
    # aggregate verdict therefore stays ALL_PROCESSED. This is the REAL
    # behavior; the failure is observable via the broker's own envelope.
    assert run.dispatch_result.mode == "ALL_PROCESSED"
    assert run.dispatch_result.success is True

    # The broker's trail still records the attempt against the exact order.
    assert len(run.brokers[SIM_B].place_order_calls) == VOLUME // 2

    assert_healthy_chain(run, harness)


def test_failed_response_does_not_pair_with_other_sequences():
    harness = make_harness()
    run = harness.run_failure_scenario(fail_nsc_id=STOCK_B, fail_mode="failed_response")

    # Only ONE injected failure on the whole plan, scoped to Stock B.
    assert injected_kinds(run.brokers[SIM_B]) == ["failed_response"]
    assert injected_kinds(run.brokers[SIM_A]) == []
    # Every execution kept its own order/result pairing (identity) — the
    # failed_response outcome belongs ONLY to its own Stock-B sequence.
    trail_b = run.brokers[SIM_B].place_order_calls
    assert [id(o) for o, _ in trail_b] == [
        id(run.plan.orders[s - 1]) for s in B_SEQS
    ]
    assert_healthy_chain(run, harness)


# ---------------------------------------------------------------------------
# C) Simulated timeout injection
# ---------------------------------------------------------------------------


def test_simulated_timeout_fires_without_network_or_sleep():
    harness = make_harness()
    run = harness.run_failure_scenario(fail_nsc_id=STOCK_B, fail_mode="timeout")

    # Exactly one simulated timeout was raised on SIM-B.
    assert injected_kinds(run.brokers[SIM_B]) == ["timeout"]
    assert run.brokers[SIM_B].timeouts_raised == 1
    assert run.dispatch_result.mode == "BLOCKED"
    assert run.dispatch_result.success is False

    assert_healthy_chain(run, harness)


def test_timeout_error_reaches_engine_as_per_order_error():
    harness = make_harness()
    run = harness.run_failure_scenario(
        fail_nsc_id=STOCK_B,
        fail_mode="exception",
        # The engine's place_order except-branch (order_engine.py) converts
        # ANY broker exception — including TimeoutError — into a per-order
        # ERROR result carrying the exception text; the aggregate verdict
        # then fail-closes to BLOCKED. Using TimeoutError here proves the
        # timeout travels the REAL engine path.
        failure_exception=TimeoutError("SIM: simulated timeout"),
    )
    assert injected_kinds(run.brokers[SIM_B]) == ["exception"]
    assert run.dispatch_result.mode == "BLOCKED"
    assert_healthy_chain(run, harness)


# ---------------------------------------------------------------------------
# Main scenario: mid-path failure with healthy neighbors (concept example)
# ---------------------------------------------------------------------------


def test_mid_path_failure_leaves_neighbors_healthy():
    harness = make_harness()
    # seq 1: ACC-1 → SIM-A → STOCK-A (SUCCESS, before the failure)
    # seq 2: ACC-2 → SIM-B → STOCK-B (FAILURE)
    # seq 3: ACC-1 → SIM-A → STOCK-C (SUCCESS, after the failure)
    run = harness.run_failure_scenario(fail_nsc_id=STOCK_B)

    # Failure happened exactly once, on the intended broker/instrument.
    assert injected_kinds(run.brokers[SIM_B]) == ["exception"]
    b_ops = [c.op for c in run.brokers[SIM_B].calls]
    fail_at = b_ops.index("injected_failure")
    # ...after the FIRST Stock-B attempt's M6 gates...
    assert b_ops.index("get_trading_state") < fail_at
    # ...and the plan continued: SIM-A executed seq 3 (STOCK-C) after it.
    trail_a = trail_orders(run.brokers[SIM_A])
    assert len(trail_a) == 4
    assert trail_a[1].nsc_id == STOCK_C  # seq 3 executed independently

    # seq 1 (before) and seq 3 (after) kept their exact expected identities.
    acc, _b, ins, _bal, price, qty = expected_row(1)
    o1 = run.plan.orders[0]
    assert (o1.nsc_id, o1.price, o1.quantity) == (ins, price, qty)
    acc, _b, ins, _bal, price, qty = expected_row(3)
    o3 = run.plan.orders[2]
    assert (o3.nsc_id, o3.price, o3.quantity) == (ins, price, qty)
    assert run.dispatch_result.mode == "BLOCKED"
    assert_healthy_chain(run, harness)


# ---------------------------------------------------------------------------
# Isolation chain test: Account 1 → Stock A → Broker A vs Account 2 → B
# ---------------------------------------------------------------------------


def test_isolation_chain_account1_brokerA_account2_brokerB():
    harness = make_harness()
    run = harness.run_failure_scenario(fail_nsc_id=STOCK_B)

    binding = run.plan.conditions["binding"]
    trail_a = trail_orders(run.brokers[SIM_A])
    trail_b = trail_orders(run.brokers[SIM_B])

    # Account 1 was NOT moved to Broker B:
    acc1_orders = [
        run.plan.orders[s - 1] for s in range(1, VOLUME + 1)
        if binding[s]["account_id"] == ACC1
    ]
    assert {id(o) for o in acc1_orders} == {id(o) for o in trail_a}
    assert {id(o) for o in acc1_orders}.isdisjoint(
        {id(o) for o in trail_b}
    )
    # Stock A was NOT contaminated by the Stock-B failure:
    assert {o.nsc_id for o in trail_a} == {STOCK_A, STOCK_C}
    assert STOCK_B not in {o.nsc_id for o in trail_a}
    # Broker A did NOT receive Broker B's failure:
    assert injected_kinds(run.brokers[SIM_A]) == []
    assert injected_kinds(run.brokers[SIM_B]) == ["exception"]
    # Account 1's outcome was not confused with Account 2's: all four
    # SIM-A placements were healthy dry-runs, and the engine's fund trail
    # proves each broker ran with ONLY its own account's balance.
    assert all(live is False for _, live in run.brokers[SIM_A].place_order_calls)
    assert {
        c.payload["fund"] for c in run.brokers[SIM_A].calls
        if c.op == "get_buy_capacity"
    } == {BALANCE_1}
    assert {
        c.payload["fund"] for c in run.brokers[SIM_B].calls
        if c.op == "get_buy_capacity"
    } == {BALANCE_2}

    # The failure did not mutate the existing plan binding.
    for sequence in range(1, VOLUME + 1):
        acc, broker, _ins, _bal, _price, _qty = expected_row(sequence)
        assert binding[sequence]["account_id"] == acc
        assert binding[sequence]["broker_name"] == broker
    assert run.dispatch_result.mode == "BLOCKED"


# ---------------------------------------------------------------------------
# Sequence-scoped failure (position-targeted, deterministic)
# ---------------------------------------------------------------------------


def test_broker_sequence_scoped_failure_hits_exact_position():
    harness = make_harness()
    # Fail SIM-B's SECOND incoming place_order (i.e. plan sequence 4).
    run = harness.run_failure_scenario(fail_nsc_id=None, fail_on_broker_sequence=2)

    assert injected_kinds(run.brokers[SIM_B]) == ["exception"]
    # All four Stock-B orders were still attempted, exactly once, in order —
    # only the targeted position failed.
    trail_b = run.brokers[SIM_B].place_order_calls
    assert [o for o, _ in trail_b] == [
        run.plan.orders[s - 1] for s in B_SEQS
    ]
    assert run.dispatch_result.mode == "BLOCKED"
    assert_healthy_chain(run, harness)


# ---------------------------------------------------------------------------
# State isolation: consecutive runs (Run 1 failure, Run 2 healthy)
# ---------------------------------------------------------------------------


def test_state_isolation_failure_run_then_healthy_run():
    harness = make_harness()

    run1 = harness.run_failure_scenario(fail_nsc_id=STOCK_B)
    snap_a = list(run1.brokers[SIM_A].place_order_calls)
    snap_b = list(run1.brokers[SIM_B].place_order_calls)
    assert injected_kinds(run1.brokers[SIM_B]) == ["exception"]
    assert run1.dispatch_result.mode == "BLOCKED"

    run2 = harness.run_failure_scenario(fail_nsc_id=None)  # healthy run

    # Run 1's failure did not leak: run 2 executed ALL orders, on the same
    # routes, with zero NEW injected failures (the broker trails accumulate
    # across runs on the shared broker, so read run 2's own delta).
    new_injected_b = injected_kinds(run2.brokers[SIM_B])[len(injected_kinds(run1.brokers[SIM_B])):]
    new_injected_a = injected_kinds(run2.brokers[SIM_A])[len(injected_kinds(run1.brokers[SIM_A])):]
    assert new_injected_a == []
    assert new_injected_b == []
    # Lifetime counters on the shared broker include run 1; run 2 added none.
    assert run2.brokers[SIM_B].fired_count == len(injected_kinds(run1.brokers[SIM_B]))
    assert run2.dispatch_result.mode == "ALL_PROCESSED"
    assert run2.dispatch_result.order_count == VOLUME

    # Exact call growth per broker: 4 more placements each, no replay.
    new_a = run1.brokers[SIM_A].place_order_calls[len(snap_a):]
    new_b = run1.brokers[SIM_B].place_order_calls[len(snap_b):]
    assert len(new_a) == VOLUME // 2
    assert len(new_b) == VOLUME // 2
    # Run 2's placements are identity-equal to run 2's OWN plan orders.
    for offset, sequence in enumerate(SIM_A_SEQS):
        order, live = new_a[offset]
        assert order is run2.plan.orders[sequence - 1]
        assert live is False
    for offset, sequence in enumerate(B_SEQS):
        order, live = new_b[offset]
        assert order is run2.plan.orders[sequence - 1]
        assert live is False

    # Binding unchanged between runs; no state from run 1 altered run 2.
    assert run2.plan.conditions["binding"] == run1.plan.conditions["binding"]
    assert run2.plan.account_routes == run1.plan.account_routes


# ---------------------------------------------------------------------------
# Determinism: same failure scenario twice, ignoring trace_id/creationDate
# ---------------------------------------------------------------------------


def test_failure_scenario_deterministic_rerun():
    a = make_harness().run_failure_scenario(fail_nsc_id=STOCK_B)
    b = make_harness().run_failure_scenario(fail_nsc_id=STOCK_B)

    # Failure position / sequence / outcome are NOT random.
    assert injected_kinds(a.brokers[SIM_B]) == injected_kinds(b.brokers[SIM_B])
    assert a.brokers[SIM_B].fired_count == b.brokers[SIM_B].fired_count == 1

    # Plans identical.
    assert a.plan.execution_order == b.plan.execution_order
    assert a.plan.conditions["binding"] == b.plan.conditions["binding"]
    assert a.plan.account_routes == b.plan.account_routes
    assert [(o.nsc_id, o.price, o.quantity) for o in a.plan.orders] == [
        (o.nsc_id, o.price, o.quantity) for o in b.plan.orders
    ]

    # Aggregate verdict identical (mode/success/order_count/sent), message
    # included (it embeds the injected exception text, which is fixed).
    a_fields = {
        k: v for k, v in a.dispatch_result.__dict__.items() if k != "trace_id"
    }
    b_fields = {
        k: v for k, v in b.dispatch_result.__dict__.items() if k != "trace_id"
    }
    assert a_fields == b_fields  # exclusion #1: random per-dispatch trace_id

    # Per-broker trails identical.
    def comparable(payload):
        if isinstance(payload, dict):
            # exclusion #2: wall-clock creationDate stamped by the real
            # models/order.py datetime.now() default.
            return {k: v for k, v in payload.items() if k != "creationDate"}
        return payload

    for broker_name in (SIM_A, SIM_B):
        assert [
            (c.op, comparable(c.payload)) for c in a.brokers[broker_name].calls
        ] == [
            (c.op, comparable(c.payload)) for c in b.brokers[broker_name].calls
        ]
        assert [
            (o.nsc_id, o.price, o.quantity, live)
            for o, live in a.brokers[broker_name].place_order_calls
        ] == [
            (o.nsc_id, o.price, o.quantity, live)
            for o, live in b.brokers[broker_name].place_order_calls
        ]


# ---------------------------------------------------------------------------
# Live refusal still wins over any injected failure (fail-closed layering)
# ---------------------------------------------------------------------------


def test_live_refusal_wins_over_injected_failure():
    harness = make_harness()
    broker_b = run_b = None
    run = harness.run_failure_scenario(fail_nsc_id=STOCK_B)
    broker_b = run.brokers[SIM_B]
    # The injected path never saw live=True: every recorded placement was a
    # dry-run, and the broker's hard-off flag is unchanged.
    assert all(live is False for _, live in broker_b.place_order_calls)
    assert broker_b.live_trading_enabled is False
    # Direct contract-level proof (same seam as production): a live attempt
    # on the failing broker still refuses fail-closed, BEFORE any failure
    # logic — and nothing real is reachable either way.
    try:
        broker_b.live_trading_enabled = True  # temporarily flip the flag
        try:
            broker_b.place_order(run.plan.orders[1], live=True)
            raised = False
        except RuntimeError:
            raised = True
        assert raised is True
    finally:
        broker_b.live_trading_enabled = False
    assert broker_b.live_trading_enabled is False


# ---------------------------------------------------------------------------
# Offline / safety guards (reused pattern from Tasks 9.1–9.5)
# ---------------------------------------------------------------------------


def test_failure_scenario_uses_no_network_and_no_real_broker():
    # Guard 1: the production Agaah binding is never constructed.
    with patch("brokers.manager.AgaahBroker") as agaah_spy, patch(
        "brokers.manager.AgaahInstrumentProvider"
    ) as provider_spy:
        harness = make_harness()
        run = harness.run_failure_scenario(fail_nsc_id=STOCK_B)
        agaah_spy.assert_not_called()
        provider_spy.assert_not_called()

    # Guard 2: any socket open attempt fails the run instantly (the injected
    # timeout is purely simulated — no socket, no sleep, no real network).
    def forbidden_socket(*args, **kwargs):
        raise AssertionError("Network access attempted during failure run")

    with patch(f"{socket.socket.__module__}.socket", forbidden_socket):
        harness2 = make_harness()
        run2 = harness2.run_failure_scenario(
            fail_nsc_id=STOCK_B, fail_mode="timeout"
        )

    assert run2.dispatch_result.mode == "BLOCKED"
    assert injected_kinds(run2.brokers[SIM_B]) == ["timeout"]
    # No real credential was needed anywhere: the harness works with plain
    # in-memory accounts and never calls login.
    assert all(
        c.op != "login"
        for b in (run.brokers[SIM_A], run.brokers[SIM_B])
        for c in b.calls
    )
