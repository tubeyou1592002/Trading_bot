"""
ui/account_store.py — UI-2.1 account store.

A registry of the accounts the user has added in the User Application,
together with the explicit broker association of each account. It is
in-memory by default and optionally backed by a non-sensitive metadata
repository so the account list and its order survive restarts.

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
    * ``AccountStore`` defaults to purely in-memory (no repository): accounts
      exist only while the application runs. Production may inject a
      repository for non-sensitive account metadata so the account list and
      its display order survive restarts. Only ``account_id``,
      ``broker_name``, ``display_name`` and ordering are ever persisted —
      never credentials, sessions, tokens or the active selection.
    * No active account exists until the user explicitly selects one with
      ``set_active``; at most one account is active at any moment. The
      active selection is never persisted and is ``None`` after a reload.
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
    explicit broker association kept at the application layer;
    ``display_name`` is the user-chosen name for this account.
    """

    account: Account
    broker_name: str
    display_name: str

    @property
    def account_id(self):
        """The account's identity, taken verbatim from the Account model."""
        return self.account.account_id


class AccountStore:
    """
    Registry of AccountRecords with single-active selection.

    Contract:

        AccountStore(repository=None, *, database_path=None)
        AccountStore.persistent_default()           -> AccountStore
        add(account_id, broker_name, display_name)  -> AccountRecord
        update(account_id, *, broker_name=None, display_name=None)
                                                    -> AccountRecord
        delete(account_id)                          -> None
        move(account_id, new_position)              -> None
        reorder(account_ids)                        -> None
        all_accounts()                              -> tuple[AccountRecord, ...]
        set_active(account_id)                      -> account_id (selection switch)
        active_account_id()                         -> str | None
        is_active(account_id)                       -> bool
        get(account_id)                             -> AccountRecord

    Persistence is optional and injectable:

        * ``AccountStore()`` is purely in-memory (``_repository`` is None).
        * ``AccountStore(repository=...)`` persists through the given
          repository object.
        * ``AccountStore(database_path=...)`` builds the standard SQLite
          repository for that path — the injectable seam used by tests to
          keep them off the real user database.
        * Only non-sensitive metadata (account id, broker name, display
          name, order) is persisted; the active selection is never stored.

    Rules:

        * ``account_id`` must satisfy the existing ``Account`` identity
          validation (non-empty, non-whitespace string) — the store never
          redefines or relaxes it.
        * ``broker_name`` must be a non-empty, non-whitespace string.
        * ``display_name`` is required and must be a non-empty,
          non-whitespace string; it is stored exactly as provided
          (stripped of surrounding whitespace).
        * A duplicate ``account_id`` is rejected.
        * Nothing is active until ``set_active`` is called; selecting a
          second account deactivates the first (at most one active).
    """

    def __init__(self, repository=None, *, database_path=None):
        self._records = {}
        self._active_account_id = None

        if repository is not None and database_path is not None:
            raise ValueError(
                "Specify repository or database_path, not both"
            )

        if database_path is not None:
            from ui.account_repository import SQLiteAccountRepository

            repository = SQLiteAccountRepository(database_path)
        elif repository is False:
            repository = None

        self._repository = repository

        if repository is not None:
            try:
                rows = repository.load_accounts()
                self._records = {
                    record.account_id: record
                    for record in (
                        AccountRecord(
                            Account(account_id),
                            broker,
                            display_name,
                        )
                        for account_id, broker, display_name in rows
                    )
                }
            except Exception as exc:
                if isinstance(exc, AccountStoreError):
                    raise
                raise AccountStoreError(
                    "Could not load saved account metadata"
                ) from exc

    @classmethod
    def persistent_default(cls):
        """
        Build a store backed by the default per-user accounts database.

        Used by the real application so the account list and its order
        survive restarts. Tests must NOT use this — they inject a
        temporary ``database_path`` or an in-memory repository instead.
        """
        from ui.account_repository import SQLiteAccountRepository

        return cls(repository=SQLiteAccountRepository())

    # ---------------------------------------------------------
    # Registration
    # ---------------------------------------------------------

    def add(self, account_id, broker_name, display_name):
        """
        Register a new account with its explicit broker association and
        user-chosen display name.

        Builds a real ``models.account.Account`` with the given identity —
        the model's own validation decides whether the identity is
        acceptable, so invalid identities raise ``AccountValidationError``
        exactly as anywhere else in the project.

        ``display_name`` is required and must be a non-empty,
        non-whitespace string.

        Returns the created ``AccountRecord``.
        """
        if not isinstance(broker_name, str) or not broker_name.strip():
            raise AccountStoreError(
                "broker_name must be a non-empty, non-whitespace string"
            )

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

        if not isinstance(display_name, str) or not display_name.strip():
            raise AccountStoreError(
                "display_name must be a non-empty, non-whitespace string"
            )

        record = AccountRecord(
            account=account,
            broker_name=broker_name.strip(),
            display_name=display_name.strip(),
        )

        if self._repository is not None:
            try:
                self._repository.add_account(
                    record.account_id,
                    record.broker_name,
                    record.display_name,
                )
            except Exception as exc:
                if isinstance(exc, AccountStoreError):
                    raise
                raise AccountStoreError(
                    "Could not save account metadata"
                ) from exc

        self._records[record_id] = record
        return record

    def update(self, account_id, *, broker_name=None, display_name=None):
        """
        Update the broker association and/or display name of an account.

        Only the supplied fields change; omitted fields keep their current
        value. Returns the updated ``AccountRecord``. Raises
        AccountStoreError for an unknown id, an invalid value, or a
        persistence failure — in which case the in-memory state is left
        untouched.
        """
        current = self.get(account_id)
        new_broker = (
            current.broker_name if broker_name is None else broker_name
        )
        new_name = (
            current.display_name if display_name is None else display_name
        )
        if not isinstance(new_broker, str) or not new_broker.strip():
            raise AccountStoreError(
                "broker_name must be a non-empty string"
            )
        if not isinstance(new_name, str) or not new_name.strip():
            raise AccountStoreError(
                "display_name must be a non-empty string"
            )
        updated = AccountRecord(
            current.account,
            new_broker.strip(),
            new_name.strip(),
        )
        if self._repository is not None:
            try:
                self._repository.update_account(
                    account_id,
                    broker_name=updated.broker_name,
                    display_name=updated.display_name,
                )
            except Exception as exc:
                raise AccountStoreError(
                    "Could not update account metadata"
                ) from exc
        self._records[account_id] = updated
        return updated

    def delete(self, account_id):
        """
        Delete an account and, if it was active, clear the active selection.

        Raises AccountStoreError for an unknown id or a persistence
        failure — in which case the in-memory state is left untouched.
        """
        self.get(account_id)
        if self._repository is not None:
            try:
                self._repository.delete_account(account_id)
            except Exception as exc:
                raise AccountStoreError(
                    "Could not delete account metadata"
                ) from exc
        del self._records[account_id]
        if self._active_account_id == account_id:
            self._active_account_id = None

    def move(self, account_id, new_position):
        """
        Move an account to ``new_position`` (clamped to the valid range).

        The display order is persisted when a repository is attached. Raises
        AccountStoreError for an unknown id or a persistence failure — in
        which case the in-memory order is left untouched.
        """
        record = self.get(account_id)
        records = list(self._records.values())
        records.remove(record)
        position = max(0, min(int(new_position), len(records)))
        records.insert(position, record)
        if self._repository is not None:
            try:
                self._repository.move_account(account_id, position)
            except Exception as exc:
                raise AccountStoreError(
                    "Could not reorder account metadata"
                ) from exc
        self._records = {
            item.account_id: item for item in records
        }
        return None

    def reorder(self, account_ids):
        """
        Reorder ALL accounts to match ``account_ids`` exactly.

        ``account_ids`` must contain every current account id exactly once.
        Raises AccountStoreError for a mismatch or a persistence failure —
        in which case the in-memory order is left untouched.
        """
        current_ids = list(self._records)
        if (
            len(account_ids) != len(current_ids)
            or set(account_ids) != set(current_ids)
        ):
            raise AccountStoreError(
                "account ordering does not match current accounts"
            )
        if self._repository is not None:
            try:
                self._repository.reorder_accounts(tuple(account_ids))
            except Exception as exc:
                raise AccountStoreError(
                    "Could not reorder account metadata"
                ) from exc
        self._records = {
            account_id: self._records[account_id]
            for account_id in account_ids
        }
        return None

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
