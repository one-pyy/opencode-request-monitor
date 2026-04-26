from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .schemas import (
    DiffBlockedResponse,
    DiffComparableResponse,
    PacketCreate,
    PacketDetail,
    PacketSummary,
    SummaryStats,
)
from .settings import DATA_DIR, MISC_DIFF_PATH, STATIC_DIR
from .storage import PacketRepository, resolve_compare_type

repository = PacketRepository(DATA_DIR / "packets.sqlite3")

app = FastAPI(title="opencode-request-monitor")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/diff-viewer")
def diff_viewer() -> FileResponse:
    return FileResponse(MISC_DIFF_PATH)


@app.post("/api/packets", response_model=PacketDetail)
def create_packet(payload: PacketCreate) -> PacketDetail:
    record = repository.create_packet(payload)
    return _to_detail(record)


@app.get("/api/packets", response_model=list[PacketSummary])
def list_packets(only_cache_drop: bool = Query(default=False)) -> list[PacketSummary]:
    return [_to_summary(item) for item in repository.list_packets(only_cache_drop=only_cache_drop)]


@app.get("/api/packets/{packet_id}", response_model=PacketDetail)
def get_packet(packet_id: int) -> PacketDetail:
    record = repository.get_packet(packet_id)
    if record is None:
        raise HTTPException(status_code=404, detail="packet not found")
    return _to_detail(record)


@app.get("/api/packets/{packet_id}/diff-prev", response_model=DiffComparableResponse | DiffBlockedResponse)
def diff_prev(packet_id: int) -> DiffComparableResponse | DiffBlockedResponse:
    current = repository.get_packet(packet_id)
    if current is None:
        raise HTTPException(status_code=404, detail="packet not found")
    if current.comparable_prev_packet_id is None:
        reason = current.compare_block_reason or "missing_previous"
        status = "missing_previous" if reason == "missing_previous" else "blocked"
        return DiffBlockedResponse(status=status, packet_id=current.id, reason=reason)
    previous = repository.get_packet(current.comparable_prev_packet_id)
    if previous is None:
        return DiffBlockedResponse(status="missing_previous", packet_id=current.id, reason="missing_previous")
    current_text = current.request_body_text
    previous_text = previous.request_body_text
    compare_type = resolve_compare_type(current_text, previous_text)
    return DiffComparableResponse(
        status="comparable",
        packet_id=current.id,
        previous_packet_id=previous.id,
        compare_type=compare_type,
        current_text=current_text,
        previous_text=previous_text,
    )


@app.get("/api/stats/summary", response_model=SummaryStats)
def summary_stats() -> SummaryStats:
    return SummaryStats(**repository.summary_stats())


@app.delete("/api/packets")
def clear_packets() -> dict[str, bool]:
    repository.clear_packets()
    return {"ok": True}


def _to_summary(record) -> PacketSummary:
    return PacketSummary(
        id=record.id,
        sequence=record.sequence,
        captured_at=record.captured_at,
        method=record.method,
        host=record.host,
        path=record.path,
        cached_tokens=record.cached_tokens,
        total_tokens=record.total_tokens,
        cache_ratio=record.cache_ratio,
        is_cache_drop=record.is_cache_drop,
        comparable_prev_packet_id=record.comparable_prev_packet_id,
        compare_block_reason=record.compare_block_reason,
    )


def _to_detail(record) -> PacketDetail:
    summary = _to_summary(record)
    return PacketDetail(
        **summary.model_dump(),
        raw_request_text=record.raw_request_text,
        raw_response_text=record.raw_response_text,
        request_headers_text=record.request_headers_text,
        request_body_text=record.request_body_text,
        response_headers_text=record.response_headers_text,
        response_body_text=record.response_body_text,
        formatted_request_body_text=record.formatted_request_body_text,
        formatted_response_body_text=record.formatted_response_body_text,
    )
