# Human Tmux Reference

Use this when a human wants to inspect or interfere with shared sessions directly.

## Attach

Prefer the no-arg project wrapper command shown by `report`:

```bash
.agent/tmux attach
```

With one live session it attaches directly. With multiple live sessions it lands you in a benign internal session named `__agent_tmux_picker__` (the "lobby") and overlays the picker on top, so dismissing the picker leaves you in the lobby instead of in a working agent's pane. The lobby is hidden from `list`, `report`, and the picker itself; the name is reserved.

The `agent-tmux attach` command uses the lobby even when run from inside the project tmux server. The profile keybinding (`Prefix S`) intentionally keeps the faster in-place overlay, so dismissing that picker returns to the pane where the shortcut was pressed.

Direct attach still works when you know the session:

```bash
.agent/tmux attach <session>
```

Equivalent raw tmux form for direct attach:

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

The profile is applied automatically by `launch` and `attach`. It enables mouse support, larger scrollback, pane labels, a compact status line, navigation bindings, and turns off `automatic-rename` so window names stay stable instead of inheriting the foreground process's title (e.g. Claude Code's version string). It does not write `~/.tmux.conf`.

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
