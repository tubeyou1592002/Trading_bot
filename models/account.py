"""
Block 6 — Task 6.1: Account Model.

``Account`` is the identity of one trading account in the core of the
application. It is a *model*, not a routing table and not a session: it
carries the account's own identity plus the balance / settlement data that
M6-A … M6-E already consume, and nothing else.

Task 6.1 boundary:

    Account (this module)
        │  account_id                <- unique, stable identity (Task 6.1)
        ▼
    PlannedOrder.account_id          (Block 1 — planning binding)
        │
        ▼
    ExecutionPlan.accounts           (Block 0 contract)
    BrokerDispatchRequest.account
        │
        ▼
    DispatchCore._plan_account       (Block 2 — exact binding lookup)

Design rules (Task 6.1):
  * ``account_id`` is a plain, simple identity value. It is validated with
    the *same* rule Block 1 already uses for ``PlannedOrder.account_id``
    (a non-empty, non-whitespace string), so an ``Account`` can be bound to
    an execution plan without any translation or adapter.
  * ``account_id`` defaults to ``None`` for backward compatibility: existing
    call sites build ``Account`` from balance data only
    (``brokers/agaah/broker.py`` -> ``get_account``) and existing Block 2/4/5
    and M6 tests construct ``Account`` with balance fields only. An unset
    identity stays ``None``; a blank or non-string identity is rejected —
    an identity is never fabricated.
  * The existing balance / settlement fields are unchanged (same names,
    types, defaults, and order). Nothing was removed, renamed, or retyped.
  * No secret (password, token, credential, session) is stored on this
    model, and nothing here enables live trading.

Explicitly OUT of scope for Task 6.1 (later tasks / blocks):
  * AccountManager, credential manager, account -> broker routing.
  * Account-aware dispatch, multi-account execution, multi-account tracking.
  * Any change to ``ExecutionPlan``, ``PlannedOrder``, ``DispatchCore``,
    ``BrokerManager``, ``OrderEngine``, ``ExecutionTracker``, or
    ``StopSignal``.
"""

from dataclasses import dataclass


class AccountValidationError(ValueError):
    """
    Raised when an ``Account`` is constructed with an invalid identity.

    Follows the existing model-validation convention of the project
    (``OrderValidationError``, ``PlannerValidationError``): fail-closed,
    never silently accepting a malformed identity.
    """


@dataclass
class Account:
    """
    One trading account.

    ``account_id`` is the account's unique, stable identity (Task 6.1). When
    provided it must be a non-empty, non-whitespace string; ``None`` means
    the identity has not been assigned yet (for example a raw balance
    snapshot returned by ``broker.get_account()``).

    The remaining fields are the pre-existing balance / settlement data and
    are intentionally unchanged.
    """

    account_id: str | None = None

    last_balance: int | float | None = None
    adjusted_balance_t2: int | float | None = None

    tradable_balance_t1: int | float | None = None
    tradable_balance_t2: int | float | None = None

    payable_balance_with_agah_credit_t0: int | float | None = None
    payable_balance_with_agah_credit_t1: int | float | None = None
    payable_balance_with_agah_credit_t2: int | float | None = None

    payable_balance_without_agah_credit_t0: int | float | None = None

    block: int | float | None = None
    credit: int | float | None = None

    settlement_date_t0: str | None = None
    settlement_date_t1: str | None = None
    settlement_date_t2: str | None = None

    def __post_init__(self) -> None:
        """
        Fail-closed validation of the account identity (Task 6.1).

        The rule is exactly the one Block 1 already enforces for
        ``PlannedOrder.account_id``, so both sides of the Planner -> Dispatch
        binding agree on what a valid account identity is.

        ``None`` is allowed and means "identity not assigned yet" (legacy
        balance snapshots). An empty string, a whitespace-only string, or a
        non-string value is rejected; an identity is never invented.
        """
        if self.account_id is None:
            return

        if (
            not isinstance(self.account_id, str)
            or not self.account_id.strip()
        ):
            raise AccountValidationError(
                "Account.account_id must be a non-empty, non-whitespace "
                "string or None"
            )