# Manager Events

Use this when one agent supervises terminal agents running inside `agent-tmux`.

## Core Loop

```bash
agent-tmux launch --session reviewer --agent claude --events --require-events --purpose review --run "claude --name reviewer" --log
agent-tmux prompt reviewer --agent claude "Run the task and post a concise memo."
agent-tmux events wait --session reviewer --timeout 1800
agent-tmux board read <message-id>
```

Use `--agent codex --run "codex"` for Codex CLI sessions.

Events are small wakeups for the manager agent. They are not task truth.

## Commands

```bash
agent-tmux events emit --kind needs_input --session reviewer --summary "Need a decision"
agent-tmux events list --unread
agent-tmux events wait --session reviewer --timeout 1800 --ack
agent-tmux events ack <event-id>
```

Use `--json` on `events wait` or `events list` when a manager agent needs machine-readable output.

## Event Meaning

- `agent_stop`: a native hook says the worker turn ended.
- `needs_input`: the worker or native hook says attention is needed.
- `permission_request`: the worker requested permission; do not auto-approve.
- `board_post`: a durable board memo was posted.
- `session_started`: `agent-tmux launch` created or reused a session.

Use `read`, `wait`, `search`, and `attach` only for recovery, inherited sessions, or evidence checks.
