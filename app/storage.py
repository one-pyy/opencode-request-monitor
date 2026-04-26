from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from .schemas import PacketCreate

FOUR_MINUTES_SECONDS = 4 * 60


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_datetime(value: datetime | None) -> datetime:
    if value is None:
        return utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def isoformat(value: datetime) -> str:
    return normalize_datetime(value).isoformat()


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def prettify_text(value: str) -> str:
    if not value.strip():
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    return json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)


def resolve_compare_type(current_text: str, previous_text: str) -> Literal["json", "text"]:
    try:
        json.loads(current_text)
        json.loads(previous_text)
        return "json"
    except json.JSONDecodeError:
        return "text"


@dataclass(slots=True)
class PacketRecord:
    id: int
    sequence: int
    captured_at: datetime
    method: str
    host: str
    path: str
    raw_request_text: str
    raw_response_text: str
    request_headers_text: str
    request_body_text: str
    response_headers_text: str
    response_body_text: str
    formatted_request_body_text: str
    formatted_response_body_text: str
    cached_tokens: int | None
    total_tokens: int | None
    cache_ratio: float | None
    is_cache_drop: bool
    comparable_prev_packet_id: int | None
    compare_block_reason: str | None


class PacketRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS request_packets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sequence INTEGER NOT NULL UNIQUE,
                    captured_at TEXT NOT NULL,
                    method TEXT NOT NULL,
                    host TEXT NOT NULL,
                    path TEXT NOT NULL,
                    raw_request_text TEXT NOT NULL DEFAULT '',
                    raw_response_text TEXT NOT NULL DEFAULT '',
                    request_headers_text TEXT NOT NULL,
                    request_body_text TEXT NOT NULL,
                    response_headers_text TEXT NOT NULL,
                    response_body_text TEXT NOT NULL,
                    formatted_request_body_text TEXT NOT NULL,
                    formatted_response_body_text TEXT NOT NULL,
                    cached_tokens INTEGER,
                    total_tokens INTEGER,
                    cache_ratio REAL,
                    is_cache_drop INTEGER NOT NULL,
                    comparable_prev_packet_id INTEGER,
                    compare_block_reason TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(comparable_prev_packet_id) REFERENCES request_packets(id)
                )
                """
            )
            self._ensure_column(connection, "raw_request_text", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "raw_response_text", "TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, name: str, definition: str) -> None:
        columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(request_packets)")}
        if name not in columns:
            connection.execute(f"ALTER TABLE request_packets ADD COLUMN {name} {definition}")

    def create_packet(self, payload: PacketCreate) -> PacketRecord:
        captured_at = normalize_datetime(payload.captured_at)
        formatted_request_body = prettify_text(payload.request_body_text)
        formatted_response_body = prettify_text(payload.response_body_text)
        cache_ratio = self._cache_ratio(payload.cached_tokens, payload.total_tokens)
        is_cache_drop = self._is_cache_drop(payload.cached_tokens, payload.total_tokens)

        with self._connect() as connection:
            previous = connection.execute(
                "SELECT id, captured_at FROM request_packets ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if previous is None else int(previous["id"] and 0) + 1
            if previous is not None:
                previous_sequence = connection.execute(
                    "SELECT sequence FROM request_packets WHERE id = ?", (previous["id"],)
                ).fetchone()
                sequence = int(previous_sequence["sequence"]) + 1
            comparable_prev_packet_id, compare_block_reason = self._resolve_compare_state(previous, captured_at)
            cursor = connection.execute(
                """
                INSERT INTO request_packets (
                    sequence,
                    captured_at,
                    method,
                    host,
                    path,
                    raw_request_text,
                    raw_response_text,
                    request_headers_text,
                    request_body_text,
                    response_headers_text,
                    response_body_text,
                    formatted_request_body_text,
                    formatted_response_body_text,
                    cached_tokens,
                    total_tokens,
                    cache_ratio,
                    is_cache_drop,
                    comparable_prev_packet_id,
                    compare_block_reason,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    isoformat(captured_at),
                    payload.method,
                    payload.host,
                    payload.path,
                    payload.raw_request_text,
                    payload.raw_response_text,
                    payload.request_headers_text,
                    payload.request_body_text,
                    payload.response_headers_text,
                    payload.response_body_text,
                    formatted_request_body,
                    formatted_response_body,
                    payload.cached_tokens,
                    payload.total_tokens,
                    cache_ratio,
                    int(is_cache_drop),
                    comparable_prev_packet_id,
                    compare_block_reason,
                    isoformat(utcnow()),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("failed to determine inserted packet id")
            packet_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM request_packets WHERE id = ?", (packet_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("failed to load inserted packet")
            return self._row_to_record(row)

    def list_packets(self, only_cache_drop: bool = False) -> list[PacketRecord]:
        query = "SELECT * FROM request_packets"
        params: tuple[Any, ...] = ()
        if only_cache_drop:
            query += " WHERE is_cache_drop = 1"
        query += " ORDER BY sequence DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_packet(self, packet_id: int) -> PacketRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM request_packets WHERE id = ?", (packet_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def summary_stats(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_packets,
                    COALESCE(SUM(is_cache_drop), 0) AS cache_drop_packets,
                    COALESCE(SUM(CASE WHEN comparable_prev_packet_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS comparable_packets,
                    MAX(captured_at) AS last_captured_at
                FROM request_packets
                """
            ).fetchone()
        return {
            "total_packets": int(row["total_packets"]),
            "cache_drop_packets": int(row["cache_drop_packets"]),
            "comparable_packets": int(row["comparable_packets"]),
            "last_captured_at": None
            if row["last_captured_at"] is None
            else parse_datetime(cast(str, row["last_captured_at"])),
        }

    def clear_packets(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM request_packets")

    @staticmethod
    def _cache_ratio(cached_tokens: int | None, total_tokens: int | None) -> float | None:
        if cached_tokens is None or total_tokens is None or total_tokens <= 0:
            return None
        return cached_tokens / total_tokens

    @staticmethod
    def _is_cache_drop(cached_tokens: int | None, total_tokens: int | None) -> bool:
        if cached_tokens is None or total_tokens is None or total_tokens <= 0:
            return False
        return cached_tokens < total_tokens * 0.5

    @staticmethod
    def _resolve_compare_state(previous: sqlite3.Row | None, captured_at: datetime) -> tuple[int | None, str | None]:
        if previous is None:
            return None, "missing_previous"
        previous_captured_at = parse_datetime(str(previous["captured_at"]))
        gap = (captured_at - previous_captured_at).total_seconds()
        if gap > FOUR_MINUTES_SECONDS:
            return None, "gap_exceeds_4_minutes"
        return int(previous["id"]), None

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> PacketRecord:
        return PacketRecord(
            id=int(row["id"]),
            sequence=int(row["sequence"]),
            captured_at=parse_datetime(str(row["captured_at"])),
            method=str(row["method"]),
            host=str(row["host"]),
            path=str(row["path"]),
            raw_request_text=str(row["raw_request_text"]),
            raw_response_text=str(row["raw_response_text"]),
            request_headers_text=str(row["request_headers_text"]),
            request_body_text=str(row["request_body_text"]),
            response_headers_text=str(row["response_headers_text"]),
            response_body_text=str(row["response_body_text"]),
            formatted_request_body_text=str(row["formatted_request_body_text"]),
            formatted_response_body_text=str(row["formatted_response_body_text"]),
            cached_tokens=None if row["cached_tokens"] is None else int(row["cached_tokens"]),
            total_tokens=None if row["total_tokens"] is None else int(row["total_tokens"]),
            cache_ratio=None if row["cache_ratio"] is None else float(row["cache_ratio"]),
            is_cache_drop=bool(row["is_cache_drop"]),
            comparable_prev_packet_id=None
            if row["comparable_prev_packet_id"] is None
            else int(row["comparable_prev_packet_id"]),
            compare_block_reason=None if row["compare_block_reason"] is None else str(row["compare_block_reason"]),
        )
