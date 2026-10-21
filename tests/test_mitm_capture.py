# pyright: reportMissingImports=false

import importlib
import json
import threading
import time
import urllib.error
from unittest.mock import Mock

import pytest
from mitmproxy import http
from mitmproxy.test.tflow import tflow

capture = importlib.import_module("mitm_capture")


@pytest.fixture
def addon():
    instance = capture.PacketCaptureAddon()
    yield instance
    if hasattr(instance, "done"):
        instance.done()


def make_flow(path="/v1/chat/completions", content_type="text/event-stream", body=""):
    flow = tflow(resp=True)
    flow.request = http.Request.make(
        "POST", f"http://localhost{path}", b'{"model":"probe"}',
        {"content-type": "application/json"},
    )
    flow.response = http.Response.make(200, body.encode(), {"content-type": content_type})
    return flow


def test_load_keeps_streamed_bodies(addon, monkeypatch):
    options = Mock()
    monkeypatch.setattr(capture.ctx, "options", options, raising=False)
    monkeypatch.setattr(capture.ctx, "log", Mock(), raising=False)
    addon.load(Mock())
    options.update.assert_called_once_with(store_streamed_bodies=True)


@pytest.mark.parametrize("path", [
    "/v1/chat/completions", "/v1/messages", "/v1/responses",
    "/v1beta/models/gemini:streamGenerateContent",
])
def test_model_sse_streams_from_headers(addon, path):
    flow = make_flow(path, "Text/Event-Stream; charset=utf-8")
    addon.responseheaders(flow)
    assert flow.response is not None
    assert flow.response.stream is True


@pytest.mark.parametrize("path,content_type", [
    ("/v1/chat/completions", "application/json"),
    ("/unrelated", "text/event-stream"),
])
def test_other_responses_keep_existing_behavior(addon, path, content_type):
    flow = make_flow(path, content_type)
    addon.responseheaders(flow)
    assert flow.response is not None
    assert flow.response.stream is False


def test_missing_response_is_ignored(addon):
    flow = make_flow()
    flow.response = None
    addon.responseheaders(flow)


def test_complete_capture_runs_in_background_and_drains(addon, monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    records = []

    def send(url, payload):
        entered.set()
        release.wait(timeout=2)
        records.append((url, payload))
        finished.set()

    monkeypatch.setattr(capture, "send_to_api", send)
    body = 'data: {"choices":[{"delta":{"reasoning_content":"思考"}}]}\n\n'
    body += 'data: {"choices":[{"delta":{"content":"回答"}}]}\n\n'
    body += 'data: {"usage":{"prompt_tokens":100,"prompt_tokens_details":{"cached_tokens":70}}}\n\n'
    body += 'data: [DONE]\n\n'
    start = time.monotonic()
    addon.response(make_flow(body=body))
    assert time.monotonic() - start < 0.5
    try:
        assert entered.wait(timeout=1)
        assert not finished.is_set()
    finally:
        release.set()
        addon.done()
    assert finished.is_set()
    url, payload = records[0]
    assert url == addon.api_url
    assert payload["response_body_text"] == body
    assert payload["raw_response_text"].endswith(body)
    assert payload["request_body_text"] == '{"model":"probe"}'
    assert (payload["cached_tokens"], payload["total_tokens"]) == (70, 100)


def test_json_capture_keeps_body_and_usage(addon, monkeypatch):
    records = []
    monkeypatch.setattr(capture, "send_to_api", lambda _url, payload: records.append(payload))
    body = json.dumps({"choices": [], "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 70}}})
    addon.response(make_flow("/v1/responses", "application/json", body))
    addon.done()
    assert records[0]["response_body_text"] == body
    assert (records[0]["cached_tokens"], records[0]["total_tokens"]) == (70, 100)


def test_unrelated_request_is_not_uploaded(addon, monkeypatch):
    sender = Mock()
    monkeypatch.setattr(capture, "send_to_api", sender)
    addon.response(make_flow("/unrelated"))
    addon.done()
    sender.assert_not_called()


def test_unexpected_upload_failure_is_logged(addon, monkeypatch, caplog):
    def fail(_url, _payload):
        raise RuntimeError("upload-probe-failure")

    monkeypatch.setattr(capture, "send_to_api", fail)
    addon.response(make_flow())
    addon.done()
    assert "upload-probe-failure" in caplog.text


def test_api_network_failure_is_logged(monkeypatch, caplog):
    def fail(*_args, **_kwargs):
        raise urllib.error.URLError("network-probe-failure")

    monkeypatch.setattr(capture.urllib.request, "urlopen", fail)
    capture.send_to_api("http://localhost/api/packets", {})
    assert "network-probe-failure" in caplog.text


def test_done_waits_for_pending_upload(addon, monkeypatch):
    finished = threading.Event()

    def send(_url, _payload):
        time.sleep(0.05)
        finished.set()

    monkeypatch.setattr(capture, "send_to_api", send)
    addon.response(make_flow())
    addon.done()
    assert finished.is_set()


def test_background_upload_preserves_capture_order(addon, monkeypatch):
    entered, release, second_done = threading.Event(), threading.Event(), threading.Event()
    paths = []

    def send(_url, payload):
        if payload["path"].endswith("first"):
            entered.set()
            release.wait(timeout=2)
        paths.append(payload["path"])
        if payload["path"].endswith("second"):
            second_done.set()

    monkeypatch.setattr(capture, "send_to_api", send)
    first = "/v1/chat/completions?case=first"
    second = "/v1/chat/completions?case=second"
    try:
        addon.response(make_flow(first))
        assert entered.wait(timeout=1)
        addon.response(make_flow(second))
        second_done.wait(timeout=0.1)
    finally:
        release.set()
        addon.done()
    assert paths == [first, second]
