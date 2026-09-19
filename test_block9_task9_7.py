"""
Block 9 — Task 9.7: Acceptance & Closure test (independent verification).

ONE combined, deterministic Acceptance scenario that exercises EVERYTHING
proved individually in Tasks 9.1–9.6, together, on the REAL dispatch path —
no new architecture, no bypass, no production change:

    ExecutionPlanner → ExecutionPlan → DispatchCore.dispatch()
        → BrokerManager (per-sequence broker + provider resolution)
        → OrderEngine (M6-A … M6-E, untouched and NOT bypassed)
        → SimulationBroker SIM-A / SimulationBroker SIM-B
        → DispatchResult

Combined scenario (8 orders, ONE ExecutionPlan, ONE real dispatch call):

    seq % 4 == 1 → ACC-SIM-1 → SIM-A → STOCK-A   (healthy)
    seq % 4 == 3 → ACC-SIM-1 → SIM-A → STOCK-C   (healthy)
    seq % 4 == 2 → ACC-SIM-2 → SIM-B → STOCK-B   (failure injected at seq 2)
    seq % 4 == 0 → ACC-SIM-2 → SIM-B → STOCK-D   (healthy)

=> 2 accounts, 2 brokers, 4 instruments, 4 executions per account/broker,
   strictly interleaved (A/B/C/D pattern by sequence parity).

Failure injection (Task 9.6 mechanism ONLY — configure_failure, one-shot,
identity-scoped, exception mode) is armed on SIM-B for STOCK-B, so:
    * seq 2  → the injected failure inside the real engine path
    * seq 4/6/8 → independent Broker-B orders stay healthy (the one-shot
      disarm means even the second STOCK-B order at seq 6 runs normally)
    * every SIM-A order stays healthy and untouched.

Distinct balances / prices / quantities make every identity swap detectable
from the real trails alone (the real M6-D gate passes
``account.tradable_balance_t1`` as ``fund``).

The scenario builder lives INSIDE this test file (composed from the
existing harness components: ``build_dual_broker_harness``,
``build_simulation_catalog``, ``make_simulation_account``,
``make_simulation_order``, the real ``ExecutionPlanner``) — Task 9.7 is
Acceptance, not Development: zero production or harness changes.

Only the inherently random per-dispatch ``trace_id`` and the wall-clock
``creationDate`` order stamp are excluded from deterministic comparisons,
each with a documented reason.
"""

import socket
from unittest.mock import patch

from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from core.simulation_harness import (
    SimulationRunRecord,
    build_dual_broker_harness,
    build_simulation_catalog,
    make_simulation_account,
    make_simulation_order,
)

ACC1, ACC2 = "ACC-SIM-1", "ACC-SIM-2"
STOCK_A, STOCK_B, STOCK_C, STOCK_D = "STOCK-A", "STOCK-B", "STOCK-C", "STOCK-D"
SIM_A, SIM_B = "SIM-A", "SIM-B"
BALANCE_1, BALANCE_2 = 1_000_000_000, 2_000_000_000
VOLUME = 8

SIM_A_SEQS = (1, 3, 5, 7)  # SIM-A arrivals, ascending plan order
SIM_B_SEQS = (2, 4, 6, 8)  # SIM-B arrivals, ascending plan order
FAIL_SEQ = 2               # the ONLY injected failure
FAIL_TEXT = "SIM: acceptance failure (STOCK-B on SIM-B)"


def make_harness():
    """Acceptance environment: 2 brokers, 4 instruments — existing seams."""
    return build_dual_broker_harness(
        broker_a_name=SIM_A,
        broker_b_name=SIM_B,
        ins_codes=(STOCK_A, STOCK_B, STOCK_C, STOCK_D),
    )


def expected_row(sequence):
    """The ONLY allowed (account, broker, instrument, balance, price, qty)."""
    if sequence % 4 == 1:
        return ACC1, SIM_A, STOCK_A, BALANCE_1, 10_000 + sequence, 100 + sequence
    if sequence % 4 == 3:
        return ACC1, SIM_A, STOCK_C, BALANCE_1, 30_000 + sequence, 300 + sequence
    if sequence % 4 == 2:
        return ACC2, SIM_B, STOCK_B, BALANCE_2, 20_000 + sequence, 200 + sequence
    return ACC2, SIM_B, STOCK_D, BALANCE_2, 40_000 + sequence, 400 + sequence


def build_acceptance_plan(harness, plan_id="task9.7-acceptance-plan"):
    """ONE interleaved 8-order plan via the REAL Block 1 planner."""
    acc1 = make_simulation_account(ACC1, tradable_balance_t1=BALANCE_1)
    acc2 = make_simulation_account(ACC2, tradable_balance_t1=BALANCE_2)
    planned = []
    for sequence in range(1, VOLUME + 1):
        acc_id, broker_name, ins, _bal, price, qty = expected_row(sequence)
        planned.append(
            PlannedOrder(
                order=make_simulation_order(
                    ins_code=ins, side=1, price=price, quantity=qty
                ),
                account_id=acc_id,
                broker_name=broker_name,
                sequence=sequence,
            )
        )
    plan = ExecutionPlanner().build_plan(
        LogicalOrderInstruction(plan_id=plan_id, orders=planned)
    )
    plan.accounts = [acc1, acc2]
    return plan


def run_acceptance(harness, with_failure=True, plan_id="task9.7-acceptance-plan"):
    """Build, (optionally) arm the 9.6-style failure, and REALLY dispatch."""
    plan = build_acceptance_plan(harness, plan_id=plan_id)
    if with_failure:
        # Task 9.6 mechanism ONLY: one-shot, identity-scoped, exception mode.
        harness.manager.get(SIM_B).configure_failure(
            fail_on_nsc_id=STOCK_B,
            fail_mode="exception",
            failure_exception=RuntimeError(FAIL_TEXT),
        )
    result = harness.dispatch_core.dispatch(plan)  # the REAL dispatch
    return SimulationRunRecord(
        dispatch_result=result,
        broker=harness.broker,
        provider=harness.provider,
        plan=plan,
        brokers={
            name: harness.manager.get(name) for name in (SIM_A, SIM_B)
        },
        providers={
            name: harness.manager.get_instrument_provider(name)
            for name in (SIM_A, SIM_B)
        },
    )


def trail_orders(broker):
    return [o for o, _ in broker.place_order_calls]


def injected_kinds(broker):
    return [
        c.payload["kind"] for c in broker.calls if c.op == "injected_failure"
    ]


def assert_acceptance_chain(run, harness, expect_failure=True):
    """Every Acceptance invariant that must hold in every scenario variant."""
    plan = run.plan

    # --- Plan shape: interleaved, complete, unique ---------------------------
    assert len(plan.orders) == VOLUME
    assert plan.execution_order == list(range(1, VOLUME + 1))
    assert [o.nsc_id for o in plan.orders] == [
        STOCK_A, STOCK_B, STOCK_C, STOCK_D, STOCK_A, STOCK_B, STOCK_C, STOCK_D
    ]

    # --- Binding integrity: exact quad per sequence --------------------------
    binding = plan.conditions["binding"]
    assert plan.account_routes == {ACC1: SIM_A, ACC2: SIM_B}
    for sequence in range(1, VOLUME + 1):
        acc, broker, ins, _bal, _price, _qty = expected_row(sequence)
        assert binding[sequence]["account_id"] == acc
        assert binding[sequence]["broker_name"] == broker
        order = plan.orders[sequence - 1]
        assert order.nsc_id == ins

    # --- Per-broker trails: exactly this broker's own orders, once, in order --
    for broker_name, own_seqs in ((SIM_A, SIM_A_SEQS), (SIM_B, SIM_B_SEQS)):
        trail = run.brokers[broker_name].place_order_calls
        assert len(trail) == len(own_seqs)
        for offset, sequence in enumerate(own_seqs):
            order, live = trail[offset]
            acc, _b, ins, _bal, price, qty = expected_row(sequence)
            assert live is False
            # Order identity (not equality): the plan's OWN object.
            assert order is plan.orders[sequence - 1]
            assert (order.nsc_id, order.price, order.quantity) == (
                ins, price, qty
            )
        # M6-A..M6-E active on the real path: every executed order passed the
        # real trading-state gate (M6-A input) and the real capacity gate
        # (M6-D) BEFORE placement, exactly once each.
        ops = [c.op for c in run.brokers[broker_name].calls]
        assert ops.count("get_trading_state") == len(own_seqs)
        assert ops.count("get_buy_capacity") == len(own_seqs)
        assert ops.count("place_order") == len(own_seqs)
        first_place = ops.index("place_order")
        assert ops.index("get_trading_state") < first_place
        assert ops.index("get_buy_capacity") < first_place

    # No duplicated order object across the whole dispatch.
    placed = [
        o for b in (SIM_A, SIM_B) for o, _ in run.brokers[b].place_order_calls
    ]
    assert len(placed) == VOLUME
    assert len({id(o) for o in placed}) == VOLUME

    # --- Account identity via the real engine (M6-D fund proof) --------------
    funds_a = {
        c.payload["fund"] for c in run.brokers[SIM_A].calls
        if c.op == "get_buy_capacity"
    }
    funds_b = {
        c.payload["fund"] for c in run.brokers[SIM_B].calls
        if c.op == "get_buy_capacity"
    }
    assert funds_a == {BALANCE_1}  # SIM-A ran ONLY with Account 1's funds
    assert funds_b == {BALANCE_2}  # SIM-B ran ONLY with Account 2's funds

    # --- Failure scope (when armed): exactly one, on the intended path -------
    if expect_failure:
        assert injected_kinds(run.brokers[SIM_B]) == ["exception"]
        assert injected_kinds(run.brokers[SIM_A]) == []
        assert run.dispatch_result.success is False
        assert run.dispatch_result.mode == "BLOCKED"
        assert run.dispatch_result.sent is False
        # The injected exception text traveled the REAL engine path into the
        # aggregate fail-closed message (order_engine except-branch ->
        # _build_result first-failure message).
        assert FAIL_TEXT in run.dispatch_result.message
    else:
        assert injected_kinds(run.brokers[SIM_A]) == []
        assert injected_kinds(run.brokers[SIM_B]) == []
        assert run.dispatch_result.success is True
        assert run.dispatch_result.mode == "ALL_PROCESSED"
        assert run.dispatch_result.sent is False
    assert run.dispatch_result.order_count == VOLUME
    assert run.dispatch_result.trace_id is not None

    # --- Live trading stays off everywhere ------------------------------------
    assert harness.broker.live_trading_enabled is False
    assert run.brokers[SIM_A].live_trading_enabled is False
    assert run.brokers[SIM_B].live_trading_enabled is False
    assert harness.dispatch_core.live_trading_enabled is False


# ---------------------------------------------------------------------------
# 1. Combined multi-account + multi-broker scenario on the real path
# ---------------------------------------------------------------------------


def test_combined_acceptance_scenario_runs_on_real_path():
    harness = make_harness()
    run = run_acceptance(harness, with_failure=True)

    # The run's brokers/providers ARE the manager's own — no parallel wiring.
    assert run.brokers[SIM_A] is harness.manager.get(SIM_A)
    assert run.brokers[SIM_B] is harness.manager.get(SIM_B)
    assert set(harness.manager.names()) == {SIM_A, SIM_B}
    assert set(harness.broker.catalog) == {STOCK_A, STOCK_B, STOCK_C, STOCK_D}

    # 2 accounts / 2 brokers / 4 instruments / 4 executions each.
    assert {a.account_id for a in run.plan.accounts} == {ACC1, ACC2}
    assert {b for b in run.plan.account_routes.values()} == {SIM_A, SIM_B}
    assert {o.nsc_id for o in run.plan.orders} == {
        STOCK_A, STOCK_B, STOCK_C, STOCK_D
    }
    assert len(run.brokers[SIM_A].place_order_calls) == 4
    assert len(run.brokers[SIM_B].place_order_calls) == 4

    assert_acceptance_chain(run, harness, expect_failure=True)


# ---------------------------------------------------------------------------
# 2. Binding / account / broker / instrument isolation
# ---------------------------------------------------------------------------


def test_binding_and_isolation_matrix():
    harness = make_harness()
    run = run_acceptance(harness, with_failure=True)

    binding = run.plan.conditions["binding"]
    trail_a = run.brokers[SIM_A].place_order_calls
    trail_b = run.brokers[SIM_B].place_order_calls

    # A) Account isolation — each account's orders went ONLY to its own path.
    acc1_orders = [
        run.plan.orders[s - 1] for s in range(1, VOLUME + 1)
        if binding[s]["account_id"] == ACC1
    ]
    acc2_orders = [
        run.plan.orders[s - 1] for s in range(1, VOLUME + 1)
        if binding[s]["account_id"] == ACC2
    ]
    assert [o for o, _ in trail_a] == acc1_orders  # identity list equality
    assert [o for o, _ in trail_b] == acc2_orders
    assert {id(o) for o in acc1_orders}.isdisjoint(
        {id(o) for o in trail_orders(run.brokers[SIM_B])}
    )
    assert {id(o) for o in acc2_orders}.isdisjoint(
        {id(o) for o in trail_orders(run.brokers[SIM_A])}
    )

    # B) Broker isolation — binding reads SIM-A only on odd, SIM-B only on even.
    assert {
        s for s in range(1, VOLUME + 1)
        if binding[s]["broker_name"] == SIM_A
    } == {1, 3, 5, 7}
    assert {
        s for s in range(1, VOLUME + 1)
        if binding[s]["broker_name"] == SIM_B
    } == {2, 4, 6, 8}
    assert {b["broker_name"] for b in binding.values()} == {SIM_A, SIM_B}

    # C) Instrument isolation — each stock appears ONLY on its own path.
    assert {o.nsc_id for o in trail_orders(run.brokers[SIM_A])} == {
        STOCK_A, STOCK_C
    }
    assert {o.nsc_id for o in trail_orders(run.brokers[SIM_B])} == {
        STOCK_B, STOCK_D
    }
    for sequence in range(1, VOLUME + 1):
        _acc, _broker, ins, _bal, price, qty = expected_row(sequence)
        order = run.plan.orders[sequence - 1]
        assert (order.nsc_id, order.price, order.quantity) == (ins, price, qty)

    # D) Full quad integrity, per sequence, in one assertion.
    for sequence in range(1, VOLUME + 1):
        acc, broker, ins, _bal, _price, _qty = expected_row(sequence)
        assert (
            sequence,
            binding[sequence]["account_id"],
            binding[sequence]["broker_name"],
            run.plan.orders[sequence - 1].nsc_id,
        ) == (sequence, acc, broker, ins)

    assert_acceptance_chain(run, harness, expect_failure=True)


# ---------------------------------------------------------------------------
# 3. Failure isolation inside the combined scenario
# ---------------------------------------------------------------------------


def test_failure_isolation_in_combined_scenario():
    harness = make_harness()
    run = run_acceptance(harness, with_failure=True)

    # The failure happened EXACTLY once, on SIM-B, scoped to STOCK-B.
    injected = [
        c for c in run.brokers[SIM_B].calls if c.op == "injected_failure"
    ]
    assert len(injected) == 1
    assert injected[0].payload == {
        "kind": "exception", "nsc_id": STOCK_B
    }
    assert run.brokers[SIM_B].fired_count == 1

    # SIM-A's entire trail is IDENTICAL to the failure-free expectation:
    # same objects, same order, all dry-run — zero failure contamination.
    trail_a = run.brokers[SIM_A].place_order_calls
    assert [o for o, _ in trail_a] == [
        run.plan.orders[s - 1] for s in SIM_A_SEQS
    ]
    assert all(live is False for _, live in trail_a)

    # SIM-B's independent orders (seq 4, 6, 8 — incl. the second STOCK-B,
    # because the 9.6 failure is one-shot) were still attempted exactly once
    # and in order: failure did not contaminate the whole broker path.
    trail_b = trail_orders(run.brokers[SIM_B])
    assert trail_b == [run.plan.orders[s - 1] for s in SIM_B_SEQS]

    # E) The failure changed NO identity/routing: binding byte-identical to
    # the failure-free plan structure.
    binding = run.plan.conditions["binding"]
    for sequence in range(1, VOLUME + 1):
        acc, broker, ins, _bal, _price, _qty = expected_row(sequence)
        assert binding[sequence]["account_id"] == acc
        assert binding[sequence]["broker_name"] == broker
    assert run.plan.account_routes == {ACC1: SIM_A, ACC2: SIM_B}

    # I) Result integrity = the CURRENT contract's real behavior: per-order
    # ERROR on the failing sequence, aggregate fail-closed BLOCKED for the
    # dispatch, all 8 orders accounted for (none lost).
    assert run.dispatch_result.mode == "BLOCKED"
    assert run.dispatch_result.success is False
    assert run.dispatch_result.order_count == VOLUME
    assert FAIL_TEXT in run.dispatch_result.message

    assert_acceptance_chain(run, harness, expect_failure=True)


# ---------------------------------------------------------------------------
# 4. No loss / no duplication / identity integrity
# ---------------------------------------------------------------------------


def test_no_loss_no_duplication_identity_integrity():
    harness = make_harness()
    run = run_acceptance(harness, with_failure=True)

    # F) No lost executions: every sequence reached exactly one broker.
    placed = [o for b in (SIM_A, SIM_B) for o, _ in
              run.brokers[b].place_order_calls]
    assert len(placed) == VOLUME
    assert {id(o) for o in placed} == {id(o) for o in run.plan.orders}

    # G) No duplicated executions: each order object exactly once overall.
    assert len({id(o) for o in placed}) == VOLUME
    for broker_name in (SIM_A, SIM_B):
        ops = [c.op for c in run.brokers[broker_name].calls]
        assert ops.count("place_order") == 4
        assert ops.count("get_trading_state") == 4
        assert ops.count("get_buy_capacity") == 4

    # H) Order identity: every placement IS the plan's own object at its
    # sequence slot (identity, not equality).
    for broker_name, own in ((SIM_A, SIM_A_SEQS), (SIM_B, SIM_B_SEQS)):
        for offset, sequence in enumerate(own):
            order, live = run.brokers[broker_name].place_order_calls[offset]
            assert order is run.plan.orders[sequence - 1]
            assert live is False

    assert_acceptance_chain(run, harness, expect_failure=True)


# ---------------------------------------------------------------------------
# 5. State isolation: failure run → healthy run on ONE harness
# ---------------------------------------------------------------------------


def test_state_isolation_failure_then_healthy_run():
    harness = make_harness()

    run1 = run_acceptance(harness, with_failure=True)
    # Snapshot cumulative trails (brokers/providers are shared per harness).
    snap_a = list(run1.brokers[SIM_A].place_order_calls)
    snap_b = list(run1.brokers[SIM_B].place_order_calls)
    snap_inj_a = len(injected_kinds(run1.brokers[SIM_A]))
    snap_inj_b = len(injected_kinds(run1.brokers[SIM_B]))
    snap_fired = run1.brokers[SIM_B].fired_count
    assert run1.dispatch_result.mode == "BLOCKED"

    run2 = run_acceptance(harness, with_failure=False)  # healthy run

    # Failure did NOT leak: zero NEW injected failures anywhere.
    assert len(injected_kinds(run2.brokers[SIM_A])) == snap_inj_a
    assert len(injected_kinds(run2.brokers[SIM_B])) == snap_inj_b
    assert run2.brokers[SIM_B].fired_count == snap_fired  # no new firing
    assert run2.dispatch_result.mode == "ALL_PROCESSED"
    assert run2.dispatch_result.order_count == VOLUME
    assert run2.dispatch_result.success is True

    # Exact per-broker growth: 4 more placements each, no replay of run 1.
    new_a = run2.brokers[SIM_A].place_order_calls[len(snap_a):]
    new_b = run2.brokers[SIM_B].place_order_calls[len(snap_b):]
    assert len(new_a) == 4
    assert len(new_b) == 4
    # Run 2's identities belong to Run 2's OWN plan objects.
    for offset, sequence in enumerate(SIM_A_SEQS):
        order, live = new_a[offset]
        assert order is run2.plan.orders[sequence - 1]
        assert live is False
    for offset, sequence in enumerate(SIM_B_SEQS):
        order, live = new_b[offset]
        assert order is run2.plan.orders[sequence - 1]
        assert live is False
    ids1 = {id(o) for o in run1.plan.orders}
    assert {id(o) for o in new_a + new_b}.isdisjoint(ids1)

    # Run 1's failure did not corrupt Run 2's routing or counters:
    # funds still perfectly separated, binding unchanged, gates re-run.
    assert {
        c.payload["fund"] for c in run2.brokers[SIM_A].calls
        if c.op == "get_buy_capacity"
    } == {BALANCE_1}
    assert {
        c.payload["fund"] for c in run2.brokers[SIM_B].calls
        if c.op == "get_buy_capacity"
    } == {BALANCE_2}
    assert run2.plan.conditions["binding"] == run1.plan.conditions["binding"]
    assert run2.plan.account_routes == run1.plan.account_routes
    # Live flags stayed off on the shared brokers across both runs.
    assert run2.brokers[SIM_A].live_trading_enabled is False
    assert run2.brokers[SIM_B].live_trading_enabled is False
    assert harness.dispatch_core.live_trading_enabled is False
    # NOTE: the full per-broker chain helper is intentionally NOT re-run
    # here — broker trails are cumulative on ONE harness (4+4 per broker),
    # and every run-2-specific invariant is asserted above via deltas.


# ---------------------------------------------------------------------------
# 6. Deterministic rerun (two independent harnesses)
# ---------------------------------------------------------------------------


def test_acceptance_deterministic_rerun():
    a = run_acceptance(make_harness(), with_failure=True)
    b = run_acceptance(make_harness(), with_failure=True)

    # Plan structure / sequences / bindings / instrument mapping identical.
    assert a.plan.plan_id == b.plan.plan_id
    assert a.plan.execution_order == b.plan.execution_order
    assert a.plan.account_routes == b.plan.account_routes
    assert a.plan.conditions["binding"] == b.plan.conditions["binding"]
    assert [(o.nsc_id, o.price, o.quantity) for o in a.plan.orders] == [
        (o.nsc_id, o.price, o.quantity) for o in b.plan.orders
    ]

    # Aggregate result fields identical (documented exclusion #1: the random
    # per-dispatch ``trace_id`` = str(uuid4()) inside DispatchCore).
    a_fields = {
        k: v for k, v in a.dispatch_result.__dict__.items() if k != "trace_id"
    }
    b_fields = {
        k: v for k, v in b.dispatch_result.__dict__.items() if k != "trace_id"
    }
    assert a_fields == b_fields

    # Relevant broker operation trails identical, per broker (documented
    # exclusion #2: ``creationDate`` is the wall-clock stamp set by the real
    # models/order.py datetime.now() default). Nothing else is excluded.
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

    # Failure position/outcome deterministic: exactly one exception on SIM-B.
    assert injected_kinds(a.brokers[SIM_B]) == injected_kinds(b.brokers[SIM_B])
    assert a.brokers[SIM_B].fired_count == b.brokers[SIM_B].fired_count == 1


# ---------------------------------------------------------------------------
# 7. Offline / live-trading safety (guards reused from Tasks 9.1–9.6)
# ---------------------------------------------------------------------------


def test_acceptance_offline_and_live_safety():
    # Guard 1: the production Agaah binding is never constructed.
    with patch("brokers.manager.AgaahBroker") as agaah_spy, patch(
        "brokers.manager.AgaahInstrumentProvider"
    ) as provider_spy:
        harness = make_harness()
        run = run_acceptance(harness, with_failure=True)
        agaah_spy.assert_not_called()
        provider_spy.assert_not_called()

    # Guard 2: any socket open attempt fails instantly — the run (including
    # the simulated timeout-free exception path) needs no network at all.
    def forbidden_socket(*args, **kwargs):
        raise AssertionError("Network access attempted during acceptance run")

    with patch(f"{socket.socket.__module__}.socket", forbidden_socket):
        harness2 = make_harness()
        run2 = run_acceptance(harness2, with_failure=True)

    # No credentials anywhere: no login call on either broker trail.
    for broker_name in (SIM_A, SIM_B):
        assert all(
            c.op != "login" for c in run2.brokers[broker_name].calls
        )

    # Full acceptance chain FIRST (before any manual live-probe can touch
    # the broker trails below).
    assert_acceptance_chain(run2, harness2, expect_failure=True)

    # live=True cannot become a real order: the broker refuses fail-closed
    # (and the engine layer blocks independently when the flag is False).
    # NOTE: the broker records the ATTEMPT before refusing, so this probe
    # runs last and its one trail entry is not misread as a dispatch.
    broker_b = run2.brokers[SIM_B]
    assert all(live is False for _, live in broker_b.place_order_calls)
    try:
        broker_b.live_trading_enabled = True  # temporarily flip (test only)
        try:
            broker_b.place_order(run2.plan.orders[1], live=True)
            raised = False
        except RuntimeError:
            raised = True
        assert raised is True
    finally:
        broker_b.live_trading_enabled = False
    assert broker_b.live_trading_enabled is False
    assert harness2.dispatch_core.live_trading_enabled is False
