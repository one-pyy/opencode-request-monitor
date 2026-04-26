# pyright: reportMissingImports=false

from __future__ import annotations

import importlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mitmproxy import ctx, http

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

settings = importlib.import_module("app.settings")
DEFAULT_WEB_HOST = settings.DEFAULT_WEB_HOST
DEFAULT_WEB_PORT = settings.DEFAULT_WEB_PORT

ALLOWED_PATH_PREFIXES = (
    "/v1/chat/completions",
    "/v1/messages",
    "/v1/responses",
    "/v1beta/models/",
)


class PacketCaptureAddon:
    def __init__(self) -> None:
        self.api_url = os.environ.get(
            "OPENCODE_REQUEST_MONITOR_API_URL",
            f"http://{DEFAULT_WEB_HOST}:{DEFAULT_WEB_PORT}/api/packets",
        )

    def load(self, loader) -> None:  # type: ignore[no-untyped-def]
        ctx.log.info(f"opencode-request-monitor api => {self.api_url}")

    def response(self, flow: http.HTTPFlow) -> None:
        if not should_capture(flow.request.path):
            return
        request_body = normalize_captured_text(flow.request.get_text(strict=False))
        if request_body is None:
            request_body = ""
        response_body = normalize_captured_text(flow.response.get_text(strict=False)) if flow.response is not None else ""
        if response_body is None:
            response_body = ""
        response_headers = dict(flow.response.headers.items()) if flow.response is not None else {}
        cached_tokens, total_tokens = extract_token_stats(response_body, response_headers)
        payload = {
            "method": flow.request.method,
            "host": flow.request.pretty_host,
            "path": flow.request.path,
            "raw_request_text": build_raw_request_text(flow),
            "raw_response_text": build_raw_response_text(flow),
            "request_headers_text": json.dumps(dict(flow.request.headers.items()), ensure_ascii=False),
            "request_body_text": request_body,
            "response_headers_text": json.dumps(response_headers, ensure_ascii=False),
            "response_body_text": response_body,
            "cached_tokens": cached_tokens,
            "total_tokens": total_tokens,
        }
        send_to_api(self.api_url, payload)


def send_to_api(url: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
    except urllib.error.URLError as error:
        ctx.log.warn(f"failed to send packet to api: {error}")


def normalize_captured_text(value: str | None) -> str | None:
    if value is None:
        return None
    return repair_mojibake_text(value)


def build_raw_request_text(flow: http.HTTPFlow) -> str:
    http_version = flow.request.http_version or "HTTP/1.1"
    headers = list(flow.request.headers.items())
    if not any(name.lower() == "host" for name, _value in headers):
        headers.insert(0, ("Host", flow.request.pretty_host))
    return join_raw_http_message(
        f"{flow.request.method} {flow.request.path or '/'} {http_version}",
        headers,
        decode_raw_content(flow.request.raw_content),
    )


def build_raw_response_text(flow: http.HTTPFlow) -> str:
    if flow.response is None:
        return ""
    http_version = flow.response.http_version or flow.request.http_version or "HTTP/1.1"
    reason = f" {flow.response.reason}" if flow.response.reason else ""
    return join_raw_http_message(
        f"{http_version} {flow.response.status_code}{reason}",
        list(flow.response.headers.items()),
        decode_raw_content(flow.response.raw_content),
    )


def join_raw_http_message(start_line: str, headers: list[tuple[str, str]], body: str) -> str:
    header_lines = [f"{name}: {value}" for name, value in headers]
    return "\r\n".join([start_line, *header_lines, "", body])


def decode_raw_content(value: bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace")


def repair_mojibake_text(value: str) -> str:
    if not looks_like_mojibake(value):
        return value
    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value
    return repaired


def looks_like_mojibake(value: str) -> bool:
    suspicious_chars = "ÃÂæåäçéèêëîïôöûüœøßðñ"
    return any(char in suspicious_chars for char in value)


def extract_token_stats(response_body: str, response_headers: dict[str, Any]) -> tuple[int | None, int | None]:
    usage = extract_usage_from_json_body(response_body)
    if usage is not None:
        cached_tokens = nested_int(
            usage,
            ["prompt_tokens_details", "cached_tokens"],
            ["input_tokens_details", "cached_tokens"],
            ["cache_read_input_tokens"],
            ["cachedContentTokenCount"],
            ["cached_tokens"],
        )
        total_tokens = nested_int(
            usage,
            ["prompt_tokens"],
            ["input_tokens"],
            ["promptTokenCount"],
            ["total_tokens"],
            ["totalTokenCount"],
        )
        if cached_tokens is not None or total_tokens is not None:
            return cached_tokens, total_tokens

    stream_cached_tokens, stream_total_tokens = extract_token_stats_from_sse(response_body)
    if stream_cached_tokens is not None or stream_total_tokens is not None:
        return stream_cached_tokens, stream_total_tokens

    header_cached_tokens = header_int(
        response_headers,
        "x-openai-prompt-cached-tokens",
        "x-opencode-prompt-cached-tokens",
    )
    header_total_tokens = header_int(
        response_headers,
        "x-openai-prompt-tokens",
        "x-opencode-prompt-tokens",
        "x-openai-total-tokens",
    )
    return header_cached_tokens, header_total_tokens


def extract_usage_from_json_body(response_body: str) -> dict[str, Any] | None:
    if not response_body.strip():
        return None
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and isinstance(parsed.get("usage"), dict):
        return parsed["usage"]
    if isinstance(parsed, dict) and isinstance(parsed.get("usageMetadata"), dict):
        return parsed["usageMetadata"]
    if isinstance(parsed, dict) and isinstance(parsed.get("response"), dict):
        response = parsed["response"]
        if isinstance(response.get("usage"), dict):
            return response["usage"]
        if isinstance(response.get("usageMetadata"), dict):
            return response["usageMetadata"]
    return None


def extract_token_stats_from_sse(response_body: str) -> tuple[int | None, int | None]:
    if "data:" not in response_body:
        return None, None

    final_cached_tokens: int | None = None
    final_total_tokens: int | None = None

    for line in response_body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        usage = extract_usage_from_stream_event(parsed)
        if not isinstance(usage, dict):
            continue
        cached_tokens = nested_int(
            usage,
            ["prompt_tokens_details", "cached_tokens"],
            ["input_tokens_details", "cached_tokens"],
            ["cache_read_input_tokens"],
            ["cachedContentTokenCount"],
            ["cached_tokens"],
        )
        total_tokens = nested_int(
            usage,
            ["prompt_tokens"],
            ["input_tokens"],
            ["promptTokenCount"],
            ["total_tokens"],
            ["totalTokenCount"],
        )
        if cached_tokens is not None:
            final_cached_tokens = cached_tokens
        if total_tokens is not None:
            final_total_tokens = total_tokens

    return final_cached_tokens, final_total_tokens


def extract_usage_from_stream_event(event: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(event.get("usage"), dict):
        return event["usage"]
    if isinstance(event.get("usageMetadata"), dict):
        return event["usageMetadata"]
    response = event.get("response")
    if isinstance(response, dict):
        if isinstance(response.get("usage"), dict):
            return response["usage"]
        if isinstance(response.get("usageMetadata"), dict):
            return response["usageMetadata"]
    return None


def should_capture(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES)


def nested_int(source: dict[str, Any], *paths: list[str]) -> int | None:
    for path in paths:
        current: Any = source
        for part in path:
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if isinstance(current, int):
            return current
    return None


def header_int(source: dict[str, Any], *keys: str) -> int | None:
    lowered = {str(key).lower(): value for key, value in source.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is None:
            continue
        try:
            return int(str(value))
        except ValueError:
            continue
    return None


addons = [PacketCaptureAddon()]
