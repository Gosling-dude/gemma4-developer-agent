"""A scripted OpenAI-compatible chat server for pipeline tests of the OFFICIAL harness (no GPU, no model).

It replays a fixed list of steps as tool calls, one per request, and logs every request and the
tool results it receives. It stands in for vLLM only to check that the harness path works end to end:
submission compile -> tools -> skills (run_skill_script in the sandbox) -> submit_patch -> Phase-2 grading.
Its output says nothing about model quality.

Usage: python scripts/fake_openai_server.py --port 8765 --steps steps.json --log requests.jsonl
steps.json: [{"tool": "name", "args": {...}} | {"text": "..."}]
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_handler(steps: list[dict], log: Path):
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, obj: dict, code: int = 200) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send({"object": "list", "data": [{"id": "gemma-4-31b-it-qat-w4a16-ct", "object": "model"}]})

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            with lock:
                step = steps.pop(0) if steps else {"text": "done"}
                with log.open("a") as fh:
                    last = req.get("messages", [])[-1] if req.get("messages") else {}
                    fh.write(json.dumps({"t": time.time(), "model": req.get("model"),
                                         "n_messages": len(req.get("messages", [])),
                                         "tools": [t.get("function", {}).get("name") for t in req.get("tools") or []],
                                         "last_role": last.get("role"), "last_content": str(last.get("content"))[:3000],
                                         "params": {k: v for k, v in req.items() if k not in ("messages", "tools")},
                                         "step": step}) + "\n")
            if "tool" in step:
                msg = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                    "function": {"name": step["tool"], "arguments": json.dumps(step.get("args", {}))}}]}
                finish = "tool_calls"
            else:
                msg = {"role": "assistant", "content": step["text"]}
                finish = "stop"
            self._send({"id": f"chatcmpl-{uuid.uuid4().hex[:8]}", "object": "chat.completion", "created": int(time.time()),
                        "model": req.get("model", "x"), "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}})

    return H


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--steps", type=Path, required=True)
    ap.add_argument("--log", type=Path, required=True)
    a = ap.parse_args()
    a.log.write_text("")
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(json.loads(a.steps.read_text()), a.log)).serve_forever()


if __name__ == "__main__":
    main()
