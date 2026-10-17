"""SQLite account metadata persistence tests using temporary databases."""

import sqlite3

import pytest

from ui.account_store import AccountStore, AccountStoreError


BROKER = "آگاه"


def test_account_records_and_order_survive_store_reopen(tmp_path):
    db = tmp_path / "accounts.db"
    store = AccountStore(database_path=db)
    store.add("A", BROKER, "Alpha")
    store.add("B", BROKER, "Beta")
    store.move("B", 0)
    store.update("B", display_name="Beta renamed")
    store.set_active("A")

    reopened = AccountStore(database_path=db)

    assert [
        (r.account_id, r.broker_name, r.display_name)
        for r in reopened.all_accounts()
    ] == [("B", BROKER, "Beta renamed"), ("A", BROKER, "Alpha")]

    assert reopened.active_account_id() is None

    reopened.delete("B")
    assert [
        r.account_id
        for r in AccountStore(database_path=db).all_accounts()
    ] == ["A"]


def test_sqlite_contains_only_nonsecret_metadata(tmp_path):
    db = tmp_path / "accounts.db"
    AccountStore(database_path=db).add("A", BROKER, "Alpha")

    with sqlite3.connect(db) as connection:
        columns = [
            row[1]
            for row in connection.execute("PRAGMA table_info(accounts)")
        ]
        row = connection.execute("SELECT * FROM accounts").fetchone()

    assert columns == [
        "account_id",
        "broker_name",
        "display_name",
        "position",
    ]
    assert row == ("A", BROKER, "Alpha", 0)


def test_sqlite_write_failure_does_not_add_partial_store_record():
    class FailingRepository:
        def load_accounts(self):
            return ()

        def add_account(self, account_id, broker_name, display_name):
            raise RuntimeError("secret-bearing database error")

    store = AccountStore(repository=FailingRepository())
    with pytest.raises(AccountStoreError) as error:
        store.add("A", BROKER, "Alpha")

    assert store.all_accounts() == ()
    assert "secret-bearing" not in str(error.value)


def test_account_store_without_repository_stays_in_memory():
    store = AccountStore(repository=False)
    store.add("A", BROKER, "Alpha")
    assert store._repository is None
