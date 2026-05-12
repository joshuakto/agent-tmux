# Manager Events

Use this when one agent supervises terminal agents running inside `agent-tmux`.

## Core Loop

```bash
agent-tmux launch --session reviewer --events --require-events --purpose review --run "claude --name reviewer" --log
agent-tmux prompt reviewer "Run the task. When finished or blocked, run: agent-tmux board post --topic review \"concise status memo\""
agent-tmux events wait --session reviewer --since-mark <mark-id> --ack --json --timeout 1800
```

Use `--run "codex"` for Codex CLI sessions. `--agent` is inferred for recognized binaries; pass it only to override.

`prompt` infers the agent profile from the session registry. At launch, `--agent` is usually inferred from recognized `--run` binaries.
Events are small wakeups for the manager agent. Use the mark printed by `prompt` as the event cursor so stale unread events from earlier turns are ignored. Events are not task truth.

## Default Kind Filter

`events wait` and `events list` default `--kind` to the manager attention set:

```text
board_post,needs_input,permission_request,agent_stop,hook_error
```

To widen, pass `--kind all`. To narrow, pass an explicit comma-separated list (e.g. `--kind board_post`).

## Commands

```bash
agent-tmux events emit --kind needs_input --session reviewer --summary "Need a decision"
agent-tmux events list --unread
agent-tmux events wait --session reviewer --since-mark <mark-id> --timeout 1800 --ack
agent-tmux events ack <event-id>
```

Use `--json` on `events wait` or `events list` when a manager agent needs machine-readable output.
Use `--since-mark <mark-id>` after `prompt`; use `--from-now` only when no prompt mark exists.
Use `--topic <topic>` for board-specific waits. Do not combine `--topic` with the default attention wait unless you intentionally want to ignore native events that have no topic.

## Event Meaning

Recommended attention kinds (in the default `--kind`):

- `agent_stop`: a native hook says the worker turn ended.
- `needs_input`: the worker or native hook says attention is needed.
- `permission_request`: the worker requested permission; do not auto-approve.
- `hook_error`: a native stop-hook failure was reported; run `hooks status` or `doctor`.
- `board_post`: a durable board memo was posted.

Session lifecycle (emitted by `agent-tmux launch`, not in the default attention set):

- `session_started`: `launch` created a new session.
- `session_reused`: `launch` attached to an existing session in the registry.
- `session_recovered`: `launch --session <name>` recreated a registered session that was no longer live.

Observability-only kinds (emitted by `hooks ingest` for non-attention vendor hooks; not in the default set and not wired by default for built-in vendors):

- `prompt_submitted`: vendor `UserPromptSubmit` hook fired.
- `tool_event`: vendor `PreToolUse`/`PostToolUse` hook fired.
- `agent_event`: catch-all for any other vendor hook payload.

Pass `--kind all` (or an explicit list) to surface these.

## Manager Branches

- `board_post`: read the memo with the event's `read_command` or `board read <message-id>`.
- `needs_input`: inspect recent output or ask the human for the missing input.
- `permission_request`: surface the decision; never auto-approve.
- `agent_stop`: if no memo arrived, read recent output or prompt the worker to post one.
- `hook_error`: run `hooks status` or `doctor`.

Use `read`, `wait`, `search`, and `attach` only for recovery, inherited sessions, or evidence checks.

## Field Lessons

Practical edges from real multi-agent runs:

- Use `prompt` marks as the event cursor. `events wait --since-mark <mark-id>` prevents stale unread hook events from waking the manager after a new prompt.
- Parallel `prompt` calls are safe across sessions and serialized per target pane, so text and submit keys are not interleaved.
- Treat native events as wakeups, not conclusions. Verify task truth from artifacts, commits, process status, and explicit board memos.
- Keep persistence policy outside `agent-tmux`. The project should say where durable artifacts live; for Colab experiments, GitHub branches were more reliable than Drive because Drive auth can require interactive credentials.
- If a TUI agent remains wedged after one interrupt, preserve the pane for inspection and start a fresh session with a shorter corrected prompt. Do not keep layering prompts into a stuck tool-call state.
- Use `report` for cleanup review. Detached sessions are candidates to inspect or kill, but attached sessions may be under active human control.
- Humans can run `attach` with no session name to open the live-session picker.
