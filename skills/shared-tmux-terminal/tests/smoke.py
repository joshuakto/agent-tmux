#!/usr/bin/env python3
"""Smoke test for tmux_session.py — guards the manager-loop contract.

Run:  python3 skills/shared-tmux-terminal/tests/smoke.py

Stdlib only. Hermetic: no live agents, tmux servers, or network. Checks the seams
that the supervised golden path depends on, so an accidental regression in any of
them fails loudly instead of silently breaking the loop.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
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
    check("events wait does not ack by default (--ack opt-in, --no-ack gone, --unread present)", "--ack" in ew and "--no-ack" not in ew and "--unread" in ew)
    ph = helptext("prompt", cwd=d)
    check("prompt has --report-back-topic, dropped --print-mark/--quiet", "--report-back-topic" in ph and "--print-mark" not in ph and "--quiet" not in ph)
    check("launch has --json", "--json" in helptext("launch", cwd=d))

# --- #33: events wait is idempotent by default, its timeout is informative, and
# drain semantics remain available via opt-in. Guards the manager-loop contract:
# a repeated wait must not turn a real event into a misleading "stalled" timeout. ---
with tempfile.TemporaryDirectory() as d:
    def wait_kind(*extra: str) -> str:
        return json.loads(run("events", "wait", "--timeout", "1", "--json", *extra, cwd=d).stdout).get("kind")

    run("events", "emit", "--kind", "board_post", "--session", "rev", "--summary", "done", cwd=d)
    k1 = wait_kind("--kind", "board_post", "--session", "rev")
    k2 = wait_kind("--kind", "board_post", "--session", "rev")
    check("events wait is idempotent (repeat wait still returns the event, not a stale timeout)", k1 == "board_post" and k2 == "board_post")

    run("events", "emit", "--kind", "agent_stop", "--session", "solo", "--summary", "stopped", cwd=d)
    t = json.loads(run("events", "wait", "--kind", "board_post", "--session", "solo", "--timeout", "1", "--json", cwd=d).stdout)
    check(
        "events wait timeout is informative (reports attention events after the cursor)",
        t.get("kind") == "timeout" and t.get("events_after_cursor", 0) >= 1 and "agent_stop" in (t.get("kinds_after_cursor") or {}),
    )
    g = json.loads(run("events", "wait", "--kind", "board_post", "--session", "ghost", "--timeout", "1", "--json", cwd=d).stdout)
    check("events wait timeout reports 0 after-cursor events when nothing landed", g.get("kind") == "timeout" and g.get("events_after_cursor") == 0)

    # a --topic wait must still surface topic-less attention events on timeout,
    # else it re-introduces the #33 false "stalled" reading for topic-scoped waits
    run("events", "emit", "--kind", "agent_stop", "--session", "topicy", "--summary", "stopped", cwd=d)
    tp = json.loads(run("events", "wait", "--kind", "board_post", "--topic", "sometopic", "--session", "topicy", "--timeout", "1", "--json", cwd=d).stdout)
    check("events wait timeout is not topic-scoped (surfaces topic-less attention events)", tp.get("events_after_cursor", 0) >= 1 and "agent_stop" in (tp.get("kinds_after_cursor") or {}))

    run("events", "emit", "--kind", "board_post", "--session", "drain", "--summary", "x", cwd=d)
    d1 = wait_kind("--kind", "board_post", "--session", "drain", "--unread", "--ack")
    d2 = wait_kind("--kind", "board_post", "--session", "drain", "--unread")
    check("events wait --unread --ack drains (next --unread wait times out)", d1 == "board_post" and d2 == "timeout")

# --- stdout-capture contract (behavioral): emit_capturable_id() — shared by prompt
# and mark — must put the bare id on stdout (so MARK=$(...) captures just it) and the
# receipt on stderr; with --json, the full receipt on stdout. ---
_out, _err = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(_out), contextlib.redirect_stderr(_err):
    m.emit_capturable_id("m_x", {"mark": "m_x"}, "mark created: target=t", as_json=False)
check(
    "emit_capturable_id: bare id on stdout, receipt on stderr",
    _out.getvalue().strip() == "m_x" and "mark created" in _err.getvalue() and "mark created" not in _out.getvalue(),
)
_out = io.StringIO()
with contextlib.redirect_stdout(_out):
    m.emit_capturable_id("m_x", {"mark": "m_x", "target": "t"}, "ignored", as_json=True)
check(
    "emit_capturable_id --json: full receipt on stdout",
    json.loads(_out.getvalue()).get("mark") == "m_x",
)

print(f"\n{len(_failures)} failure(s): {', '.join(_failures)}" if _failures else "\nAll smoke checks passed.")
sys.exit(1 if _failures else 0)
