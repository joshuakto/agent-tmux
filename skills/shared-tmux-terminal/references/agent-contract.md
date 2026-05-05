# Agent Contract

`agent-tmux` is the vendor-neutral control surface for shared human-agent terminals.

Use it from Codex, Claude Code, shell scripts, or any terminal agent. Do not rely on editor-specific terminal internals when a live, inspectable, interruptible session is needed.

## Commands

```bash
agent-tmux launch --session reviewer --purpose review --run "claude --name reviewer"
agent-tmux report
agent-tmux list
agent-tmux status reviewer
agent-tmux read reviewer --lines 120
agent-tmux send reviewer "npm test"
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

## Runtime State

By default, runtime files live under the project:

```text
.agent/tmux.sock
.agent/tmux.d/registry.json
```

The wrapper `.agent/tmux` may be committed. Runtime files should be ignored.
