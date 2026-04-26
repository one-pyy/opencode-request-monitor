from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PacketCreate(BaseModel):
    captured_at: datetime | None = None
    method: str
    host: str
    path: str
    raw_request_text: str = ""
    raw_response_text: str = ""
    request_headers_text: str = ""
    request_body_text: str = ""
    response_headers_text: str = ""
    response_body_text: str = ""
    cached_tokens: int | None = None
    total_tokens: int | None = None


class PacketSummary(BaseModel):
    id: int
    sequence: int
    captured_at: datetime
    method: str
    host: str
    path: str
    cached_tokens: int | None
    total_tokens: int | None
    cache_ratio: float | None
    is_cache_drop: bool
    comparable_prev_packet_id: int | None
    compare_block_reason: str | None


class PacketDetail(PacketSummary):
    raw_request_text: str
    raw_response_text: str
    request_headers_text: str
    request_body_text: str
    response_headers_text: str
    response_body_text: str
    formatted_request_body_text: str
    formatted_response_body_text: str


class SummaryStats(BaseModel):
    total_packets: int
    cache_drop_packets: int
    comparable_packets: int
    last_captured_at: datetime | None


class DiffComparableResponse(BaseModel):
    status: Literal["comparable"]
    packet_id: int
    previous_packet_id: int
    compare_type: Literal["json", "text"]
    current_text: str
    previous_text: str


class DiffBlockedResponse(BaseModel):
    status: Literal["blocked", "missing_previous"]
    packet_id: int
    reason: str = Field(description="不可比较原因")


DiffResponse = DiffComparableResponse | DiffBlockedResponse
