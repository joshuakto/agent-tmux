# Agent Profiles

Agent profiles map common terminal-agent actions to tmux key sequences. They are intentionally conservative: they cover submission, interruption, exit, escape, and clear-screen actions. They do not auto-approve edits or permissions.

## Profiles

```bash
agent-tmux profiles                  # list all built-in profiles
agent-tmux profiles --agent <name>   # show one profile
```

Profiles keep vendor-specific key quirks behind `prompt` and `action`. For the list of profiles and which `--run` binaries auto-infer them, see `references/wiring-internals.md`.

## Interaction Pattern

Use `prompt` when you want to send a user message to a terminal agent:

```bash
agent-tmux prompt reviewer "Summarize current status."
```

`prompt` and `action` infer the agent profile from the session registry. At `launch`, `--agent` is also inferred from the `--run` binary basename when it matches a recognized profile; pass `--agent` explicitly to override or when the binary basename is unknown.

`prompt` creates a transcript mark before sending by default. The mark is an out-of-band log offset and event cursor, not text typed into the terminal. In the manager-agent loop, use it with `events wait --since-mark`. Use transcript reads only when you need raw terminal evidence:

```bash
agent-tmux read reviewer --since-mark <mark-id> --lines 120
agent-tmux wait reviewer "complete|failed" --since-mark <mark-id> --timeout 300
```

Use `action` when text is already present in the terminal UI or when you need a non-text key:

```bash
agent-tmux action reviewer submit
agent-tmux action reviewer interrupt
agent-tmux action reviewer escape
```

Use raw keys only when the profile action does not exist:

```bash
agent-tmux raw keys reviewer Tab Enter
```

## Current Conservative Actions

Most built-in profiles expose the same stable actions:

```text
submit: Enter
interrupt: C-c
eof: C-d
escape: Escape
clear: C-l
```

OpenCode and Pi use their documented TUI defaults instead:

```text
submit: Enter
interrupt: Escape
eof: C-d
escape: Escape
clear: C-c
```

OpenCode documents `session_interrupt: escape` and `input_clear: ctrl+c` in its keybinds (`https://opencode.ai/docs/keybinds/`). Pi documents `app.interrupt: escape` and `app.clear: ctrl+c` in its keybindings (`https://pi.dev/docs/latest/keybindings`). The codex profile additionally applies a 300ms post-submit delay (`submit_delay_seconds: 0.3`) to give its TUI time to register the keypress.

Profiles are one place to document and change vendor-specific interaction behavior later. Transcript readability is shared across agents — `read --since-mark` and `wait --from-now` normalize common terminal control sequences. For the rules on adding a new profile, see `references/wiring-internals.md`.
