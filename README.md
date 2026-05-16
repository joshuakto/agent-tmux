# agent-tmux

Vendor-neutral tmux session manager for shared human-agent terminals.

`agent-tmux` gives terminal agents a stable way to launch, inspect, attach to, interrupt, and manage project-local tmux sessions that humans can watch and interfere with live. It works with Claude Code, Codex, shell scripts, and other terminal agents because the shared interface is a normal CLI.

tmux still owns the live terminal state. `agent-tmux` is the control and reporting layer around it.

## Install

Requires tmux ≥ 3.2 (the attach-picker uses `choose-tree -f` filtering).
The session name `__agent_tmux_picker__` is reserved for an internal
attach-picker lobby and cannot be used for user sessions.

Clone the repo:

```bash
git clone https://github.com/joshuakto/agent-tmux ~/.agent-tmux
```

Install the CLI:

```bash
~/.agent-tmux/bin/agent-tmux install-bin
```

Install the per-project wrapper from inside a project:

```bash
agent-tmux install-wrapper
```

The wrapper is intentionally small. It forwards to `agent-tmux` and does not store state.

## Golden Path

```bash
agent-tmux launch --session reviewer --events --require-events --purpose review --run "claude --name reviewer" --log
agent-tmux report
agent-tmux prompt reviewer "Run tests. When finished or blocked, run: agent-tmux board post --topic review \"concise status memo\""
agent-tmux events wait --session reviewer --since-mark <mark-id> --ack --json --timeout 1800
agent-tmux board read <message-id>
```

With the project wrapper, replace `agent-tmux` with `.agent/tmux`.

`prompt` infers the agent profile from the session registry and prints the pre-send transcript mark in its receipt. `events wait` and `events list` default `--kind` to the manager attention set (`board_post,needs_input,permission_request,agent_stop,hook_error`); pass `--kind all` to widen, or an explicit comma-separated list to narrow.

`--require-events` makes event wiring reliable for native-hook profiles: launch fails if hooks cannot be wired or if the run-command binary is not resolvable on `PATH` or as an absolute executable. Wiring is session-local under `.agent/tmux.d/hooks/<session>/`; no global user settings are edited. Relative paths with separators (e.g. `./bin/claude`) are rejected — pass an absolute path or a `PATH`-resolvable name. Recognized `--run` basenames (`claude`, `codex`, `opencode`, `pi`, `gemini`) and per-vendor specifics live in `skills/shared-tmux-terminal/references/wiring-internals.md`.

Events are wakeups for the manager agent. Board posts are durable memos. Neither is task truth. Branch on the returned event kind: read memos for `board_post`, inspect/ask for `needs_input` or `permission_request`, recover from `agent_stop` without a memo, and diagnose `hook_error`.

## What It Provides

- one project-local tmux server, usually at `.agent/tmux.sock`
- multiple named sessions for agents, shells, dev servers, test watchers, and REPLs
- guarded cleanup: `kill <session>` drops the registry entry and tears down the live session if any, refusing attached or multi-window live sessions without `--force`
- a registry under `.agent/tmux.d/registry.json`
- diagnostics under `.agent/tmux.d/doctor/events.jsonl`
- pane transcripts under `.agent/tmux.d/logs/`
- transcript marks under `.agent/tmux.d/marks.json`
- one-file-per-event manager events under `.agent/tmux.d/events/events/`
- one-file-per-message board memos under `.agent/board/`
- session-local native hook ingestion for Claude Code, Codex CLI, and OpenCode
- a project wrapper at `.agent/tmux`
- Claude Code plugin metadata at `.claude-plugin/plugin.json`
- Codex skill metadata under `skills/shared-tmux-terminal`

## Basic Shared Terminal Path

For shells, REPLs, dev servers, and inherited sessions that do not need native agent events:

```bash
agent-tmux launch --session shell --purpose repl --run "bash" --log
agent-tmux raw send shell "pwd"
agent-tmux read shell --lines 120
agent-tmux wait shell "ready|failed" --from-now --timeout 300
agent-tmux attach shell
```

## References

Detailed documentation lives in `skills/shared-tmux-terminal/references/`:

- `agent-contract.md`: reusable agent instruction block for handing the contract to terminal agents.
- `manager-events.md`: event-driven manager-agent loop, default kind filter, full event meaning, field lessons.
- `board.md`: append-only memo board for durable agent memos.
- `hooks.md`: native hook ingestion, canonical event kinds, the reliable launch path.
- `wiring-internals.md`: recognized `--run` binaries, per-vendor file layout, rules for adding a new vendor.
- `agent-profiles.md`: terminal-agent input profiles and profile inference.
- `recovery.md`: missing sessions, stale history, stuck processes, layout recovery.
- `human-tmux.md`: attach, mouse scrolling, tmux profile, pane/window navigation for humans.

## Diagnostics

Run commands from the project root, or pass `--cwd /path/to/project`. The default socket is project-local.

Use `doctor` when a human can see sessions that the agent cannot, when a socket error appears, or when registry state and live tmux state disagree:

```bash
agent-tmux doctor --question "<what looked wrong>" --context "<what you were doing>"
```

`doctor` reports the resolved root, socket, registry, live sessions, and mismatches. It also appends structured JSONL events to `.agent/tmux.d/doctor/events.jsonl`.

## Project State

Commit:

```text
.agent/tmux
```

Ignore:

```text
.agent/tmux.sock
.agent/tmux.d/
.agent/board/
```

The socket, registry, marks, events, doctor events, dumps, transcripts, hooks, and board messages are runtime state. They should not be source-controlled.

## Claude Code Plugin

Claude Code auto-discovers skills from personal skills, project skills, and installed plugins. This repository is also a Claude Code plugin: it has `.claude-plugin/plugin.json`, `skills/shared-tmux-terminal/SKILL.md`, and `bin/agent-tmux`.

For local testing:

```bash
claude --plugin-dir ~/.agent-tmux
```

Inside Claude Code, the skill is available as `/agent-tmux:shared-tmux-terminal`. Claude can also invoke it automatically when the request matches the skill description. The plugin `bin/` directory is added to Claude Code's Bash tool `PATH` while the plugin is enabled, so `agent-tmux` is available to the agent.

For shared installation, add this repository as a Claude Code plugin marketplace or install it as a project/personal skill by copying `skills/shared-tmux-terminal` into `.claude/skills/` or `~/.claude/skills/`.

## Codex Skill

Install the Codex adapter with:

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo joshuakto/agent-tmux \
  --path skills/shared-tmux-terminal
```

Restart Codex after installing the skill.
