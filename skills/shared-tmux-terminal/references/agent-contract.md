# Agent Contract

Give terminal agents this concise contract when they need shared tmux access.

```text
Use agent-tmux for shared interactive terminal work.
Run from the project root, or pass --cwd /path/to/project.

Use the canonical supervised worker loop in skills/shared-tmux-terminal/SKILL.md. These are the contract rules around it:
1. If continuing existing work, scan first:
   agent-tmux list
2. Reuse only an obvious live match. Otherwise launch a fresh named session with native event wiring:
   agent-tmux launch --session <name> --require-events --purpose <purpose> --run "<native-hook cli>" --log
3. Relay the launch receipt's session name and attach command to the human.
4. Send work with prompt. Use --report-back-topic <topic> to automatically inject the board-post instruction; the worker is told to post when finished or blocked.
   MARK=$(agent-tmux prompt <session> "<task>" --report-back-topic <topic>)
5. Use the mark returned by prompt as the event cursor; with --since-mark, the session is inferred.
6. If the event is board_post, .board_body in the JSON output contains the stripped memo body directly.
7. Use transcript reads only for recovery or evidence:
   agent-tmux read --since-mark <mark-id> --lines 120
8. If the session seems missing or socket access fails:
   agent-tmux doctor --question "<what looked wrong>" --context "<what you were doing>"
9. If a human wants to inspect:
   agent-tmux attach

`prompt` infers the agent profile from the session registry. `--agent` is inferred at launch for recognized binaries; pass it only to override.
`--report-back-topic` appends a standard board-post instruction; `prompt` prints the mark id on stdout (receipt + warning go to stderr), so `MARK=$(agent-tmux prompt …)` needs no flag. Pass `--json` for the full receipt.
`events wait` is idempotent: it does not ack (the prompt mark is your cursor), so re-running with the same mark returns the same event. On timeout, `--json` adds `.events_after_cursor`/`.kinds_after_cursor` to distinguish a stalled worker (0) from one that finished with a different event kind (>0). For drain-style consumption, add `--unread --ack`.
`events wait` exits 0 for both event-found and timeout; exits non-zero only on errors. Check `.kind` (not `$?`) to detect timeout — this keeps `set -e` scripts safe.
`events wait` and `events list` default to the manager attention set (`board_post,needs_input,permission_request,agent_stop,hook_error`). Pass `--kind all` to widen, or `--kind <list>` to narrow.
For `board_post` events, `--json` output includes `.board_body` with the stripped memo body; no separate `board read` call needed.
Do not treat logs, marks, or wait output as task truth.
Task truth comes from artifacts, tests, commits, process exit status, and explicit reports.
`prompt` keeps text and submit together even when multiple prompts are sent concurrently.
```

If a project wrapper exists, use `.agent/tmux` instead of `agent-tmux`.
Reuse an existing session only when `list` shows an obvious live match. Otherwise launch a fresh named session.

## Manager-Agent Contract

When supervising another terminal agent, use events and board messages to avoid repeated pane polling. The supported native-hook CLIs are `claude`, `codex`, `opencode`, and `pi`; the exact launch wiring and vendor limits live in `references/wiring-internals.md`.

Events are wakeups. Board posts are durable memos and infer poster/session from the current managed tmux pane. Neither is task truth.

For recovery tools, read `references/recovery.md`. For profile behavior, read `references/agent-profiles.md`.

## Runtime State

```text
.agent/tmux.sock
.agent/tmux.d/registry.json
.agent/tmux.d/marks.json
.agent/tmux.d/events/events/
.agent/tmux.d/hooks/
.agent/tmux.d/doctor/events.jsonl
.agent/tmux.d/logs/
.agent/board/
```

The wrapper `.agent/tmux` may be committed. Runtime files should be ignored.
