# Human Tmux Reference

Use this when a human wants to inspect or interfere with shared sessions directly.

## Attach

Prefer the project wrapper command shown by `report`:

```bash
.agent/tmux attach <session>
```

Equivalent raw tmux form:

```bash
tmux -S /path/to/project/.agent/tmux.sock attach -t <session>
```

Multiple clients may attach to the same session. Humans can type, change panes, or interrupt while agents are also observing.

## Project Tmux Profile

Apply ergonomic settings to the project tmux server only:

```bash
agent-tmux tmux-profile show
agent-tmux tmux-profile apply
```

The profile enables mouse support, larger scrollback, pane labels, a compact status line, and navigation bindings. It does not write `~/.tmux.conf`.

## Navigation

With the profile applied:

```text
Prefix S  choose sessions
Prefix W  choose windows
Prefix P  display pane numbers
mouse     select panes and scroll history
```

Default tmux detach is usually:

```text
Prefix d
```

The default prefix is usually `Ctrl-b` unless the user's tmux config changes it.

## Human/Agent Coordination

- Tell the agent if you changed pane focus, typed into the UI, or interrupted a process.
- If the agent seems confused after human changes, ask it to run `report` or `status`.
- Logs and marks help navigate terminal output; they are not task status.
