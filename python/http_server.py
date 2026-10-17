#!/usr/bin/env python3
"""最小控制 HTTP 服务：POST /v1/control  {"text":"..."}。

默认 FakeLLM；板上设环境变量 CONTROL_BACKEND=rkllm_cli 且提供模型路径后走真推理封装。
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from audit import AuditLog  # noqa: E402
from fake_llm import FakeLLM  # noqa: E402
from mock_device import MockDevice  # noqa: E402
from pipeline import ControlPipeline  # noqa: E402
from verifier import ActionVerifier  # noqa: E402

LOCK = Lock()


def build_pipeline() -> ControlPipeline:
    backend = os.environ.get("CONTROL_BACKEND", "fake").lower()
    if backend == "rkllm_cli":
        from rkllm_backend import RKLLMCliBackend

        model = os.environ["RKLLM_MODEL"]
        prompt = (ROOT / "configs/system_prompt.txt").read_text(encoding="utf-8")
        llm = RKLLMCliBackend(model, prompt)
    else:
        llm = FakeLLM()
    return ControlPipeline(
        llm,
        ActionVerifier(),
        MockDevice(),
        AuditLog(ROOT / "bench/logs/audit.jsonl"),
    )


PIPE: ControlPipeline | None = None


def get_pipe() -> ControlPipeline:
    global PIPE
    if PIPE is None:
        PIPE = build_pipeline()
    return PIPE


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/health", "/v1/health"):
            self._json(200, {"ok": True, "backend": os.environ.get("CONTROL_BACKEND", "fake")})
            return
        if self.path in ("/v1/status", "/status"):
            self._json(200, {"state": get_pipe().device.state.snapshot()})
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in ("/v1/control", "/control"):
            self._json(404, {"error": "not_found"})
            return
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n)
        try:
            payload = json.loads(raw.decode("utf-8"))
            text = str(payload.get("text", "")).strip()
        except Exception:
            self._json(400, {"error": "bad_json"})
            return
        if not text:
            self._json(400, {"error": "empty_text"})
            return
        with LOCK:
            out = get_pipe().handle(text)
        self._json(200, out)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8787"))
    get_pipe()  # 启动时预热
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(
        f"control server on http://{host}:{port} backend={os.environ.get('CONTROL_BACKEND', 'fake')}",
        flush=True,
    )
    httpd.serve_forever()


if __name__ == "__main__":
    main()
