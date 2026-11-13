from __future__ import annotations

import sqlite3
from pathlib import Path

from .settings import DATA_DIR

FREE_SPACE_THRESHOLD = 1024**3


def compact_database(db_path: Path) -> int:
    """收缩空闲页超过 1 GiB 的现有数据库，返回文件减少的字节数。"""
    if not db_path.exists():
        return 0

    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=rw", uri=True)
    try:
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        free_pages = connection.execute("PRAGMA freelist_count").fetchone()[0]
        if page_size * free_pages <= FREE_SPACE_THRESHOLD:
            return 0

        before = db_path.stat().st_size
        # SQLite acquires its write lock; a busy database fails without deleting records.
        connection.execute("VACUUM")
        return max(0, before - db_path.stat().st_size)
    finally:
        connection.close()


if __name__ == "__main__":
    reclaimed = compact_database(DATA_DIR / "packets.sqlite3")
    if reclaimed:
        print(f"SQLite 空闲空间已回收：{reclaimed / 1024**3:.3f} GiB")
