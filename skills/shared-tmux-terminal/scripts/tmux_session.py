#!/usr/bin/env python3
"""Project-local tmux session manager for shared human/agent terminals."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
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


TMUX_PROFILE_COMMANDS: list[list[str]] = [
    ["set-option", "-g", "mouse", "on"],
    ["set-option", "-g", "history-limit", "50000"],
    ["set-option", "-g", "display-panes-time", "3000"],
    ["set-option", "-g", "status-interval", "5"],
    ["set-option", "-g", "status-left-length", "40"],
    ["set-option", "-g", "status-right-length", "80"],
    ["set-option", "-g", "status-left", "[#S] "],
    ["set-option", "-g", "status-right", "#{pane_id} #{pane_current_command} %H:%M"],
    ["set-window-option", "-g", "pane-border-status", "top"],
    ["set-window-option", "-g", "pane-border-format", "#P #{pane_id} #{pane_current_command}"],
    ["bind-key", "S", "choose-tree", "-Zs"],
    ["bind-key", "W", "choose-tree", "-Zw"],
    ["bind-key", "P", "display-panes"],
]


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


def marks_path(root: Path) -> Path:
    return root / ".agent" / "tmux.d" / "marks.json"


def events_dir(root: Path) -> Path:
    return root / ".agent" / "tmux.d" / "events" / "events"


def events_ack_dir(root: Path) -> Path:
    return root / ".agent" / "tmux.d" / "events" / "acks"


def board_root(root: Path) -> Path:
    return root / ".agent" / "board"


def hooks_dir(root: Path, session: str) -> Path:
    return root / ".agent" / "tmux.d" / "hooks" / slugify(session)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


@contextlib.contextmanager
def file_lock(path: Path):
    ensure_parent(path)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def write_json_atomic(path: Path, data: dict[str, Any], *, indent: int | None = 2) -> None:
    atomic_write_text(path, json.dumps(data, indent=indent, sort_keys=True) + "\n")


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
    write_json_atomic(path, data)


def load_marks(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "marks": {},
            "latest_by_target": {},
        }
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("marks file is not a JSON object")
    data.setdefault("schema_version", 1)
    data.setdefault("marks", {})
    data.setdefault("latest_by_target", {})
    return data


def save_marks(path: Path, data: dict[str, Any]) -> None:
    write_json_atomic(path, data)


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


def unique_record_id(prefix: str, *parts: str | None) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    clean_parts = [slugify(part) for part in parts if part]
    clean_parts = [part for part in clean_parts if part]
    suffix = uuid.uuid4().hex[:8]
    return "_".join([prefix, timestamp, *clean_parts, suffix])


def emit_event(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    record = {
        "schema_version": 1,
        "id": event.get("id") or unique_record_id("evt", event.get("session"), event.get("kind")),
        "kind": event.get("kind") or "event",
        "session": event.get("session"),
        "agent": event.get("agent"),
        "source": event.get("source") or "agent_tmux",
        "confidence": event.get("confidence") or "explicit",
        "summary": event.get("summary") or "",
        "created_at": event.get("created_at") or now_iso(),
        "read_command": event.get("read_command"),
    }
    for key, value in event.items():
        if key not in record and value is not None:
            record[key] = value
    write_json_atomic(events_dir(root) / f"{record['id']}.json", record)
    return record


def load_event_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("id", path.stem)
    return data


def parse_kind_filter(kind: str | None) -> set[str] | None:
    if not kind:
        return None
    kinds = {part.strip() for part in kind.split(",") if part.strip()}
    return kinds or None


def list_events(
    root: Path,
    *,
    session: str | None = None,
    kind: str | None = None,
    topic: str | None = None,
    unread: bool = False,
    consumer: str | None = None,
) -> list[dict[str, Any]]:
    directory = events_dir(root)
    if not directory.exists():
        return []
    kinds = parse_kind_filter(kind)
    entries: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        event = load_event_file(path)
        if event is None:
            continue
        if not event_matches_filters(event, session=session, kinds=kinds, topic=topic):
            continue
        if unread and event_is_acked(root, event["id"], consumer):
            continue
        entries.append(event)
    return sorted(entries, key=lambda event: (str(event.get("created_at", "")), str(event.get("id", ""))))


def event_matches_filters(
    event: dict[str, Any],
    *,
    session: str | None = None,
    kinds: set[str] | None = None,
    topic: str | None = None,
) -> bool:
    if session and event.get("session") != session:
        return False
    if kinds and event.get("kind") not in kinds:
        return False
    if topic and event.get("topic") != topic:
        return False
    return True


def default_consumer() -> str:
    return slugify(os.environ.get("AGENT_TMUX_CONSUMER") or "manager")


def ack_path(root: Path, event_id: str, consumer: str | None = None) -> Path:
    return events_ack_dir(root) / slugify(consumer or default_consumer()) / f"{slugify(event_id)}.ack"


def event_is_acked(root: Path, event_id: str, consumer: str | None = None) -> bool:
    return ack_path(root, event_id, consumer).exists()


def ack_event(root: Path, event_id: str, consumer: str | None = None) -> Path:
    path = ack_path(root, event_id, consumer)
    atomic_write_text(path, json.dumps({"event_id": event_id, "consumer": consumer or default_consumer(), "acked_at": now_iso()}, sort_keys=True) + "\n")
    return path


def print_event(event: dict[str, Any], *, json_output: bool = False) -> None:
    if json_output:
        print(json.dumps(event, sort_keys=True))
        return
    print(f"{event.get('id')}  {event.get('kind')}  session={event.get('session') or '-'}  source={event.get('source')}")
    if event.get("summary"):
        print(f"  {event['summary']}")
    if event.get("read_command"):
        print(f"  read: {event['read_command']}")


def board_topic_dir(root: Path, topic: str) -> Path:
    return board_root(root) / "threads" / slugify(topic)


def board_message_path(root: Path, message_id: str) -> Path | None:
    for path in (board_root(root) / "threads").glob(f"*/{message_id}.md"):
        return path
    return None


def board_frontmatter_value(text: str, key: str) -> str:
    if not text.startswith("---\n"):
        return ""
    for line in text.splitlines()[1:80]:
        if line == "---":
            break
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


def list_board_messages(root: Path, *, topic: str | None = None) -> list[dict[str, str]]:
    base = board_root(root) / "threads"
    if not base.exists():
        return []
    paths = sorted((board_topic_dir(root, topic).glob("*.md") if topic else base.glob("*/*.md")))
    messages: list[dict[str, str]] = []
    for path in paths:
        text = path.read_text(errors="replace")
        messages.append(
            {
                "id": path.stem,
                "topic": board_frontmatter_value(text, "topic") or path.parent.name,
                "from": board_frontmatter_value(text, "from") or "",
                "session": board_frontmatter_value(text, "session") or "",
                "created_at": board_frontmatter_value(text, "created_at") or "",
                "path": str(path),
            }
        )
    return sorted(messages, key=lambda message: (message["created_at"], message["id"]))


def hook_ingest_command(root: Path, agent: str, session: str, *, quiet: bool = False) -> str:
    exe = Path(__file__).resolve()
    parts = [
        str(exe),
        "--cwd",
        str(root),
        "hooks",
        "ingest",
        "--agent",
        agent,
        "--session",
        session,
    ]
    if quiet:
        parts.append("--quiet")
    return " ".join(shlex.quote(part) for part in parts)


def claude_hook_settings(root: Path, session: str) -> dict[str, Any]:
    command = hook_ingest_command(root, "claude", session)
    hook = {"type": "command", "command": command}
    return {
        "hooks": {
            "Stop": [{"hooks": [hook]}],
            "SubagentStop": [{"hooks": [hook]}],
            "StopFailure": [{"hooks": [hook]}],
            "Notification": [{"hooks": [hook]}],
            "PermissionRequest": [{"hooks": [hook]}],
        }
    }


CODEX_HOOK_EVENTS = ["SessionStart", "UserPromptSubmit", "Stop", "PermissionRequest"]


def toml_string(value: str) -> str:
    return json.dumps(value)


def codex_hooks_toml(root: Path, session: str) -> str:
    command = hook_ingest_command(root, "codex", session, quiet=True)
    hook = f'{{type="command", command={toml_string(command)}}}'
    group = f"{{hooks=[{hook}]}}"
    entries = [f"{event}=[{group}]" for event in CODEX_HOOK_EVENTS]
    return "hooks={" + ",".join(entries) + "}"


def write_hook_settings(root: Path, agent: str, session: str) -> tuple[Path | None, str, str | None, dict[str, Any]]:
    profile_name, _profile = resolve_profile(agent)
    if profile_name == "claude":
        settings_path = hooks_dir(root, session) / "claude-settings.json"
        write_json_atomic(settings_path, claude_hook_settings(root, session))
        return settings_path, "native-hook", None, {"mode": "settings-file"}
    if profile_name == "codex":
        config_value = codex_hooks_toml(root, session)
        config_path = hooks_dir(root, session) / "codex-hooks.toml"
        atomic_write_text(config_path, config_value + "\n")
        return config_path, "native-hook", None, {"mode": "wrapper-cli-config", "config_path": str(config_path)}
    return None, "unsupported-agent", f"native hook wiring is not implemented for agent profile: {profile_name}", {}


def wire_claude_run_command(run: str | None, settings_path: Path | None) -> tuple[str | None, bool, str | None]:
    if not run or settings_path is None:
        return run, False, "no run command to wire" if not run else "no settings path"
    try:
        tokens = shlex.split(run)
    except ValueError as exc:
        return run, False, f"could not parse --run for hook wiring: {exc}"
    if not tokens or Path(tokens[0]).name != "claude":
        return run, False, "run command is not a simple claude invocation"
    if any(token == "--settings" or token.startswith("--settings=") for token in tokens):
        return run, False, "run command already contains --settings"
    tokens[1:1] = ["--settings", str(settings_path)]
    return shlex.join(tokens), True, None


def run_has_codex_hooks_override(tokens: list[str]) -> bool:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-c", "--config"} and index + 1 < len(tokens):
            if tokens[index + 1].startswith("hooks"):
                return True
            index += 2
            continue
        if token.startswith("--config=") and token.split("=", 1)[1].startswith("hooks"):
            return True
        index += 1
    return False


def write_codex_wrapper(root: Path, session: str, codex_program: str, config_path: Path) -> Path:
    wrapper_path = hooks_dir(root, session) / "codex-with-hooks"
    script = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"exec {shlex.quote(codex_program)} -c \"$(cat {shlex.quote(str(config_path))})\" \"$@\"",
            "",
        ]
    )
    atomic_write_text(wrapper_path, script)
    wrapper_path.chmod(0o755)
    return wrapper_path


def wire_codex_run_command(root: Path, session: str, run: str | None, config_path: Path | None) -> tuple[str | None, bool, str | None]:
    if not run or not config_path:
        return run, False, "no run command to wire" if not run else "no Codex hooks config"
    try:
        tokens = shlex.split(run)
    except ValueError as exc:
        return run, False, f"could not parse --run for hook wiring: {exc}"
    if not tokens or Path(tokens[0]).name != "codex":
        return run, False, "run command is not a simple codex invocation"
    if run_has_codex_hooks_override(tokens):
        return run, False, "run command already configures hooks"
    wrapper_path = write_codex_wrapper(root, session, tokens[0], config_path)
    tokens[0] = str(wrapper_path)
    return shlex.join(tokens), True, None


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


def infer_current_tmux_session(socket: Path) -> str | None:
    pane_id = os.environ.get("TMUX_PANE")
    if not pane_id:
        return None
    try:
        out = tmux_output(socket, ["list-panes", "-a", "-F", "#{session_name}\t#{pane_id}"])
    except TmuxError:
        return None
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            session_name, current_pane_id = line.split("\t", 1)
        except ValueError:
            continue
        if current_pane_id == pane_id:
            return session_name
    return None


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


OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)", re.DOTALL)
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CURSOR_RIGHT_RE = re.compile(r"\x1b\[(\d*)C")
CURSOR_LEFT_RE = re.compile(r"\x1b\[(\d*)D")


def strip_backspaces(text: str) -> str:
    chars: list[str] = []
    for char in text:
        if char == "\b":
            if chars:
                chars.pop()
            continue
        chars.append(char)
    return "".join(chars)


def normalize_transcript(text: str, *, ansi: bool = False) -> str:
    if not ansi:
        text = OSC_RE.sub("", text)
        text = CURSOR_RIGHT_RE.sub(lambda match: " " * int(match.group(1) or "1"), text)
        text = CURSOR_LEFT_RE.sub(lambda match: "\b" * int(match.group(1) or "1"), text)
        text = ANSI_RE.sub("", text)
        text = strip_backspaces(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def read_file_from_offset(path: Path, offset: int, *, max_bytes: int | None = None) -> tuple[str, int, int]:
    if not path.exists():
        raise SystemExit(f"Transcript log not found: {path}")
    size = path.stat().st_size
    start = min(max(offset, 0), size)
    omitted = 0
    if max_bytes is not None and max_bytes > 0 and size - start > max_bytes:
        omitted = size - start - max_bytes
        start = size - max_bytes
    with path.open("rb") as handle:
        handle.seek(start)
        data = handle.read()
    return data.decode(errors="replace"), size, omitted


def resolve_registered_log(registry: dict[str, Any], session: str, target: str) -> Path | None:
    pane_log = registry.get("sessions", {}).get(session, {}).get("logs", {}).get(target, {})
    if pane_log.get("path") and not pane_log.get("stopped_at"):
        return Path(pane_log["path"])
    return None


def pane_for_target(socket: Path, session: str, target: str) -> dict[str, Any] | None:
    target_session = session_name_from_target(session, target)
    for pane in list_panes(socket, target_session):
        pane_target = f"{target_session}:{pane['window_index']}.{pane['pane_index']}"
        if pane_target == target:
            return pane
    return None


def ensure_transcript(
    root: Path,
    socket: Path,
    registry: dict[str, Any],
    session: str,
    target: str,
) -> tuple[Path, bool]:
    target_session = session_name_from_target(session, target)
    pane = pane_for_target(socket, target_session, target)
    if pane is None:
        raise SystemExit(f"Pane not found: {target}")

    log_path = resolve_registered_log(registry, target_session, target)
    if log_path is not None:
        if not log_path.is_absolute():
            log_path = root / log_path
        if not pane.get("pipe"):
            start_transcript(socket, target, log_path)
            update_log_registry(
                registry,
                target_session,
                target,
                {"path": str(log_path), "started_at": now_iso(), "stopped_at": None},
            )
            return log_path, True
        ensure_parent(log_path)
        if not log_path.exists():
            log_path.touch()
        return log_path, False

    if pane.get("pipe"):
        raise SystemExit(
            f"Pane {target} already has an unregistered tmux pipe. "
            "Stop it or start logging with agent-tmux before using marks."
        )

    log_path = default_log_file(root, target)
    start_transcript(socket, target, log_path)
    update_log_registry(
        registry,
        target_session,
        target,
        {"path": str(log_path), "started_at": now_iso(), "stopped_at": None},
    )
    return log_path, True


def unique_mark_id(marks: dict[str, Any], target: str, label: str | None) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_parts = ["m", timestamp, slugify(label or target)]
    base = "_".join(base_parts)
    candidate = base
    suffix = 2
    existing = marks.setdefault("marks", {})
    while candidate in existing:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def create_mark(
    root: Path,
    socket: Path,
    registry: dict[str, Any],
    session: str,
    target: str,
    *,
    label: str | None = None,
) -> tuple[str, dict[str, Any], bool]:
    registry_changed = False
    log_path, changed = ensure_transcript(root, socket, registry, session, target)
    registry_changed = registry_changed or changed
    ensure_parent(log_path)
    if not log_path.exists():
        log_path.touch()

    marks_file = marks_path(root)
    with file_lock(marks_file):
        marks = load_marks(marks_file)
        mark_id = unique_mark_id(marks, target, label)
        entry = {
            "id": mark_id,
            "label": label,
            "session": session_name_from_target(session, target),
            "target": target,
            "log_path": str(log_path),
            "offset": log_path.stat().st_size,
            "created_at": now_iso(),
        }
        marks.setdefault("marks", {})[mark_id] = entry
        marks.setdefault("latest_by_target", {})[target] = mark_id
        save_marks(marks_file, marks)
    return mark_id, entry, registry_changed


def resolve_mark(root: Path, mark_id: str) -> dict[str, Any]:
    marks = load_marks(marks_path(root))
    if mark_id == "latest":
        latest = marks.get("latest_by_target", {})
        if len(latest) != 1:
            raise SystemExit("Mark id 'latest' is ambiguous; pass an explicit mark id.")
        mark_id = next(iter(latest.values()))
    entry = marks.get("marks", {}).get(mark_id)
    if not entry:
        raise SystemExit(f"Mark not found: {mark_id}")
    return entry


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
    agent: str | None = None,
    events: dict[str, Any] | None = None,
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
            "agent": agent or entry.get("agent"),
            "socket": str(socket),
            "created_at": entry.get("created_at", now_iso()),
            "last_seen_at": now_iso(),
        }
    )
    if events is not None:
        entry["events"] = events
    sessions[session] = entry


def remove_registry_entry(registry: dict[str, Any], session: str) -> None:
    registry.get("sessions", {}).pop(session, None)


def save_registry_session(path: Path, registry: dict[str, Any], session: str) -> None:
    with file_lock(path):
        latest = load_registry(path)
        latest["schema_version"] = registry.get("schema_version", latest.get("schema_version", 1))
        latest["project_root"] = registry.get("project_root", latest.get("project_root"))
        latest["socket"] = registry.get("socket", latest.get("socket"))
        latest.setdefault("sessions", {})[session] = registry.get("sessions", {}).get(session, {})
        save_registry(path, latest)


def remove_registry_session(path: Path, session: str) -> None:
    with file_lock(path):
        registry = load_registry(path)
        remove_registry_entry(registry, session)
        save_registry(path, registry)


def launch(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    ensure_parent(socket)
    registry_file = registry_path(root)
    registry = load_registry(registry_file)

    session = args.session or slugify(f"{root.name}-{args.purpose or 'agent'}-{datetime.now().strftime('%H%M%S')}")
    effective_run = args.run
    events_info: dict[str, Any] | None = None
    hook_warning: str | None = None
    if args.require_events:
        args.events = True
    if args.events:
        if not args.agent:
            events_info = {"requested": True, "status": "missing-agent", "warning": "pass --agent to enable native hook wiring"}
            hook_warning = events_info["warning"]
        else:
            settings_path, status, warning, hook_config = write_hook_settings(root, args.agent, session)
            events_info = {"requested": True, "status": status, "agent": resolve_profile(args.agent)[0]}
            if settings_path is not None:
                events_info["settings_path"] = str(settings_path)
            if hook_config.get("mode"):
                events_info["mode"] = hook_config["mode"]
            if warning:
                events_info["warning"] = warning
                hook_warning = warning
            if settings_path is not None:
                if events_info["agent"] == "claude":
                    effective_run, wired, run_warning = wire_claude_run_command(args.run, settings_path)
                elif events_info["agent"] == "codex":
                    effective_run, wired, run_warning = wire_codex_run_command(root, session, args.run, settings_path)
                else:
                    wired, run_warning = False, f"native hook run wiring is not implemented for agent profile: {events_info['agent']}"
                events_info["run_wired"] = wired
                if run_warning:
                    events_info["run_warning"] = run_warning
                    hook_warning = run_warning
    if args.require_events:
        if not events_info:
            raise SystemExit("--require-events needs --events and --agent")
        if events_info.get("status") != "native-hook":
            raise SystemExit(f"--require-events failed: {events_info.get('warning') or events_info.get('status')}")
        if not events_info.get("run_wired"):
            reason = events_info.get("run_warning") or "native hook settings were not injected into the launch command"
            raise SystemExit(f"--require-events failed: {reason}")

    with file_lock(registry_file):
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

    if effective_run:
        if mode == "started" and args.run_delay > 0:
            time.sleep(args.run_delay)
        target = active_pane_target(session, list_panes(socket, session))
        send_text(socket, target, effective_run)
        run_tmux(socket, ["send-keys", "-t", target, "Enter"])

    update_registry_entry(
        registry,
        root,
        socket,
        session,
        purpose=args.purpose,
        cwd=str(root),
        run=effective_run,
        agent=args.agent,
        events=events_info,
    )
    save_registry_session(registry_file, registry, session)
    emit_event(
        root,
        {
            "kind": "session_started" if mode == "started" else "session_reused",
            "session": session,
            "agent": args.agent,
            "source": "agent_tmux",
            "confidence": "explicit",
            "summary": f"{mode}: {session}",
            "read_command": user_command(root, f"status {session}"),
        },
    )

    panes = list_panes(socket, session)
    print(f"{mode}: {session}")
    print(f"socket: {socket}")
    print(f"attach: {user_command(root, f'attach {session}')}")
    print(f"tmux attach: tmux -S {socket} attach -t {session}")
    print(f"cwd: {root}")
    print(f"registry: {registry_file}")
    if log_path:
        print(f"log: {log_path}")
    if events_info is not None:
        print(f"events: {events_info.get('status')}")
        if events_info.get("mode"):
            print(f"event mode: {events_info['mode']}")
        if events_info.get("settings_path"):
            label = "hook settings" if events_info.get("mode") == "settings-file" else "hook config"
            print(f"{label}: {events_info['settings_path']}")
        if hook_warning:
            print(f"hook warning: {hook_warning}")
    print(f"windows: {len({pane['window_index'] for pane in panes})}  panes: {len(panes)}")
    for pane in panes:
        marker = "*" if pane["active"] else " "
        print(
            f"  {marker} {session}:{pane['window_index']}.{pane['pane_index']} "
            f"{pane['pane_id']} {pane['command']} \"{pane['title']}\""
        )
    if effective_run:
        print(f"initial command sent: {effective_run}")
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
    if args.since_mark:
        if args.all or args.start is not None or args.end is not None or args.no_join:
            raise SystemExit("--since-mark cannot be combined with --all, --start, --end, or --no-join")
        mark = resolve_mark(root, args.since_mark)
        if mark.get("session") != args.session:
            raise SystemExit(f"Mark {args.since_mark} belongs to session {mark.get('session')}, not {args.session}")
        if args.pane and mark.get("target") != args.pane:
            raise SystemExit(f"Mark {args.since_mark} belongs to pane {mark.get('target')}, not {args.pane}")
        max_bytes = None if args.max_bytes == 0 else args.max_bytes
        output, _size, omitted = read_file_from_offset(Path(mark["log_path"]), int(mark["offset"]), max_bytes=max_bytes)
        output = normalize_transcript(output, ansi=args.ansi)
        output = tail_lines(output, limit=args.lines)
        if omitted:
            print(f"[agent-tmux: omitted {omitted} bytes before this excerpt]", file=sys.stderr)
        formatted = format_lines(output, number=args.number)
        print(formatted, end="")
        if formatted and not formatted.endswith("\n"):
            print()
        return 0

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
    if args.from_now and args.since_mark:
        raise SystemExit("--from-now and --since-mark are mutually exclusive")
    target = args.pane or args.session
    flags = re.MULTILINE | (re.IGNORECASE if args.ignore_case else 0)
    pattern = re.compile(args.pattern, flags)
    deadline = time.monotonic() + args.timeout
    last_text = ""

    if args.from_now or args.since_mark:
        registry_file = registry_path(root)
        registry = load_registry(registry_file)
        if args.since_mark:
            mark = resolve_mark(root, args.since_mark)
            if mark.get("session") != args.session:
                raise SystemExit(f"Mark {args.since_mark} belongs to session {mark.get('session')}, not {args.session}")
            if args.pane and mark.get("target") != args.pane:
                raise SystemExit(f"Mark {args.since_mark} belongs to pane {mark.get('target')}, not {args.pane}")
            log_path = Path(mark["log_path"])
            offset = int(mark["offset"])
        else:
            target = target_for_args(socket, args.session, args.pane)
            log_path, changed = ensure_transcript(root, socket, registry, args.session, target)
            if changed:
                save_registry_session(registry_file, registry, session_name_from_target(args.session, target))
            ensure_parent(log_path)
            if not log_path.exists():
                log_path.touch()
            offset = log_path.stat().st_size

        max_bytes = None if args.max_bytes == 0 else args.max_bytes
        while True:
            last_text, _size, omitted = read_file_from_offset(log_path, offset, max_bytes=max_bytes)
            last_text = normalize_transcript(last_text, ansi=args.ansi)
            if pattern.search(last_text):
                if not args.quiet:
                    print(f"matched: {args.pattern}")
                    if omitted:
                        print(f"[agent-tmux: omitted {omitted} bytes before this excerpt]", file=sys.stderr)
                    print(tail_lines(last_text, limit=args.tail))
                return 0
            if time.monotonic() >= deadline:
                if not args.quiet:
                    print(f"timeout waiting for: {args.pattern}")
                    if omitted:
                        print(f"[agent-tmux: omitted {omitted} bytes before this excerpt]", file=sys.stderr)
                    print(tail_lines(last_text, limit=args.tail))
                return 1
            time.sleep(args.interval)

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
    registry_file = registry_path(root)
    registry = load_registry(registry_file)
    target = target_for_args(socket, args.session, args.pane)
    profile_name, profile = resolve_profile(args.agent)
    mark_id = None
    if args.mark:
        mark_id, _mark, changed = create_mark(
            root,
            socket,
            registry,
            args.session,
            target,
            label=args.mark_label or "prompt",
        )
        if changed:
            save_registry_session(registry_file, registry, session_name_from_target(args.session, target))
    send_text(socket, target, args.text)
    if args.submit:
        send_profile_action(socket, target, profile, "submit")
    if not args.quiet:
        suffix = f" mark={mark_id}" if mark_id else ""
        print(f"prompt sent: target={target} profile={profile_name} submitted={'yes' if args.submit else 'no'}{suffix}")
    return 0


def mark_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    registry_file = registry_path(root)
    registry = load_registry(registry_file)
    target = target_for_args(socket, args.session, args.pane)
    mark_id, mark, changed = create_mark(root, socket, registry, args.session, target, label=args.label)
    if changed:
        save_registry_session(registry_file, registry, session_name_from_target(args.session, target))
    print(f"mark created: {mark_id}")
    print(f"target: {mark['target']}")
    print(f"log: {mark['log_path']}")
    print(f"offset: {mark['offset']}")
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


def events_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, getattr(args, "socket", None))
    consumer = getattr(args, "consumer", None) or default_consumer()

    if args.events_action == "emit":
        event: dict[str, Any] = {}
        json_input = getattr(args, "json_input", None)
        if json_input:
            if json_input == "-":
                event = json.loads(sys.stdin.read() or "{}")
            else:
                event = json.loads(Path(json_input).expanduser().read_text())
            if not isinstance(event, dict):
                raise SystemExit("--json must provide a JSON object")
        if args.kind:
            event["kind"] = args.kind
        if args.session:
            event["session"] = args.session
        if not event.get("session"):
            inferred_session = infer_current_tmux_session(socket)
            if inferred_session:
                event["session"] = inferred_session
        if args.agent:
            event["agent"] = args.agent
        if args.summary:
            event["summary"] = args.summary
        if args.source:
            event["source"] = args.source
        if args.confidence:
            event["confidence"] = args.confidence
        if args.read_command:
            event["read_command"] = args.read_command
        if not event.get("kind"):
            raise SystemExit("events emit requires --kind or a JSON object with kind")
        record = emit_event(root, event)
        print_event(record, json_output=args.json)
        return 0

    if args.events_action == "list":
        events = list_events(
            root,
            session=args.session,
            kind=args.kind,
            topic=args.topic,
            unread=args.unread,
            consumer=consumer,
        )
        if args.limit and len(events) > args.limit:
            events = events[-args.limit :]
        if args.json:
            print(json.dumps(events, sort_keys=True))
            return 0
        for event in events:
            print_event(event)
        return 0 if events else 1

    if args.events_action == "wait":
        deadline = time.monotonic() + args.timeout
        while True:
            events = list_events(
                root,
                session=args.session,
                kind=args.kind,
                topic=args.topic,
                unread=True,
                consumer=consumer,
            )
            if events:
                event = events[0]
                if args.ack:
                    ack_event(root, event["id"], consumer)
                print_event(event, json_output=args.json)
                return 0
            if time.monotonic() >= deadline:
                if not args.quiet:
                    print("timeout waiting for event")
                return 1
            time.sleep(args.interval)

    if args.events_action == "ack":
        path = ack_event(root, args.event_id, consumer)
        print(f"acked: {args.event_id}")
        print(path)
        return 0

    raise SystemExit(f"unknown events action: {args.events_action}")


def board_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, getattr(args, "socket", None))

    if args.board_action == "post":
        session = args.session or infer_current_tmux_session(socket)
        if args.body_file:
            body_path = Path(args.body_file).expanduser()
            body = body_path.read_text()
        elif args.body is not None:
            body = args.body
        else:
            body = sys.stdin.read()
        if not body.strip():
            raise SystemExit("board post requires non-empty body text")
        message_id = unique_record_id("msg", args.topic, args.from_agent)
        created_at = now_iso()
        metadata = {
            "id": message_id,
            "from": args.from_agent,
            "topic": args.topic,
            "created_at": created_at,
        }
        if session:
            metadata["session"] = session
        frontmatter = "\n".join(["---", *[f'{key}: "{value}"' for key, value in metadata.items()], "---", ""])
        content = frontmatter + body.rstrip() + "\n"
        path = board_topic_dir(root, args.topic) / f"{message_id}.md"
        atomic_write_text(path, content)
        read_command = user_command(root, f"board read {message_id}")
        emit_event(
            root,
            {
                "kind": "board_post",
                "session": session,
                "agent": args.from_agent,
                "source": "agent_tmux",
                "confidence": "explicit",
                "summary": f"{args.from_agent} posted to {args.topic}",
                "read_command": read_command,
                "message_id": message_id,
                "topic": args.topic,
                "path": str(path),
            },
        )
        print(f"posted: {message_id}")
        print(f"topic: {args.topic}")
        if session:
            print(f"session: {session}")
        print(f"path: {path}")
        print(f"read: {read_command}")
        return 0

    if args.board_action == "list":
        messages = list_board_messages(root, topic=args.topic)
        if args.json:
            print(json.dumps(messages, sort_keys=True))
            return 0
        for message in messages:
            session_part = f"  session={message['session']}" if message.get("session") else ""
            print(
                f"{message['id']}  topic={message['topic']}  "
                f"from={message['from']}{session_part}  created_at={message['created_at']}"
            )
        return 0 if messages else 1

    if args.board_action == "read":
        path = board_message_path(root, args.message_id)
        if path is None:
            raise SystemExit(f"board message not found: {args.message_id}")
        print(path.read_text(), end="")
        return 0

    raise SystemExit(f"unknown board action: {args.board_action}")


def hook_kind(agent: str, payload: dict[str, Any]) -> tuple[str, str]:
    event_name = str(payload.get("hook_event_name") or payload.get("event") or payload.get("type") or "")
    event_lower = re.sub(r"[^a-z0-9]+", "", event_name.lower())
    message = str(payload.get("message") or payload.get("reason") or payload.get("tool_name") or "").strip()
    if event_lower in {"stop", "subagentstop", "afteragent"}:
        return "agent_stop", message or f"{agent} turn ended"
    if event_lower in {"stopfailure"}:
        return "hook_error", message or f"{agent} stop hook failure"
    if event_lower in {"notification"}:
        return "needs_input", message or f"{agent} notification"
    if event_lower in {"permissionrequest"}:
        return "permission_request", message or f"{agent} permission request"
    if event_lower in {"sessionstart"}:
        return "session_started", message or f"{agent} session started"
    if event_lower in {"userpromptsubmit"}:
        return "prompt_submitted", message or f"{agent} prompt submitted"
    if event_lower in {"pretooluse", "posttooluse"}:
        return "tool_event", message or f"{agent} tool event"
    return "agent_event", message or f"{agent} hook event: {event_name or 'unknown'}"


def hooks_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)

    if args.hooks_action == "ingest":
        payload_text = sys.stdin.read()
        payload: dict[str, Any] = {}
        if payload_text.strip():
            try:
                parsed = json.loads(payload_text)
            except json.JSONDecodeError as exc:
                parsed = {"hook_event_name": "HookParseError", "message": str(exc)}
            if isinstance(parsed, dict):
                payload = parsed
        profile_name, _profile = resolve_profile(args.agent)
        kind, summary = hook_kind(profile_name, payload)
        emit_event(
            root,
            {
                "kind": kind,
                "session": args.session,
                "agent": profile_name,
                "source": "native_hook",
                "confidence": "native_hook",
                "summary": summary,
                "read_command": user_command(root, f"read {args.session} --lines 120"),
                "hook_event_name": payload.get("hook_event_name") or payload.get("event") or payload.get("type"),
                "tool_name": payload.get("tool_name"),
                "notification_type": payload.get("notification_type"),
                "cwd": payload.get("cwd"),
            },
        )
        if not args.quiet:
            print(json.dumps({"continue": True, "suppressOutput": True}, sort_keys=True))
        return 0

    if args.hooks_action == "show-config":
        profile_name, _profile = resolve_profile(args.agent)
        if profile_name == "claude":
            print(json.dumps(claude_hook_settings(root, args.session), indent=2, sort_keys=True))
            return 0
        if profile_name == "codex":
            print(codex_hooks_toml(root, args.session))
            return 0
        raise SystemExit(f"show-config is only implemented for claude and codex, not {profile_name}")

    if args.hooks_action == "status":
        registry = load_registry(registry_path(root))
        reg = registry.get("sessions", {}).get(args.session, {})
        events_info = reg.get("events") or {}
        print(f"Session: {args.session}")
        print(f"Events: {events_info.get('status', 'not configured')}")
        if events_info.get("agent"):
            print(f"Agent: {events_info['agent']}")
        if events_info.get("mode"):
            print(f"Mode: {events_info['mode']}")
        if events_info.get("settings_path"):
            path = Path(events_info["settings_path"])
            label = "Settings" if events_info.get("mode") == "settings-file" else "Config"
            print(f"{label}: {path} ({'exists' if path.exists() else 'missing'})")
        if events_info.get("warning"):
            print(f"Warning: {events_info['warning']}")
        if events_info.get("run_warning"):
            print(f"Run warning: {events_info['run_warning']}")
        return 0

    raise SystemExit(f"unknown hooks action: {args.hooks_action}")


def tmux_profile_cmd(args: argparse.Namespace) -> int:
    root = project_root(Path(args.cwd) if args.cwd else None)
    socket = socket_path(root, args.socket)
    if args.profile_action == "show":
        print("# Project-local tmux profile applied by:")
        print(f"# agent-tmux --cwd {shlex.quote(str(root))} tmux-profile apply")
        for command in TMUX_PROFILE_COMMANDS:
            print("tmux " + " ".join(shlex.quote(part) for part in command))
        return 0

    ensure_parent(socket)
    run_tmux(socket, ["start-server"])
    for command in TMUX_PROFILE_COMMANDS:
        run_tmux(socket, command)
    print(f"tmux profile applied: {socket}")
    print("scope: project tmux server only")
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
        save_registry_session(registry_file, registry, session)
        print(f"log started: {target}")
        print(output_path)
        return 0

    if args.log_action == "stop":
        stop_transcript(socket, target)
        update_log_registry(registry, session, target, {"stopped_at": now_iso()})
        save_registry_session(registry_file, registry, session)
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
    remove_registry_session(registry_file, args.session)
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
    launch_cmd.add_argument("--agent", help="Agent profile for the launched process, e.g. claude, codex, gemini")
    launch_cmd.add_argument("--events", action="store_true", help="Enable native event hook wiring for supported agents")
    launch_cmd.add_argument("--require-events", action="store_true", help="Fail launch unless native event hook wiring is verified")
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
    read.add_argument("--since-mark", help="Read transcript output appended after a mark id")
    read.add_argument("--max-bytes", type=int, default=20000, help="Maximum transcript bytes to read after a mark; 0 means no limit")
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
    wait.add_argument("--from-now", action="store_true", help="Wait only on transcript output appended after invocation")
    wait.add_argument("--since-mark", help="Wait only on transcript output appended after a mark id")
    wait.add_argument("--ansi", action="store_true", help="Preserve ANSI escape sequences when matching transcript output")
    wait.add_argument("--max-bytes", type=int, default=0, help="Maximum transcript bytes to search after the start offset; 0 means no limit")
    wait.set_defaults(func=wait_cmd)

    prompt = command("prompt", help="Send text to a terminal agent and submit using an agent profile")
    prompt.add_argument("session")
    prompt.add_argument("text")
    prompt.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    prompt.add_argument("--agent", default="generic", help="Agent profile: claude, codex, gemini, generic")
    prompt.add_argument("--no-submit", dest="submit", action="store_false", help="Paste text but do not submit")
    prompt.add_argument("--no-mark", dest="mark", action="store_false", help="Do not create a transcript mark before sending")
    prompt.add_argument("--mark-label", help="Optional label for the pre-send mark")
    prompt.add_argument("--quiet", action="store_true")
    prompt.set_defaults(func=prompt_cmd, submit=True, mark=True)

    mark = command("mark", help="Create a transcript mark for a session or pane")
    mark.add_argument("session")
    mark.add_argument("--pane", help="Explicit pane target, e.g. session:0.0")
    mark.add_argument("--label", help="Optional human-readable label")
    mark.set_defaults(func=mark_cmd)

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

    events = command("events", help="Emit, list, wait for, and acknowledge manager-agent events")
    events_sub = events.add_subparsers(dest="events_action", required=True)
    events_emit = events_sub.add_parser("emit", help="Append a canonical event")
    events_emit.add_argument("--kind", help="Event kind, e.g. agent_stop, needs_input, board_post")
    events_emit.add_argument("--session", help="Related tmux session")
    events_emit.add_argument("--agent", help="Related agent profile/name")
    events_emit.add_argument("--summary", help="Short event summary")
    events_emit.add_argument("--source", default="agent_tmux", help="Event source")
    events_emit.add_argument("--confidence", default="explicit", help="Event confidence")
    events_emit.add_argument("--read-command", help="Command that reads related details")
    events_emit.add_argument("--json", dest="json_input", help="Read event JSON object from path or '-'")
    events_emit.add_argument("--json-output", dest="json", action="store_true", help="Print event as JSON")
    events_emit.set_defaults(func=events_cmd)
    events_list = events_sub.add_parser("list", help="List events")
    events_list.add_argument("--session", help="Filter by session")
    events_list.add_argument("--kind", help="Filter by event kind; comma-separated means any matching kind")
    events_list.add_argument("--topic", help="Filter by board/event topic")
    events_list.add_argument("--unread", action="store_true", help="Only show events not acked by this consumer")
    events_list.add_argument("--consumer", help="Consumer name for unread filtering")
    events_list.add_argument("--limit", type=int, default=50)
    events_list.add_argument("--json", action="store_true")
    events_list.set_defaults(func=events_cmd)
    events_wait = events_sub.add_parser("wait", help="Wait for the next unread event")
    events_wait.add_argument("--session", help="Filter by session")
    events_wait.add_argument("--kind", help="Filter by event kind; comma-separated means any matching kind")
    events_wait.add_argument("--topic", help="Filter by board/event topic")
    events_wait.add_argument("--timeout", type=float, default=1800)
    events_wait.add_argument("--interval", type=float, default=1.0)
    events_wait.add_argument("--consumer", help="Consumer name for unread filtering")
    events_wait.add_argument("--ack", action="store_true", help="Ack the event before returning")
    events_wait.add_argument("--json", action="store_true")
    events_wait.add_argument("--quiet", action="store_true")
    events_wait.set_defaults(func=events_cmd)
    events_ack = events_sub.add_parser("ack", help="Acknowledge an event for a consumer")
    events_ack.add_argument("event_id")
    events_ack.add_argument("--consumer", help="Consumer name")
    events_ack.set_defaults(func=events_cmd)

    board = command("board", help="Append-only message board for durable agent memos")
    board_sub = board.add_subparsers(dest="board_action", required=True)
    board_post = board_sub.add_parser("post", help="Post one immutable Markdown message")
    board_post.add_argument("--topic", required=True)
    board_post.add_argument("--from", dest="from_agent", required=True)
    board_post.add_argument("--session", help="Related tmux session")
    board_post.add_argument("--body-file", help="Read message body from a file")
    board_post.add_argument("body", nargs="?", help="Message body; stdin is used if omitted")
    board_post.set_defaults(func=board_cmd)
    board_list = board_sub.add_parser("list", help="List board messages")
    board_list.add_argument("--topic")
    board_list.add_argument("--json", action="store_true")
    board_list.set_defaults(func=board_cmd)
    board_read = board_sub.add_parser("read", help="Read one board message by id")
    board_read.add_argument("message_id")
    board_read.set_defaults(func=board_cmd)

    hooks = command("hooks", help="Native terminal-agent hook adapter")
    hooks_sub = hooks.add_subparsers(dest="hooks_action", required=True)
    hooks_ingest = hooks_sub.add_parser("ingest", help="Read vendor hook JSON from stdin and emit a canonical event")
    hooks_ingest.add_argument("--agent", required=True)
    hooks_ingest.add_argument("--session", required=True)
    hooks_ingest.add_argument("--quiet", action="store_true")
    hooks_ingest.set_defaults(func=hooks_cmd)
    hooks_show = hooks_sub.add_parser("show-config", help="Print hook config for a supported agent")
    hooks_show.add_argument("--agent", required=True)
    hooks_show.add_argument("--session", required=True)
    hooks_show.set_defaults(func=hooks_cmd)
    hooks_status = hooks_sub.add_parser("status", help="Show stored hook wiring status for a session")
    hooks_status.add_argument("session")
    hooks_status.set_defaults(func=hooks_cmd)

    tmux_profile = command("tmux-profile", help="Show or apply the project-local tmux ergonomics profile")
    tmux_profile_sub = tmux_profile.add_subparsers(dest="profile_action", required=True)
    tmux_profile_show = tmux_profile_sub.add_parser("show", help="Print the tmux commands in the profile")
    tmux_profile_show.set_defaults(func=tmux_profile_cmd)
    tmux_profile_apply = tmux_profile_sub.add_parser("apply", help="Apply profile settings to the project tmux server")
    tmux_profile_apply.set_defaults(func=tmux_profile_cmd)

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
