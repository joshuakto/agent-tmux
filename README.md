# agent-tmux

Vendor-neutral tmux session manager for shared human-agent terminals.

`agent-tmux` gives terminal agents a stable way to launch, inspect, attach to, interrupt, and manage project-local tmux sessions that humans can watch and interfere with live. It works with Claude Code, Codex, shell scripts, and other terminal agents because the shared interface is a normal CLI.

## What It Provides

- one project-local tmux server, usually at `.agent/tmux.sock`
- multiple named sessions for agents, shells, dev servers, test watchers, and REPLs
- a lightweight registry at `.agent/tmux.d/registry.json`
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
agent-tmux launch --session reviewer --purpose review --run "claude --name reviewer"
agent-tmux report
agent-tmux list
agent-tmux status reviewer
agent-tmux read reviewer --lines 120
agent-tmux read reviewer --all --number
agent-tmux search reviewer "error|failed" --ignore-case --context 3
agent-tmux wait reviewer "tests passed|failed" --ignore-case --timeout 120
agent-tmux dump reviewer --all
agent-tmux send reviewer "npm test"
agent-tmux prompt reviewer --agent claude "What is your current status?"
agent-tmux action reviewer submit --agent claude
agent-tmux interrupt reviewer
agent-tmux attach reviewer
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

Launch a session with:
agent-tmux launch --session <name> --purpose <purpose> --run "<command>"

Report status with:
agent-tmux report

Read output with:
agent-tmux read <session> --lines 120

Search deeper history with:
agent-tmux search <session> "<pattern>" --context 3

Wait for a progress signal with:
agent-tmux wait <session> "<pattern>" --timeout 120

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

The socket and registry are runtime state. They should not be source-controlled.
