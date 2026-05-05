#!/usr/bin/env python3
"""Project-local tmux session manager for shared human/agent terminals."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def run_tmux(socket: Path, args: list[str], *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["tmux", "-S", str(socket), *args]
    return subprocess.run(cmd, text=True, capture_output=capture, check=check)


def tmux_output(socket: Path, args: list[str]) -> str:
    try:
        result = run_tmux(socket, args, capture=True)
        return result.stdout
    except subprocess.CalledProcessError as exc:
        return (exc.stdout or "") + (exc.stderr or "")


def session_exists(socket: Path, session: str) -> bool:
    try:
        run_tmux(socket, ["has-session", "-t", session], capture=True)
        return True
    except subprocess.CalledProcessError:
        return False


def list_sessions(socket: Path) -> list[dict[str, Any]]:
    try:
        out = tmux_output(socket, [
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created}\t#{session_id}",
        ])
    except Exception:
        return []
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
        "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t#{pane_active}\t#{pane_current_command}\t#{pane_title}\t#{pane_pid}",
    ])
    panes = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        session_name, window_index, pane_index, pane_id, active, command, title, pid = parts[:8]
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
            }
        )
    return panes


def capture_pane(socket: Path, target: str, lines: int = 80) -> str:
    return tmux_output(socket, ["capture-pane", "-t", target, "-p", "-S", f"-{lines}", "-J"])


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
            print(
                f"    {marker} {target} {pane['pane_id']} {pane['command']} "
                f'"{pane["title"]}" pid={pane["pid"]}'
            )
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

    if args.run:
        run_tmux(socket, ["send-keys", "-t", session, "-l", args.run])
        run_tmux(socket, ["send-keys", "-t", session, "Enter"])

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
    print_report(root, socket, registry, lines=args.lines)
    return 0


def status_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    registry = load_registry(registry_path(root))
    session = args.session
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
        print(f"{marker} {target} {pane['pane_id']} {pane['command']} \"{pane['title']}\"")
        sample = tail_lines(capture_pane(socket, target, lines=args.lines), limit=8)
        if sample.strip():
            for line in sample.splitlines():
                print(f"    {line}")
    return 0


def send_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    if args.pane:
        target = args.pane
    else:
        panes = list_panes(socket, args.session)
        target = active_pane_target(args.session, panes)
    run_tmux(socket, ["send-keys", "-t", target, "-l", args.text])
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
    print(capture_pane(socket, target, lines=args.lines), end="")
    return 0


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
    read.add_argument("--lines", type=int, default=200)
    read.set_defaults(func=read_cmd)

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
        return launch(args)
    if getattr(args, "cmd", None) == "send":
        if args.no_enter:
            args.enter = False
        else:
            args.enter = True
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
