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

Supervised worker loop. Use `agent-tmux` (or `.agent/tmux` if the wrapper is installed). Variables splice IDs between steps; `jq` is the wiring.

```bash
# 1. Launch (--agent inferred from --run basename; --purpose labels the session in list/report).
agent-tmux launch --session reviewer --purpose "review" --require-events --run "claude --name reviewer" --log

# 2. Send task and capture mark. The task MUST end with the report-back command verbatim.
TASK='<task>. When done or blocked, run: agent-tmux board post --topic <topic> "<concise memo>"'
MARK=$(agent-tmux prompt reviewer "$TASK" --json | jq -r .mark)

# 3. Wait for the next attention event after the mark. Session is inferred from the mark.
EVENT=$(agent-tmux events wait --since-mark "$MARK" --ack --json --timeout 1800)
KIND=$(echo "$EVENT" | jq -r .kind)

# 4. Branch on the event kind.
case "$KIND" in
  board_post)                       agent-tmux board read "$(echo "$EVENT" | jq -r .message_id)" ;;
  needs_input|permission_request)   agent-tmux read reviewer --since-mark "$MARK" ;;  # inspect, decide
  agent_stop)                       agent-tmux read reviewer --since-mark "$MARK" ;;  # no memo; recover
  hook_error)                       echo "see references/hooks.md" ;;
  null)                             agent-tmux read reviewer --since-mark "$MARK" ;;  # timeout; inspect
esac
```

- **Receipt JSON:** `{mark, profile, session, submitted, target}`; `.mark` is your event cursor.
- **Event JSON:** use `.kind`; for `board_post`, read `.message_id` with `board read`.
- **Recognized `--run` basenames** (`--agent` auto-inferred): `claude`, `codex`, `opencode`, `pi`, `gemini`. `--require-events` succeeds only for native-hook profiles (`claude`, `codex`, `opencode`, `pi`) — see `references/wiring-internals.md`.
- The board is the report channel; the transcript is not task truth. Treat memos as reports, verify artifacts.

## Decision Rules

- Continuing existing shared work: run `list` first; reuse only when there is an obvious matching live session. Otherwise launch fresh.
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

After launch, include the session name and attach command from the launch receipt. For focused follow-up, run `agent-tmux status <session>`; reserve `agent-tmux report` for multi-session review.

## Runtime Notes

- Commit `.agent/tmux` if a project wants the convenience command.
- Do not commit `.agent/tmux.sock`, `.agent/tmux.d/`, or `.agent/board/`.
- The socket is project-local, but tmux persistence still depends on the tmux server process staying alive.
- `doctor` writes intentional diagnostics under `.agent/tmux.d/doctor/events.jsonl`; use them to improve the tool, not as task status.
