# Manager Events

Use this when one agent supervises terminal agents running inside `agent-tmux`.

## Core Loop

```bash
agent-tmux launch --session reviewer --agent claude --events --require-events --purpose review --run "claude --name reviewer" --log
agent-tmux prompt reviewer --agent claude "Run the task. When finished or blocked, run: agent-tmux board post --topic review \"concise status memo\""
agent-tmux events wait --session reviewer --kind board_post,needs_input,permission_request,agent_stop,hook_error --since-mark <mark-id> --ack --json --timeout 1800
```

Use `--agent codex --run "codex"` for Codex CLI sessions.

Events are small wakeups for the manager agent. Use the mark printed by `prompt` as the event cursor so stale unread events from earlier turns are ignored. Events are not task truth.

## Commands

```bash
agent-tmux events emit --kind needs_input --session reviewer --summary "Need a decision"
agent-tmux events list --unread --kind board_post,needs_input,permission_request,agent_stop,hook_error
agent-tmux events wait --session reviewer --kind board_post,needs_input,permission_request,agent_stop,hook_error --since-mark <mark-id> --timeout 1800 --ack
agent-tmux events ack <event-id>
```

Use `--json` on `events wait` or `events list` when a manager agent needs machine-readable output.
Use `--since-mark <mark-id>` after `prompt`; use `--from-now` only when no prompt mark exists.
Use `--topic <topic>` for board-specific waits. Do not combine `--topic` with the multi-kind attention wait unless you intentionally want to ignore native events that have no topic.
Use comma-separated `--kind` values when waiting for any attention event.

## Event Meaning

- `agent_stop`: a native hook says the worker turn ended.
- `needs_input`: the worker or native hook says attention is needed.
- `permission_request`: the worker requested permission; do not auto-approve.
- `board_post`: a durable board memo was posted.
- `session_started`: `agent-tmux launch` created or reused a session.

## Manager Branches

- `board_post`: read the memo with the event's `read_command` or `board read <message-id>`.
- `needs_input`: inspect recent output or ask the human for the missing input.
- `permission_request`: surface the decision; never auto-approve.
- `agent_stop`: if no memo arrived, read recent output or prompt the worker to post one.
- `hook_error`: run `hooks status` or `doctor`.

Use `read`, `wait`, `search`, and `attach` only for recovery, inherited sessions, or evidence checks.
