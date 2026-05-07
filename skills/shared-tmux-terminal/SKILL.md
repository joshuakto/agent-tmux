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
.agent/tmux launch --session <name> --purpose <purpose> --run "<agent command>" --log
.agent/tmux report
.agent/tmux prompt <session> --agent claude "<instruction>"
.agent/tmux read <session> --since-mark <mark-id> --lines 120
.agent/tmux wait <session> "<pattern>" --since-mark <mark-id> --timeout 300
.agent/tmux search <session> "<error|failed|complete>" --context 3
.agent/tmux doctor --question "<what looked wrong>" --context "<what you were doing>"
.agent/tmux attach <session>
```

`prompt` creates a transcript mark before sending and prints it in the receipt. After `prompt`, use that mark for follow-up reads and waits. Marks are out-of-band transcript offsets; they are not typed into the terminal.

## Manager-Agent Path

When supervising other terminal agents, prefer events and board memos over repeated pane polling:

```bash
.agent/tmux launch --session <name> --agent claude --events --require-events --purpose <purpose> --run "claude --name <name>" --log
.agent/tmux prompt <session> --agent claude "<instruction; post a board memo when done>"
.agent/tmux events wait --session <session> --kind board_post,needs_input,permission_request,agent_stop,hook_error --ack --json --timeout 1800
```

For Codex CLI, use the same path with `--agent codex --run "codex"`. `--require-events` fails fast unless the session-local hook config is injected.

`board post` auto-associates with the current session when it is run inside a managed tmux pane, so worker agents usually do not need to pass `--session`.

Branch on the returned event: `board_post` -> `board read <message-id>`; `needs_input` or `permission_request` -> inspect or ask the human; `agent_stop` without a memo -> read recent output or prompt for a memo; `hook_error` -> run `hooks status` or `doctor`.

Use `read`, `search`, and `attach` for recovery or evidence checks, not routine manager-agent notification. Events and board messages are coordination aids, not task truth.

## Decision Rules

- Need to start shared work: `launch --log`, then `report`.
- Need to send a user message to Claude/Codex/Gemini: use `prompt`, not raw `send`.
- Need the response to your last prompt: use `read --since-mark <mark-id>`.
- Need to wait for new output: use `wait --since-mark <mark-id>` or `wait --from-now`.
- Session seems missing or socket access fails: run `doctor`; do not conclude absence from a failed probe.
- Human wants to inspect/interfere: report the `attach` command.
- Need proof of completion: inspect artifacts/tests/branches, not logs or marks.
- Supervising a worker agent: use `--require-events`, wait for attention events, then branch by event kind.

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
