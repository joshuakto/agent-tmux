# Wiring Internals

Implementation details for the native-hook wiring per vendor. Read this only when debugging the hook plumbing, adding a new vendor, or troubleshooting an unexpected file — normal use never needs it.

## Recognized `--run` Binaries

`agent-tmux` infers `--agent` from the basename of the first token of `--run`. Recognized basenames:

| Binary | Inferred profile | Wiring style |
| --- | --- | --- |
| `claude` | claude | session-local `--settings <file>` |
| `codex` | codex | session-local wrapper exec'ing `codex -c <inline-toml>` |
| `opencode` | opencode | session-local wrapper setting `OPENCODE_CONFIG_DIR` |
| `pi` | pi | profile-aware keys only — no native hooks |
| `gemini` | gemini | profile-aware keys only — no native hooks yet |

To add another binary, add a row to `RUN_BINARY_TO_PROFILE` in `tmux_session.py` and follow the "Adding a New Vendor" checklist below.

## Vendor Event → Canonical Kind

`hooks ingest` normalizes vendor event names to canonical kinds. The current mapping:

| Vendor event | Canonical kind |
| --- | --- |
| `Stop`, `SubagentStop`, `AfterAgent` | `agent_stop` |
| `StopFailure`, `session.error` | `hook_error` |
| `Notification` | `needs_input` |
| `PermissionRequest`, `permission.asked` | `permission_request` |
| `session.idle` | `agent_stop` |
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

Codex requires hook trust. `agent-tmux` runs `codex app-server -c <config>` and exchanges `initialize` + `hooks/list` messages to capture each hook's `currentHash`, then re-launches Codex with `state={<key>={trusted_hash=...}}` injected so the session sees them as trusted. If trust verification fails, the launch falls back to an unverified config and surfaces `hook trust: unverified` in the report.

## OpenCode CLI

Files written:

```text
.agent/tmux.d/hooks/<session>/opencode-config/plugins/agent-tmux.js
.agent/tmux.d/hooks/<session>/opencode-with-hooks
```

Run command rewrite:

```bash
opencode ...  →  .agent/tmux.d/hooks/<session>/opencode-with-hooks ...
```

The wrapper sets `OPENCODE_CONFIG_DIR` to the session-local config directory, then execs the original `opencode` binary. `agent-tmux` refuses native event wiring when `--run` contains `--pure`, because OpenCode documents that flag as "Run without external plugins." It also refuses to replace a parent `OPENCODE_CONFIG_DIR`; that avoids silently dropping a user's custom config directory.

Wired events: `session.idle`, `permission.asked`, `session.error`. The generated plugin only observes events and synchronously invokes `hooks ingest --quiet`; it does not approve permissions, register tools, or change OpenCode behavior.

OpenCode loads local JavaScript/TypeScript plugins from config plugin directories, and config/plugin sources can co-exist with user project/global config. `agent-tmux` does not edit project `.opencode/` or global OpenCode config. If a user plugin also runs, it is OpenCode's normal plugin model, not a separate agent-tmux setup step.

OpenCode introduces vendor-loaded generated code. Claude and Codex artifacts are settings/config plus wrappers invoked by `agent-tmux`; OpenCode loads `agent-tmux.js` in the vendor runtime. Keep that bridge tiny, dependency-free, and observer-only so a bridge bug can at worst lose or report hook events rather than alter the agent's decisions.

## Pi CLI and Gemini CLI

These profiles currently provide prompt/action key behavior only. They do not write hook files or rewrite the run command for native event ingestion. `--events --require-events --run "pi ..."` fails clearly as unsupported native hooks. Use transcript reads and board memos as the reliable supervision path until the CLI exposes a stable event surface that maps cleanly without adding a generated extension path.

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
