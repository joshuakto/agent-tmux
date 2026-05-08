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

## Golden Path First

Use the project wrapper when present; otherwise replace `.agent/tmux` with `agent-tmux`.

```bash
.agent/tmux launch --session <name> --agent claude --events --require-events --purpose <purpose> --run "claude --name <name>" --log
.agent/tmux report
.agent/tmux prompt <session> --agent claude "<instruction; when finished or blocked, run: .agent/tmux board post --topic <topic> \"concise status memo\">"
.agent/tmux events wait --session <session> --kind board_post,needs_input,permission_request,agent_stop,hook_error --since-mark <mark-id> --ack --json --timeout 1800
.agent/tmux board read <message-id>
```

`prompt` creates a transcript mark before sending and prints it in the receipt. Use that mark for `events wait --since-mark` so stale unread events from earlier turns do not wake the manager. Marks are out-of-band transcript offsets and event cursors; they are not typed into the terminal.

## Manager-Agent Path

When supervising other terminal agents, prefer events and board memos over repeated pane polling:

```bash
.agent/tmux launch --session <name> --agent claude --events --require-events --purpose <purpose> --run "claude --name <name>" --log
.agent/tmux prompt <session> --agent claude "<instruction; when finished or blocked, run: .agent/tmux board post --topic <topic> \"concise status memo\">"
.agent/tmux events wait --session <session> --kind board_post,needs_input,permission_request,agent_stop,hook_error --since-mark <mark-id> --ack --json --timeout 1800
```

For Codex CLI, use the same path with `--agent codex --run "codex"`. `--require-events` fails fast unless the session-local hook config is injected.

`board post` auto-associates with the current session when it is run inside a managed tmux pane, so worker agents usually only need `--topic` and a memo body.

Branch on the returned event: `board_post` -> `board read <message-id>`; `needs_input` or `permission_request` -> inspect or ask the human; `agent_stop` without a memo -> read recent output or prompt for a memo; `hook_error` -> run `hooks status` or `doctor`.

Use `read`, `wait`, `search`, and `attach` for recovery, non-agent shells, or evidence checks, not routine manager-agent notification. Events and board messages are coordination aids, not task truth.

## Decision Rules

- Need to start shared work: `launch --log`, then `report`.
- Need to send a user message to Claude/Codex/Gemini: use `prompt`, not raw `send`.
- Need the response to your last worker prompt: use `events wait --since-mark <mark-id>`, then `board read`.
- Need raw terminal evidence: use `read --since-mark <mark-id>`, `wait --since-mark <mark-id>`, or `search`.
- Session seems missing or socket access fails: `list`/`status` already flag `Dead but registered` for sessions killed externally. Run `doctor` for full diagnostics; do not conclude absence from a failed probe.
- Human wants to inspect/interfere: report the `attach` command.
- Need proof of completion: inspect artifacts/tests/branches, not logs or marks.
- Supervising a worker agent: use `--require-events`, wait for attention events since the prompt mark, then branch by event kind.

## Load References Only When Needed

- `references/agent-contract.md`: concise reusable instruction block for terminal agents.
- `references/recovery.md`: missing sessions, stale history, stuck processes, raw keys, logs, dumps, pane/window recovery.
- `references/agent-profiles.md`: Claude/Codex/Gemini key behavior and profile actions.
- `references/human-tmux.md`: attach, mouse scrolling, tmux profile, pane/window navigation for humans.
- `references/manager-events.md`: event-driven manager-agent loop.
- `references/board.md`: append-only message board for clean memos.
- `references/hooks.md`: native hook ingestion and session-local Claude/Codex wiring.

## Reporting Contract

After every launch or layout change, report:

- project root
- socket path
- session name
- attach command
- active pane and pane list
- compact recent output sample

Keep reports compact. The goal is easy human attachment and easy agent recovery, not a full task summary.

## Runtime Notes

- Commit `.agent/tmux` if a project wants the convenience command.
- Do not commit `.agent/tmux.sock`, `.agent/tmux.d/`, or `.agent/board/`.
- The socket is project-local, but tmux persistence still depends on the tmux server process staying alive.
- `doctor` writes intentional diagnostics under `.agent/tmux.d/doctor/events.jsonl`; use them to improve the tool, not as task status.
