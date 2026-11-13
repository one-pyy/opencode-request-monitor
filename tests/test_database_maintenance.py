# pyright: reportMissingImports=false

import importlib
from pathlib import Path
import sqlite3

from pytest import MonkeyPatch

database_maintenance = importlib.import_module("app.database_maintenance")


def make_database(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE packets (id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT)")
        connection.executemany(
            "INSERT INTO packets (body) VALUES (?)", [("x" * 32768,)] * 128
        )
        connection.execute("DELETE FROM packets WHERE id > 1")
        connection.commit()
        return (
            connection.execute("PRAGMA page_size").fetchone()[0]
            * connection.execute("PRAGMA freelist_count").fetchone()[0]
        )
    finally:
        connection.close()


def test_missing_database_is_not_created(tmp_path: Path):
    path = tmp_path / "missing.sqlite3"
    assert database_maintenance.compact_database(path) == 0
    assert not path.exists()


def test_small_free_space_is_untouched(tmp_path: Path):
    path = tmp_path / "packets.sqlite3"
    make_database(path)
    before = path.read_bytes()
    assert database_maintenance.compact_database(path) == 0
    assert path.read_bytes() == before


def test_exact_threshold_is_untouched(tmp_path: Path, monkeypatch: MonkeyPatch):
    path = tmp_path / "packets.sqlite3"
    free_bytes = make_database(path)
    monkeypatch.setattr(database_maintenance, "FREE_SPACE_THRESHOLD", free_bytes)
    before = path.read_bytes()
    assert database_maintenance.compact_database(path) == 0
    assert path.read_bytes() == before


def test_over_threshold_reclaims_space_and_preserves_records(tmp_path: Path, monkeypatch: MonkeyPatch):
    path = tmp_path / "packets.sqlite3"
    free_bytes = make_database(path)
    monkeypatch.setattr(database_maintenance, "FREE_SPACE_THRESHOLD", free_bytes - 1)
    before = path.stat().st_size
    reclaimed = database_maintenance.compact_database(path)
    assert reclaimed == before - path.stat().st_size
    assert reclaimed > 0
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT id, body FROM packets").fetchall() == [(1, "x" * 32768)]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA freelist_count").fetchone()[0] == 0
        # Existing sequence state must survive compaction.
        assert connection.execute("INSERT INTO packets (body) VALUES ('next')").lastrowid == 129
    finally:
        connection.close()
