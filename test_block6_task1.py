"""Block 6 — Task 6.1: Account Model tests.

Covers the account identity added to ``models/account.py``:

  - a valid Account carrying ``account_id`` can be built;
  - a blank / whitespace-only / non-string ``account_id`` is rejected
    fail-closed (``AccountValidationError``);
  - two Accounts with different ids are distinguishable;
  - the pre-existing balance / settlement fields still work unchanged
    (defaults, explicit values, field order) and legacy construction and
    legacy attribute assignment without an id stay valid;
  - the existing layers that already carry an ``Account`` object
    (``PlannedOrder``, ``ExecutionPlan``, ``BrokerDispatchRequest``,
    ``DispatchCore._plan_account``) stay compatible with the model.

Scope guard: this suite only READS the other layers. It does not change
``ExecutionPlan``, ``PlannedOrder``, ``DispatchCore``, ``BrokerManager``,
``OrderEngine``, ``ExecutionTracker``, or ``StopSignal``; it never calls a
real Broker API and never enables live trading.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from dataclasses import fields

from core.dispatch_contracts import BrokerDispatchRequest, ExecutionPlan
from core.dispatch_core import DispatchCore
from core.execution_planner import PlannerValidationError, PlannedOrder
from models.account import Account, AccountValidationError
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, Order


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The balance / settlement keyword set that existing call sites already use
# (brokers/agaah/broker.py get_account, M6 preflight tests, Block 2/4/5 tests).
LEGACY_FIELDS = [
    "last_balance",
    "adjusted_balance_t2",
    "tradable_balance_t1",
    "tradable_balance_t2",
    "payable_balance_with_agah_credit_t0",
    "payable_balance_with_agah_credit_t1",
    "payable_balance_with_agah_credit_t2",
    "payable_balance_without_agah_credit_t0",
    "block",
    "credit",
    "settlement_date_t0",
    "settlement_date_t1",
    "settlement_date_t2",
]


def make_balance_snapshot(**overrides):
    """Build an Account exactly like the existing balance-loading call sites."""
    values = dict(
        last_balance=0,
        adjusted_balance_t2=0,
        tradable_balance_t1=1_000_000,
        tradable_balance_t2=1_000_000,
        payable_balance_with_agah_credit_t0=0,
        payable_balance_with_agah_credit_t1=0,
        payable_balance_with_agah_credit_t2=0,
        payable_balance_without_agah_credit_t0=0,
        block=0,
        credit=0,
        settlement_date_t0=None,
        settlement_date_t1=None,
        settlement_date_t2=None,
    )
    values.update(overrides)
    return Account(**values)


def make_order(nsc_id="IRO1TEST0001"):
    return Order(nsc_id=nsc_id, side=BUY, price=150, quantity=10)


def make_plan(accounts, account_id="acc-1", broker_name="broker-a"):
    """Minimal ExecutionPlan carrying explicit Account objects (Block 0 contract)."""
    return ExecutionPlan(
        orders=[make_order()],
        accounts=list(accounts),
        broker_names=[broker_name],
        execution_order=[0],
        conditions={
            "binding": {
                0: {"account_id": account_id, "broker_name": broker_name},
            }
        },
        plan_id="task-6-1-plan",
    )


def expect_account_validation_error(fn, label):
    try:
        fn()
    except AccountValidationError:
        return
    raise AssertionError(f"{label}: expected AccountValidationError")


# ---------------------------------------------------------------------------
# Task 6.1 — identity
# ---------------------------------------------------------------------------


def test_valid_account_with_id_succeeds():
    """A valid Account with an account_id can be built."""
    account = Account(account_id="acc-1")
    assert account.account_id == "acc-1"
    assert isinstance(account, Account)


def test_valid_account_with_id_succeeds_with_balance_fields():
    """Identity and balance data can be provided together."""
    account = Account(account_id="acc-1", tradable_balance_t1=1_000_000)
    assert account.account_id == "acc-1"
    assert account.tradable_balance_t1 == 1_000_000


def test_account_id_is_a_simple_string_identity():
    """The identity is a plain, simple string usable as PlannedOrder.account_id."""
    account = Account(account_id="acc-1")
    assert isinstance(account.account_id, str)

    planned = PlannedOrder(
        order=make_order(),
        account_id=account.account_id,
        broker_name="broker-a",
        sequence=0,
    )
    assert planned.account_id == account.account_id


def test_account_id_defaults_to_none():
    """Unset identity stays None (legacy snapshots); nothing is invented."""
    assert Account().account_id is None
    assert make_balance_snapshot().account_id is None


def test_legacy_balance_snapshot_construction_still_valid():
    """The existing broker-style construction (balance kwargs only) still works."""
    account = make_balance_snapshot()
    assert account.last_balance == 0
    assert account.adjusted_balance_t2 == 0
    assert account.tradable_balance_t1 == 1_000_000
    assert account.settlement_date_t2 is None


def test_legacy_attribute_assignment_still_works():
    """The pattern used by existing Block 2/4/5 tests (assign after build) works."""
    account = make_balance_snapshot()
    account.account_id = "acc-2"
    assert account.account_id == "acc-2"


def test_empty_account_id_rejected():
    """An empty account_id is rejected fail-closed."""
    expect_account_validation_error(
        lambda: Account(account_id=""),
        "empty account_id",
    )


def test_whitespace_only_account_id_rejected():
    """A whitespace-only account_id is rejected fail-closed."""
    for blank in (" ", "   ", "\t", "\n", " \t\n "):
        expect_account_validation_error(
            lambda blank=blank: Account(account_id=blank),
            f"whitespace account_id {blank!r}",
        )


def test_non_string_account_id_rejected():
    """A non-string identity (including bool) is rejected fail-closed."""
    for invalid in (123, 1.5, True, False, ["acc-1"], {"account_id": "acc-1"}):
        expect_account_validation_error(
            lambda invalid=invalid: Account(account_id=invalid),
            f"non-string account_id {invalid!r}",
        )


def test_account_validation_error_is_value_error():
    """The error follows the project convention: a ValueError subclass."""
    assert issubclass(AccountValidationError, ValueError)

    try:
        Account(account_id="   ")
    except ValueError:
        pass
    else:
        raise AssertionError("blank account_id must raise a ValueError")


def test_two_accounts_with_different_ids_are_distinguishable():
    """Two Accounts with different ids must never be confused."""
    acc1 = Account(account_id="acc-1", tradable_balance_t1=1_000_000)
    acc2 = Account(account_id="acc-2", tradable_balance_t1=1_000_000)

    assert acc1.account_id != acc2.account_id
    assert acc1 != acc2
    assert acc1.account_id == "acc-1" and acc2.account_id == "acc-2"


def test_accounts_with_the_same_id_are_equal():
    """Identity participates in equality: same id + same data -> equal."""
    acc1 = Account(account_id="acc-1", tradable_balance_t1=5)
    acc2 = Account(account_id="acc-1", tradable_balance_t1=5)
    assert acc1 == acc2

    acc3 = Account(account_id="acc-2", tradable_balance_t1=5)
    assert acc1 != acc3


# ---------------------------------------------------------------------------
# Task 6.1 — existing fields preserved (backward compatibility)
# ---------------------------------------------------------------------------


def test_field_set_is_identity_plus_unchanged_legacy_fields():
    """account_id is added; the legacy field set and its order are unchanged."""
    names = [f.name for f in fields(Account)]
    assert names[0] == "account_id"
    assert names[1:] == LEGACY_FIELDS


def test_existing_balance_field_defaults_unchanged():
    """Every legacy field still defaults to None (broker snapshots stay valid)."""
    defaults = {f.name: f.default for f in fields(Account)}
    for name in LEGACY_FIELDS:
        assert defaults[name] is None, f"{name} default changed"


def test_existing_balance_field_types_unchanged():
    """Every legacy field keeps its original annotation."""
    annotations = {f.name: str(f.type) for f in fields(Account)}
    for name in LEGACY_FIELDS:
        expected = "str | None" if name.startswith("settlement_date_") else "int | float | None"
        assert annotations[name] == expected, (
            f"{name} annotation changed: {annotations[name]!r} != {expected!r}"
        )


def test_existing_balance_fields_roundtrip():
    """The legacy balance / settlement values still round-trip unchanged."""
    account = make_balance_snapshot(
        last_balance=12_000_000,
        adjusted_balance_t2=11_500_000,
        tradable_balance_t1=10_000_000,
        tradable_balance_t2=9_000_000,
        payable_balance_with_agah_credit_t0=8_000_000,
        payable_balance_with_agah_credit_t1=7_000_000,
        payable_balance_with_agah_credit_t2=6_000_000,
        payable_balance_without_agah_credit_t0=5_000_000,
        block=1_000,
        credit=2_000,
        settlement_date_t0="2026-09-15",
        settlement_date_t1="2026-09-16",
        settlement_date_t2="2026-09-17",
    )

    assert account.last_balance == 12_000_000
    assert account.adjusted_balance_t2 == 11_500_000
    assert account.tradable_balance_t1 == 10_000_000
    assert account.tradable_balance_t2 == 9_000_000
    assert account.payable_balance_with_agah_credit_t0 == 8_000_000
    assert account.payable_balance_with_agah_credit_t1 == 7_000_000
    assert account.payable_balance_with_agah_credit_t2 == 6_000_000
    assert account.payable_balance_without_agah_credit_t0 == 5_000_000
    assert account.block == 1_000
    assert account.credit == 2_000
    assert account.settlement_date_t0 == "2026-09-15"
    assert account.settlement_date_t1 == "2026-09-16"
    assert account.settlement_date_t2 == "2026-09-17"


def test_broker_style_snapshot_can_be_identified_later():
    """A broker balance snapshot can receive its identity without changing the broker."""
    snapshot = make_balance_snapshot()
    assert snapshot.account_id is None

    snapshot.account_id = "acc-1"
    assert snapshot.account_id == "acc-1"
    assert snapshot.tradable_balance_t1 == 1_000_000


def test_no_secret_fields_on_account_model():
    """No password / token / secret / credential / session lives on the model."""
    names = {f.name.lower() for f in fields(Account)}
    forbidden = (
        "password",
        "pass",
        "token",
        "secret",
        "credential",
        "session",
        "api_key",
        "apikey",
        "username",
    )
    for word in forbidden:
        assert not any(word in name for name in names), (
            f"Account must not carry a secret-like field: {word}"
        )


def test_account_is_not_order_instrument_or_execution():
    """Account stays an independent identity, not an Order/Instrument/Execution."""
    assert Account is not Order
    assert Account is not Instrument
    assert Account is not BrokerInstrument

    account = Account(account_id="acc-1")
    for foreign in (
        "nsc_id",
        "ins_code",
        "tse_id",
        "side",
        "quantity",
        "price",
        "execution_id",
        "status",
    ):
        assert not hasattr(account, foreign), (
            f"Account must not carry {foreign!r} (not an Order/Instrument/Execution)"
        )


# ---------------------------------------------------------------------------
# Task 6.1 — compatibility with the existing contracts / layers
# ---------------------------------------------------------------------------


def test_planned_order_still_rejects_blank_account_id():
    """Block 1 keeps rejecting a blank identity (both sides agree on the rule)."""
    try:
        PlannedOrder(
            order=make_order(),
            account_id="   ",
            broker_name="broker-a",
            sequence=0,
        )
    except PlannerValidationError:
        return
    raise AssertionError("PlannedOrder must still reject a blank account_id")


def test_execution_plan_accepts_account_objects_and_id_strings():
    """Both plan shapes coexist: resolved Account objects and legacy id strings."""
    acc1 = Account(account_id="acc-1", tradable_balance_t1=1_000_000)
    acc2 = Account(account_id="acc-2", tradable_balance_t1=2_000_000)

    object_plan = make_plan([acc1, acc2])
    assert object_plan.accounts[0].account_id == "acc-1"
    assert object_plan.accounts[1].account_id == "acc-2"

    id_plan = ExecutionPlan(
        orders=[make_order()],
        accounts=["acc-1"],
        broker_names=["broker-a"],
        execution_order=[0],
    )
    assert id_plan.accounts == ["acc-1"]


def test_broker_dispatch_request_carries_account_identity():
    """The Block 0 envelope carries the Account object and its identity."""
    account = Account(account_id="acc-1", tradable_balance_t1=1_000_000)

    request = BrokerDispatchRequest(
        broker_name="broker-a",
        order=make_order(),
        account=account,
        instrument=BrokerInstrument(nsc_id="IRO1TEST0001"),
    )

    assert request.account is account
    assert request.account.account_id == "acc-1"
    assert request.live is False


def test_dispatch_core_resolves_account_by_identity():
    """DispatchCore binds each order to the exact Account of that account_id."""
    core = DispatchCore()
    acc1 = Account(account_id="acc-1", tradable_balance_t1=1_000_000)
    acc2 = Account(account_id="acc-2", tradable_balance_t1=2_000_000)

    plan = make_plan([acc1, acc2], account_id="acc-1")

    assert core._plan_account(plan, "acc-1") is acc1
    assert core._plan_account(plan, "acc-2") is acc2


def test_dispatch_core_id_only_account_still_fails_closed():
    """An id-only plan (real Block 1 output) is still preserved, not invented."""
    core = DispatchCore()
    plan = make_plan(["acc-1"], account_id="acc-1")

    assert core._plan_account(plan, "acc-1") is None


def test_dispatch_core_unknown_account_id_still_raises():
    """An account_id that is not bound in the plan still raises (fail-closed)."""
    core = DispatchCore()
    plan = make_plan([Account(account_id="acc-1")], account_id="acc-1")

    try:
        core._plan_account(plan, "acc-9")
    except ValueError:
        return
    raise AssertionError("an unbound account_id must raise ValueError")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main():
    tests = [
        test_valid_account_with_id_succeeds,
        test_valid_account_with_id_succeeds_with_balance_fields,
        test_account_id_is_a_simple_string_identity,
        test_account_id_defaults_to_none,
        test_legacy_balance_snapshot_construction_still_valid,
        test_legacy_attribute_assignment_still_works,
        test_empty_account_id_rejected,
        test_whitespace_only_account_id_rejected,
        test_non_string_account_id_rejected,
        test_account_validation_error_is_value_error,
        test_two_accounts_with_different_ids_are_distinguishable,
        test_accounts_with_the_same_id_are_equal,
        test_field_set_is_identity_plus_unchanged_legacy_fields,
        test_existing_balance_field_defaults_unchanged,
        test_existing_balance_field_types_unchanged,
        test_existing_balance_fields_roundtrip,
        test_broker_style_snapshot_can_be_identified_later,
        test_no_secret_fields_on_account_model,
        test_account_is_not_order_instrument_or_execution,
        test_planned_order_still_rejects_blank_account_id,
        test_execution_plan_accepts_account_objects_and_id_strings,
        test_broker_dispatch_request_carries_account_identity,
        test_dispatch_core_resolves_account_by_identity,
        test_dispatch_core_id_only_account_still_fails_closed,
        test_dispatch_core_unknown_account_id_still_raises,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS  {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {test.__name__}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"  ERROR {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()

    print()
    print("=" * 50)
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    print("=" * 50)

    if failed:
        sys.exit(1)

    print(f"\nAll Block 6 Task 1 Account Model tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()