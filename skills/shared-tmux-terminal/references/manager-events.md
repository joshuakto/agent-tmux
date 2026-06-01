# Manager Events

Use this when one agent supervises terminal agents running inside `agent-tmux`.

## Canonical Loop

Use the canonical supervised worker loop in [SKILL.md](../SKILL.md#golden-path). This reference explains event semantics, filters, and recovery edges so the loop stays in one place.

In the SKILL loop, replace the launch command's `--run` value for native-hook CLIs such as `--run "codex"`, `--run "opencode"`, or `--run "pi"`. `--agent` is inferred for recognized binaries; pass it only to override.
With `--since-mark`, session is inferred from the mark. Add `--all-sessions` only when you need the next event from any session after that mark.

`prompt` infers the agent profile from the session registry. At launch, `--agent` is usually inferred from recognized `--run` binaries.
Events are small wakeups for the manager agent. Use the mark printed by `prompt` as the event cursor so stale unread events from earlier turns are ignored. Events are not task truth.

## Event JSON Fields

Event records include `{schema_version, id, kind, session, agent, source, confidence, summary, created_at, read_command}` plus kind-specific fields such as `message_id`, `topic`, `path`, and `from`. `.agent` is the terminal-agent profile when known; for `board_post`, `.from` is the poster. Branch on `.kind`. For `board_post`, use `.message_id` with `board read`. `read_command` may be null; treat it as metadata for manual recovery or tooling, not the golden path.

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
agent-tmux events wait --since-mark <mark-id> --timeout 1800        # idempotent; add --unread --ack for drain-style consumption
agent-tmux events ack <event-id>
```

Use `--json` on `events wait` or `events list` when a manager agent needs machine-readable output.
Use `--since-mark <mark-id>` after `prompt`; session is inferred from the mark automatically. Add `--all-sessions` only when waiting for any session after that mark.
Use `--from-now` only when no prompt mark exists; add `--session <name>` when targeting a specific session without a mark.
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

Other event kinds (only shown with `--kind all` or an explicit `--kind`):

- `prompt_submitted`: `UserPromptSubmit` hook fired for prompt delivery confirmation.
- `tool_event`: vendor `PreToolUse`/`PostToolUse` hook fired.
- `agent_event`: catch-all for any other vendor hook payload.

Pass `--kind all` (or an explicit list) to surface these.

## Manager Branches

The entries below are the decision to make *after* the golden path's `*` branch reads the transcript — one per event kind.

- `board_post`: with `--json`, `.board_body` contains the stripped memo body directly; or call `board read <message-id>` from the event's `.message_id`.
- `needs_input`: inspect recent output or ask the human for the missing input.
- `permission_request`: surface the decision; never auto-approve.
- `agent_stop`: if no memo arrived, read recent output or prompt the worker to post one.
- `hook_error`: run `hooks status` or `doctor`.
- `timeout`: `events wait --json` emits `{"kind":"timeout","session":...,"events_after_cursor":N,"kinds_after_cursor":{...}}` on timeout and exits 0. `events_after_cursor == 0` means nothing actionable landed after the cursor (worker still working or stalled — re-prompt or read output); `> 0` means attention events you weren't waiting on landed (inspect them with `events list --since-mark <mark>`). The count spans the whole attention set and is not topic-scoped, so a `--topic` wait still surfaces topic-less signals like `needs_input`. Do not check `$?` to detect timeout; check `.kind` instead — this keeps `set -e` scripts safe.

Use `read`, `wait`, `search`, and `attach` only for recovery, inherited sessions, or evidence checks.

## Field Lessons

Practical edges from real multi-agent runs:

- Use `prompt` marks as the event cursor. `events wait --since-mark <mark-id>` excludes earlier-turn events, so the wait is idempotent — re-running after the same prompt returns the same event instead of a misleading "stalled" timeout. The mark is the sole cursor; add `--unread --ack` only for drain-style consumption when reusing one mark across several waits.
- Parallel `prompt` calls are safe across sessions and serialized per target pane, so text and submit keys are not interleaved.
- Treat native events as wakeups, not conclusions. Verify task truth from artifacts, commits, process status, and explicit board memos.
- Keep persistence policy outside `agent-tmux`. The project should say where durable artifacts live; for Colab experiments, GitHub branches were more reliable than Drive because Drive auth can require interactive credentials.
- If a TUI agent remains wedged after one interrupt, preserve the pane for inspection and start a fresh session with a shorter corrected prompt. Do not keep layering prompts into a stuck tool-call state.
- Use `report` for cleanup review. Detached sessions are candidates to inspect or kill, but attached sessions may be under active human control.
- Humans can run `attach` with no session name to open the live-session picker.
