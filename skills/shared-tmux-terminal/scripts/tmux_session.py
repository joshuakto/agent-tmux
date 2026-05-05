#!/usr/bin/env python3
"""Project-local tmux session manager for shared human/agent terminals."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AGENT_PROFILES: dict[str, dict[str, Any]] = {
    "generic": {
        "aliases": ["shell", "bash", "zsh", "terminal"],
        "actions": {
            "submit": ["Enter"],
            "interrupt": ["C-c"],
            "eof": ["C-d"],
            "escape": ["Escape"],
            "clear": ["C-l"],
        },
        "notes": "Generic terminal profile. Use for shells, REPLs, and unknown terminal agents.",
    },
    "claude": {
        "aliases": ["claude-code", "anthropic"],
        "actions": {
            "submit": ["Enter"],
            "interrupt": ["C-c"],
            "eof": ["C-d"],
            "escape": ["Escape"],
            "clear": ["C-l"],
        },
        "notes": "Claude Code profile. Use prompt to paste text and submit it as a user message.",
    },
    "codex": {
        "aliases": ["openai", "codex-cli"],
        "actions": {
            "submit": ["Enter"],
            "interrupt": ["C-c"],
            "eof": ["C-d"],
            "escape": ["Escape"],
            "clear": ["C-l"],
        },
        "notes": "Codex CLI profile. Use prompt for user-message style input.",
    },
    "gemini": {
        "aliases": ["gemini-cli", "google"],
        "actions": {
            "submit": ["Enter"],
            "interrupt": ["C-c"],
            "eof": ["C-d"],
            "escape": ["Escape"],
            "clear": ["C-l"],
        },
        "notes": "Gemini CLI profile. Use prompt for user-message style input.",
    },
}


WRAPPER = """#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${AGENT_TMUX_BIN:-}" && -x "$AGENT_TMUX_BIN" ]]; then
  exec "$AGENT_TMUX_BIN" "$@"
fi

if command -v agent-tmux >/dev/null 2>&1; then
  exec agent-tmux "$@"
fi

if [[ -x "$HOME/.local/bin/agent-tmux" ]]; then
  exec "$HOME/.local/bin/agent-tmux" "$@"
fi

CODEX_SCRIPT="${CODEX_HOME:-$HOME/.codex}/skills/shared-tmux-terminal/scripts/tmux_session.py"
if [[ -x "$CODEX_SCRIPT" ]]; then
  exec "$CODEX_SCRIPT" "$@"
fi

echo "agent-tmux not found. Install it or set AGENT_TMUX_BIN to its path." >&2
exit 1
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "session"


def project_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            check=True,
            text=True,
            capture_output=True,
        )
        return Path(result.stdout.strip()).resolve()
    except Exception:
        return start


def socket_path(root: Path, override: str | None = None) -> Path:
    if override:
        path = Path(override).expanduser()
        return path if path.is_absolute() else (root / path)
    return root / ".agent" / "tmux.sock"


def registry_path(root: Path) -> Path:
    return root / ".agent" / "tmux.d" / "registry.json"


def doctor_log_path(root: Path) -> Path:
    return root / ".agent" / "tmux.d" / "doctor" / "events.jsonl"


def transcript_dir(root: Path) -> Path:
    return root / ".agent" / "tmux.d" / "logs"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "project_root": None,
            "socket": None,
            "sessions": {},
        }
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("registry is not a JSON object")
    data.setdefault("schema_version", 1)
    data.setdefault("project_root", None)
    data.setdefault("socket", None)
    data.setdefault("sessions", {})
    return data


def save_registry(path: Path, data: dict[str, Any]) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


class TmuxError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, stdout: str, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(self.message)

    @property
    def output(self) -> str:
        return (self.stdout or "") + (self.stderr or "")

    @property
    def message(self) -> str:
        output = self.output.strip()
        return output or f"tmux exited with status {self.returncode}"


def run_tmux(
    socket: Path,
    args: list[str],
    *,
    capture: bool = False,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = ["tmux", "-S", str(socket), *args]
    result = subprocess.run(cmd, text=True, input=input_text, capture_output=capture or check, check=False)
    if check and result.returncode != 0:
        raise TmuxError(cmd, result.returncode, result.stdout or "", result.stderr or "")
    return result


def tmux_output(socket: Path, args: list[str]) -> str:
    result = run_tmux(socket, args, capture=True, check=False)
    if result.returncode != 0:
        raise TmuxError(["tmux", "-S", str(socket), *args], result.returncode, result.stdout or "", result.stderr or "")
    return result.stdout


def try_tmux(socket: Path, args: list[str]) -> dict[str, Any]:
    cmd = ["tmux", "-S", str(socket), *args]
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    except OSError as exc:
        return {
            "cmd": cmd,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
            "ok": False,
        }
    return {
        "cmd": cmd,
        "returncode": result.returncode,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
        "ok": result.returncode == 0,
    }


def classify_tmux_failure(socket: Path, message: str) -> str:
    text = message.lower()
    if "operation not permitted" in text or "permission denied" in text:
        return "permission-denied"
    if "no such file or directory" in text:
        return "socket-missing" if not socket.exists() else "stale-socket"
    if "no server running" in text:
        return "no-server"
    if "error connecting" in text:
        return "connection-error"
    if "can't find session" in text:
        return "session-not-found"
    return "tmux-error"


def print_tmux_error(root: Path, socket: Path, exc: TmuxError, *, context: str) -> None:
    kind = classify_tmux_failure(socket, exc.message)
    print(f"tmux {context} failed: {kind}", file=sys.stderr)
    print(f"socket: {socket}", file=sys.stderr)
    print(f"error: {exc.message}", file=sys.stderr)
    print(f"diagnose: {user_command(root, 'doctor')}", file=sys.stderr)


def append_doctor_event(root: Path, event: dict[str, Any]) -> Path:
    path = doctor_log_path(root)
    ensure_parent(path)
    with path.open("a") as handle:
        handle.write(json.dumps({"schema_version": 1, "timestamp": now_iso(), **event}, sort_keys=True) + "\n")
    return path


def session_exists(socket: Path, session: str) -> bool:
    try:
        run_tmux(socket, ["has-session", "-t", session], capture=True)
        return True
    except TmuxError:
        return False


def list_sessions(socket: Path) -> list[dict[str, Any]]:
    out = tmux_output(socket, [
        "list-sessions",
        "-F",
        "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created}\t#{session_id}",
    ])
    sessions = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        name, windows, attached, created, session_id = parts[:5]
        sessions.append(
            {
                "name": name,
                "windows": int(windows),
                "attached": attached == "1",
                "created": created,
                "id": session_id,
            }
        )
    return sessions


def list_panes(socket: Path, session: str) -> list[dict[str, Any]]:
    out = tmux_output(socket, [
        "list-panes",
        "-t",
        session,
        "-F",
        "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t#{pane_active}\t#{pane_current_command}\t#{pane_title}\t#{pane_pid}\t#{pane_current_path}\t#{pane_pipe}",
    ])
    panes = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        session_name, window_index, pane_index, pane_id, active, command, title, pid = parts[:8]
        current_path = parts[8] if len(parts) > 8 else ""
        pane_pipe = parts[9] if len(parts) > 9 else ""
        panes.append(
            {
                "session_name": session_name,
                "window_index": int(window_index),
                "pane_index": int(pane_index),
                "pane_id": pane_id,
                "active": active == "1",
                "command": command,
                "title": title,
                "pid": pid,
                "current_path": current_path,
                "pipe": pane_pipe == "1",
            }
        )
    return panes


def capture_pane(
    socket: Path,
    target: str,
    *,
    lines: int = 80,
    start: str | int | None = None,
    end: str | int | None = None,
    join: bool = True,
    ansi: bool = False,
) -> str:
    cmd = ["capture-pane", "-t", target, "-p"]
    if ansi:
        cmd.append("-e")
    if join:
        cmd.append("-J")
    if start is not None:
        cmd.extend(["-S", str(start)])
    else:
        cmd.extend(["-S", f"-{lines}"])
    if end is not None:
        cmd.extend(["-E", str(end)])
    output = tmux_output(socket, cmd)
    if start is None and end is None and lines > 0:
        return tail_lines(output, limit=lines)
    return output


def format_lines(text: str, *, number: bool = False, base: int = 1) -> str:
    if not number:
        return text
    lines = text.splitlines()
    width = max(4, len(str(base + len(lines))))
    return "\n".join(f"{index:>{width}}  {line}" for index, line in enumerate(lines, base)) + ("\n" if text.endswith("\n") else "")


def resolve_profile(name: str | None) -> tuple[str, dict[str, Any]]:
    requested = (name or "generic").lower()
    for profile_name, profile in AGENT_PROFILES.items():
        aliases = [alias.lower() for alias in profile.get("aliases", [])]
        if requested == profile_name or requested in aliases:
            return profile_name, profile
    known = ", ".join(sorted(AGENT_PROFILES))
    raise SystemExit(f"Unknown agent profile: {name}. Known profiles: {known}")


def target_for_args(socket: Path, session: str, pane: str | None) -> str:
    if pane:
        return pane
    panes = list_panes(socket, session)
    return active_pane_target(session, panes)


def send_text(socket: Path, target: str, text: str) -> None:
    if "\n" in text or len(text) > 500:
        run_tmux(socket, ["load-buffer", "-b", "agent-tmux", "-"], input_text=text)
        run_tmux(socket, ["paste-buffer", "-b", "agent-tmux", "-t", target, "-d"])
        return
    run_tmux(socket, ["send-keys", "-t", target, "-l", text])


def send_profile_action(socket: Path, target: str, profile: dict[str, Any], action: str) -> None:
    actions = profile.get("actions", {})
    if action not in actions:
        known = ", ".join(sorted(actions))
        raise SystemExit(f"Unknown action: {action}. Known actions for this profile: {known}")
    keys = actions[action]
    run_tmux(socket, ["send-keys", "-t", target, *keys])


def user_command(root: Path, args: str) -> str:
    if (root / ".agent" / "tmux").exists():
        return f".agent/tmux {args}"
    return f"agent-tmux {args}"


def tail_lines(text: str, limit: int = 12) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) <= limit:
        return "\n".join(lines)
    return "\n".join(lines[-limit:])


def active_pane_target(session: str, panes: list[dict[str, Any]]) -> str:
    for pane in panes:
        if pane["active"]:
            return f'{session}:{pane["window_index"]}.{pane["pane_index"]}'
    return f"{session}:0.0"


def session_name_from_target(session: str, target: str) -> str:
    if ":" in target:
        return target.split(":", 1)[0]
    return session


def default_log_file(root: Path, target: str) -> Path:
    safe_target = slugify(target.replace(":", "-").replace(".", "-"))
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return transcript_dir(root) / f"{safe_target}-{timestamp}.log"


def start_transcript(socket: Path, target: str, output_path: Path) -> None:
    ensure_parent(output_path)
    command = f"cat >> {shlex.quote(str(output_path))}"
    run_tmux(socket, ["pipe-pane", "-o", "-t", target, command])


def stop_transcript(socket: Path, target: str) -> None:
    run_tmux(socket, ["pipe-pane", "-t", target])


def update_log_registry(registry: dict[str, Any], session: str, target: str, data: dict[str, Any]) -> None:
    sessions = registry.setdefault("sessions", {})
    entry = sessions.setdefault(session, {})
    logs = entry.setdefault("logs", {})
    pane_log = logs.setdefault(target, {})
    pane_log.update(data)
    entry["last_seen_at"] = now_iso()


def print_report(root: Path, socket: Path, registry: dict[str, Any], *, lines: int = 60) -> None:
    sessions = list_sessions(socket)
    registry_sessions = registry.get("sessions", {})

    print(f"Project root: {root}")
    print(f"Socket: {socket}")
    print(f"Live sessions: {len(sessions)}")
    if not sessions:
        print("No live tmux sessions found on this socket.")
        return

    for sess in sessions:
        name = sess["name"]
        panes = list_panes(socket, name)
        reg = registry_sessions.get(name, {})
        purpose = reg.get("purpose")
        cwd = reg.get("cwd")
        print()
        print(f"Session: {name}")
        print(f"  windows: {sess['windows']}  attached: {'yes' if sess['attached'] else 'no'}")
        if purpose:
            print(f"  purpose: {purpose}")
        if cwd:
            print(f"  cwd: {cwd}")
        print(f"  attach: {user_command(root, f'attach {name}')}")
        print(f"  tmux attach: tmux -S {socket} attach -t {name}")
        print("  panes:")
        for pane in panes:
            marker = "*" if pane["active"] else " "
            target = f"{name}:{pane['window_index']}.{pane['pane_index']}"
            pane_log = reg.get("logs", {}).get(target, {})
            print(
                f"    {marker} {target} {pane['pane_id']} {pane['command']} "
                f'"{pane["title"]}" pid={pane["pid"]} pipe={"yes" if pane.get("pipe") else "no"}'
            )
            if pane_log.get("path"):
                print(f"      log: {pane_log['path']}")
            sample = tail_lines(capture_pane(socket, target, lines=lines), limit=8)
            if sample.strip():
                for line in sample.splitlines():
                    print(f"      {line}")


def update_registry_entry(
    registry: dict[str, Any],
    root: Path,
    socket: Path,
    session: str,
    *,
    purpose: str | None,
    cwd: str,
    run: str | None,
) -> None:
    registry["project_root"] = str(root)
    registry["socket"] = str(socket)
    sessions = registry.setdefault("sessions", {})
    entry = sessions.get(session, {})
    entry.update(
        {
            "purpose": purpose or entry.get("purpose"),
            "cwd": cwd,
            "run": run or entry.get("run"),
            "socket": str(socket),
            "created_at": entry.get("created_at", now_iso()),
            "last_seen_at": now_iso(),
        }
    )
    sessions[session] = entry


def remove_registry_entry(registry: dict[str, Any], session: str) -> None:
    registry.get("sessions", {}).pop(session, None)


def launch(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    ensure_parent(socket)
    registry_file = registry_path(root)
    registry = load_registry(registry_file)

    session = args.session or slugify(f"{root.name}-{args.purpose or 'agent'}-{datetime.now().strftime('%H%M%S')}")
    if session_exists(socket, session):
        mode = "reused"
    else:
        run_tmux(socket, ["new-session", "-Ad", "-s", session, "-c", str(root)])
        mode = "started"

    log_path: Path | None = None
    if args.log:
        target = active_pane_target(session, list_panes(socket, session))
        log_path = Path(args.log_output).expanduser() if args.log_output else default_log_file(root, target)
        if not log_path.is_absolute():
            log_path = root / log_path
        start_transcript(socket, target, log_path)
        update_log_registry(
            registry,
            session,
            target,
            {"path": str(log_path), "started_at": now_iso(), "stopped_at": None},
        )

    if args.run:
        if mode == "started" and args.run_delay > 0:
            time.sleep(args.run_delay)
        target = active_pane_target(session, list_panes(socket, session))
        send_text(socket, target, args.run)
        run_tmux(socket, ["send-keys", "-t", target, "Enter"])

    update_registry_entry(
        registry,
        root,
        socket,
        session,
        purpose=args.purpose,
        cwd=str(root),
        run=args.run,
    )
    save_registry(registry_file, registry)

    panes = list_panes(socket, session)
    print(f"{mode}: {session}")
    print(f"socket: {socket}")
    print(f"attach: {user_command(root, f'attach {session}')}")
    print(f"tmux attach: tmux -S {socket} attach -t {session}")
    print(f"cwd: {root}")
    print(f"registry: {registry_file}")
    if log_path:
        print(f"log: {log_path}")
    print(f"windows: {len({pane['window_index'] for pane in panes})}  panes: {len(panes)}")
    for pane in panes:
        marker = "*" if pane["active"] else " "
        print(
            f"  {marker} {session}:{pane['window_index']}.{pane['pane_index']} "
            f"{pane['pane_id']} {pane['command']} \"{pane['title']}\""
        )
    if args.run:
        print(f"initial command sent: {args.run}")
    if args.attach:
        os.execvp("tmux", ["tmux", "-S", str(socket), "attach", "-t", session])
    return 0


def list_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    registry_file = registry_path(root)
    registry = load_registry(registry_file)
    if not socket.exists():
        registry_sessions = sorted((registry.get("sessions") or {}).keys())
        if registry_sessions:
            print(f"Project tmux socket is missing but registry has sessions at {registry_file}:")
            for name in registry_sessions:
                print(f"- {name}")
            print(f"Run {user_command(root, 'doctor')} to diagnose stale registry/socket state.")
            return 1
        print(f"No project tmux socket found at {socket}")
        print(f"Start one with {user_command(root, 'launch --purpose <purpose>')}")
        return 0
    sessions = list_sessions(socket)
    if not sessions:
        print(f"No live tmux sessions found at {socket}")
        return 0

    print(f"Socket: {socket}")
    for sess in sessions:
        name = sess["name"]
        panes = list_panes(socket, name)
        reg = registry.get("sessions", {}).get(name, {})
        purpose = reg.get("purpose", "")
        print(
            f"- {name}  windows={sess['windows']}  panes={len(panes)}  "
            f"attached={'yes' if sess['attached'] else 'no'}  purpose={purpose}"
        )
    return 0


def report_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    registry = load_registry(registry_path(root))
    if not socket.exists() and not (registry.get("sessions") or {}):
        print(f"Project root: {root}")
        print(f"Socket: {socket} (missing)")
        print("Live sessions: 0")
        print(f"Start one with {user_command(root, 'launch --purpose <purpose>')}")
        return 0
    print_report(root, socket, registry, lines=args.lines)
    return 0


def status_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    registry = load_registry(registry_path(root))
    session = args.session
    probe = try_tmux(socket, ["has-session", "-t", session])
    if not probe["ok"]:
        message = (probe["stdout"] + probe["stderr"]).strip()
        if classify_tmux_failure(socket, message) == "session-not-found":
            print(f"Session not found: {session}")
            return 1
        raise TmuxError(probe["cmd"], probe["returncode"], probe["stdout"], probe["stderr"])
    if not session_exists(socket, session):
        print(f"Session not found: {session}")
        return 1
    sess = next((s for s in list_sessions(socket) if s["name"] == session), None)
    panes = list_panes(socket, session)
    reg = registry.get("sessions", {}).get(session, {})
    print(f"Session: {session}")
    print(f"Socket: {socket}")
    print(f"Purpose: {reg.get('purpose', '')}")
    print(f"Cwd: {reg.get('cwd', '')}")
    print(f"Attach: {user_command(root, f'attach {session}')}")
    print(f"Tmux attach: tmux -S {socket} attach -t {session}")
    print(f"Windows: {sess['windows'] if sess else len({p['window_index'] for p in panes})}")
    for pane in panes:
        marker = "*" if pane["active"] else " "
        target = f"{session}:{pane['window_index']}.{pane['pane_index']}"
        pane_log = reg.get("logs", {}).get(target, {})
        print(f"{marker} {target} {pane['pane_id']} {pane['command']} \"{pane['title']}\" pipe={'yes' if pane.get('pipe') else 'no'}")
        if pane_log.get("path"):
            print(f"    log: {pane_log['path']}")
        sample = tail_lines(capture_pane(socket, target, lines=args.lines), limit=8)
        if sample.strip():
            for line in sample.splitlines():
                print(f"    {line}")
    return 0


def send_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    target = target_for_args(socket, args.session, args.pane)
    send_text(socket, target, args.text)
    if args.enter:
        run_tmux(socket, ["send-keys", "-t", target, "Enter"])
    return 0


def keys_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    target = args.pane or args.session
    run_tmux(socket, ["send-keys", "-t", target, *args.keys])
    return 0


def read_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    target = args.pane or args.session
    start: str | int | None
    if args.all:
        start = "-"
    elif args.start is not None:
        start = args.start
    else:
        start = None
    output = capture_pane(
        socket,
        target,
        lines=args.lines,
        start=start,
        end=args.end,
        join=not args.no_join,
        ansi=args.ansi,
    )
    formatted = format_lines(output, number=args.number)
    print(formatted, end="")
    if formatted and not formatted.endswith("\n"):
        print()
    return 0


def dump_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    target = args.pane or args.session
    start: str | int | None = "-" if args.all else None
    output = capture_pane(
        socket,
        target,
        lines=args.lines,
        start=start,
        join=not args.no_join,
        ansi=args.ansi,
    )
    output_path = Path(args.output).expanduser() if args.output else None
    if output_path is None:
        safe_target = slugify(target.replace(":", "-").replace(".", "-"))
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = root / ".agent" / "tmux.d" / "dumps" / f"{safe_target}-{timestamp}.txt"
    if not output_path.is_absolute():
        output_path = root / output_path
    ensure_parent(output_path)
    output_path.write_text(output)
    print(output_path)
    return 0


def search_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    flags = re.MULTILINE | (re.IGNORECASE if args.ignore_case else 0)
    pattern = re.compile(args.pattern, flags)
    targets: list[str] = []
    if args.all_panes:
        for sess in list_sessions(socket):
            for pane in list_panes(socket, sess["name"]):
                targets.append(f"{sess['name']}:{pane['window_index']}.{pane['pane_index']}")
    else:
        if not args.pane and not args.session:
            raise SystemExit("search requires a session, --pane, or --all-panes")
        targets.append(args.pane or args.session)

    any_match = False
    for target in targets:
        text = capture_pane(socket, target, lines=args.lines, start="-" if args.all else None)
        lines = text.splitlines()
        matches = [index for index, line in enumerate(lines) if pattern.search(line)]
        if not matches:
            continue
        any_match = True
        print(f"== {target} ==")
        for match_index in matches[: args.max_matches]:
            start = max(0, match_index - args.context)
            end = min(len(lines), match_index + args.context + 1)
            for index in range(start, end):
                prefix = ">" if index == match_index else " "
                print(f"{prefix} {index + 1:>5}  {lines[index]}")
            print()
    return 0 if any_match else 1


def wait_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    target = args.pane or args.session
    flags = re.MULTILINE | (re.IGNORECASE if args.ignore_case else 0)
    pattern = re.compile(args.pattern, flags)
    deadline = time.monotonic() + args.timeout
    last_text = ""
    while True:
        last_text = capture_pane(socket, target, lines=args.lines)
        if pattern.search(last_text):
            if not args.quiet:
                print(f"matched: {args.pattern}")
                print(tail_lines(last_text, limit=args.tail))
            return 0
        if time.monotonic() >= deadline:
            if not args.quiet:
                print(f"timeout waiting for: {args.pattern}")
                print(tail_lines(last_text, limit=args.tail))
            return 1
        time.sleep(args.interval)


def prompt_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    target = target_for_args(socket, args.session, args.pane)
    profile_name, profile = resolve_profile(args.agent)
    send_text(socket, target, args.text)
    if args.submit:
        send_profile_action(socket, target, profile, "submit")
    if not args.quiet:
        print(f"prompt sent: target={target} profile={profile_name} submitted={'yes' if args.submit else 'no'}")
    return 0


def action_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    target = target_for_args(socket, args.session, args.pane)
    profile_name, profile = resolve_profile(args.agent)
    send_profile_action(socket, target, profile, args.action)
    if not args.quiet:
        print(f"action sent: target={target} profile={profile_name} action={args.action}")
    return 0


def profiles_cmd(args: argparse.Namespace) -> int:
    if args.agent:
        profile_name, profile = resolve_profile(args.agent)
        print(f"{profile_name}")
        print(f"  aliases: {', '.join(profile.get('aliases', []))}")
        print(f"  actions: {', '.join(sorted(profile.get('actions', {})))}")
        print(f"  notes: {profile.get('notes', '')}")
        for action, keys in sorted(profile.get("actions", {}).items()):
            print(f"    {action}: {' '.join(keys)}")
        return 0
    for profile_name, profile in sorted(AGENT_PROFILES.items()):
        aliases = ", ".join(profile.get("aliases", []))
        print(f"{profile_name}: actions={', '.join(sorted(profile.get('actions', {})))} aliases={aliases}")
    return 0


def log_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    registry_file = registry_path(root)
    registry = load_registry(registry_file)
    target = target_for_args(socket, args.session, getattr(args, "pane", None))
    session = session_name_from_target(args.session, target)

    if args.log_action == "start":
        output_path = Path(args.output).expanduser() if args.output else default_log_file(root, target)
        if not output_path.is_absolute():
            output_path = root / output_path
        start_transcript(socket, target, output_path)
        update_log_registry(
            registry,
            session,
            target,
            {"path": str(output_path), "started_at": now_iso(), "stopped_at": None},
        )
        save_registry(registry_file, registry)
        print(f"log started: {target}")
        print(output_path)
        return 0

    if args.log_action == "stop":
        stop_transcript(socket, target)
        update_log_registry(registry, session, target, {"stopped_at": now_iso()})
        save_registry(registry_file, registry)
        print(f"log stopped: {target}")
        return 0

    panes = list_panes(socket, session)
    reg = registry.get("sessions", {}).get(session, {})
    print(f"Session: {session}")
    for pane in panes:
        pane_target = f"{session}:{pane['window_index']}.{pane['pane_index']}"
        if args.pane and pane_target != args.pane:
            continue
        pane_log = reg.get("logs", {}).get(pane_target, {})
        print(f"- {pane_target} pipe={'yes' if pane.get('pipe') else 'no'}")
        if pane_log.get("path"):
            print(f"  log: {pane_log['path']}")
            if pane_log.get("started_at"):
                print(f"  started_at: {pane_log['started_at']}")
            if pane_log.get("stopped_at"):
                print(f"  stopped_at: {pane_log['stopped_at']}")
    return 0


def doctor_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    registry_file = registry_path(root)
    registry: dict[str, Any] = {}
    registry_error = None
    try:
        registry = load_registry(registry_file)
    except Exception as exc:
        registry_error = str(exc)

    registry_sessions = sorted((registry.get("sessions") or {}).keys())
    probe = try_tmux(socket, [
        "list-sessions",
        "-F",
        "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created}\t#{session_id}",
    ])
    live_sessions: list[dict[str, Any]] = []
    issues: list[str] = []
    if probe["ok"]:
        for line in probe["stdout"].splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            live_sessions.append({"name": parts[0], "raw": line})
    else:
        message = (probe["stdout"] + probe["stderr"]).strip()
        issues.append(classify_tmux_failure(socket, message))

    live_names = sorted(session["name"] for session in live_sessions)
    missing_live = [name for name in registry_sessions if name not in live_names]
    unregistered_live = [name for name in live_names if name not in registry_sessions]
    if registry_error:
        issues.append("registry-unreadable")
    if registry.get("project_root") and Path(registry["project_root"]) != root:
        issues.append("registry-project-root-mismatch")
    if registry.get("socket") and Path(registry["socket"]) != socket:
        issues.append("registry-socket-mismatch")
    if missing_live:
        issues.append("registered-session-not-live")
    if unregistered_live:
        issues.append("live-session-not-registered")
    if not socket.exists() and registry_sessions:
        issues.append("missing-socket-with-registered-sessions")
    if not issues and live_sessions:
        issues.append("ok-live-sessions")
    elif not issues:
        issues.append("ok-no-live-sessions")

    event = {
        "tool": "agent-tmux",
        "command": "doctor",
        "question": args.question,
        "context": args.context,
        "cwd": str(Path.cwd()),
        "resolved_project_root": str(root),
        "socket": str(socket),
        "socket_exists": socket.exists(),
        "registry_path": str(registry_file),
        "registry_exists": registry_file.exists(),
        "registry_error": registry_error,
        "registry_sessions": registry_sessions,
        "live_sessions": live_names,
        "missing_live": missing_live,
        "unregistered_live": unregistered_live,
        "issues": issues,
        "tmux_probe": probe,
    }
    log_path = None if args.no_log else append_doctor_event(root, event)

    print(f"Project root: {root}")
    print(f"Current directory: {Path.cwd()}")
    print(f"Socket: {socket} ({'exists' if socket.exists() else 'missing'})")
    print(f"Registry: {registry_file} ({'exists' if registry_file.exists() else 'missing'})")
    if registry_error:
        print(f"Registry error: {registry_error}")
    print(f"Registry sessions: {', '.join(registry_sessions) if registry_sessions else '(none)'}")
    if probe["ok"]:
        print(f"Live sessions: {', '.join(live_names) if live_names else '(none)'}")
    else:
        message = (probe["stdout"] + probe["stderr"]).strip()
        print(f"tmux probe failed: {classify_tmux_failure(socket, message)}")
        if message:
            print(f"tmux error: {message}")
    if missing_live:
        print(f"Registered but not live: {', '.join(missing_live)}")
    if unregistered_live:
        print(f"Live but not registered: {', '.join(unregistered_live)}")
    print(f"Issues: {', '.join(issues)}")
    if args.show_log_path and log_path:
        print(f"Doctor event log: {log_path}")
    return 0 if all(issue.startswith("ok-") for issue in issues) else 1


def attach_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    os.execvp("tmux", ["tmux", "-S", str(socket), "attach", "-t", args.session])
    return 0


def interrupt_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    target = args.pane or args.session
    run_tmux(socket, ["send-keys", "-t", target, "C-c"])
    return 0


def kill_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    run_tmux(socket, ["kill-session", "-t", args.session])
    registry_file = registry_path(root)
    registry = load_registry(registry_file)
    remove_registry_entry(registry, args.session)
    save_registry(registry_file, registry)
    return 0


def split_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    target = args.session if args.target is None else args.target
    cmd = ["split-window", "-t", target]
    if args.horizontal:
        cmd.append("-h")
    else:
        cmd.append("-v")
    if args.cwd:
        cmd.extend(["-c", str(root)])
    if args.run:
        cmd.extend(["bash", "-lc", args.run])
    run_tmux(socket, cmd)
    return 0


def move_window_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    run_tmux(socket, ["move-window", "-s", args.source, "-t", args.target])
    return 0


def join_pane_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    cmd = ["join-pane", "-s", args.source, "-t", args.target]
    if args.horizontal:
        cmd.append("-h")
    elif args.vertical:
        cmd.append("-v")
    run_tmux(socket, cmd)
    return 0


def install_wrapper_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    wrapper = root / ".agent" / "tmux"
    if wrapper.exists() and not args.force:
        print(f"Wrapper already exists: {wrapper}")
        print("Use --force to overwrite it.")
        return 1
    ensure_parent(wrapper)
    wrapper.write_text(WRAPPER)
    wrapper.chmod(0o755)
    print(f"Installed wrapper: {wrapper}")
    print("Example: .agent/tmux report")
    return 0


def install_bin_cmd(args: argparse.Namespace) -> int:
    source = Path(__file__).resolve()
    target_dir = Path(args.dir).expanduser().resolve()
    target = target_dir / args.name
    ensure_parent(target)
    shutil.copy2(source, target)
    target.chmod(0o755)
    print(f"Installed CLI: {target}")
    print(f"Example: {args.name} report")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Manage project-local tmux sessions for shared human/agent terminals.")
    p.add_argument("--socket", help="Override tmux socket path")
    p.add_argument("--cwd", help="Project directory to use instead of the current directory")

    sub = p.add_subparsers(dest="cmd", required=True)

    def command(name: str, **kwargs: Any) -> argparse.ArgumentParser:
        cmd = sub.add_parser(name, **kwargs)
        cmd.add_argument("--socket", default=argparse.SUPPRESS, help="Override tmux socket path")
        cmd.add_argument("--cwd", default=argparse.SUPPRESS, help="Project directory to use instead of the current directory")
        return cmd

    launch_cmd = command("launch", help="Start or reuse a session")
    launch_cmd.add_argument("--session", help="Session name to create or reuse")
    launch_cmd.add_argument("--purpose", help="Short purpose label stored in the registry")
    launch_cmd.add_argument("--run", help="Literal command to send after launch")
    launch_cmd.add_argument("--run-delay", type=float, default=0.5, help="Seconds to wait before sending --run to a newly started shell")
    launch_cmd.add_argument("--log", action="store_true", help="Start transcript logging for the active pane")
    launch_cmd.add_argument("--log-output", help="Transcript path; defaults under .agent/tmux.d/logs/")
    launch_cmd.add_argument("--attach", action="store_true", help="Attach after launch")
    launch_cmd.set_defaults(func=launch)

    list_p = command("list", help="List live sessions")
    list_p.set_defaults(func=list_cmd)

    report = command("report", help="Show a detailed report of all live sessions")
    report.add_argument("--lines", type=int, default=60, help="Capture depth for visible output")
    report.set_defaults(func=report_cmd)

    status = command("status", help="Show detailed status for one session")
    status.add_argument("session")
    status.add_argument("--lines", type=int, default=60)
    status.set_defaults(func=status_cmd)

    send = command("send", help="Send literal text to the active pane of a session")
    send.add_argument("session")
    send.add_argument("text")
    send.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    send.add_argument("--no-enter", action="store_true", help="Do not press Enter after sending")
    send.set_defaults(func=send_cmd)

    keys = command("keys", help="Send raw tmux keys")
    keys.add_argument("session")
    keys.add_argument("keys", nargs="+")
    keys.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    keys.set_defaults(func=keys_cmd)

    read = command("read", help="Capture pane history")
    read.add_argument("session")
    read.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    read.add_argument("--lines", type=int, default=200, help="Tail this many captured lines unless --start or --all is used")
    read.add_argument("--start", help="tmux capture-pane start line for explicit history slices, e.g. -500 or 0")
    read.add_argument("--end", help="tmux capture-pane end line")
    read.add_argument("--all", action="store_true", help="Capture full available history")
    read.add_argument("--no-join", action="store_true", help="Do not join wrapped lines")
    read.add_argument("--ansi", action="store_true", help="Preserve ANSI escape sequences")
    read.add_argument("--number", action="store_true", help="Prefix captured lines with line numbers")
    read.set_defaults(func=read_cmd)

    dump = command("dump", help="Write pane history to a file")
    dump.add_argument("session")
    dump.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    dump.add_argument("--lines", type=int, default=2000, help="Tail this many captured lines unless --all is used")
    dump.add_argument("--all", action="store_true", help="Dump full available history")
    dump.add_argument("--no-join", action="store_true", help="Do not join wrapped lines")
    dump.add_argument("--ansi", action="store_true", help="Preserve ANSI escape sequences")
    dump.add_argument("--output", help="Output file path; defaults under .agent/tmux.d/dumps/")
    dump.set_defaults(func=dump_cmd)

    search = command("search", help="Search pane history")
    search.add_argument("session", nargs="?", help="Session or target to search")
    search.add_argument("pattern")
    search.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    search.add_argument("--all-panes", action="store_true", help="Search all panes in the project tmux server")
    search.add_argument("--all", action="store_true", help="Search full available history")
    search.add_argument("--lines", type=int, default=5000, help="Tail this many captured lines unless --all is used")
    search.add_argument("--context", type=int, default=2)
    search.add_argument("--max-matches", type=int, default=20)
    search.add_argument("--ignore-case", action="store_true")
    search.set_defaults(func=search_cmd)

    wait = command("wait", help="Wait until pane history matches a pattern")
    wait.add_argument("session")
    wait.add_argument("pattern")
    wait.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    wait.add_argument("--lines", type=int, default=500, help="Tail this many captured lines on each poll")
    wait.add_argument("--timeout", type=float, default=30.0)
    wait.add_argument("--interval", type=float, default=1.0)
    wait.add_argument("--tail", type=int, default=12, help="Lines to print when done")
    wait.add_argument("--ignore-case", action="store_true")
    wait.add_argument("--quiet", action="store_true")
    wait.set_defaults(func=wait_cmd)

    prompt = command("prompt", help="Send text to a terminal agent and submit using an agent profile")
    prompt.add_argument("session")
    prompt.add_argument("text")
    prompt.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    prompt.add_argument("--agent", default="generic", help="Agent profile: claude, codex, gemini, generic")
    prompt.add_argument("--no-submit", dest="submit", action="store_false", help="Paste text but do not submit")
    prompt.add_argument("--quiet", action="store_true")
    prompt.set_defaults(func=prompt_cmd, submit=True)

    action = command("action", help="Send a named action from an agent profile")
    action.add_argument("session")
    action.add_argument("action", help="Profile action, e.g. submit, interrupt, eof, escape, clear")
    action.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    action.add_argument("--agent", default="generic", help="Agent profile: claude, codex, gemini, generic")
    action.add_argument("--quiet", action="store_true")
    action.set_defaults(func=action_cmd)

    profiles = command("profiles", help="List terminal-agent interaction profiles")
    profiles.add_argument("--agent", help="Show one profile")
    profiles.set_defaults(func=profiles_cmd)

    doctor = command("doctor", help="Diagnose project tmux socket, registry, and live-session mismatches")
    doctor.add_argument("--question", help="Short troubleshooting question to record in the diagnostic event")
    doctor.add_argument("--context", help="Short context to record in the diagnostic event")
    doctor.add_argument("--no-log", action="store_true", help="Do not append a structured doctor event")
    doctor.add_argument("--show-log-path", action="store_true", help="Print the structured doctor log path")
    doctor.set_defaults(func=doctor_cmd)

    log = command("log", help="Manage pane transcript logging via tmux pipe-pane")
    log_sub = log.add_subparsers(dest="log_action", required=True)
    log_start = log_sub.add_parser("start", help="Start transcript logging for a pane")
    log_start.add_argument("session")
    log_start.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    log_start.add_argument("--output", help="Transcript path; defaults under .agent/tmux.d/logs/")
    log_start.set_defaults(func=log_cmd)
    log_stop = log_sub.add_parser("stop", help="Stop transcript logging for a pane")
    log_stop.add_argument("session")
    log_stop.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    log_stop.set_defaults(func=log_cmd)
    log_status = log_sub.add_parser("status", help="Show transcript logging status")
    log_status.add_argument("session")
    log_status.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    log_status.set_defaults(func=log_cmd)

    attach = command("attach", help="Attach to a session")
    attach.add_argument("session")
    attach.set_defaults(func=attach_cmd)

    interrupt = command("interrupt", help="Send Ctrl-C to a session or pane")
    interrupt.add_argument("session")
    interrupt.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    interrupt.set_defaults(func=interrupt_cmd)

    kill = command("kill", help="Kill a session and remove it from the registry")
    kill.add_argument("session")
    kill.set_defaults(func=kill_cmd)

    split = command("split", help="Split a pane inside a session")
    split.add_argument("session")
    split.add_argument("--target", help="Explicit pane target")
    split.add_argument("--horizontal", action="store_true", help="Split horizontally")
    split.add_argument("--vertical", action="store_true", help="Split vertically")
    split.add_argument("--run", help="Command to start in the new pane")
    split.set_defaults(func=split_cmd)

    move = command("move-window", help="Move a window between sessions")
    move.add_argument("source", help="Source window target, e.g. session:0")
    move.add_argument("target", help="Target window target, e.g. other-session:1")
    move.set_defaults(func=move_window_cmd)

    join = command("join-pane", help="Join a pane into another window")
    join.add_argument("source", help="Source pane target, e.g. session:0.1")
    join.add_argument("target", help="Target pane target, e.g. session:0.0")
    join.add_argument("--horizontal", action="store_true")
    join.add_argument("--vertical", action="store_true")
    join.set_defaults(func=join_pane_cmd)

    install_wrapper = command("install-wrapper", help="Install the dumb project wrapper at .agent/tmux")
    install_wrapper.add_argument("--force", action="store_true", help="Overwrite an existing wrapper")
    install_wrapper.set_defaults(func=install_wrapper_cmd)

    install_bin = command("install-bin", help="Install this CLI as agent-tmux")
    install_bin.add_argument("--dir", default="~/.local/bin", help="Destination directory")
    install_bin.add_argument("--name", default="agent-tmux", help="Installed command name")
    install_bin.set_defaults(func=install_bin_cmd)

    return p


def main() -> int:
    args = parser().parse_args()
    if getattr(args, "cmd", None) == "launch":
        try:
            return launch(args)
        except TmuxError as exc:
            root = project_root(Path(args.cwd) if getattr(args, "cwd", None) else None)
            print_tmux_error(root, socket_path(root, getattr(args, "socket", None)), exc, context="launch")
            return 2
    if getattr(args, "cmd", None) == "send":
        if args.no_enter:
            args.enter = False
        else:
            args.enter = True
    try:
        return args.func(args)
    except TmuxError as exc:
        root = project_root(Path(args.cwd) if getattr(args, "cwd", None) else None)
        print_tmux_error(root, socket_path(root, getattr(args, "socket", None)), exc, context=getattr(args, "cmd", "command"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
