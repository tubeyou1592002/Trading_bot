"""Offline tests for persistent non-sensitive account metadata."""

import sqlite3

import pytest

from ui.account_repository import SQLiteAccountRepository
from ui.account_store import AccountStore, AccountStoreError


BROKER = "آگاه"


def test_account_metadata_and_manual_order_survive_store_restart(tmp_path):
    database = tmp_path / "accounts.db"
    store = AccountStore(repository=SQLiteAccountRepository(database))
    store.add("id-A", BROKER, "Alpha")
    store.add("id-B", BROKER, "Beta")
    store.move("id-B", 0)
    store.update("id-B", display_name="Beta renamed")
    store.set_active("id-A")

    restarted = AccountStore(repository=SQLiteAccountRepository(database))

    assert [
        (record.account_id, record.display_name)
        for record in restarted.all_accounts()
    ] == [("id-B", "Beta renamed"), ("id-A", "Alpha")]

    assert restarted.active_account_id() is None

    restarted.delete("id-B")
    reopened = AccountStore(repository=SQLiteAccountRepository(database))
    assert [record.account_id for record in reopened.all_accounts()] == [
        "id-A"
    ]


def test_database_schema_contains_only_non_sensitive_metadata(tmp_path):
    database = tmp_path / "accounts.db"
    store = AccountStore(repository=SQLiteAccountRepository(database))
    store.add("id-A", BROKER, "Alpha")

    with sqlite3.connect(database) as connection:
        columns = [
            row[1]
            for row in connection.execute("PRAGMA table_info(accounts)")
        ]
        values = connection.execute("SELECT * FROM accounts").fetchone()

    assert columns == [
        "account_id",
        "broker_name",
        "display_name",
        "position",
    ]
    assert "username" not in columns
    assert "password" not in columns
    assert "token" not in columns
    assert values == ("id-A", BROKER, "Alpha", 0)


def test_metadata_write_failure_does_not_mutate_store_or_leak_input():
    class FailingRepository:
        def load_accounts(self):
            return ()

        def add_account(self, account_id, broker_name, display_name):
            raise RuntimeError("database fault carrying private values")

    store = AccountStore(repository=FailingRepository())

    with pytest.raises(AccountStoreError) as error:
        store.add("new-id", BROKER, "Private display")

    assert store.all_accounts() == ()
    assert "private" not in str(error.value).lower()
    assert "new-id" not in str(error.value)


def test_plain_account_store_remains_in_memory():
    store = AccountStore()
    store.add("id-A", BROKER, "Alpha")
    store.move("id-A", 0)
    assert store.get("id-A").display_name == "Alpha"
    assert store._repository is None


def test_resequence_handles_large_sparse_positions_without_unique_clash(
    tmp_path,
):
    database = tmp_path / "accounts.db"
    repository = SQLiteAccountRepository(database)

    # Seed large, sparse positions directly, including a pair whose
    # difference equals a naive fixed offset (0 and 1_000_000). Such data
    # cannot be produced by the resequencing API itself, but a fixed
    # "+1_000_000" shift would collide it and raise a UNIQUE violation.
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO accounts VALUES (?, ?, ?, ?)",
            [
                ("A", BROKER, "Alpha", 0),
                ("B", BROKER, "Beta", 1_000_000),
                ("C", BROKER, "Gamma", 2_500_000),
                ("D", BROKER, "Delta", 7_000_000),
            ],
        )

    # Neither operation may raise a UNIQUE violation on `position`.
    repository.move_account("A", 3)
    repository.reorder_accounts(("C", "A", "B", "D"))

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT account_id, position FROM accounts ORDER BY position"
        ).fetchall()

    assert rows == [("C", 0), ("A", 1), ("B", 2), ("D", 3)]

    store = AccountStore(database_path=database)
    assert [record.account_id for record in store.all_accounts()] == [
        "C", "A", "B", "D",
    ]
