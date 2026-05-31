#!/usr/bin/env python3
"""Smoke test for tmux_session.py — guards the manager-loop contract.

Run:  python3 skills/shared-tmux-terminal/tests/smoke.py

Stdlib only. Hermetic: no live agents, tmux servers, or network. Checks the seams
that the supervised golden path depends on, so an accidental regression in any of
them fails loudly instead of silently breaking the loop.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tmux_session.py"

_failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
    if not ok:
        _failures.append(name)


def load_module():
    spec = importlib.util.spec_from_file_location("tmux_session", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(*args: str, cwd: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd
    )


def helptext(*args: str, cwd: str) -> str:
    return run(*args, "--help", cwd=cwd).stdout


m = load_module()

# --- pure-function units ---
check("board_body strips frontmatter", m.board_body_from_text("---\nid: x\n---\nHELLO") == "HELLO")
check("board_body passes plain text", m.board_body_from_text("just body") == "just body")

# --- CLI behavior through the real main() dispatch (no live session needed) ---
with tempfile.TemporaryDirectory() as d:
    r = run("events", "wait", "--from-now", "--timeout", "0.2", "--json", cwd=d)
    check("events wait exits 0 on timeout", r.returncode == 0 and json.loads(r.stdout).get("kind") == "timeout")

    r = run("read", cwd=d)
    check("read without session/--since-mark errors clearly", r.returncode != 0 and "session is required" in (r.stderr + r.stdout))

    r = run("--socket", "/x/custom.sock", "report", cwd=d)
    check("--socket propagates into generated commands", "--socket /x/custom.sock" in (r.stdout + r.stderr))
    r = run("report", cwd=d)
    check("no --socket in generated commands by default", "--socket" not in (r.stdout + r.stderr))

    # --- flag-contract guards (cheap regression catch) ---
    ew = helptext("events", "wait", cwd=d)
    check("events wait defaults to ack (--no-ack present, bare --ack absent)", "--no-ack" in ew and "--ack" not in ew)
    ph = helptext("prompt", cwd=d)
    check("prompt has --report-back-topic, dropped --print-mark/--quiet", "--report-back-topic" in ph and "--print-mark" not in ph and "--quiet" not in ph)
    check("launch has --json", "--json" in helptext("launch", cwd=d))

print(f"\n{len(_failures)} failure(s): {', '.join(_failures)}" if _failures else "\nAll smoke checks passed.")
sys.exit(1 if _failures else 0)
