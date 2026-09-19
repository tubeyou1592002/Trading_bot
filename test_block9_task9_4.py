"""
Block 9 — Task 9.4: Multi-Account Isolation simulation tests.

Extends the Task 9.1 harness with an interleaved two-account / two-instrument
scenario on the SAME real dispatch path — no new architecture, no bypass:

    ExecutionPlanner → ExecutionPlan → DispatchCore.dispatch()
        → BrokerManager → OrderEngine → SimulationBroker → DispatchResult

Scenario under test (Task 9.4 proves EXISTING Block 6 isolation):

    odd  sequences → ACC-SIM-1 → STOCK-A
    even sequences → ACC-SIM-2 → STOCK-B

The orders are deliberately interleaved (1,2,3,4,…) so isolation between the
accounts is actually exercised, not batched per account. Both accounts use
the same single registered simulation broker (multi-broker is Task 9.5).
The harness is built over the existing two-stock simulation catalog
(``build_simulation_catalog(ins_codes=("STOCK-A", "STOCK-B"))``) so both
instruments resolve through the real provider path.

This file proves, for every execution:

  * each sequence is bound to exactly its OWN account (real path: the core
    resolves the Account object per sequence from ``plan.accounts`` via the
    sequence's ``conditions["binding"]`` entry);
  * ACC-SIM-1 receives ONLY Stock A and ACC-SIM-2 receives ONLY Stock B —
    the pair assertion fails if accounts or instruments are ever swapped;
  * the (sequence, account, instrument) triple holds end to end, including
    inside the real engine's ``get_buy_capacity(fund=...)`` call (M6-D passes
    ``account.tradable_balance_t1`` as ``fund``; the two accounts carry
    deliberately distinct balances, so the driving account of every broker
    call is provable from the broker's own trail);
  * plan.account_routes keeps the existing Block 6 structure and routes both
    accounts to the registered SIM broker;
  * sequences are complete, unique, and connected to the right order object
    (the broker call is identity-equal to the plan's own order);
  * a second identical run neither replays the first run's orders nor reuses
    its order objects; per-run call counts are exact; accounts never mix;
  * a rerun is deterministic (only the inherently random per-dispatch
    ``trace_id`` and the wall-clock ``creationDate`` order stamp are
    excluded, each with a documented reason);
  * live trading stays disabled and nothing real (broker/credential/
    network/order) is touched — the Task 9.1/9.2/9.3 guards are reused.

Everything is fully offline and deterministic.
"""

import socket
from unittest.mock import patch

from core.simulation_harness import SimulationHarness, build_simulation_catalog


# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

ACC1, ACC2 = "ACC-SIM-1", "ACC-SIM-2"
STOCK_A, STOCK_B = "STOCK-A", "STOCK-B"
BALANCE_1, BALANCE_2 = 1_000_000_000, 2_000_000_000
VOLUME = 8  # 4 interleaved pairs: 1,2,3,4,5,6,7,8


def make_harness():
    """The Task 9.1 harness over the existing two-stock simulation catalog."""
    return SimulationHarness(
        catalog=build_simulation_catalog(ins_codes=(STOCK_A, STOCK_B))
    )


def expected_pair(sequence):
    """The ONLY allowed (account, instrument, balance, price) per sequence."""
    if sequence % 2 == 1:
        return ACC1, STOCK_A, BALANCE_1, 10_000 + sequence
    return ACC2, STOCK_B, BALANCE_2, 20_000 + sequence


# ---------------------------------------------------------------------------
# Shared invariants — the full chain per sequence
# ---------------------------------------------------------------------------


def assert_multi_account_chain(run):
    """Prove sequence → account → instrument → route → call, per sequence."""
    plan = run.plan
    volume = len(plan.orders)

    # --- Plan shape: interleaved, complete, unique ---------------------------
    assert volume == VOLUME
    assert plan.execution_order == list(range(1, VOLUME + 1))
    assert len(set(plan.execution_order)) == VOLUME

    # --- Binding integrity: every sequence bound to its OWN account ----------
    binding = plan.conditions["binding"]
    assert set(binding) == set(range(1, VOLUME + 1))
    for sequence in range(1, VOLUME + 1):
        acc, ins, balance, price = expected_pair(sequence)
        assert binding[sequence]["account_id"] == acc, (
            f"sequence {sequence} misbound: expected account {acc}"
        )
        assert binding[sequence]["broker_name"] == "SIM"

    # --- Account routes keep the existing Block 6 structure ------------------
    assert plan.account_routes == {ACC1: "SIM", ACC2: "SIM"}
    assert {a.account_id for a in plan.accounts} == {ACC1, ACC2}
    balances = {a.account_id: a.tradable_balance_t1 for a in plan.accounts}
    assert balances == {ACC1: BALANCE_1, ACC2: BALANCE_2}

    # --- Pair integrity: (sequence, account, instrument) is exact ------------
    for sequence in range(1, VOLUME + 1):
        acc, ins, _balance, price = expected_pair(sequence)
        order = plan.orders[sequence - 1]  # planner sorts ascending
        assert order.nsc_id == ins, f"sequence {sequence} got wrong instrument"
        assert order.price == price
        # Distinct fingerprints so any swap is detectable.
        assert (order.nsc_id, order.price) == (ins, price)

    # --- Broker received exactly the planned orders, in sequence order -------
    calls = run.broker.place_order_calls
    assert len(calls) == VOLUME
    for index, (order, live) in enumerate(calls, start=1):
        acc, ins, _balance, price = expected_pair(index)
        assert live is False
        assert order is plan.orders[index - 1]  # identity integrity
        assert order.nsc_id == ins
        assert order.price == price

    # No duplicated order object reached the broker.
    assert len({id(order) for order, _ in calls}) == VOLUME

    # --- Real-path account identity: the engine's M6-D capacity call ---------
    # ``get_buy_capacity(fund=...)`` receives ``account.tradable_balance_t1``
    # of the account the CORE resolved for that sequence. The two balances
    # are distinct, so the fund value proves which account drove the call.
    capacity_calls = [
        c.payload for c in run.broker.calls if c.op == "get_buy_capacity"
    ]
    assert len(capacity_calls) == VOLUME
    for index, payload in enumerate(capacity_calls, start=1):
        acc, ins, balance, _price = expected_pair(index)
        assert payload["fund"] == balance, (
            f"sequence {index} executed with the WRONG account's funds"
        )
        assert payload["nsc_id"] == ins
        if acc == ACC1:
            assert payload["price"] == 10_000 + index
        else:
            assert payload["price"] == 20_000 + index

    # --- Result integrity via the real engine's recorded trail ----------------
    assert run.dispatch_result.success is True
    assert run.dispatch_result.mode == "ALL_PROCESSED"
    assert run.dispatch_result.sent is False
    assert run.dispatch_result.order_count == VOLUME
    assert run.dispatch_result.trace_id is not None

    # --- Live trading stays off everywhere ------------------------------------
    assert run.broker.live_trading_enabled is False


# ---------------------------------------------------------------------------
# Scenario construction
# ---------------------------------------------------------------------------


def test_multi_account_scenario_constructs_two_accounts_two_instruments():
    harness = make_harness()
    plan = harness.multi_account_plan(volume=VOLUME)

    assert {a.account_id for a in plan.accounts} == {ACC1, ACC2}
    assert {o.nsc_id for o in plan.orders} == {STOCK_A, STOCK_B}
    # Interleaved by construction: odd → A, even → B.
    assert [o.nsc_id for o in plan.orders] == [
        STOCK_A, STOCK_B, STOCK_A, STOCK_B, STOCK_A, STOCK_B, STOCK_A, STOCK_B
    ]
    assert plan.broker_names == ["SIM"]


def test_multi_account_run_reaches_simulation_broker():
    harness = make_harness()
    run = harness.run_multi_account_scenario(volume=VOLUME)

    assert run.reached_simulation_broker is True
    assert_multi_account_chain(run)


# ---------------------------------------------------------------------------
# Account / instrument / pair isolation (swap-detecting assertions)
# ---------------------------------------------------------------------------


def test_account_binding_integrity_per_sequence():
    harness = make_harness()
    run = harness.run_multi_account_scenario(volume=VOLUME)

    binding = run.plan.conditions["binding"]
    for sequence in range(1, VOLUME + 1):
        acc, _ins, _bal, _price = expected_pair(sequence)
        # Exact account per sequence — no sequence ever borrows the other's.
        assert binding[sequence]["account_id"] == acc
    # Both accounts present, nothing else.
    assert {b["account_id"] for b in binding.values()} == {ACC1, ACC2}


def test_account1_gets_only_stock_a():
    harness = make_harness()
    run = harness.run_multi_account_scenario(volume=VOLUME)

    binding = run.plan.conditions["binding"]
    for sequence in range(1, VOLUME + 1):
        if binding[sequence]["account_id"] == ACC1:
            order = run.plan.orders[sequence - 1]
            assert order.nsc_id == STOCK_A, (
                f"Account 1 received Stock B at sequence {sequence}"
            )


def test_account2_gets_only_stock_b():
    harness = make_harness()
    run = harness.run_multi_account_scenario(volume=VOLUME)

    binding = run.plan.conditions["binding"]
    for sequence in range(1, VOLUME + 1):
        if binding[sequence]["account_id"] == ACC2:
            order = run.plan.orders[sequence - 1]
            assert order.nsc_id == STOCK_B, (
                f"Account 2 received Stock A at sequence {sequence}"
            )


def test_sequence_account_instrument_pair_integrity():
    harness = make_harness()
    run = run_pair = harness.run_multi_account_scenario(volume=VOLUME)

    binding = run.plan.conditions["binding"]
    pairs = set()
    for sequence in range(1, VOLUME + 1):
        acc, ins, _bal, _price = expected_pair(sequence)
        order = run.plan.orders[sequence - 1]
        # The full triple must match EXACTLY, not just piecewise.
        assert (binding[sequence]["account_id"], order.nsc_id) == (acc, ins)
        pairs.add((sequence, acc, ins))
    expected = {
        (s, ACC1, STOCK_A) if s % 2 == 1 else (s, ACC2, STOCK_B)
        for s in range(1, VOLUME + 1)
    }
    assert pairs == expected


def test_broker_route_integrity():
    harness = make_harness()
    run = harness.run_multi_account_scenario(volume=VOLUME)

    plan = run.plan
    # Existing Block 6 structure: account_routes is a flat account->broker map.
    assert plan.account_routes == {ACC1: "SIM", ACC2: "SIM"}
    binding = plan.conditions["binding"]
    for sequence in range(1, VOLUME + 1):
        # Every sequence routes to the registered SIM broker...
        assert binding[sequence]["broker_name"] == "SIM"
    # ...which is the ONLY broker registered in the harness manager.
    assert plan.broker_names == ["SIM"]
    assert run.broker.name == "SIM"
    # Dispatch used exactly that manager route (no other broker exists to
    # receive anything).
    assert run.dispatch_result.success is True

    # Fail-closed negative check: a foreign broker name cannot even be
    # resolved by the manager (routing never leaves the registered pair).
    try:
        harness.manager.get("NOT-REGISTERED")
        raised = False
    except Exception:
        raised = True
    assert raised is True


def test_broker_received_order_identity():
    harness = make_harness()
    run = harness.run_multi_account_scenario(volume=VOLUME)

    calls = run.broker.place_order_calls
    assert len(calls) == VOLUME
    for index, (order, live) in enumerate(calls, start=1):
        _acc, ins, _bal, price = expected_pair(index)
        assert order is run.plan.orders[index - 1]
        assert (order.nsc_id, order.price) == (ins, price)
        assert live is False
    assert len({id(order) for order, _ in calls}) == VOLUME

    # The instrument provider resolved ONLY Stock A / Stock B.
    resolved = sorted({c.split(":", 1)[1] for c in run.provider.calls if ":" in c})
    assert resolved == [STOCK_A, STOCK_B]


def test_execution_result_identity_per_sequence():
    """Result integrity via the real engine's per-sequence observable trail."""
    harness = make_harness()
    run = harness.run_multi_account_scenario(volume=VOLUME)

    # Aggregate result matches the real executions...
    result = run.dispatch_result
    assert result.mode == "ALL_PROCESSED"
    assert result.order_count == VOLUME
    # ...and the real broker trail is exactly one place_order per sequence,
    # identity-bound to that sequence's own order object (proven above in
    # test_broker_received_order_identity). The M6-D fund proof additionally
    # ties every engine call to the right account:
    capacity_calls = [
        c.payload for c in run.broker.calls if c.op == "get_buy_capacity"
    ]
    assert len(capacity_calls) == VOLUME
    for index, payload in enumerate(capacity_calls, start=1):
        acc, _ins, balance, _price = expected_pair(index)
        assert payload["fund"] == balance  # the RIGHT account drove this call
    # No result of Account 1 was attributed to Account 2: balances are
    # disjoint, so any mix would surface here.
    assert BALANCE_1 != BALANCE_2


def test_no_cross_account_or_cross_instrument_contamination():
    harness = make_harness()
    run = harness.run_multi_account_scenario(volume=VOLUME)

    calls = run.broker.place_order_calls
    binding = run.plan.conditions["binding"]
    for index, (order, _live) in enumerate(calls, start=1):
        acc, ins, _bal, _price = expected_pair(index)
        # The order placed for sequence `index` belongs to that sequence's
        # account AND that account's instrument — simultaneously.
        assert binding[index]["account_id"] == acc
        assert order.nsc_id == ins
    # Global invariants: Account 1's orders never touch Stock B and vice versa.
    acc1_orders = [
        run.plan.orders[s - 1]
        for s in range(1, VOLUME + 1)
        if binding[s]["account_id"] == ACC1
    ]
    acc2_orders = [
        run.plan.orders[s - 1]
        for s in range(1, VOLUME + 1)
        if binding[s]["account_id"] == ACC2
    ]
    assert {o.nsc_id for o in acc1_orders} == {STOCK_A}
    assert {o.nsc_id for o in acc2_orders} == {STOCK_B}


# ---------------------------------------------------------------------------
# State isolation between two consecutive identical runs
# ---------------------------------------------------------------------------


def test_state_isolated_across_two_consecutive_runs():
    harness = make_harness()

    run1 = harness.run_multi_account_scenario(volume=VOLUME)
    trail1 = list(harness.broker.place_order_calls)
    assert len(trail1) == VOLUME

    run2 = harness.run_multi_account_scenario(volume=VOLUME)

    # Run 2 added exactly its own volume — no replay of run 1.
    new_calls = harness.broker.place_order_calls[len(trail1):]
    assert len(new_calls) == VOLUME
    assert len(harness.broker.place_order_calls) == 2 * VOLUME

    # Run 1's order objects were never reused: every run-2 call is
    # identity-equal to run 2's own plan orders.
    ids1 = {id(o) for o in run1.plan.orders}
    for index, (order, _live) in enumerate(new_calls, start=1):
        assert order is run2.plan.orders[index - 1]
        assert id(order) not in ids1

    # Account state never mixed: the run-2 capacity calls (the LAST VOLUME
    # entries of the shared broker's trail) carry the exact distinct balance
    # of the owning account, per sequence.
    tail2 = [
        c.payload
        for c in harness.broker.calls
        if c.op == "get_buy_capacity"
    ][-VOLUME:]
    assert len(tail2) == VOLUME
    for index, payload in enumerate(tail2, start=1):
        acc, _ins, balance, _price = expected_pair(index)
        assert payload["fund"] == balance

    assert run2.dispatch_result.mode == "ALL_PROCESSED"
    assert run2.dispatch_result.order_count == VOLUME


# ---------------------------------------------------------------------------
# Deterministic rerun (documented exclusions only)
# ---------------------------------------------------------------------------


def test_deterministic_rerun_excluding_trace_id_and_creation_date():
    a = make_harness().run_multi_account_scenario(volume=VOLUME)
    b = make_harness().run_multi_account_scenario(volume=VOLUME)

    # --- Plans identical ------------------------------------------------------
    assert a.plan.plan_id == b.plan.plan_id
    assert a.plan.execution_order == b.plan.execution_order
    assert a.plan.account_routes == b.plan.account_routes
    assert a.plan.conditions["binding"] == b.plan.conditions["binding"]
    assert [(o.nsc_id, o.price, o.quantity) for o in a.plan.orders] == [
        (o.nsc_id, o.price, o.quantity) for o in b.plan.orders
    ]

    # --- DispatchResults identical EXCEPT the random per-dispatch trace_id ----
    a_fields = {
        k: v for k, v in a.dispatch_result.__dict__.items() if k != "trace_id"
    }
    b_fields = {
        k: v for k, v in b.dispatch_result.__dict__.items() if k != "trace_id"
    }
    assert a_fields == b_fields

    # --- Real execution trails identical --------------------------------------
    # Documented exclusions (the ONLY two):
    #   * trace_id — uuid4 generated per dispatch by DispatchCore;
    #   * creationDate — wall-clock stamp set by models/order.py's
    #     datetime.now() default when each real Order is constructed.
    def comparable(payload):
        if isinstance(payload, dict):
            return {k: v for k, v in payload.items() if k != "creationDate"}
        return payload

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
# Offline / live-trading guard (reused from Tasks 9.1–9.3)
# ---------------------------------------------------------------------------


def test_multi_account_uses_no_network_and_no_real_broker():
    # Guard 1: the production Agaah binding is never constructed.
    with patch("brokers.manager.AgaahBroker") as agaah_spy, patch(
        "brokers.manager.AgaahInstrumentProvider"
    ) as provider_spy:
        harness = make_harness()
        run = harness.run_multi_account_scenario(volume=VOLUME)
        agaah_spy.assert_not_called()
        provider_spy.assert_not_called()

    assert run.dispatch_result.mode == "ALL_PROCESSED"

    # Guard 2: any socket open attempt fails the run instantly.
    def forbidden_socket(*args, **kwargs):
        raise AssertionError("Network access attempted during multi-account run")

    with patch(f"{socket.socket.__module__}.socket", forbidden_socket):
        harness2 = make_harness()
        run2 = harness2.run_multi_account_scenario(volume=VOLUME)

    assert run2.dispatch_result.mode == "ALL_PROCESSED"
    assert len(run2.broker.place_order_calls) == VOLUME
    assert all(live is False for _, live in run2.broker.place_order_calls)
    assert harness2.broker.live_trading_enabled is False
    assert harness2.dispatch_core.live_trading_enabled is False
