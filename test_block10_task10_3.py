"""
Block 10 — Task 10.3: Controlled Live Dispatch (focused tests).

ONE controlled bridge is under test: the real ``DispatchCore`` consumes the
real Task 10.2 ``SafetyGate`` decision at the exact boundary the Task 10.1
contract designated — the construction of ``BrokerDispatchRequest`` inside
``_dispatch()`` — so that ``live=True`` is produced ONLY when
``SafetyGateDecision.allowed is True``:

    ExecutionPlanner → ExecutionPlan → DispatchCore.dispatch()
        ↑ the bridge lives here (the ONLY live=True writer)
        → BrokerManager (binding preserved, untouched)
        → OrderEngine (M6-A … M6-E + engine live guard, authoritative)
        → SimulationBroker (broker-level live lock; the only seam)
        → DispatchResult

Everything runs on the REAL dispatch path (real DispatchCore, real
OrderEngine, real BrokerManager, real planner) with the Task 9.1 offline
harness — no second dispatch path, no real broker, no credential, no
network, and NO real order: the engine guard and the broker lock still
refuse live submissions fail-closed, and SimulationBroker refuses
``live=True`` unconditionally.

Fail-closed matrix proven against the real path:

    no gate attached      → live=False (Dry Run, default, unchanged)
    gate BLOCKED          → live=False (Dry Run)
    gate raises           → live=False (Dry Run)
    decision invalid      → live=False (Dry Run)
    gate ALLOWED          → live=True MAY appear in the envelope, and the
                            existing engine guard / broker lock still stop
                            any actual submission independently.

Per-order observability comes from the existing ``dispatch_with_latency``
entry point (the SAME single ``_dispatch`` implementation — using it here
also proves both public entry points share the one bridge).

The gate doubles used below (raising / returning None / returning an alien
decision object) exist ONLY at the bridge seam: the real Task 10.2 gate
never raises and always returns a valid ``SafetyGateDecision``, so
``DispatchCore``'s own defensive fail-closed branches can be exercised in
no other way. The doubles never touch DispatchCore, OrderEngine, or the
dispatch path itself.
"""

import types

from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from core.safety_gate import SafetyGate
from core.simulation_harness import (
    SimulationBroker,
    SimulationHarness,
    build_dual_broker_harness,
    make_simulation_account,
    make_simulation_order,
)

SIM = "SIM"
SIM_A, SIM_B = "SIM-A", "SIM-B"
ACC1, ACC2 = "ACC-SIM-1", "ACC-SIM-2"
STOCK_A, STOCK_B = "STOCK-A", "STOCK-B"
ENGINE_GUARD_TEXT = "live_trading_enabled=False"
BROKER_LOCK_TEXT = "forbidden in simulation"

# The caller-supplied status contract (Task 10.2 final design): the TEST
# acts as the system's official wiring and supplies the vocabulary it
# recognizes as valid. The gate itself invents no vocabulary; DispatchCore
# forwards the decision without interpreting it.
ALLOWED_GATE_KWARGS = dict(
    live_block9_state="COMPLETED",
    explicit_live_request=True,
    human_approval=True,
    live_state="KNOWN",
    m6_status="ACTIVE",
    broker_status="READY",
    acceptable_m6_statuses=("ACTIVE",),
    acceptable_broker_statuses=("READY",),
)


def make_allowed_gate() -> SafetyGate:
    """An ALLOWED decision from the REAL Task 10.2 gate."""
    return SafetyGate(**ALLOWED_GATE_KWARGS)


def build_basic_plan(harness, order, account, plan_id="task10.3-basic-plan"):
    """One-order plan via the REAL Block 1 planner (run_basic_scenario
    pattern: real planner, real binding, resolved Account attached)."""
    planned = PlannedOrder(
        order=order,
        account_id=account.account_id,
        broker_name=harness.broker_name,
        sequence=1,
    )
    plan = ExecutionPlanner().build_plan(
        LogicalOrderInstruction(plan_id=plan_id, orders=[planned])
    )
    plan.accounts = [account]
    return plan


def build_dual_plan(harness, plan_id="task10.3-dual-plan"):
    """Two-account / two-broker plan via the REAL Block 1 planner."""
    acc1 = make_simulation_account(ACC1, tradable_balance_t1=1_000_000_000)
    acc2 = make_simulation_account(ACC2, tradable_balance_t1=2_000_000_000)
    planned = [
        PlannedOrder(
            order=make_simulation_order(
                STOCK_A, side=1, price=11_000, quantity=110
            ),
            account_id=ACC1,
            broker_name=SIM_A,
            sequence=1,
        ),
        PlannedOrder(
            order=make_simulation_order(
                STOCK_B, side=1, price=22_000, quantity=220
            ),
            account_id=ACC2,
            broker_name=SIM_B,
            sequence=2,
        ),
    ]
    plan = ExecutionPlanner().build_plan(
        LogicalOrderInstruction(plan_id=plan_id, orders=planned)
    )
    plan.accounts = [acc1, acc2]
    return plan


def assert_dry_run(run):
    """The complete Dry Run signature on the real broker boundary."""
    assert run.dispatch_result.success is True
    assert run.dispatch_result.sent is False
    assert run.dispatch_result.mode == "ALL_PROCESSED"
    assert run.place_order_calls == [(run.plan.orders[0], False)]
    assert run.reached_simulation_broker is True


# ---------------------------------------------------------------------------
# 1. Default: no gate attached → Dry Run, byte-for-byte unchanged
# ---------------------------------------------------------------------------


def test_no_gate_attached_stays_dry_run():
    harness = SimulationHarness()
    core = harness.dispatch_core

    # Default construction: no permission authority, no live switch flipped.
    assert core.safety_gate is None
    assert core.live_trading_enabled is False
    assert harness.broker.live_trading_enabled is False
    assert isinstance(harness.broker, SimulationBroker)
    # The private manager registers ONLY the simulation pair.
    assert set(harness.manager.brokers) == {SIM}

    run = harness.run_basic_scenario()
    assert_dry_run(run)


# ---------------------------------------------------------------------------
# 2. Safety Gate BLOCKED → the dispatch must not create a Live request
# ---------------------------------------------------------------------------


def test_safety_gate_blocked_produces_no_live_request():
    blocking_gates = [
        SafetyGate(),  # default: nothing supplied → blocked (block9_state)
        # fully supplied but human approval absent → blocked (human_approval)
        SafetyGate(**{**ALLOWED_GATE_KWARGS, "human_approval": False}),
        # live status ambiguous → blocked (live_state)
        SafetyGate(**{**ALLOWED_GATE_KWARGS, "live_state": "UNKNOWN"}),
    ]
    for gate in blocking_gates:
        harness = SimulationHarness()
        harness.dispatch_core.safety_gate = gate
        # The real Task 10.2 gate genuinely blocks for each wiring above.
        assert gate.evaluate().allowed is False

        run = harness.run_basic_scenario()
        assert_dry_run(run)  # BLOCKED decision → live=False everywhere

    # Both public entry points funnel through the SAME single _dispatch
    # bridge: dispatch_with_latency stays Dry Run for a blocked gate too.
    harness = SimulationHarness()
    harness.dispatch_core.safety_gate = SafetyGate()
    run = harness.run_basic_scenario()
    assert_dry_run(run)
    result, report = harness.dispatch_core.dispatch_with_latency(run.plan)
    assert result.mode == "ALL_PROCESSED"
    assert report.order(1).execution_result.sent is False
    # the second dispatch appended one more dry-run call, still live=False
    assert all(
        live is False for _, live in harness.broker.place_order_calls
    )


# ---------------------------------------------------------------------------
# 3. Safety Gate ALLOWED → the envelope may contain live=True … and the
#    engine live guard (the preserved downstream layer) still refuses.
# ---------------------------------------------------------------------------


def test_gate_allowed_produces_live_envelope_engine_guard_blocks():
    harness = SimulationHarness()
    gate = make_allowed_gate()
    # The real Task 10.2 gate genuinely allows for this wiring.
    assert gate.evaluate().allowed is True
    harness.dispatch_core.safety_gate = gate

    order = make_simulation_order()
    plan = build_basic_plan(harness, order, make_simulation_account())

    # Broker live flag stays False (default) — the engine guard must hold.
    assert harness.broker.live_trading_enabled is False

    result, report = harness.dispatch_core.dispatch_with_latency(plan)

    # Aggregate fail-closed: BLOCKED, never sent.
    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    # The engine's own live-guard message is the failure reason: this
    # PROVES the envelope reached the engine carrying live=True (the only
    # way that guard can trigger), and the guard stopped it fail-closed.
    assert ENGINE_GUARD_TEXT in result.message

    per = report.order(1)
    assert per.broker_name == SIM
    assert per.execution_result.mode == "BLOCKED"
    assert per.execution_result.sent is False
    # Order identity preserved through the live envelope.
    assert per.execution_result.order is order

    # The guard returned BEFORE the broker: zero place_order calls —
    # no submission of any kind happened.
    assert harness.broker.place_order_calls == []
    assert all(c.op != "place_order" for c in harness.broker.calls)
    # Downstream flags untouched by the bridge.
    assert harness.broker.live_trading_enabled is False
    assert harness.dispatch_core.live_trading_enabled is False


# ---------------------------------------------------------------------------
# 4. Safety Gate ALLOWED + engine guard passes → the envelope's live=True is
#    observed AT the broker boundary, where the broker lock refuses it.
#    (Test-only flip of the SIMULATION broker's flag — the Task 9.7 probe
#    pattern; restored in finally; nothing real can happen offline.)
# ---------------------------------------------------------------------------


def test_allowed_live_envelope_reaches_broker_lock_and_is_refused():
    harness = SimulationHarness()
    harness.dispatch_core.safety_gate = make_allowed_gate()
    order = make_simulation_order()
    plan = build_basic_plan(harness, order, make_simulation_account())

    try:
        harness.broker.live_trading_enabled = True  # test-only, sim broker
        result, report = harness.dispatch_core.dispatch_with_latency(plan)
    finally:
        harness.broker.live_trading_enabled = False

    # DIRECT proof of the controlled bridge: the envelope arrived at the
    # real broker boundary with live=True — and the broker lock refused.
    assert harness.broker.place_order_calls == [(order, True)]
    per = report.order(1).execution_result
    assert per.sent is False
    assert per.mode == "ERROR"
    assert BROKER_LOCK_TEXT in per.message

    # Aggregate fail-closed.
    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    # Restored: nothing stays enabled after the test.
    assert harness.broker.live_trading_enabled is False
    assert harness.dispatch_core.live_trading_enabled is False


# ---------------------------------------------------------------------------
# 5. Gate raises → fail-closed to Dry Run (never fail-open)
# ---------------------------------------------------------------------------


class _ExplodingGate:
    """Bridge-seam double: the real Task 10.2 gate never raises (it
    converts errors to BLOCKED internally); this exercises DispatchCore's
    own defensive branch for a misbehaving supplied gate."""

    def evaluate(self):
        raise RuntimeError("gate exploded")


def test_gate_exception_fails_closed_to_dry_run():
    harness = SimulationHarness()
    harness.dispatch_core.safety_gate = _ExplodingGate()

    run = harness.run_basic_scenario()  # must NOT raise, must NOT go live
    assert_dry_run(run)


# ---------------------------------------------------------------------------
# 6. Invalid / missing decision → fail-closed to Dry Run
# ---------------------------------------------------------------------------


class _NoneDecisionGate:
    def evaluate(self):
        return None


class _AlienDecisionGate:
    """allowed=True but NOT a SafetyGateDecision → invalid → fail-closed."""

    def evaluate(self):
        return types.SimpleNamespace(
            allowed=True,
            mode="ALLOWED",
            blocked_by=None,
            reason="forged",
        )


def test_invalid_gate_decision_fails_closed_to_dry_run():
    for gate in (_NoneDecisionGate(), _AlienDecisionGate()):
        harness = SimulationHarness()
        harness.dispatch_core.safety_gate = gate

        run = harness.run_basic_scenario()
        assert_dry_run(run)


# ---------------------------------------------------------------------------
# 7. Account → Broker binding and order identity preserved under the bridge
# ---------------------------------------------------------------------------


def test_binding_and_identity_preserved_when_gate_allows_live():
    harness = build_dual_broker_harness(
        broker_a_name=SIM_A,
        broker_b_name=SIM_B,
        ins_codes=(STOCK_A, STOCK_B),
    )
    plan = build_dual_plan(harness)

    binding_before = {
        seq: dict(row) for seq, row in plan.conditions["binding"].items()
    }
    routes_before = dict(plan.account_routes)

    harness.dispatch_core.safety_gate = make_allowed_gate()
    result, report = harness.dispatch_core.dispatch_with_latency(plan)

    # The bridge changed no planning decision whatsoever.
    assert plan.conditions["binding"] == binding_before
    assert plan.account_routes == routes_before

    expected_account = {1: ACC1, 2: ACC2}
    expected_broker = {1: SIM_A, 2: SIM_B}
    for seq in (1, 2):
        per = report.order(seq)
        # Each sequence kept its exact Planner-decided account and broker.
        assert per.account_id == expected_account[seq]
        assert per.broker_name == expected_broker[seq]
        # Each live envelope was blocked by the engine guard, fail-closed.
        assert per.execution_result.mode == "BLOCKED"
        assert per.execution_result.sent is False
        assert per.execution_result.order is plan.orders[seq - 1]

    # No submission reached either broker — no cross-broker contamination.
    broker_a = harness.manager.brokers[SIM_A]
    broker_b = harness.manager.brokers[SIM_B]
    assert broker_a.place_order_calls == []
    assert broker_b.place_order_calls == []

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"


# ---------------------------------------------------------------------------
# 8. M6-A … M6-E still reached and still authoritative on the live path
# ---------------------------------------------------------------------------


def test_m6_gates_still_reached_when_gate_allows_live():
    harness = SimulationHarness()
    harness.dispatch_core.safety_gate = make_allowed_gate()

    # Deterministic M6-B violation (offline): zero quantity fails the
    # engine's order validation inside prepare(), BEFORE the live guard
    # is ever consulted.
    order = make_simulation_order(quantity=0)
    plan = build_basic_plan(
        harness, order, make_simulation_account()
    )

    result, report = harness.dispatch_core.dispatch_with_latency(plan)

    per = report.order(1).execution_result
    assert per.mode == "BLOCKED"
    assert per.sent is False
    # The block came from the M6 order-validation gate inside prepare(),
    # NOT from the engine live guard and NOT from the gate bridge.
    assert "بیشتر از صفر" in per.message
    assert ENGINE_GUARD_TEXT not in per.message

    # Positive proof M6 executed on the real path: prepare() performed its
    # real M6 trading-state read against the broker BEFORE blocking.
    ops = [c.op for c in harness.broker.calls]
    assert "get_trading_state" in ops
    # And nothing was submitted.
    assert harness.broker.place_order_calls == []
    assert result.mode == "BLOCKED"
    assert result.sent is False
