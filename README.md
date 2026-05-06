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

## Usage

```bash
agent-tmux launch --session reviewer --purpose review --run "claude --name reviewer" --log
agent-tmux report
agent-tmux list
agent-tmux doctor
agent-tmux status reviewer
agent-tmux log status reviewer
agent-tmux mark reviewer --label before-test
agent-tmux read reviewer --lines 120
agent-tmux read reviewer --since-mark <mark-id> --lines 120
agent-tmux read reviewer --all --number
agent-tmux search reviewer "error|failed" --ignore-case --context 3
agent-tmux wait reviewer "tests passed|failed" --ignore-case --timeout 120
agent-tmux wait reviewer "tests passed|failed" --from-now --timeout 120
agent-tmux dump reviewer --all
agent-tmux send reviewer "npm test"
agent-tmux prompt reviewer --agent claude "What is your current status?"
agent-tmux action reviewer submit --agent claude
agent-tmux interrupt reviewer
agent-tmux attach reviewer
agent-tmux tmux-profile apply
```

With the project wrapper:

```bash
.agent/tmux report
.agent/tmux attach reviewer
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

Launch a session with:
agent-tmux launch --session <name> --purpose <purpose> --run "<command>" --log

Report status with:
agent-tmux report

If a session seems missing or socket access fails, diagnose with:
agent-tmux doctor --question "<what looked wrong>" --context "<what you were doing>"

Read output with:
agent-tmux read <session> --lines 120
agent-tmux read <session> --since-mark <mark-id> --lines 120

Search deeper history with:
agent-tmux search <session> "<pattern>" --context 3

Wait for a progress signal with:
agent-tmux wait <session> "<pattern>" --timeout 120
agent-tmux wait <session> "<pattern>" --from-now --timeout 120

Send input with:
agent-tmux send <session> "<text>"

Send a terminal-agent prompt with:
agent-tmux prompt <session> --agent claude "<prompt>"

Submit already-entered text with:
agent-tmux action <session> submit --agent claude

Interrupt stuck work with:
agent-tmux interrupt <session>

After every launch or layout change, report the session name, socket path, attach command, pane list, active pane, and a recent output sample.
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
```

The socket, registry, marks, doctor events, dumps, and transcripts are runtime state. They should not be source-controlled.
