"""SQLite persistence for non-sensitive local account metadata only."""

import os
import sqlite3
from pathlib import Path


class AccountRepositoryError(RuntimeError):
    """Safe public error for account metadata persistence failures."""


def default_database_path():
    """Return the per-user LocalAppData database path."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = os.environ.get(
            "XDG_DATA_HOME",
            str(Path.home() / ".local" / "share"),
        )
    return Path(local_app_data) / "Trading Bot" / "accounts.db"


class SQLiteAccountRepository:
    """Persist account ID, broker, display name and display order only."""

    def __init__(self, database_path=None):
        self.database_path = (
            Path(database_path)
            if database_path is not None
            else default_database_path()
        )
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS accounts (
                        account_id TEXT PRIMARY KEY,
                        broker_name TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        position INTEGER NOT NULL UNIQUE
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS accounts_position_idx "
                    "ON accounts(position)"
                )
        except Exception as exc:
            raise AccountRepositoryError(
                "Could not initialize local account metadata storage"
            ) from exc

    def _connect(self):
        return sqlite3.connect(str(self.database_path), timeout=5)

    def _resequence(self, connection, ordered_ids):
        """
        Rewrite positions to ``0..N-1`` in ``ordered_ids`` order.

        Temporary positions are shifted by an offset strictly larger than
        the current maximum position, so the intermediate values can never
        collide with any existing position (or with each other) under the
        ``UNIQUE`` constraint — regardless of how large or sparse the
        current positions are. Must run inside an already-open transaction.
        """
        max_position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) FROM accounts"
        ).fetchone()[0]
        offset = max_position + 1
        connection.execute(
            "UPDATE accounts SET position = position + ?",
            (offset,),
        )
        for position, account_id in enumerate(ordered_ids):
            connection.execute(
                "UPDATE accounts SET position = ? WHERE account_id = ?",
                (position, account_id),
            )

    def load_accounts(self):
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT account_id, broker_name, display_name "
                    "FROM accounts ORDER BY position"
                ).fetchall()
            return tuple(rows)
        except Exception as exc:
            raise AccountRepositoryError(
                "Could not read local account metadata"
            ) from exc

    def add_account(self, account_id, broker_name, display_name):
        try:
            with self._connect() as connection:
                with connection:
                    position = connection.execute(
                        "SELECT COALESCE(MAX(position), -1) + 1 FROM accounts"
                    ).fetchone()[0]
                    connection.execute(
                        "INSERT INTO accounts"
                        "(account_id, broker_name, display_name, position) "
                        "VALUES (?, ?, ?, ?)",
                        (account_id, broker_name, display_name, position),
                    )
        except Exception as exc:
            if isinstance(exc, sqlite3.IntegrityError):
                raise AccountRepositoryError(
                    "Account metadata already exists"
                ) from exc
            raise AccountRepositoryError(
                "Could not save account metadata"
            ) from exc

    def update_account(self, account_id, broker_name, display_name):
        try:
            with self._connect() as connection:
                with connection:
                    cursor = connection.execute(
                        "UPDATE accounts SET broker_name = ?, "
                        "display_name = ? WHERE account_id = ?",
                        (broker_name, display_name, account_id),
                    )
                    if cursor.rowcount != 1:
                        raise sqlite3.IntegrityError
        except Exception as exc:
            raise AccountRepositoryError(
                "Could not update account metadata"
            ) from exc

    def delete_account(self, account_id):
        try:
            with self._connect() as connection:
                with connection:
                    connection.execute(
                        "DELETE FROM accounts WHERE account_id = ?",
                        (account_id,),
                    )
                    rows = connection.execute(
                        "SELECT account_id FROM accounts ORDER BY position"
                    ).fetchall()
                    self._resequence(
                        connection, [row[0] for row in rows]
                    )
        except Exception as exc:
            raise AccountRepositoryError(
                "Could not delete account metadata"
            ) from exc

    def move_account(self, account_id, new_position):
        try:
            with self._connect() as connection:
                with connection:
                    ids = [
                        row[0]
                        for row in connection.execute(
                            "SELECT account_id FROM accounts ORDER BY position"
                        ).fetchall()
                    ]
                    if account_id not in ids:
                        raise sqlite3.IntegrityError
                    ids.remove(account_id)
                    new_position = max(0, min(int(new_position), len(ids)))
                    ids.insert(new_position, account_id)
                    self._resequence(connection, ids)
        except Exception as exc:
            raise AccountRepositoryError(
                "Could not reorder account metadata"
            ) from exc

    def reorder_accounts(self, account_ids):
        try:
            with self._connect() as connection:
                with connection:
                    existing = [
                        row[0]
                        for row in connection.execute(
                            "SELECT account_id FROM accounts ORDER BY position"
                        ).fetchall()
                    ]
                    if (
                        len(existing) != len(account_ids)
                        or set(existing) != set(account_ids)
                    ):
                        raise sqlite3.IntegrityError
                    self._resequence(connection, list(account_ids))
        except Exception as exc:
            raise AccountRepositoryError(
                "Could not reorder account metadata"
            ) from exc
