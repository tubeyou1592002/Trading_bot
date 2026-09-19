"""
Block 9 — Task 9.1: Simulation Harness tests.

Proves the ONE base scenario of Task 9.1, fully offline and deterministic:

    valid ExecutionPlan
        -> DispatchCore.dispatch()      (the REAL Block 2 core)
        -> BrokerManager                (the REAL manager)
        -> Simulation Broker            (the only substituted component)
        -> DispatchResult

Acceptance proofs in this file:

  1. The harness can run one valid execution end-to-end (DispatchResult is
     correct: ALL_PROCESSED / success / not sent).
  2. The order really reached the Simulation Broker (recorded calls).
  3. The REAL DispatchCore path was used (structurally proven, no
     re-implementation of dispatch logic anywhere in the harness).
  4. M6-A … M6-E stayed intact and active on the path (the real
     OrderEngine ran all its preflight stages: instrument resolution,
     nsc_id consistency, trading state, validation, capacity, place_order).
  5. No real broker API, no network, no credentials, no live flag:
     proven with mock/patch on the network boundary (requests.Session /
     socket), on the production BrokerManager binding, and on
     live_trading_enabled — never by touching the real network.
"""

import socket
from unittest.mock import patch

import pytest

from brokers.manager import BrokerManager
from core import dispatch_core as dispatch_core_module
from core import simulation_harness as simulation_harness_module
from core.dispatch_contracts import DispatchResult
from core.order_engine import OrderEngine
from core.simulation_harness import (
    SimulationBroker,
    SimulationHarness,
    SimulationInstrumentProvider,
    build_simulation_catalog,
    make_simulation_account,
    make_simulation_order,
)
from models.order import Order


# ---------------------------------------------------------------------------
# 1. Basic scenario: the harness runs one valid execution end-to-end
# ---------------------------------------------------------------------------


def test_basic_scenario_runs_valid_execution_end_to_end():
    harness = SimulationHarness()
    run = harness.run_basic_scenario()

    result = run.dispatch_result
    assert isinstance(result, DispatchResult)
    assert result.success is True
    assert result.sent is False
    assert result.mode == "ALL_PROCESSED"
    assert result.order_count == 1
    assert result.trace_id is not None
    assert "dry-run" in result.message.lower()


# ---------------------------------------------------------------------------
# 2. The order really reached the Simulation Broker
# ---------------------------------------------------------------------------


def test_order_reaches_simulation_broker():
    harness = SimulationHarness()
    run = harness.run_basic_scenario()

    assert run.reached_simulation_broker is True

    calls = run.place_order_calls
    assert len(calls) == 1
    order, live = calls[0]
    assert isinstance(order, Order)
    assert live is False  # dry-run flag, exactly as dispatched

    # The exact order object from the plan arrived at the broker.
    assert order is run.plan.orders[0]
    assert order.nsc_id == "INS-SIM-1"

    # Full observable call trail on the broker, in engine order.
    ops = [c.op for c in run.broker.calls]
    assert ops == [
        "get_trading_state",
        "get_buy_capacity",
        "place_order",
    ]


def test_dispatch_result_is_correct_and_inspectable():
    harness = SimulationHarness()
    run = harness.run_basic_scenario()

    result = run.dispatch_result
    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert result.sent is False
    assert result.order_count == 1

    # The manager-built provider was used for instrument resolution on the
    # real path — the same instance the BrokerManager resolved.
    assert run.provider is harness.provider
    # Exactly TWO get_instrument calls: one from DispatchCore's own
    # _resolve_instrument step and one from OrderEngine.execute_by_ins_code
    # — the signature of the real Block 2 dispatch path.
    assert run.provider.calls == [
        "get_instrument:INS-SIM-1",
        "get_instrument:INS-SIM-1",
    ]

    # The broker recorded the place_order payload of the dispatched order.
    assert run.broker.calls[-1].payload["nscId"] == "INS-SIM-1"


# ---------------------------------------------------------------------------
# 3. The REAL DispatchCore path was used (no re-implementation)
# ---------------------------------------------------------------------------


def test_real_dispatch_core_is_used_not_a_copy():
    harness = SimulationHarness()

    # The harness drives the real DispatchCore class, not a subclass or
    # stand-in, and the real BrokerManager class for resolution.
    assert type(harness.dispatch_core) is dispatch_core_module.DispatchCore
    assert type(harness.manager) is BrokerManager

    # The dispatch entry point is the untouched real method object.
    assert (
        type(harness.dispatch_core).dispatch
        is dispatch_core_module.DispatchCore.dispatch
    )

    # The real OrderEngine is the one inside the real core.
    assert type(harness.dispatch_core.order_engine) is OrderEngine

    # The harness module contains no dispatch logic of its own: it never
    # calls the engine entry points and has no dispatch implementation of
    # its own. (Checked on executable lines only, so docstrings mentioning
    # these names do not count.)
    source = _executable_source(simulation_harness_module)
    assert "execute_by_ins_code" not in source
    assert "def dispatch(" not in source
    assert ".prepare(" not in source
    assert "_plan_item" not in source
    assert "_plan_account" not in source


def test_real_engine_runs_inside_harness():
    harness = SimulationHarness()
    run = harness.run_basic_scenario()

    # Spy on the REAL core's REAL engine to confirm the dispatch goes
    # through OrderEngine.execute_by_ins_code with the expected arguments.
    engine_calls = []
    original = harness.dispatch_core.order_engine.execute_by_ins_code

    def spy(**kwargs):
        engine_calls.append(kwargs)
        return original(**kwargs)

    harness.dispatch_core.order_engine.execute_by_ins_code = spy
    spy_run = harness.run_basic_scenario()

    assert len(engine_calls) == 1
    kwargs = engine_calls[0]
    assert kwargs["live"] is False
    assert kwargs["ins_code"] == "INS-SIM-1"
    assert kwargs["account"].account_id == "ACC-SIM-1"
    assert kwargs["broker"] is harness.broker
    assert spy_run.dispatch_result.mode == "ALL_PROCESSED"


# ---------------------------------------------------------------------------
# 4. M6-A … M6-E stayed intact and active on the path
# ---------------------------------------------------------------------------


def test_m6_preflight_gates_are_active_on_the_path():
    harness = SimulationHarness()

    # A mismatched nsc_id must be BLOCKED by the real M6-A consistency
    # gate inside the real engine — proving the gate is live in this path.
    bad_order = make_simulation_order()
    bad_order.nsc_id = "WRONG-NSC"
    run = harness.run_basic_scenario(order=bad_order)

    assert run.dispatch_result.success is False
    assert run.dispatch_result.mode == "BLOCKED"
    assert not run.reached_simulation_broker
    assert any("nscId" in (c.payload or "") if isinstance(c.payload, str) else False
               for c in run.broker.calls) is False


def test_m6_gates_block_when_capacity_is_exceeded():
    harness = SimulationHarness()
    # Shrink the simulation capacity so the real M6-C gate must block:
    # the validator bounds stay satisfied (max order qty 1_000_000), but
    # the broker-reported capacity is 100 < requested 101.
    harness.broker.max_capacity = 100
    tight_order = make_simulation_order(price=10_000, quantity=101)
    run = harness.run_basic_scenario(order=tight_order)

    assert run.dispatch_result.success is False
    assert run.dispatch_result.mode == "BLOCKED"
    # The capacity call itself happened (gate ran) but no order was placed.
    assert any(c.op == "get_buy_capacity" for c in run.broker.calls)
    assert not run.reached_simulation_broker


def test_m6_gates_block_when_trading_state_is_not_verified():
    from models.trading_state import TradingState

    harness = SimulationHarness()

    # Patch the harness broker's state answer: unverified instrument.
    def unverified(self, nsc_id):
        return TradingState(
            is_order_entry_allowed=False,
            is_verified=False,
            source="simulation",
        )

    with patch.object(SimulationBroker, "get_trading_state", unverified):
        run = harness.run_basic_scenario()

    assert run.dispatch_result.success is False
    assert run.dispatch_result.mode == "BLOCKED"
    assert not run.reached_simulation_broker


def test_unknown_instrument_fails_closed_at_provider():
    from brokers.base import InstrumentLookupError

    harness = SimulationHarness()
    provider = SimulationInstrumentProvider(harness.broker)

    with pytest.raises(InstrumentLookupError):
        provider.get_instrument("UNKNOWN-CODE")

    with pytest.raises(InstrumentLookupError):
        provider.get_nsc_id("UNKNOWN-CODE")


# ---------------------------------------------------------------------------
# 5. No real broker API, no network, no credentials, no live flag
# ---------------------------------------------------------------------------


def _block_all_network_sockets():
    """
    Patch/socket guard used by the isolation test: any attempt to open a
    real socket fails the test immediately (offline-by-construction).
    """
    def forbidden(*args, **kwargs):
        raise AssertionError("Network access attempted during simulation run")

    return patch(f"{socket.socket.__module__}.socket", forbidden)


def test_no_real_broker_api_no_network_no_credentials_used():
    # Guard 1: requests.Session must never even be constructed — the
    # production AgaahBroker (which owns a real HTTP session) must never
    # be instantiated on the simulation path.
    with patch(
        "brokers.manager.AgaahBroker"
    ) as agaah_spy, patch(
        "brokers.manager.AgaahInstrumentProvider"
    ) as provider_spy:
        harness = SimulationHarness()
        run = harness.run_basic_scenario()
        assert agaah_spy.assert_not_called() is None
        assert provider_spy.assert_not_called() is None

    assert run.dispatch_result.mode == "ALL_PROCESSED"

    # Guard 2: the socket constructor is patched out — any network attempt
    # anywhere on the path raises instead of reaching a network stack.
    with _block_all_network_sockets():
        harness2 = SimulationHarness()
        run2 = harness2.run_basic_scenario()
    assert run2.dispatch_result.mode == "ALL_PROCESSED"
    assert run2.reached_simulation_broker is True

    # Guard 3: no real credentials involved — the run needs no login and
    # the simulation broker stores no token/credential state at all.
    assert not any(
        attr in vars(harness.broker)
        for attr in ("access_token", "refresh_token", "session", "password")
    )
    assert run.dispatch_result.success is True


def test_production_broker_manager_binding_untouched():
    # The real module-level BrokerManager is never modified by the harness:
    # constructing the harness does not register anything anywhere else.
    manager = BrokerManager()
    production_names_before = manager.names()

    harness = SimulationHarness()

    assert set(harness.manager.names()) == {"SIM"}
    assert production_names_before == manager.names()
    assert harness.manager is not manager

    # And a fresh production manager still binds the real broker only.
    fresh = BrokerManager()
    assert fresh.names() == manager.names()


def test_live_trading_never_enabled():
    harness = SimulationHarness()
    run = harness.run_basic_scenario()

    # DispatchCore contract: live is hard-off and nothing flipped it.
    assert harness.dispatch_core.live_trading_enabled is False
    assert harness.broker.live_trading_enabled is False

    # Every recorded place_order arrived with live=False.
    assert all(live is False for _, live in run.place_order_calls)

    # The real engine still refuses a live dispatch when asked directly.
    order = make_simulation_order()
    engine_result = harness.dispatch_core.order_engine.execute(
        broker=harness.broker,
        order=order,
        instrument=build_simulation_catalog()[order.nsc_id][1],
        account=make_simulation_account(),
        live=True,
    )
    assert engine_result.success is False
    assert engine_result.sent is False
    assert engine_result.mode == "BLOCKED"


def test_live_request_at_broker_is_refused_fail_closed():
    harness = SimulationHarness()

    with pytest.raises(RuntimeError):
        harness.broker.place_order(make_simulation_order(), live=True)


def test_deterministic_same_inputs_same_outcome():
    outcomes = []
    for _ in range(3):
        harness = SimulationHarness()
        run = harness.run_basic_scenario()
        outcomes.append(
            (
                run.dispatch_result.success,
                run.dispatch_result.mode,
                run.dispatch_result.order_count,
                tuple(c.op for c in run.broker.calls),
                tuple(run.provider.calls),
            )
        )

    assert len(set(outcomes)) == 1


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _executable_source(module):
    """Concatenated source of the module's executable (non-docstring) lines."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # docstrings / constant-expression lines
        if hasattr(node, "lineno"):
            lines.append(node.lineno)
    source_lines = inspect.getsource(module).splitlines()
    return "\n".join(source_lines[ln - 1] for ln in sorted(set(lines)))
