# Agent Contract

`agent-tmux` is the vendor-neutral control surface for shared human-agent terminals.

Use it from Codex, Claude Code, shell scripts, or any terminal agent. Do not rely on editor-specific terminal internals when a live, inspectable, interruptible session is needed.

Run commands from the project root. If the project root is uncertain, pass `--cwd /path/to/project`.

## Commands

```bash
agent-tmux launch --session reviewer --purpose review --run "claude --name reviewer" --log
agent-tmux report
agent-tmux list
agent-tmux doctor
agent-tmux status reviewer
agent-tmux log status reviewer
agent-tmux read reviewer --lines 120
agent-tmux read reviewer --all --number
agent-tmux search reviewer "error|failed" --ignore-case --context 3
agent-tmux wait reviewer "complete|failed|error" --ignore-case --timeout 120
agent-tmux dump reviewer --all
agent-tmux send reviewer "npm test"
agent-tmux prompt reviewer --agent claude "What are you working on?"
agent-tmux action reviewer submit --agent claude
agent-tmux interrupt reviewer
agent-tmux attach reviewer
```

If a project wrapper exists, use `.agent/tmux` instead of `agent-tmux`.

## Agent Behavior

After every launch or layout change, report:

- session name
- socket path
- attach command
- pane list
- active pane
- recent visible output

Treat tmux state as shared. A human can attach concurrently, change pane focus, send input, or interrupt a process.

If `list`, `report`, or `status` conflicts with what the human sees, run:

```bash
agent-tmux doctor --question "<what looked wrong>" --context "<what you were doing>"
```

Do not conclude a session is absent from a socket error. `doctor` records structured JSONL diagnostics under `.agent/tmux.d/doctor/events.jsonl`.

Use transcript logging for long-running agents:

```bash
agent-tmux log start <session>
agent-tmux log status <session>
agent-tmux log stop <session>
```

Prefer `launch --log` when starting new long-running sessions.

Use `prompt` instead of `send` when interacting with terminal agents such as Claude Code, Codex, or Gemini CLI. `prompt` sends text and then submits with the selected agent profile. Use `action submit` when text is already sitting in the input area.

Use deeper inspection before deciding a task is stuck:

```bash
agent-tmux read <session> --lines 500
agent-tmux read <session> --all --number
agent-tmux search <session> "<pattern>" --context 3
agent-tmux wait <session> "<pattern>" --timeout 120
agent-tmux dump <session> --all
```

For `read`, `search`, `wait`, and `dump`, `--lines N` means the last N captured lines. Use `read --start`, `read --end`, or `--all` for explicit tmux history slices.

For profile details, read `references/agent-profiles.md`.

## Runtime State

By default, runtime files live under the project:

```text
.agent/tmux.sock
.agent/tmux.d/registry.json
.agent/tmux.d/doctor/events.jsonl
.agent/tmux.d/logs/
```

The wrapper `.agent/tmux` may be committed. Runtime files should be ignored.
