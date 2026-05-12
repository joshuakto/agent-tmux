---
name: shared-tmux-terminal
description: Launch, inspect, attach, and manage project-local tmux sessions for shared human-agent terminals. Use when an agent needs a visible terminal a human can watch, attach to, interrupt, or inspect while preserving shell state across multiple parallel sessions.
---

# Shared Tmux Terminal

Use this skill when work needs a live terminal shared by an agent and a human.

## Core Contract

- One project tmux server, usually at `./.agent/tmux.sock`.
- Multiple named sessions inside that server, one per agent/task.
- Humans may attach concurrently, change focus, type input, or interrupt.
- Run from the project root; if uncertain, pass `--cwd /path/to/project`.
- `agent-tmux` observes and controls terminal sessions. It does not decide task state.
- Task truth comes from artifacts, tests, commits, process exit status, and explicit reports. Logs and marks are navigation aids only.
- Requires tmux ≥ 3.2 (for `choose-tree -f` filtering). The session name `__agent_tmux_picker__` is reserved for the internal attach-picker lobby.

## Golden Path

Supervising a worker terminal-agent is a four-step loop. Use `agent-tmux` (or `.agent/tmux` if the wrapper is installed).

**1. Launch the worker.** Name the session, point `--run` at the agent CLI binary, and ask for native event wiring. `--agent` is inferred from the `--run` basename (`claude`, `codex`, `opencode`, `gemini`).

```bash
agent-tmux launch --session reviewer --events --require-events --run "claude --name reviewer" --log
```

`--require-events` fails launch if hook wiring or binary resolution cannot be verified — better to fail fast than supervise blind. The launch report tells you what got wired. `--require-events` only succeeds for CLIs with native hook support; see `references/wiring-internals.md` for the matrix.

**2. Send the task and capture the mark.** `prompt --json` types the message, submits it, and prints a JSON receipt. Capture the mark — it is your event cursor for step 3.

The task text MUST end with the report-back instruction so the worker knows how to signal completion. Use this canonical phrasing verbatim (replace `<topic>` and the memo body):

> `When done or blocked, run: agent-tmux board post --topic <topic> "<concise status memo>"`

```bash
TASK='Read README.md and write a 5-bullet summary. When done or blocked, run: agent-tmux board post --topic readme-summary "<5 bullets>"'
MARK=$(agent-tmux prompt reviewer "$TASK" --json | jq -r .mark)
```

Receipt shape: `{"mark":"m_...","profile":"...","session":"...","submitted":true,"target":"..."}`. The board is how the worker tells you it's done; the transcript is not task truth.

**3. Wait for an attention event.** `events wait --json` blocks until a `board_post`, `needs_input`, `permission_request`, `agent_stop`, or `hook_error` event lands after `MARK`, then prints one event and exits.

```bash
EVENT=$(agent-tmux events wait --session reviewer --since-mark "$MARK" --ack --json --timeout 1800)
KIND=$(echo "$EVENT" | jq -r .kind)
MSG=$(echo "$EVENT"  | jq -r '.message_id // empty')
```

Event JSON has `id`, `kind`, `session`, `agent`, `source`, `summary`, `read_command` (a ready-to-run command string), and event-specific fields (`message_id`/`topic`/`path` for board posts). Branch on `$KIND`:

- `board_post` → step 4 with `$MSG`.
- `needs_input` / `permission_request` → `agent-tmux read reviewer --since-mark "$MARK"` to inspect, then decide.
- `agent_stop` without a memo → worker ended silently; recover via `read` or `attach`.
- `hook_error` → see `references/hooks.md`.

**4. Read the memo.**

```bash
agent-tmux board read "$MSG"
```

Treat the memo as a report, not as task truth — verify artifacts/tests/commits as needed.

## Decision Rules

- Continuing existing shared work: run `list` first; reuse only when there is an obvious matching live session.
- Need raw terminal evidence (not an event): use `read --since-mark <mark-id>`, `wait --since-mark <mark-id>`, or `search`.
- Session seems missing or socket access fails: `list`/`status` flag `Dead but registered` for sessions killed externally. Run `doctor` for full diagnostics; do not conclude absence from a failed probe.
- Human wants to inspect/interfere: report the no-arg `attach` command; it opens the live-session picker.
- Need proof of completion: inspect artifacts/tests/branches, not logs or marks.

## Load References Only When Needed

- `references/agent-contract.md`: concise reusable instruction block for terminal agents.
- `references/recovery.md`: missing sessions, stale history, stuck processes, raw input, logs, dumps, pane/window recovery.
- `references/agent-profiles.md`: terminal-agent key behavior and profile actions.
- `references/human-tmux.md`: attach, mouse scrolling, tmux profile, pane/window navigation for humans.
- `references/manager-events.md`: event-driven manager-agent loop.
- `references/board.md`: append-only message board for clean memos.
- `references/hooks.md`: native hook ingestion and the supported-CLI table.
- `references/wiring-internals.md`: per-vendor file layout and rewrite rules — only when debugging the plumbing or adding a new vendor.

## Reporting Contract

After every launch or layout change, report:

- project root
- socket path
- session name
- direct attach command and no-arg attach picker command
- active pane and pane list
- compact recent output sample

Keep reports compact. The goal is easy human attachment and easy agent recovery, not a full task summary.

## Runtime Notes

- Commit `.agent/tmux` if a project wants the convenience command.
- Do not commit `.agent/tmux.sock`, `.agent/tmux.d/`, or `.agent/board/`.
- The socket is project-local, but tmux persistence still depends on the tmux server process staying alive.
- `doctor` writes intentional diagnostics under `.agent/tmux.d/doctor/events.jsonl`; use them to improve the tool, not as task status.
