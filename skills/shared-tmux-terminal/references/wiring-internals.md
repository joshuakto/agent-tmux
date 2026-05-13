# Wiring Internals

Implementation details for the native-hook wiring per vendor. Read this only when debugging the hook plumbing, adding a new vendor, or troubleshooting an unexpected file — normal use never needs it.

## Recognized `--run` Binaries

`agent-tmux` infers `--agent` from the basename of the first token of `--run`. Recognized basenames:

| Binary | Inferred profile | Wiring style |
| --- | --- | --- |
| `claude` | claude | session-local `--settings <file>` |
| `codex` | codex | session-local wrapper exec'ing `codex -c <inline-toml>` |
| `opencode` | opencode | profile-aware keys only — no native hooks yet |
| `gemini` | gemini | profile-aware keys only — no native hooks yet |

To add another binary, add a row to `RUN_BINARY_TO_PROFILE` in `tmux_session.py` and follow the "Adding a New Vendor" checklist below.

## Vendor Event → Canonical Kind

`hooks ingest` normalizes vendor event names to canonical kinds. The current mapping:

| Vendor event | Canonical kind |
| --- | --- |
| `Stop`, `SubagentStop`, `AfterAgent` | `agent_stop` |
| `StopFailure` | `hook_error` |
| `Notification` | `needs_input` |
| `PermissionRequest` | `permission_request` |
| `SessionStart` | `session_started` |
| `UserPromptSubmit` | `prompt_submitted` |
| `PreToolUse`, `PostToolUse` | `tool_event` |
| anything else | `agent_event` |

## Claude Code

Files written:

```text
.agent/tmux.d/hooks/<session>/claude-settings.json
```

Run command rewrite:

```bash
claude ...  →  claude --settings .agent/tmux.d/hooks/<session>/claude-settings.json ...
```

Wired events: `Stop`, `SubagentStop`, `StopFailure`, `Notification`, `PermissionRequest`, `UserPromptSubmit`. Does not edit `~/.claude/` or project `.claude/` settings.

## Codex CLI

Files written:

```text
.agent/tmux.d/hooks/<session>/codex-hooks.toml
.agent/tmux.d/hooks/<session>/codex-with-hooks
```

Run command rewrite:

```bash
codex ...  →  .agent/tmux.d/hooks/<session>/codex-with-hooks ...
```

The wrapper exec's `codex -c "$(cat .agent/tmux.d/hooks/<session>/codex-hooks.toml)" ...`. The TOML is a single inline `hooks={Stop=[...],PermissionRequest=[...],UserPromptSubmit=[...]}` table. `SessionStart` is not wired — `launch` already emits `session_started`/`session_reused`/`session_recovered`. `UserPromptSubmit` is wired for prompt delivery confirmation, not as a manager attention event.

Codex requires hook trust. `agent-tmux` runs `codex app-server -c <config>` and exchanges `initialize` + `hooks/list` messages to capture each hook's `currentHash`, then re-launches Codex with `state={<key>={trusted_hash=...}}` injected so the session sees them as trusted. If trust verification fails, the launch falls back to an unverified config and surfaces `codex hook trust: unverified` in the report.

## opencode CLI and Gemini CLI

These profiles currently provide prompt/action key behavior only. They do not write hook files or rewrite the run command for native event ingestion. Use transcript reads and board memos as the reliable supervision path until the CLI exposes a stable event surface that maps cleanly to `agent_stop`, `needs_input`, and `permission_request`.

## Adding a New Vendor

A new vendor needs four things:

1. An entry in `AGENT_PROFILES` with stable `submit`/`interrupt`/`eof`/`escape`/`clear` keys. Keep profiles conservative — no task-status heuristics, no auto-approval, no UI text parsing. If a CLI changes its UI, update only the key sequence and validate with a small live session.
2. An entry in `RUN_BINARY_TO_PROFILE` mapping the canonical binary basename to the profile.
3. A `<vendor>_hook_*` writer in `write_hook_settings` returning `(settings_path, status, warning, hook_config)`.
4. A `wire_<vendor>_run_command` in `launch` that rewrites the run command to invoke the wrapper or injects a settings flag.

Wiring preferences, in order:

- If the vendor exposes a `--settings <file>` or `-c <inline>` mechanism, use that.
- If not, use a session-local wrapper that exec's the vendor binary with the right flags.
- Avoid project-scope file writes unless there is no session-local alternative, and document any unavoidable side effect in the launch report.

If the vendor's per-call events fire on every tool invocation, do NOT wire them as attention events — map them to `tool_event` in `hook_kind` if you wire them at all. If a new CLI renders poorly, improve the terminal-sequence normalizer, not the agent profile, unless the problem is an input key.
