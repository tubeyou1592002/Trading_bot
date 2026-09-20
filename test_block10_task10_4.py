"""
Block 10 — Task 10.4: Final Controlled Live Verification (acceptance tests).

This file is the final acceptance suite for the controlled Live Execution
contract. It verifies — on the REAL dispatch path only — the three gaps
left open by the Task 10.2 / 10.3 focused suites:

  1. Per-prerequisite fail-closed matrix AT THE REAL DISPATCH LEVEL:
     for EVERY live prerequisite (Block 9 state, M6 result, broker
     readiness, explicit live request, human approval, live state), plus
     the no-gate / raising-gate / invalid-decision cases, the dispatch
     stays Dry Run (``live=False`` in the envelope observed at the real
     broker boundary, ``sent=False``, nothing submitted). (Task 10.4 §1+§3)

  2. Account/Broker identity ON THE LIVE PATH at the broker boundary:
     a dual-account / dual-broker plan with an ALLOWED gate and live-capable
     (simulation) brokers shows Broker A received exactly Order A of
     Account 1 and Broker B exactly Order B of Account 2, each carrying
     ``live=True`` from the single Task 10.3 bridge — no fallback, no
     cross-contamination — while each broker's own safety lock refused the
     submission. (Task 10.4 §2+§5)

  3. M6 still authoritative AFTER SafetyGate=ALLOW, even for a
     live-capable broker: a deterministic M6 order-validation failure
     (fund sufficiency, inside the M6-B validator stage) blocks the order
     BEFORE the engine live guard and before any broker call —
     SafetyGate → ALLOW, M6 → BLOCK, NO ORDER. (Task 10.4 §4)

Everything runs on the Task 9.1 offline simulation harness with the real
Planner, DispatchCore, BrokerManager, OrderEngine (M6-A … M6-E untouched)
and SimulationBroker. The ONLY test-only intervention is the Task 9.7
probe pattern: temporarily flipping the SIMULATION broker's
``live_trading_enabled`` (restored in ``finally``) so the live envelope can
be OBSERVED at the broker boundary where the broker lock refuses it. No
real broker, no credential, no network, and NO real order is ever sent.
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
M6_VALIDATOR_FUND_TEXT = "موجودی قابل معامله T1 مشخص نیست"

# The caller-supplied status contract (Task 10.2 final design): the TEST
# acts as the system's official wiring and supplies the vocabulary it
# recognizes as valid. The gate itself invents no vocabulary.
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


def build_basic_plan(harness, order, account, plan_id="task10.4-basic-plan"):
    """One-order plan via the REAL Block 1 planner (real binding)."""
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


def build_dual_plan(harness, plan_id="task10.4-dual-plan"):
    """Two-account / two-broker plan via the REAL Block 1 planner:
    Account 1 → Broker A → Order A (Stock A), Account 2 → Broker B →
    Order B (Stock B)."""
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


def assert_full_dry_run(harness, run):
    """The complete Dry Run signature, observed on the REAL broker
    boundary: the envelope carried live=False, nothing was submitted,
    and no flag moved."""
    assert run.dispatch_result.success is True
    assert run.dispatch_result.sent is False
    assert run.dispatch_result.mode == "ALL_PROCESSED"
    assert run.place_order_calls == [(run.plan.orders[0], False)]
    assert run.reached_simulation_broker is True
    assert harness.broker.live_trading_enabled is False
    assert harness.dispatch_core.live_trading_enabled is False


class _RaisingGate:
    """Bridge-seam double (the real gate never raises): exercises
    DispatchCore's own defensive branch."""

    def evaluate(self):
        raise RuntimeError("gate exploded")


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


# ---------------------------------------------------------------------------
# 1 + 3. Fail-closed matrix at the REAL dispatch level: any missing or
#        invalid live prerequisite (and any misbehaving gate) → the whole
#        dispatch stays Dry Run; no live request is created.
# ---------------------------------------------------------------------------


def test_prerequisite_fail_closed_matrix_at_dispatch_level():
    """Task 10.4 §1 + §3: each row makes exactly ONE live prerequisite
    missing/invalid while all others are valid — every row must end in a
    full Dry Run on the real path."""

    def wiring(**overrides):
        kwargs = dict(ALLOWED_GATE_KWARGS)
        kwargs.update(overrides)
        return SafetyGate(**kwargs)

    # (label, gate, expected blocked_by) — None blocked_by means the case
    # is handled by DispatchCore's own fail-closed branches (no gate /
    # raising gate / invalid decision object).
    cases = [
        ("no gate at all", None, None),
        ("block9_state invalid", wiring(live_block9_state="IN_PROGRESS"),
         "block9_state"),
        ("m6 prerequisite invalid", wiring(m6_status="UNVERIFIED"),
         "m6_gates"),
        ("broker prerequisite invalid", wiring(broker_status=None),
         "broker_status"),
        ("explicit live request absent",
         wiring(explicit_live_request=False), "explicit_live_request"),
        ("human approval absent", wiring(human_approval=False),
         "human_approval"),
        ("live state unknown", wiring(live_state="UNKNOWN"), "live_state"),
        ("gate raises", _RaisingGate(), None),
        ("decision None", _NoneDecisionGate(), None),
        ("decision alien (allowed=True, wrong type)",
         _AlienDecisionGate(), None),
    ]

    for label, gate, expected_blocked_by in cases:
        harness = SimulationHarness()
        harness.dispatch_core.safety_gate = gate

        if expected_blocked_by is not None:
            # The real Task 10.2 gate genuinely blocks for this wiring.
            decision = harness.dispatch_core.safety_gate.evaluate()
            assert decision.allowed is False, label
            assert decision.blocked_by == expected_blocked_by, (label,)

        run = harness.run_basic_scenario()  # must NOT raise, must NOT go live
        assert_full_dry_run(harness, run)


# ---------------------------------------------------------------------------
# 2 + 5. The controlled Live path with ALL contract conditions satisfied:
#        live=True reaches the envelope via the single Task 10.3 bridge and
#        Account/Broker identity is preserved AT the broker boundary —
#        each simulation broker saw exactly its own order, and each
#        broker's own lock refused it (no fallback, no contamination).
# ---------------------------------------------------------------------------


def test_dual_account_broker_identity_preserved_on_live_path():
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

    # ALL contract conditions hold: the real gate allows entry into Live.
    harness.dispatch_core.safety_gate = make_allowed_gate()
    assert harness.dispatch_core.safety_gate.evaluate().allowed is True

    broker_a = harness.manager.brokers[SIM_A]
    broker_b = harness.manager.brokers[SIM_B]
    try:
        # Test-only flip of the SIMULATION brokers (Task 9.7 probe
        # pattern) so the live envelopes are OBSERVABLE at the broker
        # boundary; each broker's own lock then refuses the submission.
        broker_a.live_trading_enabled = True
        broker_b.live_trading_enabled = True

        result, report = harness.dispatch_core.dispatch_with_latency(plan)
    finally:
        broker_a.live_trading_enabled = False
        broker_b.live_trading_enabled = False

    # The bridge changed no planning decision whatsoever.
    assert plan.conditions["binding"] == binding_before
    assert plan.account_routes == routes_before

    # Broker boundary (identity on the LIVE path): Broker A received
    # exactly Order A with live=True, Broker B exactly Order B with
    # live=True — each object by identity, no fallback, no swap.
    order_a, order_b = plan.orders
    assert broker_a.place_order_calls == [(order_a, True)]
    assert broker_b.place_order_calls == [(order_b, True)]

    # Each broker's own safety lock refused its live submission.
    per_a = report.order(1).execution_result
    per_b = report.order(2).execution_result
    for per in (per_a, per_b):
        assert per.mode == "ERROR"
        assert per.sent is False
        assert BROKER_LOCK_TEXT in per.message

    # Account/Broker identity per sequence, straight from the real path.
    assert report.order(1).account_id == ACC1
    assert report.order(1).broker_name == SIM_A
    assert per_a.order is order_a
    assert report.order(2).account_id == ACC2
    assert report.order(2).broker_name == SIM_B
    assert per_b.order is order_b

    # Cross-contamination checks: neither broker saw the other's order,
    # and each account's fund reached only its own broker's M6 read.
    assert [o for o, _ in broker_a.place_order_calls] == [order_a]
    assert [o for o, _ in broker_b.place_order_calls] == [order_b]
    a_funds = {
        c.payload["fund"] for c in broker_a.calls if c.op == "get_buy_capacity"
    }
    b_funds = {
        c.payload["fund"] for c in broker_b.calls if c.op == "get_buy_capacity"
    }
    assert a_funds == {1_000_000_000}
    assert b_funds == {2_000_000_000}

    # Aggregate fail-closed (ERROR never emits → BLOCKED, never sent).
    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"

    # Restored: nothing stays enabled after the test.
    assert broker_a.live_trading_enabled is False
    assert broker_b.live_trading_enabled is False
    assert harness.dispatch_core.live_trading_enabled is False


# ---------------------------------------------------------------------------
# 4. M6 remains authoritative AFTER SafetyGate=ALLOW — even for a
#    live-capable broker, a deterministic M6 capacity-stage failure blocks
#    the order BEFORE the engine live guard and BEFORE any broker call:
#    SafetyGate → ALLOW, M6 → BLOCK, NO ORDER.
# ---------------------------------------------------------------------------


def test_m6_blocks_live_approved_order_upstream_of_guard_and_broker():
    harness = SimulationHarness()
    harness.dispatch_core.safety_gate = make_allowed_gate()

    # Deterministic M6 order-validation failure (M6-B validator, fund
    # sufficiency): the account carries no computable T1 fund, so the
    # validator inside prepare() blocks — a DIFFERENT M6 gate and message
    # than the Task 10.3 M6-B quantity case. The order itself is valid
    # (passes M6-A identity and the trading-state read).
    order = make_simulation_order(quantity=10)
    account = make_simulation_account(tradable_balance_t1=None)
    plan = build_basic_plan(harness, order, account)

    broker = harness.broker
    try:
        # Live-capable simulation broker (test-only flip): the engine live
        # guard and broker lock would BOTH pass, isolating M6 as the only
        # possible blocker.
        broker.live_trading_enabled = True

        result, report = harness.dispatch_core.dispatch_with_latency(plan)
    finally:
        broker.live_trading_enabled = False

    per = report.order(1).execution_result
    # Blocked by the M6 validator stage — NOT by the live guard, NOT by
    # the broker lock, NOT by the gate bridge.
    assert per.mode == "BLOCKED"
    assert per.sent is False
    assert M6_VALIDATOR_FUND_TEXT in per.message
    assert ENGINE_GUARD_TEXT not in per.message
    assert BROKER_LOCK_TEXT not in per.message

    # NO ORDER: the M6 block happened upstream of submission — zero
    # place_order calls even though the gate allowed Live and the broker
    # was live-capable.
    assert broker.place_order_calls == []

    # Positive proof the M6 chain executed on the real path: prepare()
    # performed its real M6 trading-state read, and stopped inside the
    # M6-B validator stage BEFORE the get_buy_capacity API call.
    ops = [c.op for c in broker.calls]
    assert "get_trading_state" in ops
    assert "get_buy_capacity" not in ops

    # Aggregate fail-closed.
    assert result.mode == "BLOCKED"
    assert result.sent is False

    # Restored: nothing stays enabled after the test.
    assert broker.live_trading_enabled is False
    assert harness.dispatch_core.live_trading_enabled is False
