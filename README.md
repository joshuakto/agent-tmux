# agent-tmux

Vendor-neutral tmux session manager for shared human-agent terminals.

`agent-tmux` gives terminal agents a stable way to launch, inspect, attach to, interrupt, and manage project-local tmux sessions that humans can watch and interfere with live. It works with Claude Code, Codex, shell scripts, and other terminal agents because the shared interface is a normal CLI.

## What It Provides

- one project-local tmux server, usually at `.agent/tmux.sock`
- multiple named sessions for agents, shells, dev servers, test watchers, and REPLs
- a lightweight registry at `.agent/tmux.d/registry.json`
- diagnostics under `.agent/tmux.d/doctor/events.jsonl`
- optional pane transcripts under `.agent/tmux.d/logs/`
- transcript marks under `.agent/tmux.d/marks.json` for reading only new output
- append-only manager-agent events under `.agent/tmux.d/events/`
- append-only board messages under `.agent/board/`
- optional native hook ingestion for supported terminal agents
- read/write controls through `send`, `read`, `keys`, `interrupt`, `split`, `join-pane`, and `move-window`
- a dumb project wrapper at `.agent/tmux`
- Claude Code plugin metadata at `.claude-plugin/plugin.json`
- optional Codex skill metadata under `skills/shared-tmux-terminal`

tmux still owns the live terminal state. `agent-tmux` is the control and reporting layer around it.

## Install

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
agent-tmux launch --session reviewer --purpose review --run "claude --name reviewer" --log
agent-tmux report
agent-tmux prompt reviewer --agent claude "Run tests and report failures."
agent-tmux read reviewer --since-mark <mark-id> --lines 120
agent-tmux wait reviewer "tests passed|failed" --since-mark <mark-id> --timeout 300
agent-tmux search reviewer "error|failed" --ignore-case --context 3
agent-tmux doctor --question "why did the session disappear?" --context "human can still see it"
agent-tmux attach reviewer
```

With the project wrapper:

```bash
.agent/tmux report
.agent/tmux attach reviewer
```

Use the golden path for routine agent supervision. Logs and marks are navigation aids; artifacts, tests, commits, process exit status, and explicit reports are task truth.

## Manager-Agent Path

When one agent is supervising other terminal agents, prefer event-driven coordination over repeated pane polling:

```bash
agent-tmux launch --session reviewer --agent claude --events --require-events --purpose review --run "claude --name reviewer" --log
agent-tmux prompt reviewer --agent claude "Run tests and post a concise memo."
agent-tmux events wait --session reviewer --kind board_post,needs_input,permission_request,agent_stop,hook_error --ack --json --timeout 1800
```

For Codex CLI:

```bash
agent-tmux launch --session reviewer --agent codex --events --require-events --purpose review --run "codex" --log
agent-tmux prompt reviewer --agent codex "Run tests and post a concise memo."
agent-tmux events wait --session reviewer --kind board_post,needs_input,permission_request,agent_stop,hook_error --ack --json --timeout 1800
```

`--require-events` makes event wiring reliable: launch fails if native hooks cannot be wired. For Claude Code, `agent-tmux` writes a session-local settings file under `.agent/tmux.d/hooks/<session>/` and injects `--settings <file>` into simple `claude ...` launch commands. For Codex CLI, it writes the equivalent hook config plus a short session-local wrapper under `.agent/tmux.d/hooks/<session>/` and rewrites simple `codex ...` launch commands to use that wrapper. It does not edit global user settings or project settings.

Events are wakeups for the manager agent. Board posts are durable memos. `board post` auto-associates with the current session when run inside a managed tmux pane. Neither is task truth. Branch on the returned event kind: read memos for `board_post`, inspect/ask for `needs_input` or `permission_request`, recover from `agent_stop` without a memo, and diagnose `hook_error`.

## Advanced Commands

Use these when recovering, debugging, or arranging sessions:

```bash
agent-tmux list
agent-tmux status reviewer
agent-tmux log status reviewer
agent-tmux mark reviewer --label before-test
agent-tmux read reviewer --lines 120
agent-tmux read reviewer --all --number
agent-tmux wait reviewer "tests passed|failed" --from-now --timeout 120
agent-tmux dump reviewer --all
agent-tmux send reviewer "npm test"
agent-tmux action reviewer submit --agent claude
agent-tmux interrupt reviewer
agent-tmux tmux-profile apply
```

Manager-agent coordination commands:

```bash
agent-tmux events emit --kind needs_input --session reviewer --summary "Need approval"
agent-tmux events list --unread --kind board_post,needs_input,permission_request,agent_stop,hook_error
agent-tmux events wait --session reviewer --kind board_post,needs_input,permission_request,agent_stop,hook_error --timeout 1800 --ack
agent-tmux events ack <event-id>
agent-tmux board post --topic review --from reviewer --body-file memo.md
agent-tmux board list --topic review
agent-tmux board read <message-id>
agent-tmux hooks status reviewer
agent-tmux hooks show-config --agent claude --session reviewer
agent-tmux hooks show-config --agent codex --session reviewer
```

## Reading Past The Viewport

The current tmux viewport is rarely enough for agent supervision. Use history-aware commands:

```bash
agent-tmux read reviewer --lines 500
agent-tmux read reviewer --start -2000 --number
agent-tmux read reviewer --all --number
agent-tmux search reviewer "error|failed|stuck" --ignore-case --context 3
agent-tmux wait reviewer "complete|failed|error" --ignore-case --timeout 120
agent-tmux dump reviewer --all
```

`dump` writes a capture file under `.agent/tmux.d/dumps/` unless `--output` is provided.
For `read`, `search`, `wait`, and `dump`, `--lines N` means the last N captured lines. Use `--start`, `--end`, or `--all` when you need an explicit tmux history slice.

## Reading Only New Output

When supervising terminal agents, prefer transcript marks over asking the target agent for status. Marks are out-of-band byte offsets in the transcript log; they are not typed into the pane and cannot collide with real terminal output.

`prompt` creates a pre-send mark by default:

```bash
agent-tmux prompt reviewer --agent claude "Run tests and report failures."
# prompt sent: target=reviewer:0.0 profile=claude submitted=yes mark=m_...
agent-tmux read reviewer --since-mark m_... --lines 120
agent-tmux wait reviewer "tests passed|failed" --since-mark m_... --timeout 300
```

Create marks manually or wait only on output appended after invocation:

```bash
agent-tmux mark reviewer --label before-test
agent-tmux wait reviewer "complete|failed" --from-now --timeout 300
```

Marks require transcript logging. `prompt`, `mark`, and `wait --from-now` will start `agent-tmux` transcript logging for the target pane if needed.

## Diagnostics And Logs

Run commands from the project root, or pass `--cwd /path/to/project`. This matters because the default socket is project-local.

Use `doctor` when a human can see sessions that the agent cannot, when a socket error appears, or when registry state and live tmux state disagree:

```bash
agent-tmux --cwd /path/to/project doctor \
  --question "why did list not show the session?" \
  --context "human can see claude-p113 attached in Zed"
```

`doctor` reports the resolved root, socket, registry, live sessions, and mismatches. It also appends structured JSONL events to `.agent/tmux.d/doctor/events.jsonl` so tool failures can be reviewed later without turning runtime status into a second source of truth.

For durable terminal history, start transcript logging:

```bash
agent-tmux launch --session reviewer --purpose review --run "claude --name reviewer" --log
agent-tmux log start reviewer
agent-tmux log status reviewer
agent-tmux log stop reviewer
```

Logs are written under `.agent/tmux.d/logs/` by default. They are raw terminal transcripts and may contain ANSI escape codes.

## Events And Board

Events are one-file-per-event JSON records under `.agent/tmux.d/events/events/`, with per-consumer acknowledgements under `.agent/tmux.d/events/acks/`. This avoids append races and lets a supervising agent block on:

```bash
agent-tmux events wait --session reviewer --kind board_post,needs_input,permission_request,agent_stop,hook_error --timeout 1800
```

Board messages are one immutable Markdown file per post under `.agent/board/threads/<topic>/`. Use the board for concise worker-agent memos when terminal TUI output is hard to read:

```bash
agent-tmux board post --topic exp12-next-steps --from reviewer --body-file memo.md
agent-tmux board list --topic exp12-next-steps
agent-tmux board read <message-id>
```

`board post` emits a `board_post` event automatically and infers the session when run inside a managed tmux pane. For long memos, prefer `--body-file` or stdin. The manager-agent loop is: wait for an attention event, branch by kind, then decide.

## Native Hook Ingestion

Supported terminal-agent hooks can feed the event queue:

```bash
agent-tmux hooks ingest --agent claude --session reviewer
agent-tmux hooks status reviewer
agent-tmux hooks show-config --agent claude --session reviewer
```

`hooks ingest` reads vendor hook JSON from stdin and emits canonical events such as `agent_stop`, `needs_input`, and `permission_request`. It is observability-only: it never approves, denies, or changes a permission decision.

Claude launch wiring is session-local:

```bash
agent-tmux launch --session reviewer --agent claude --events --require-events --run "claude --name reviewer" --log
agent-tmux launch --session reviewer --agent codex --events --require-events --run "codex" --log
```

If the launch command is not a simple `claude ...` or `codex ...` invocation, `--require-events` fails with a concrete reason. Existing `read`, `wait`, `search`, and `attach` remain recovery tools for inherited sessions, debugging, and evidence checks.
Native lifecycle events can be multiple per turn; raw events are kept for observability rather than deduped.

## Human Tmux Profile

For easier human inspection, apply the optional project-local tmux profile:

```bash
agent-tmux tmux-profile show
agent-tmux tmux-profile apply
```

The profile affects only the project tmux server. It enables mouse support, larger scrollback, pane border labels, compact status text, and navigation bindings. It does not write `~/.tmux.conf` and is not required for CLI correctness.

## Agent UI Interaction

Use `prompt` for terminal agents, not raw `send`, when the target is an interactive agent UI:

```bash
agent-tmux prompt reviewer --agent claude "Summarize your progress and blockers."
agent-tmux prompt reviewer --agent codex "Run the focused test and report the failure."
agent-tmux prompt reviewer --agent gemini "Inspect the current pane history."
```

If text is already sitting in the UI, submit it explicitly:

```bash
agent-tmux action reviewer submit --agent claude
```

Inspect available profiles and actions:

```bash
agent-tmux profiles
agent-tmux profiles --agent claude
```

## Agent Instructions

Give terminal agents this contract:

```text
Use agent-tmux for shared interactive terminal work.
Run it from the project root, or pass --cwd /path/to/project.

Golden path:

agent-tmux launch --session <name> --purpose <purpose> --run "<command>" --log
agent-tmux report
agent-tmux prompt <session> --agent claude "<instruction>"
agent-tmux read <session> --since-mark <mark-id> --lines 120
agent-tmux wait <session> "<pattern>" --since-mark <mark-id> --timeout 300

If a session seems missing or socket access fails, diagnose with:
agent-tmux doctor --question "<what looked wrong>" --context "<what you were doing>"

If a human wants to inspect:
agent-tmux attach <session>

Do not treat logs, marks, or wait output as task truth.
Task truth comes from artifacts, tests, commits, process exit status, and explicit reports.
```

The same text is available in `skills/shared-tmux-terminal/references/agent-contract.md`.

## Claude Code Plugin

Claude Code auto-discovers skills from personal skills, project skills, and installed plugins. This repository is also a Claude Code plugin: it has `.claude-plugin/plugin.json`, `skills/shared-tmux-terminal/SKILL.md`, and `bin/agent-tmux`.

For local testing:

```bash
claude --plugin-dir ~/.agent-tmux
```

Inside Claude Code, the skill is available as:

```text
/agent-tmux:shared-tmux-terminal
```

Claude can also invoke it automatically when the request matches the skill description. The plugin `bin/` directory is added to Claude Code's Bash tool `PATH` while the plugin is enabled, so `agent-tmux` is available to the agent.

For shared installation, add this repository as a Claude Code plugin marketplace or install it as a project/personal skill by copying `skills/shared-tmux-terminal` into `.claude/skills/` or `~/.claude/skills/`.

## Codex Skill

Install the Codex adapter with:

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo joshuakto/agent-tmux \
  --path skills/shared-tmux-terminal
```

Restart Codex after installing the skill.

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
