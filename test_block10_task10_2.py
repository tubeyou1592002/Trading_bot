"""
Block 10 — Task 10.2: Safety Gate tests (focused, narrowed responsibility).

The Safety Gate is ONLY the final fail-closed lock that decides whether
entry into Live execution is permitted, based on the live-permission
prerequisites supplied to it. Per the Task 10.2 review:

  * it does NOT re-implement M6 (an M6 RESULT is supplied as data),
  * it does NOT re-do binding (no account/broker is resolved here),
  * it does NOT run instrument resolution,
  * it is NOT connected to DispatchCore and nothing wires it in,
  * it invents NO "allowed for live" status vocabulary: which external
    prerequisite values are valid is supplied by the CALLER as the
    system's official contract; the empty default blocks everything.

These tests therefore exercise the gate purely as a permission evaluator:
default -> BLOCKED, every invalid prerequisite -> BLOCKED, any exception
during validation -> BLOCKED, all prerequisites valid (per the
caller-supplied contract) -> ALLOWED.

No real order is sent, ``live=True`` is never executed, and the real
dispatch path is never invoked. The harness is used only to assert that
the unchanged Dry Run default of the real system still holds.
"""

from core.safety_gate import (
    BLOCK9_COMPLETED,
    SafetyGate,
    SafetyGateDecision,
)


# Caller-supplied contract values, deliberately NOT gate-defined tokens
# (they are arbitrary strings the calling system's wiring recognizes).
M6_OK = "M6-OK-BY-CALLER-CONTRACT"
BROKER_OK = "BROKER-OK-BY-CALLER-CONTRACT"

GATE_DEFAULTS = {
    "live_block9_state": BLOCK9_COMPLETED,
    "explicit_live_request": True,
    "human_approval": True,
    "live_state": "KNOWN",
    "m6_status": M6_OK,
    "broker_status": BROKER_OK,
    "acceptable_m6_statuses": (M6_OK,),
    "acceptable_broker_statuses": (BROKER_OK,),
}


def build_gate(**overrides) -> SafetyGate:
    """A gate with every prerequisite validly satisfied under the
    caller-supplied contract, overridable per test."""
    values = dict(GATE_DEFAULTS)
    values.update(overrides)
    return SafetyGate(**values)


def evaluate(gate: SafetyGate, **overrides) -> SafetyGateDecision:
    """Evaluate with the instance-level supplied statuses, overridable."""
    return gate.evaluate(**overrides)


# ---------------------------------------------------------------------------
# 1. Default gate -> BLOCKED (Dry Run stays the system default)
# ---------------------------------------------------------------------------


def test_default_gate_blocks():
    decision = SafetyGate().evaluate()
    assert isinstance(decision, SafetyGateDecision)
    assert decision.allowed is False
    assert decision.mode == "BLOCKED"
    assert decision.blocked_by == "block9_state"

    # Nothing was sent: the gate holds no order path at all.
    gate = SafetyGate()
    assert not hasattr(gate, "dispatch")
    assert not hasattr(gate, "place_order")


# ---------------------------------------------------------------------------
# 2. Each invalid prerequisite -> BLOCKED
# ---------------------------------------------------------------------------


def test_block9_state_invalid_blocks():
    for bad in ("IN_PROGRESS", "NOT_STARTED", "UNKNOWN", "", None):
        gate = build_gate(live_block9_state=bad)
        decision = evaluate(gate)
        assert decision.allowed is False, f"Block9={bad!r} must block"
        assert decision.mode == "BLOCKED"
        assert decision.blocked_by == "block9_state", (
            bad,
            decision.blocked_by,
        )


def test_missing_explicit_live_request_blocks():
    gate = build_gate(explicit_live_request=False)
    decision = evaluate(gate)
    assert decision.allowed is False
    assert decision.mode == "BLOCKED"
    assert decision.blocked_by == "explicit_live_request"


def test_missing_human_approval_blocks():
    gate = build_gate(human_approval=False)
    decision = evaluate(gate)
    assert decision.allowed is False
    assert decision.mode == "BLOCKED"
    assert decision.blocked_by == "human_approval"


def test_unknown_live_state_blocks():
    for bad in ("UNKNOWN", "UNVERIFIED", "BLOCKED", "", None, "MAYBE"):
        gate = build_gate(live_state=bad)
        decision = evaluate(gate)
        assert decision.allowed is False, f"live_state={bad!r} must block"
        assert decision.blocked_by == "live_state", (
            bad,
            decision.blocked_by,
        )


def test_m6_prerequisite_missing_unknown_unverified_blocked_blocks():
    """The M6 prerequisite is consumed as supplied RESULT data only: any
    missing/UNKNOWN/UNVERIFIED/BLOCKED value blocks."""
    for bad in (None, "UNKNOWN", "UNVERIFIED", "BLOCKED", ""):
        gate = build_gate(m6_status=bad)
        decision = evaluate(gate)
        assert decision.allowed is False, f"m6_status={bad!r} must block"
        assert decision.blocked_by == "m6_gates", (
            bad,
            decision.blocked_by,
        )

    # Per-evaluation override wins over a valid instance value.
    gate = build_gate()
    decision = gate.evaluate(m6_status="BLOCKED")
    assert decision.allowed is False
    assert decision.blocked_by == "m6_gates"


def test_broker_prerequisite_missing_unknown_unverified_blocked_blocks():
    """The live-capable broker readiness is consumed as supplied RESULT
    data only — the gate never resolves any broker object."""
    for bad in (None, "UNKNOWN", "UNVERIFIED", "BLOCKED", ""):
        gate = build_gate(broker_status=bad)
        decision = gate.evaluate()
        assert decision.allowed is False, f"broker_status={bad!r} must block"
        assert decision.blocked_by == "broker_status", (
            bad,
            decision.blocked_by,
        )


def test_gate_invents_no_status_vocabulary():
    """The core fix of this review: the gate must NOT itself decide that
    VERIFIED / READY / ACTIVE (or any token) means 'permitted for live'.

    With the empty default contract, every external status — including
    plausible-sounding ones — blocks. Only values explicitly recognized
    by the CALLER-supplied contract pass."""
    for status in ("VERIFIED", "READY", "ACTIVE", "OK", "GOOD", "PASSED"):
        gate = build_gate(m6_status=status, broker_status=status,
                          acceptable_m6_statuses=(),
                          acceptable_broker_statuses=())
        decision = gate.evaluate()
        assert decision.allowed is False, (
            f"empty contract must block {status!r}"
        )
        assert decision.blocked_by in ("m6_gates", "broker_status")

    # The caller contract governs: with {"ACTIVE"} supplied by the caller,
    # "ACTIVE" passes but every other token still blocks.
    gate = build_gate(
        m6_status="ACTIVE",
        broker_status="ACTIVE",
        acceptable_m6_statuses=("ACTIVE",),
        acceptable_broker_statuses=("ACTIVE",),
    )
    decision = gate.evaluate()
    assert decision.allowed is True
    assert decision.blocked_by is None

    for foreign in ("VERIFIED", "READY"):
        decision = build_gate(
            m6_status=foreign,
            acceptable_m6_statuses=("ACTIVE",),
            acceptable_broker_statuses=("ACTIVE",),
        ).evaluate()
        assert decision.allowed is False, foreign
        assert decision.blocked_by == "m6_gates"


# ---------------------------------------------------------------------------
# 3. Exception during validation -> BLOCKED (fail-closed)
# ---------------------------------------------------------------------------


def test_exception_during_validation_blocks():
    class ExplodingGate(SafetyGate):
        """Test-only subclass whose live-state check raises; the gate's
        fail-closed wrapper must convert the raised exception into BLOCKED,
        never propagate it, never allow."""

        def _check_live_state(self):
            raise RuntimeError("boom")

    gate = build_gate()
    gate.__class__ = ExplodingGate  # the live-state check will raise
    try:
        # All earlier prerequisites supplied valid, so evaluation actually
        # reaches the exploding live-state check.
        decision = gate.evaluate()
    except Exception as exc:  # pragma: no cover - must NOT happen
        raise AssertionError(f"gate leaked an exception: {exc!r}")
    assert decision.allowed is False
    assert decision.mode == "BLOCKED"
    assert decision.blocked_by == "exception"
    assert "boom" in decision.reason


# ---------------------------------------------------------------------------
# 4. All prerequisites valid (caller-supplied contract) -> ALLOWED
# ---------------------------------------------------------------------------


def test_all_prerequisites_valid_allows():
    decision = evaluate(build_gate())
    assert decision.allowed is True
    assert decision.mode == "ALLOWED"
    assert decision.blocked_by is None

    # Permission is not execution: the gate exposes no order path and no
    # live writer — nothing here can send an order or set live=True.
    gate = build_gate()
    assert not hasattr(gate, "dispatch")
    assert not hasattr(gate, "place_order")
    assert not hasattr(gate, "enable_live")


# ---------------------------------------------------------------------------
# 5. The real system default remains untouched Dry Run
# ---------------------------------------------------------------------------


def test_real_dispatch_default_stays_dry_run():
    """Cross-check against the real harness default (original form, no
    skip/conditional): the real dispatch path stays fail-closed Dry Run."""
    from core.simulation_harness import SimulationHarness

    harness = SimulationHarness()
    assert harness.dispatch_core.live_trading_enabled is False
    assert harness.broker.live_trading_enabled is False

    run = harness.run_basic_scenario()
    assert run.dispatch_result.sent is False
    assert run.dispatch_result.mode == "ALL_PROCESSED"
    assert all(live is False for _, live in run.place_order_calls)
    assert harness.broker.live_trading_enabled is False
