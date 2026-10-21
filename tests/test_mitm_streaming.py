# pyright: reportMissingImports=false

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster


def test_real_script_streams_and_preserves_capture(monkeypatch):
    records, expected = [], {}

    class CaptureAPI(BaseHTTPRequestHandler):
        def log_message(self, format, *_args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            time.sleep(0.35)
            records.append(payload)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

    class ModelAPI(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            usage = {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 70}}
            if self.path.endswith("json"):
                body = json.dumps({"choices": [], "usage": usage}).encode()
                expected[self.path] = body.decode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            count = 8 if self.path.endswith("short") else 24
            frames = []
            for index in range(count):
                delta = {"reasoning_content": "thinking"} if index < 2 else {"content": str(index)}
                frames.append(("data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\n").encode())
            frames.append(("data: " + json.dumps({"choices": [], "usage": usage}) + "\n\n").encode())
            frames.append(b"data: [DONE]\n\n")
            expected[self.path] = b"".join(frames).decode()
            self.send_response(200)
            self.send_header("Content-Type", "Text/Event-Stream; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            for frame in frames:
                self.wfile.write(f"{len(frame):X}\r\n".encode() + frame + b"\r\n")
                self.wfile.flush()
                time.sleep(0.08)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

    capture_server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureAPI)
    model_server = ThreadingHTTPServer(("127.0.0.1", 0), ModelAPI)
    servers = (capture_server, model_server)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    monkeypatch.setenv("OPENCODE_REQUEST_MONITOR_API_URL", f"http://127.0.0.1:{capture_server.server_port}/api/packets")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    async def verify():
        options = Options(listen_host="127.0.0.1", listen_port=0)
        master = DumpMaster(options, with_termlog=False, with_dumper=False)
        proxy_server = master.addons.get("proxyserver")
        assert proxy_server is not None
        source = Path(__file__).resolve().parents[1] / "mitm_capture.py"
        options.update(scripts=[str(source)])
        running = asyncio.create_task(master.run())
        results = []
        try:
            for _ in range(300):
                if running.done():
                    await running
                    raise RuntimeError("test proxy exited before startup")
                if proxy_server.listen_addrs() and options.store_streamed_bodies:
                    break
                await asyncio.sleep(0.01)
            else:
                raise TimeoutError("test script did not enable streamed body storage")
            port = proxy_server.listen_addrs()[0][1]
            origin = f"http://127.0.0.1:{model_server.server_port}"
            async with httpx.AsyncClient(proxy=f"http://127.0.0.1:{port}", trust_env=False, timeout=10) as client:
                async def stream(case):
                    start = time.monotonic()
                    arrival = []
                    async with client.stream("POST", origin + f"/v1/chat/completions?case={case}", json={"model": "probe"}) as response:
                        assert response.status_code == 200
                        async for line in response.aiter_lines():
                            if line.startswith("data:"):
                                arrival.append(time.monotonic() - start)
                    result = {
                        "case": case, "first_s": round(arrival[0], 3),
                        "max_gap_s": round(max(b - a for a, b in zip(arrival, arrival[1:])), 3),
                        "tail_s": round(time.monotonic() - start - arrival[-1], 3),
                    }
                    assert len(arrival) == (10 if case == "short" else 26)
                    assert result["first_s"] < 0.3
                    assert result["max_gap_s"] < 0.25
                    assert result["tail_s"] < 0.2
                    return result

                results = await asyncio.gather(stream("short"), stream("long"))
                response = await client.post(origin + "/v1/chat/completions?case=json", json={"model": "probe"})
                assert response.text == expected["/v1/chat/completions?case=json"]
        finally:
            master.shutdown()
            await asyncio.wait_for(running, 10)
            await proxy_server.servers.update([])
        assert len(records) == 3
        for record in records:
            assert record["response_body_text"] == expected[record["path"]]
            assert record["raw_response_text"].endswith(expected[record["path"]])
            assert json.loads(record["request_body_text"]) == {"model": "probe"}
            assert (record["cached_tokens"], record["total_tokens"]) == (70, 100)
        print(json.dumps({"real_script_streams": results, "complete_captures": len(records)}))

    try:
        asyncio.run(verify())
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
