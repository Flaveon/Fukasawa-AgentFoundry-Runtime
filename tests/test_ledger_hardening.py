# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Ledger hardening tests — Gate G findings F-L1, F-L2, F-L3.

These tests go around the public `RunLedger` API on purpose: a plain
`sqlite3.connect()` handle, the kind any script or operator tool might open,
is exactly what the append-only guarantee has to hold against. sqlite_utils'
own `Database` object happens to turn `PRAGMA recursive_triggers` on, which
hides the REPLACE gap these tests target — so every test here opens its own
raw connection with that pragma explicitly off (sqlite3's own default).
"""

import sqlite3

import pytest

from src.runtime.ledger import (
    _APPEND_ONLY_TABLES,
    _TABLE_SCHEMAS,
    RunLedger,
    _is_single_integer_pk,
    _pk_columns,
)


@pytest.fixture()
def ledger(tmp_path) -> RunLedger:
    return RunLedger(tmp_path / "ledger.db")


def _raw_connection(ledger: RunLedger) -> sqlite3.Connection:
    """A bare `sqlite3` handle on the ledger's file, with the library default
    (`recursive_triggers` off) rather than sqlite_utils' own pragma."""
    conn = sqlite3.connect(str(ledger.db_path))
    conn.execute("PRAGMA recursive_triggers=OFF")
    return conn


def _sample_row(table: str, variant: str = "a") -> dict:
    """One minimal row for a table, built from its own column list.

    Good enough to prove the append-only triggers fire — the values carry no
    other meaning beyond letting two calls with different `variant`s produce
    two distinct, non-colliding rows for the same table. An integer primary
    key column is left out so SQLite assigns it as a rowid alias, the same
    way every real call site does.
    """
    columns, _ = _TABLE_SCHEMAS[table]
    pks = _pk_columns(table)
    row = {}
    for name, py_type in columns.items():
        if name in pks and py_type is int:
            continue
        row[name] = 1 if py_type is int else f"{name}-{variant}"
    return row


def _insert_and_fetch(ledger: RunLedger, table: str, variant: str = "a") -> dict:
    """Insert one sample row through the ledger's own handle and read it
    back, so the test learns whatever primary key SQLite actually assigned
    (relevant for the integer-rowid tables, irrelevant but harmless for the
    text-keyed ones)."""
    ledger.db[table].insert(_sample_row(table, variant))
    return list(ledger.db[table].rows)[-1]


class TestReplaceIsBlocked:
    """F-L1 — `INSERT OR REPLACE` through a raw handle must not rewrite a row."""

    @pytest.mark.parametrize("table", _APPEND_ONLY_TABLES)
    def test_replace_is_refused_but_a_distinct_insert_still_works(self, ledger, table):
        stored = _insert_and_fetch(ledger, table, variant="a")
        pks = _pk_columns(table)

        raw = _raw_connection(ledger)
        try:
            # A fresh row (its own distinct primary key) still inserts
            # cleanly through the raw handle — the guard is keyed on an
            # existing match, not on inserts in general.
            fresh = _sample_row(table, variant="b")
            columns = list(fresh.keys())
            raw.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
                f"({', '.join('?' for _ in columns)})",
                [fresh[c] for c in columns],
            )
            raw.commit()

            # The same primary key as the row already there, with every
            # other column tampered, must be refused.
            attack = _sample_row(table, variant="tampered")
            for col in pks:
                attack[col] = stored[col]
            columns = list(attack.keys())
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                raw.execute(
                    f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    [attack[c] for c in columns],
                )
        finally:
            raw.close()


class TestAppendOnlyCoversEveryTable:
    """F-L2 — every table in `_APPEND_ONLY_TABLES` refuses UPDATE, DELETE
    and REPLACE, each proven on a populated row (an empty table would pass
    the UPDATE/DELETE checks vacuously, since a BEFORE trigger on those
    statements only fires per matched row)."""

    @pytest.mark.parametrize("table", _APPEND_ONLY_TABLES)
    def test_update_and_delete_are_refused_on_a_populated_row(self, ledger, table):
        _insert_and_fetch(ledger, table)
        raw = _raw_connection(ledger)
        try:
            first_column = next(iter(_sample_row(table)))
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                raw.execute(f"UPDATE {table} SET {first_column} = {first_column}")
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                raw.execute(f"DELETE FROM {table}")
        finally:
            raw.close()

    def test_the_tuple_names_every_append_only_table(self):
        # Deleting a name from `_APPEND_ONLY_TABLES` would silently drop its
        # coverage from every parametrized test above (pytest would just
        # collect fewer cases); pin the membership directly so that mistake
        # fails loudly instead of quietly running less.
        assert set(_APPEND_ONLY_TABLES) == {
            "ledger",
            "promotions",
            "validation_reports",
            "risk_acceptances",
            "workflow_promotions",
            "accountable_workflows",
            "cooperation_assessments",
            "cooperative_workflows",
            "workflow_snapshots",
            "run_brief_pins",
        }


class TestTriggersReattachOnOldDatabases:
    """F-L3 — opening an older database (no triggers yet) must re-attach them."""

    def test_reopening_a_trigger_less_database_restores_all_guards(self, tmp_path):
        dbpath = tmp_path / "old.db"
        RunLedger(dbpath).record_event("c1", "w1", None, "S1", "owner", "ev", True)

        raw = sqlite3.connect(str(dbpath))
        trigger_names = [
            r[0]
            for r in raw.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        ]
        assert trigger_names, "the fresh ledger should have created triggers"
        for name in trigger_names:
            raw.execute(f"DROP TRIGGER {name}")
        raw.commit()
        remaining = list(
            raw.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        )
        raw.close()
        assert remaining == []

        # Reopening the same file (as if an older binary had never created
        # the replace guard, or an operator dropped the triggers by hand)
        # must bring every guard back without touching existing rows.
        RunLedger(dbpath)
        raw = sqlite3.connect(str(dbpath))
        restored = [
            r[0]
            for r in raw.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        ]
        raw.close()
        assert len(restored) == 3 * len(_APPEND_ONLY_TABLES)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            sqlite3.connect(str(dbpath)).execute("DELETE FROM ledger")


class TestNegativeOneRowidPlaceholderIsExcluded:
    """Gate G re-review finding R4.

    Inside a BEFORE INSERT trigger, SQLite's placeholder for an
    integer-primary-key column that was *omitted* (left to be auto-numbered)
    reads as -1 — the real rowid is not chosen until after triggers run.
    `_no_replace`'s WHEN clause has to treat `-1` as "no match" or a single
    row that happens to carry id -1 (hand-inserted, or restored from an
    import) would make every later ordinary, auto-numbered insert look like
    a replace of that row, and get refused — jamming the audit trail shut.
    """

    @pytest.mark.parametrize(
        "table", [t for t in _APPEND_ONLY_TABLES if _is_single_integer_pk(t)]
    )
    def test_a_row_at_id_negative_one_does_not_jam_later_ordinary_inserts(
        self, ledger, table
    ):
        pk = _pk_columns(table)[0]
        poisoned = _sample_row(table)
        poisoned[pk] = -1
        ledger.db[table].insert(poisoned)

        # The exact regression: an ordinary, auto-numbered insert through
        # the public sqlite_utils API must still succeed afterward.
        ledger.db[table].insert(_sample_row(table, variant="after-minus-one"))
        assert len(list(ledger.db[table].rows)) == 2

    def test_record_event_still_works_after_a_row_at_id_negative_one(self, ledger):
        ledger.db["ledger"].insert({**_sample_row("ledger"), "event_id": -1})
        # Before the fix, this raised sqlite3.IntegrityError("... replaces
        # are forbidden") even though it is a plain, unrelated insert.
        ledger.record_event("c1", "w1", None, "S1", "owner", "ev", True)
        assert len(ledger.history("w1")) == 1
