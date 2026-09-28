#!/usr/bin/env bash
# Verify an OpenAI-compatible endpoint serving the competition model, with a real tool-calling smoke test.
#
# Required environment (never commit these; put them in your shell or an untracked .env):
#   G4_API_BASE   e.g. http://127.0.0.1:8000/v1  (a vLLM server started like the official notebook)
#   G4_MODEL      served model name; must contain gemma-4-31b-it-qat-w4a16-ct
# Optional:
#   G4_API_KEY    bearer token if the server needs one
#   G4_ALLOW_NONCOMPETITION_MODEL=1  permit another model for PIPELINE DEBUGGING ONLY; results get labelled
#                                    NON-COMPETITION and must never be reported as Gemma 4 scores.
# Exit codes: 0 ok, 2 not configured, 3 unreachable, 4 wrong model, 5 smoke test failed.
set -uo pipefail
cd "$(dirname "$0")/.."
[[ -n "${G4_API_BASE:-}" ]] || { echo "FAIL: G4_API_BASE not set (see docs/kaggle_runtime.md)" >&2; exit 2; }
[[ -n "${G4_MODEL:-}" ]] || { echo "FAIL: G4_MODEL not set" >&2; exit 2; }
exec .venv/bin/python - <<'EOF'
import json, os, sys, time, urllib.request, urllib.error

base = os.environ["G4_API_BASE"].rstrip("/")
model = os.environ["G4_MODEL"]
key = os.environ.get("G4_API_KEY", "EMPTY")
hdr = {"content-type": "application/json", "authorization": f"Bearer {key}"}

def call(path, body=None, timeout=120):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body else None, headers=hdr,
                                 method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

try:
    models = [m.get("id") for m in call("/models").get("data", [])]
except Exception as e:
    print(f"FAIL: endpoint unreachable at {base}/models: {type(e).__name__}: {e}"); sys.exit(3)
print(f"endpoint ok; served models: {models}")
competition = "gemma-4-31b-it-qat-w4a16-ct" in model
if model not in models and not any(model in m or m.endswith(model) for m in models):
    print(f"FAIL: G4_MODEL={model!r} is not served here"); sys.exit(4)
if not competition:
    if os.environ.get("G4_ALLOW_NONCOMPETITION_MODEL") != "1":
        print(f"FAIL: {model!r} is not the competition model gemma-4-31b-it-qat-w4a16-ct"); sys.exit(4)
    print("WARNING: NON-COMPETITION model; results are pipeline debugging only")

tool = {"type": "function", "function": {"name": "read_file", "description": "Read a file from /workspace.",
        "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}}}
body = {"model": model, "max_tokens": 256, "temperature": 0,
        "messages": [{"role": "user", "content": "Call the read_file tool to open setup.py. Do not answer in text."}],
        "tools": [tool], "chat_template_kwargs": {"enable_thinking": False}}
t0 = time.time()
try:
    resp = call("/chat/completions", body, timeout=300)
except urllib.error.HTTPError as e:
    print(f"FAIL: chat completion HTTP {e.code}: {e.read()[:500]!r}"); sys.exit(5)
except Exception as e:
    print(f"FAIL: chat completion error: {type(e).__name__}: {e}"); sys.exit(5)
dt = time.time() - t0
msg = resp["choices"][0]["message"]
calls = msg.get("tool_calls") or []
usage = resp.get("usage", {})
out_tok = usage.get("completion_tokens") or 0
print(f"latency {dt:.1f}s, completion_tokens={out_tok}, ~{out_tok / dt:.1f} tok/s (single short request)")
if not calls or calls[0]["function"]["name"] != "read_file":
    print(f"FAIL: expected a read_file tool call (tool parser gemma4 enabled?), got: {json.dumps(msg)[:400]}"); sys.exit(5)
args = json.loads(calls[0]["function"]["arguments"] or "{}")
print(f"tool call ok: read_file({args})")
print("ENDPOINT OK" + ("" if competition else " (NON-COMPETITION MODEL)"))
EOF
