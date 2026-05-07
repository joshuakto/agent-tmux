# Native Hooks

Use native hooks when a manager agent needs reliable wakeups from a terminal-agent session.

## Reliable Claude Path

```bash
agent-tmux launch --session reviewer --agent claude --events --require-events --run "claude --name reviewer" --log
agent-tmux prompt reviewer --agent claude "<task; post a board memo when done>"
agent-tmux events wait --session reviewer --kind board_post --ack --json --timeout 1800
```

`--require-events` fails launch unless `agent-tmux` can verify session-local hook wiring.

## Reliable Codex Path

```bash
agent-tmux launch --session reviewer --agent codex --events --require-events --run "codex" --log
agent-tmux prompt reviewer --agent codex "<task; post a board memo when done>"
agent-tmux events wait --session reviewer --kind board_post --ack --json --timeout 1800
```

Codex CLI hook config is passed through a short session-local wrapper. `agent-tmux` does not edit `~/.codex/hooks.json` or project config.

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

The wrapper runs `codex -c hooks=...` internally so the visible tmux command stays readable.

## Hook Adapter

```bash
agent-tmux hooks ingest --agent claude --session reviewer
agent-tmux hooks ingest --agent codex --session reviewer --quiet
agent-tmux hooks status reviewer
agent-tmux hooks show-config --agent claude --session reviewer
agent-tmux hooks show-config --agent codex --session reviewer
```

`hooks ingest` reads vendor hook JSON from stdin and emits canonical events such as `agent_stop`, `needs_input`, `permission_request`, and `hook_error`.

The adapter is observability-only. It never approves, denies, or changes a permission decision.

## Recovery

Use `read`, `search`, and `attach` only for inherited sessions, debugging, or evidence checks. They are not the routine manager-agent notification path.

Gemini and generic terminal sessions currently have profile-aware keys but no native hook wiring in `agent-tmux`. Use transcript recovery commands for those until the CLI exposes a stable hook/event API.
