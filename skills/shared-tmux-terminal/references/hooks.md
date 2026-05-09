# Native Hooks

Use native hooks when a manager agent needs reliable wakeups from a terminal-agent session.

## Reliable Claude Path

```bash
agent-tmux launch --session reviewer --agent claude --events --require-events --run "claude --name reviewer" --log
agent-tmux prompt reviewer "<task; when finished or blocked, run: agent-tmux board post --topic review \"concise status memo\">"
agent-tmux events wait --session reviewer --since-mark <mark-id> --ack --json --timeout 1800
```

`--require-events` fails launch unless `agent-tmux` can verify session-local hook wiring *and* resolve the run-command binary (`shutil.which` for bare names, `is_file()` + executable check for absolute paths). Relative paths with separators (e.g. `./bin/claude`) are rejected — pass an absolute path or a `PATH`-resolvable name.

## Reliable Codex Path

```bash
agent-tmux launch --session reviewer --agent codex --events --require-events --run "codex" --log
agent-tmux prompt reviewer "<task; when finished or blocked, run: agent-tmux board post --topic review \"concise status memo\">"
agent-tmux events wait --session reviewer --since-mark <mark-id> --ack --json --timeout 1800
```

Codex CLI hook config is passed through a short session-local wrapper. `agent-tmux` does not edit `~/.codex/hooks.json` or project config.

`prompt` infers the agent profile from the session registry, so `--agent` is only needed at launch. `events wait`/`list` default to the manager attention set; pass `--kind all` to widen.

## What Launch Writes

For Claude Code, `agent-tmux` writes:

```text
.agent/tmux.d/hooks/<session>/claude-settings.json
```

and injects:

```bash
--settings .agent/tmux.d/hooks/<session>/claude-settings.json
```

into simple `claude ...` launch commands. It does not edit global Claude settings or project `.claude/` settings.

For Codex CLI, `agent-tmux` writes the generated hook config to:

```text
.agent/tmux.d/hooks/<session>/codex-hooks.toml
.agent/tmux.d/hooks/<session>/codex-with-hooks
```

and rewrites simple `codex ...` launch commands to:

```bash
.agent/tmux.d/hooks/<session>/codex-with-hooks ...
```

The wrapper runs `codex -c "$(cat .agent/tmux.d/hooks/<session>/codex-hooks.toml)" ...` internally. The TOML file is a single inline `hooks={Stop=[...],PermissionRequest=[...]}` table, so the visible tmux command stays readable. Codex `SessionStart` and `UserPromptSubmit` are not wired by default — `launch` already emits a `session_started`/`session_reused` event, and prompt submissions have no manager branch.

## Hook Adapter

```bash
agent-tmux hooks ingest --agent claude --session reviewer
agent-tmux hooks ingest --agent codex --session reviewer --quiet
agent-tmux hooks status reviewer
agent-tmux hooks show-config --agent claude --session reviewer
agent-tmux hooks show-config --agent codex --session reviewer
```

`hooks ingest` reads vendor hook JSON from stdin and emits a canonical event. The mapping is:

- `Stop`, `SubagentStop`, `AfterAgent` -> `agent_stop`
- `StopFailure` -> `hook_error`
- `Notification` -> `needs_input`
- `PermissionRequest` -> `permission_request`
- `SessionStart` -> `session_started`
- `UserPromptSubmit` -> `prompt_submitted`
- `PreToolUse`, `PostToolUse` -> `tool_event`
- anything else -> `agent_event`

The default `--kind` filter for `events wait`/`list` is `board_post,needs_input,permission_request,agent_stop,hook_error`. The other kinds (`session_started`, `prompt_submitted`, `tool_event`, `agent_event`) are observability records. By default, the only events `agent-tmux` wires for built-in vendors are the attention ones — Claude wires `Stop`/`SubagentStop`/`StopFailure`/`Notification`/`PermissionRequest`, and Codex wires `Stop`/`PermissionRequest`. If a vendor or user pipes a non-attention payload through `hooks ingest`, the canonical event is still emitted; pass `--kind all` (or an explicit list) on `events wait`/`list` to surface it.

The adapter is observability-only. It never approves, denies, or changes a permission decision.

Native lifecycle events can be multiple per turn. Keep raw events intact and branch on the event kind; do not treat them as task truth.
Use the mark returned by `prompt` with `events wait --since-mark` so older native events do not wake the manager.

## Recovery

Use `read`, `search`, and `attach` only for inherited sessions, debugging, or evidence checks. They are not the routine manager-agent notification path.

Gemini and generic terminal sessions currently have profile-aware keys but no native hook wiring in `agent-tmux`. Use transcript recovery commands for those until the CLI exposes a stable hook/event API.
