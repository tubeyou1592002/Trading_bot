"""
Block 9 — Task 9.5: Multi-Broker Isolation simulation tests.

Extends the Task 9.1 harness with TWO independent simulation brokers wired
through the EXISTING Block 7 registration seam, and proves that an
interleaved two-account / two-instrument / two-broker plan executes on the
SAME real dispatch path with zero cross-contamination:

    ExecutionPlanner → ExecutionPlan → DispatchCore.dispatch()
        → BrokerManager (per-sequence broker + provider resolution)
        → OrderEngine → SimulationBroker SIM-A / SimulationBroker SIM-B
        → DispatchResult

Scenario under test (all 8 orders in ONE ExecutionPlan, ONE dispatch call):

    odd  sequences → ACC-SIM-1 → STOCK-A → SIM-A
    even sequences → ACC-SIM-2 → STOCK-B → SIM-B

Distinctness makes every swap detectable from real trails alone:
    balances  1_000_000_000 (ACC-1) / 2_000_000_000 (ACC-2)  — the real
              M6-D gate passes ``account.tradable_balance_t1`` as ``fund``,
    prices    10_000+seq (A-path) / 20_000+seq (B-path),
    quantity  100+seq (A-path) / 200+seq (B-path).

Nothing production is touched: the second broker is registered via the
existing ``BrokerManager.register()`` and both providers are the manager's
own lazily-built, per-broker-cached instances (Block 7 contract).
"""

import socket
from unittest.mock import patch

from brokers.base import InstrumentProvider
from core.simulation_harness import (
    SimulationBroker,
    SimulationInstrumentProvider,
    build_dual_broker_harness,
)

ACC1, ACC2 = "ACC-SIM-1", "ACC-SIM-2"
STOCK_A, STOCK_B = "STOCK-A", "STOCK-B"
SIM_A, SIM_B = "SIM-A", "SIM-B"
BALANCE_1, BALANCE_2 = 1_000_000_000, 2_000_000_000
VOLUME = 8  # interleaved A/B/A/B/A/B/A/B


def make_harness():
    """Two independent simulation pairs on the REAL Block 7 seam."""
    return build_dual_broker_harness(broker_a_name=SIM_A, broker_b_name=SIM_B)


def expected_quad(sequence):
    """The ONLY allowed (account, broker, instrument, balance, price, qty)."""
    if sequence % 2 == 1:
        return ACC1, SIM_A, STOCK_A, BALANCE_1, 10_000 + sequence, 100 + sequence
    return ACC2, SIM_B, STOCK_B, BALANCE_2, 20_000 + sequence, 200 + sequence


def sequences_of(broker_name):
    return [s for s in range(1, VOLUME + 1)
            if expected_quad(s)[1] == broker_name]


# ---------------------------------------------------------------------------
# Shared invariants — the full per-sequence chain on both broker trails
# ---------------------------------------------------------------------------


def assert_full_chain(run, harness):
    plan = run.plan

    # --- Plan shape: interleaved, complete, unique ---------------------------
    assert len(plan.orders) == VOLUME
    assert plan.execution_order == list(range(1, VOLUME + 1))
    assert len(set(plan.execution_order)) == VOLUME
    assert [o.nsc_id for o in plan.orders] == [
        STOCK_A, STOCK_B, STOCK_A, STOCK_B, STOCK_A, STOCK_B, STOCK_A, STOCK_B
    ]

    # --- Binding + routes keep the existing Block 6/7 semantics --------------
    binding = plan.conditions["binding"]
    assert plan.account_routes == {ACC1: SIM_A, ACC2: SIM_B}
    for sequence in range(1, VOLUME + 1):
        acc, broker, _ins, _bal, _price, _qty = expected_quad(sequence)
        assert binding[sequence]["account_id"] == acc
        assert binding[sequence]["broker_name"] == broker

    # --- Per-broker trail: exactly this broker's own sequences, in order -----
    for broker_name in (SIM_A, SIM_B):
        trail = run.brokers[broker_name].place_order_calls
        own = sequences_of(broker_name)
        assert len(trail) == len(own)
        for offset, sequence in enumerate(own):
            order, live = trail[offset]
            acc, _b, ins, _bal, price, qty = expected_quad(sequence)
            assert live is False
            # Identity (not equality): the broker received the plan's OWN
            # order object for that sequence.
            assert order is plan.orders[sequence - 1]
            assert (order.nsc_id, order.price, order.quantity) == (
                ins, price, qty
            )

    # No order object was duplicated across the two brokers.
    all_placed = [
        o for b in (SIM_A, SIM_B) for o, _ in run.brokers[b].place_order_calls
    ]
    assert len(all_placed) == VOLUME
    assert len({id(o) for o in all_placed}) == VOLUME

    # --- Account identity inside the real engine (M6-D fund proof) -----------
    for broker_name, balance, ins in (
        (SIM_A, BALANCE_1, STOCK_A),
        (SIM_B, BALANCE_2, STOCK_B),
    ):
        capacity = [
            c.payload for c in run.brokers[broker_name].calls
            if c.op == "get_buy_capacity"
        ]
        assert len(capacity) == len(sequences_of(broker_name))
        for payload in capacity:
            # The engine passed THIS path's account's own balance.
            assert payload["fund"] == balance
            assert payload["nsc_id"] == ins

    # --- DispatchResult consistent with the real executions ------------------
    assert run.dispatch_result.success is True
    assert run.dispatch_result.mode == "ALL_PROCESSED"
    assert run.dispatch_result.sent is False
    assert run.dispatch_result.order_count == VOLUME
    assert run.dispatch_result.trace_id is not None

    # --- Live trading stays off on BOTH brokers -------------------------------
    assert harness.broker.live_trading_enabled is False
    assert run.brokers[SIM_B].live_trading_enabled is False
    assert harness.dispatch_core.live_trading_enabled is False


# ---------------------------------------------------------------------------
# 1. Two brokers / two accounts construction
# ---------------------------------------------------------------------------


def test_dual_broker_harness_registers_two_independent_brokers():
    harness = make_harness()

    # Registered through the REAL manager seam:
    assert set(harness.manager.names()) == {SIM_A, SIM_B}
    broker_a = harness.manager.get(SIM_A)
    broker_b = harness.manager.get(SIM_B)
    assert isinstance(broker_a, SimulationBroker)
    assert isinstance(broker_b, SimulationBroker)
    assert broker_a is not broker_b  # two independent broker instances
    assert broker_a.name == SIM_A
    assert broker_b.name == SIM_B
    assert broker_a.live_trading_enabled is False
    assert broker_b.live_trading_enabled is False

    # The shared catalog serves exactly the two scenario instruments.
    assert set(harness.broker.catalog) == {STOCK_A, STOCK_B}


def test_multi_broker_run_executes_on_real_path():
    harness = make_harness()
    run = harness.run_multi_broker_scenario()

    # The run's brokers/providers ARE the manager's own instances — no
    # parallel wiring exists.
    assert run.brokers[SIM_A] is harness.manager.get(SIM_A)
    assert run.brokers[SIM_B] is harness.manager.get(SIM_B)

    assert run.reached_simulation_broker is True
    assert_full_chain(run, harness)


# ---------------------------------------------------------------------------
# 2-4. Account routing / broker routing / quad integrity
# ---------------------------------------------------------------------------


def test_account_routing_per_sequence():
    harness = make_harness()
    run = harness.run_multi_broker_scenario()

    binding = run.plan.conditions["binding"]
    for sequence in range(1, VOLUME + 1):
        acc, _broker, _ins, _bal, _price, _qty = expected_quad(sequence)
        assert binding[sequence]["account_id"] == acc
    assert {b["account_id"] for b in binding.values()} == {ACC1, ACC2}


def test_broker_routing_per_sequence():
    harness = make_harness()
    run = harness.run_multi_broker_scenario()

    binding = run.plan.conditions["binding"]
    for sequence in range(1, VOLUME + 1):
        _acc, broker, _ins, _bal, _price, _qty = expected_quad(sequence)
        assert binding[sequence]["broker_name"] == broker
    assert run.plan.account_routes == {ACC1: SIM_A, ACC2: SIM_B}
    assert set(run.plan.broker_names) == {SIM_A, SIM_B}


def test_sequence_account_broker_instrument_quad_integrity():
    harness = make_harness()
    run = harness.run_multi_broker_scenario()

    binding = run.plan.conditions["binding"]
    quads = set()
    for sequence in range(1, VOLUME + 1):
        acc, broker, ins, _bal, _price, _qty = expected_quad(sequence)
        order = run.plan.orders[sequence - 1]
        # The FULL quad must hold simultaneously for this sequence.
        assert (
            binding[sequence]["account_id"],
            binding[sequence]["broker_name"],
            order.nsc_id,
        ) == (acc, broker, ins)
        quads.add((sequence, acc, broker, ins))
    expected = {
        (s, ACC1, SIM_A, STOCK_A) if s % 2 == 1 else (s, ACC2, SIM_B, STOCK_B)
        for s in range(1, VOLUME + 1)
    }
    assert quads == expected


# ---------------------------------------------------------------------------
# 5-6. Order identity + exact per-broker call counts + trail isolation
# ---------------------------------------------------------------------------


def test_order_identity_and_exact_call_counts_per_broker():
    harness = make_harness()
    run = harness.run_multi_broker_scenario()

    trail_a = run.brokers[SIM_A].place_order_calls
    trail_b = run.brokers[SIM_B].place_order_calls
    assert len(trail_a) == VOLUME // 2  # SIM-A: exactly half
    assert len(trail_b) == VOLUME // 2  # SIM-B: exactly half
    assert len(trail_a) + len(trail_b) == VOLUME  # sum equals plan size

    placed_ids = [id(o) for o, _ in trail_a + trail_b]
    assert len(set(placed_ids)) == VOLUME  # no duplicated order object
    plan_ids = {id(o) for o in run.plan.orders}
    assert set(placed_ids) == plan_ids  # exactly the plan's own objects


def test_broker_trails_isolated_and_in_deterministic_order():
    harness = make_harness()
    run = harness.run_multi_broker_scenario()

    # SIM-A received ONLY Account 1 orders, in its own sequence order:
    assert [o for o, _ in run.brokers[SIM_A].place_order_calls] == [
        run.plan.orders[s - 1] for s in (1, 3, 5, 7)
    ]
    # SIM-B received ONLY Account 2 orders, in its own sequence order:
    assert [o for o, _ in run.brokers[SIM_B].place_order_calls] == [
        run.plan.orders[s - 1] for s in (2, 4, 6, 8)
    ]
    # Per-broker op trail: one full engine cycle per own order, in order.
    for broker_name in (SIM_A, SIM_B):
        ops = [c.op for c in run.brokers[broker_name].calls]
        assert ops.count("get_trading_state") == VOLUME // 2
        assert ops.count("get_buy_capacity") == VOLUME // 2
        assert ops.count("place_order") == VOLUME // 2


def test_account_identity_proven_by_engine_fund_values():
    harness = make_harness()
    run = harness.run_multi_broker_scenario()

    # The real M6-D gate receives account.tradable_balance_t1; balances are
    # disjoint, so the driving account of every broker call is provable.
    funds_a = {
        c.payload["fund"]
        for c in run.brokers[SIM_A].calls
        if c.op == "get_buy_capacity"
    }
    funds_b = {
        c.payload["fund"]
        for c in run.brokers[SIM_B].calls
        if c.op == "get_buy_capacity"
    }
    assert funds_a == {BALANCE_1}  # SIM-A executed ONLY with Account 1 funds
    assert funds_b == {BALANCE_2}  # SIM-B executed ONLY with Account 2 funds
    assert BALANCE_1 != BALANCE_2


# ---------------------------------------------------------------------------
# 8. Provider isolation (existing Block 7 per-broker provider contract)
# ---------------------------------------------------------------------------


def test_provider_isolation_per_broker():
    harness = make_harness()
    run = harness.run_multi_broker_scenario()

    provider_a = run.providers[SIM_A]
    provider_b = run.providers[SIM_B]
    assert isinstance(provider_a, InstrumentProvider)
    assert isinstance(provider_b, InstrumentProvider)
    assert provider_a is not provider_b

    # Each provider is bound (by the REAL manager) to its OWN broker and is
    # the manager's cached instance — no parallel provider wiring.
    assert provider_a._broker is run.brokers[SIM_A]
    assert provider_b._broker is run.brokers[SIM_B]
    assert harness.manager.providers[SIM_A] is provider_a
    assert harness.manager.providers[SIM_B] is provider_b

    # SIM-A's provider resolved ONLY Stock A; SIM-B's ONLY Stock B.
    codes_a = {c.split(":", 1)[1] for c in provider_a.calls if ":" in c}
    codes_b = {c.split(":", 1)[1] for c in provider_b.calls if ":" in c}
    assert codes_a == {STOCK_A}
    assert codes_b == {STOCK_B}


# ---------------------------------------------------------------------------
# 9. No cross-contamination (explicit association matrix)
# ---------------------------------------------------------------------------


def test_no_cross_contamination_between_paths():
    harness = make_harness()
    run = harness.run_multi_broker_scenario()

    binding = run.plan.conditions["binding"]
    trail_a = [o for o, _ in run.brokers[SIM_A].place_order_calls]
    trail_b = [o for o, _ in run.brokers[SIM_B].place_order_calls]

    # Instrument association, proven identity-wise against the REAL broker
    # trails: every order SIM-A actually received equals Account 1's own
    # order list (in order), and none of them is Stock B.
    acc1_orders = [
        run.plan.orders[s - 1] for s in range(1, VOLUME + 1)
        if binding[s]["account_id"] == ACC1
    ]
    assert acc1_orders == trail_a
    assert {o.nsc_id for o in acc1_orders} == {STOCK_A}

    # Same for the B path: every order SIM-B actually received equals
    # Account 2's own order list (in order), and none of them is Stock A.
    acc2_orders = [
        run.plan.orders[s - 1] for s in range(1, VOLUME + 1)
        if binding[s]["account_id"] == ACC2
    ]
    assert acc2_orders == trail_b
    assert {o.nsc_id for o in acc2_orders} == {STOCK_B}

    # --- Account → Sequence mapping is direct and exact -----------------------
    odd_sequences = {1, 3, 5, 7}
    even_sequences = {2, 4, 6, 8}

    assert {
        s for s in range(1, VOLUME + 1)
        if binding[s]["account_id"] == ACC1
    } == odd_sequences

    assert {
        s for s in range(1, VOLUME + 1)
        if binding[s]["account_id"] == ACC2
    } == even_sequences

    # --- Broker → Sequence mapping is direct and exact ------------------------
    # Read from the real plan binding: Broker A is bound ONLY to Account 1's
    # sequences and Broker B ONLY to Account 2's.
    assert {
        s for s in range(1, VOLUME + 1)
        if binding[s]["broker_name"] == SIM_A
    } == odd_sequences

    assert {
        s for s in range(1, VOLUME + 1)
        if binding[s]["broker_name"] == SIM_B
    } == even_sequences

    # --- The four forbidden paths, refuted from binding + real trails --------
    # 1) ACC-SIM-1 → SIM-B: no Account-1 sequence is routed to SIM-B.
    assert all(
        binding[s]["broker_name"] != SIM_B
        for s in range(1, VOLUME + 1)
        if binding[s]["account_id"] == ACC1
    )
    # 2) ACC-SIM-2 → SIM-A: no Account-2 sequence is routed to SIM-A.
    assert all(
        binding[s]["broker_name"] != SIM_A
        for s in range(1, VOLUME + 1)
        if binding[s]["account_id"] == ACC2
    )
    # 3) STOCK-A → SIM-B: SIM-B's real trail contains NO Stock A order.
    assert all(o.nsc_id != STOCK_A for o in trail_b)
    # 4) STOCK-B → SIM-A: SIM-A's real trail contains NO Stock B order.
    assert all(o.nsc_id != STOCK_B for o in trail_a)

    # Engine-level cross-check: funds never crossed brokers (an
    # Account-1 → SIM-B route would put BALANCE_1 on broker B).
    funds_a = {c.payload["fund"] for c in run.brokers[SIM_A].calls
               if c.op == "get_buy_capacity"}
    funds_b = {c.payload["fund"] for c in run.brokers[SIM_B].calls
               if c.op == "get_buy_capacity"}
    assert funds_a == {BALANCE_1}
    assert funds_b == {BALANCE_2}
    assert funds_a.isdisjoint(funds_b)


# ---------------------------------------------------------------------------
# 10. Consecutive-run isolation on ONE harness
# ---------------------------------------------------------------------------


def test_state_isolated_across_two_consecutive_runs():
    harness = make_harness()

    run1 = harness.run_multi_broker_scenario()
    snap_a = list(run1.brokers[SIM_A].place_order_calls)
    snap_b = list(run1.brokers[SIM_B].place_order_calls)
    assert len(snap_a) == VOLUME // 2
    assert len(snap_b) == VOLUME // 2

    run2 = harness.run_multi_broker_scenario()

    # Each broker's trail grew by exactly its own half — no replay of run 1.
    new_a = run1.brokers[SIM_A].place_order_calls[len(snap_a):]
    new_b = run1.brokers[SIM_B].place_order_calls[len(snap_b):]
    assert len(new_a) == VOLUME // 2
    assert len(new_b) == VOLUME // 2

    # Run 1's order objects were never reused: every run-2 call is
    # identity-equal to run 2's OWN plan orders.
    ids1 = {id(o) for o in run1.plan.orders}
    for offset, sequence in enumerate(sequences_of(SIM_A)):
        order, live = new_a[offset]
        assert order is run2.plan.orders[sequence - 1]
        assert live is False
        assert id(order) not in ids1
    for offset, sequence in enumerate(sequences_of(SIM_B)):
        order, live = new_b[offset]
        assert order is run2.plan.orders[sequence - 1]
        assert live is False
        assert id(order) not in ids1

    # Mapping did not drift between runs; state of run 1 did not alter run 2.
    assert run2.plan.account_routes == run1.plan.account_routes
    assert run2.plan.conditions["binding"] == run1.plan.conditions["binding"]
    assert run2.dispatch_result.mode == "ALL_PROCESSED"
    assert run2.dispatch_result.order_count == VOLUME
    # Funds still perfectly separated on run 2's own calls:
    funds_a = {c.payload["fund"] for c in run2.brokers[SIM_A].calls
               if c.op == "get_buy_capacity"}
    funds_b = {c.payload["fund"] for c in run2.brokers[SIM_B].calls
               if c.op == "get_buy_capacity"}
    assert funds_a == {BALANCE_1}
    assert funds_b == {BALANCE_2}


# ---------------------------------------------------------------------------
# 11. Deterministic rerun across two independent harnesses
# ---------------------------------------------------------------------------


def test_deterministic_rerun_excluding_trace_id_and_creation_date():
    a = make_harness().run_multi_broker_scenario()
    b = make_harness().run_multi_broker_scenario()

    # --- Plans identical ------------------------------------------------------
    assert a.plan.plan_id == b.plan.plan_id
    assert a.plan.execution_order == b.plan.execution_order
    assert a.plan.account_routes == b.plan.account_routes
    assert a.plan.conditions["binding"] == b.plan.conditions["binding"]
    assert [(o.nsc_id, o.price, o.quantity) for o in a.plan.orders] == [
        (o.nsc_id, o.price, o.quantity) for o in b.plan.orders
    ]

    # --- DispatchResults identical EXCEPT trace_id -----------------------------
    # Documented exclusion #1: DispatchCore generates ``trace_id =
    # str(uuid4())`` per dispatch — inherently random.
    a_fields = {
        k: v for k, v in a.dispatch_result.__dict__.items() if k != "trace_id"
    }
    b_fields = {
        k: v for k, v in b.dispatch_result.__dict__.items() if k != "trace_id"
    }
    assert a_fields == b_fields

    # --- Per-broker execution trails identical ---------------------------------
    # Documented exclusion #2: ``creationDate`` is the wall-clock stamp set
    # by models/order.py's ``datetime.now()`` default when each real Order
    # is constructed. No other field is excluded.
    def comparable(payload):
        if isinstance(payload, dict):
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
        assert a.providers[broker_name].calls == b.providers[broker_name].calls


# ---------------------------------------------------------------------------
# 12. Offline / live-trading guard (reused pattern from Tasks 9.1–9.4)
# ---------------------------------------------------------------------------


def test_multi_broker_uses_no_network_and_no_real_broker():
    # Guard 1: the production Agaah binding is never constructed.
    with patch("brokers.manager.AgaahBroker") as agaah_spy, patch(
        "brokers.manager.AgaahInstrumentProvider"
    ) as provider_spy:
        harness = make_harness()
        run = harness.run_multi_broker_scenario()
        agaah_spy.assert_not_called()
        provider_spy.assert_not_called()

    assert run.dispatch_result.mode == "ALL_PROCESSED"

    # Guard 2: any socket open attempt fails the run instantly.
    def forbidden_socket(*args, **kwargs):
        raise AssertionError("Network access attempted during multi-broker run")

    with patch(f"{socket.socket.__module__}.socket", forbidden_socket):
        harness2 = make_harness()
        run2 = harness2.run_multi_broker_scenario()

    assert run2.dispatch_result.mode == "ALL_PROCESSED"
    # Everything placed on either broker was a dry-run.
    for broker_name in (SIM_A, SIM_B):
        calls = run2.brokers[broker_name].place_order_calls
        assert len(calls) == VOLUME // 2
        assert all(live is False for _, live in calls)
        assert run2.brokers[broker_name].live_trading_enabled is False
    assert isinstance(run2.brokers[SIM_A], SimulationBroker)
    assert isinstance(run2.providers[SIM_B], SimulationInstrumentProvider)
