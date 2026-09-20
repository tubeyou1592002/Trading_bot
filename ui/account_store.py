"""
ui/account_store.py — UI-2.1 in-memory account store.

A simple, memory-only registry of the accounts the user has added in the
User Application, together with the explicit broker association of each
account.

Architecture boundary (UI-2.1 / Decision 024):

    AccountRecord
        ├── account: models.account.Account   (the account's own identity,
        │                                     reused unchanged from the
        │                                     existing domain model)
        └── broker_name: str                  (the User Application's
                                              explicit association; NOT
                                              stored on the Account model)

    * The existing ``models.account.Account`` model is reused and is never
      modified; its own ``account_id`` validation is the single source of
      truth for what a valid account identity is.
    * ``broker_name`` lives only on ``AccountRecord`` — broker association
      is an application-layer concept, never baked into the domain model
      and never guessed from an index, symbol or anything else.
    * ``AccountStore`` is purely in-memory: no SQLite, JSON, config file or
      any other persistence. Accounts exist only while the application
      runs.
    * No active account exists until the user explicitly selects one with
      ``set_active``; at most one account is active at any moment.
    * No broker is instantiated, no BrokerManager is created and no
      network/login/credential access happens here.
"""

from dataclasses import dataclass

from models.account import Account, AccountValidationError


class AccountStoreError(ValueError):
    """
    Raised for invalid AccountStore usage: empty/invalid ids, duplicate
    ids, unknown ids, or an empty broker name.

    Account identity validation itself is delegated to the existing
    ``models.account.Account`` validation (``AccountValidationError``),
    which is never swallowed or replaced.
    """


@dataclass(frozen=True)
class AccountRecord:
    """
    One account entry of the User Application.

    ``account`` is a real ``models.account.Account`` instance (its
    ``account_id`` is the account identity); ``broker_name`` is the
    explicit broker association kept at the application layer.
    """

    account: Account
    broker_name: str

    @property
    def account_id(self):
        """The account's identity, taken verbatim from the Account model."""
        return self.account.account_id


class AccountStore:
    """
    In-memory registry of AccountRecords with single-active selection.

    Contract:

        add(account_id, broker_name)      -> AccountRecord
        all_accounts()                    -> tuple[AccountRecord, ...]
        set_active(account_id)            -> account_id (selection switch)
        active_account_id()               -> str | None
        is_active(account_id)             -> bool
        get(account_id)                   -> AccountRecord

    Rules:

        * ``account_id`` must satisfy the existing ``Account`` identity
          validation (non-empty, non-whitespace string) — the store never
          redefines or relaxes it.
        * A duplicate ``account_id`` is rejected.
        * ``broker_name`` must be a non-empty, non-whitespace string.
        * Nothing is active until ``set_active`` is called; selecting a
          second account deactivates the first (at most one active).
    """

    def __init__(self):
        self._records = {}
        self._active_account_id = None

    # ---------------------------------------------------------
    # Registration
    # ---------------------------------------------------------

    def add(self, account_id, broker_name):
        """
        Register a new account with its explicit broker association.

        Builds a real ``models.account.Account`` with the given identity —
        the model's own validation decides whether the identity is
        acceptable, so invalid identities raise ``AccountValidationError``
        exactly as anywhere else in the project.

        Returns the created ``AccountRecord``.
        """
        if not isinstance(broker_name, str) or not broker_name.strip():
            raise AccountStoreError(
                "broker_name must be a non-empty, non-whitespace string"
            )

        # Delegate identity validation to the existing domain model:
        # an empty/whitespace/non-string id raises AccountValidationError
        # here, and None is rejected by the store (an app-registered
        # account must have an explicit identity).
        if account_id is None:
            raise AccountStoreError(
                "account_id must be a non-empty, non-whitespace string"
            )
        account = Account(account_id=account_id)

        record_id = account.account_id
        if record_id in self._records:
            raise AccountStoreError(
                f"Duplicate account_id: {record_id!r} is already registered"
            )

        record = AccountRecord(
            account=account, broker_name=broker_name.strip()
        )
        self._records[record_id] = record
        return record

    # ---------------------------------------------------------
    # Read access
    # ---------------------------------------------------------

    def all_accounts(self):
        """All registered AccountRecords in registration order."""
        return tuple(self._records.values())

    def get(self, account_id):
        """
        Return the AccountRecord for ``account_id``.

        Raises AccountStoreError for an unknown id — an account is never
        guessed or substituted.
        """
        try:
            return self._records[account_id]
        except (KeyError, TypeError) as exc:
            raise AccountStoreError(
                f"Unknown account_id: {account_id!r}"
            ) from exc

    # ---------------------------------------------------------
    # Active selection (at most one, explicit only)
    # ---------------------------------------------------------

    def set_active(self, account_id):
        """
        Select the active account by its explicit identity.

        Selecting another account deactivates the previously active one.
        Returns ``account_id``. Raises AccountStoreError for an unknown id.
        """
        record = self.get(account_id)
        self._active_account_id = record.account_id
        return self._active_account_id

    def active_account_id(self):
        """The active account's id, or ``None`` while nothing is selected."""
        return self._active_account_id

    def is_active(self, account_id):
        """True exactly when ``account_id`` is the currently active account."""
        return account_id is not None and account_id == self._active_account_id
