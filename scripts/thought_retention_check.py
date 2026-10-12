"""Does the OFFICIAL harness keep the model's reasoning across tool calls? (R017 pre-run check, docs/r017.md)

Runs in the official venv (adk-submission / swegemma from the organizers' wheelhouse). For each submission given,
it compiles the agent with the official compile_submission (which applies the official thinking resolver and
installs adk-submission's LiteLLM reasoning patch), points its model at a scripted OpenAI-compatible server, and
runs two turns through google-adk:
  turn 1: the server answers with reasoning_content = a unique marker plus a get_status tool call;
  turn 2: the server records the request and answers with plain text.
It then reports what turn 1's request asked for (enable_thinking, thinking_token_budget) and whether the marker
came back to the server inside turn 2's assistant message (reasoning retained) or not (stripped).

Usage: evaluations/.cache/official_venv/bin/python scripts/thought_retention_check.py <submission dir|zip> [...]
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MARKER = "THOUGHT-MARKER-7f3c2a: the bug is in clamp(); I will check get_status first."
MODEL = "gemma-4-31b-it-qat-w4a16-ct"


def _server(log: list) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            log.append(body)
            if len(log) == 1:
                msg = {"role": "assistant", "content": None, "reasoning_content": MARKER,
                       "tool_calls": [{"id": "call_1", "type": "function",
                                       "function": {"name": "get_status", "arguments": "{}"}}]}
                finish = "tool_calls"
            else:
                msg, finish = {"role": "assistant", "content": "done"}, "stop"
            out = json.dumps({"id": "x", "object": "chat.completion", "created": 0, "model": MODEL,
                              "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                              "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _stub_tools() -> dict:
    def get_status() -> str:
        """Report remaining budget."""
        return json.dumps({"status": "ok", "tool_calls_remaining": 10})

    def run_command(command: str) -> str:
        """Run a shell command."""
        return json.dumps({"status": "ok", "stdout": ""})

    def read_file(filepath: str, start_line: int | None = None, end_line: int | None = None) -> str:
        """Read a file."""
        return json.dumps({"status": "ok", "content": ""})

    def edit_file(filepath: str, old_string: str, new_string: str, allow_multiple: bool = False) -> str:
        """Edit a file."""
        return json.dumps({"status": "ok"})

    def write_file(filepath: str, content: str) -> str:
        """Write a file."""
        return json.dumps({"status": "ok"})

    def submit_patch() -> str:
        """Submit the patch."""
        return json.dumps({"status": "ok"})

    def get_code_neighbors(node: str, edge_type: str | None = None, max_neighbors: int = 50) -> str:
        """Graph neighbors."""
        return "{}"

    def search_similar_code(query: str, k: int = 10) -> str:
        """Similar code."""
        return "{}"

    def get_code_subgraph(nodes: list[str]) -> str:
        """Subgraph."""
        return "{}"

    return {f.__name__: f for f in (get_status, run_command, read_file, edit_file, write_file, submit_patch,
                                     get_code_neighbors, search_similar_code, get_code_subgraph)}


async def _check(sub: Path) -> dict:
    from adk_eval_core.sandbox.base import AdkSandboxCodeExecutor
    from adk_submission import ModelRegistry, compile_submission
    from adk_submission.discovery import discover_adapters
    from google.adk.models.lite_llm import LiteLlm
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    from swegemma.config import build_submission_limits

    log: list = []
    srv = _server(log)
    try:
        reg = ModelRegistry()
        reg.register(MODEL, LiteLlm(model=f"openai/{MODEL}", api_base=f"http://127.0.0.1:{srv.server_port}/v1",
                                    api_key="EMPTY"))
        limits, gen = build_submission_limits()
        agent = compile_submission(submission_dir=sub, tool_registry=_stub_tools(), model_registry=reg,
                                   code_executor=AdkSandboxCodeExecutor(sandbox=None, timeout_seconds=60),
                                   script_timeout=60, limits=limits, generation_constraints=gen,
                                   adapter_manifest=discover_adapters(sub))
        runner = Runner(app_name="t", agent=agent, session_service=InMemorySessionService())
        session = await runner.session_service.create_session(
            app_name="t", user_id="u", state={"problem_description": "Fix clamp."})  # what the harness seeds
        async for _ in runner.run_async(user_id="u", session_id=session.id,
                                        new_message=types.Content(role="user", parts=[types.Part(text="Fix clamp.")])):
            pass
    finally:
        srv.shutdown()
    first, second = log[0], (log[1] if len(log) > 1 else {})
    assistant = [m for m in second.get("messages", []) if m.get("role") == "assistant"]
    carried = [k for m in assistant for k in ("reasoning", "reasoning_content") if MARKER in str(m.get(k) or "")]
    in_text = any(MARKER in str(m.get("content") or "") for m in assistant)
    return {
        "submission": str(sub), "requests": len(log),
        "turn1_chat_template_kwargs": (first.get("chat_template_kwargs")
                                       or (first.get("extra_body") or {}).get("chat_template_kwargs")),
        "turn1_thinking_token_budget": first.get("thinking_token_budget",
                                                 (first.get("extra_body") or {}).get("thinking_token_budget")),
        "turn2_assistant_messages": len(assistant),
        "reasoning_retained_in_fields": carried,
        "reasoning_leaked_into_content": in_text,
        "verdict": "RETAINED" if carried else "STRIPPED",
    }


def main(argv: list[str]) -> int:
    for target in argv:
        p = Path(target).resolve()
        if p.suffix == ".zip":
            td = Path(tempfile.mkdtemp())
            zipfile.ZipFile(p).extractall(td)
            p = td
        print(json.dumps(asyncio.run(_check(p))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
