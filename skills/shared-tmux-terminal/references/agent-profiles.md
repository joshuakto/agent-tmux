# Agent Profiles

Agent profiles map common terminal-agent actions to tmux key sequences. They are intentionally conservative: they cover submission, interruption, exit, escape, and clear-screen actions. They do not auto-approve edits or permissions.

## Profiles

```bash
agent-tmux profiles
agent-tmux profiles --agent claude
agent-tmux profiles --agent codex
agent-tmux profiles --agent gemini
agent-tmux profiles --agent generic
```

## Interaction Pattern

Use `prompt` when you want to send a user message to a terminal agent:

```bash
agent-tmux prompt reviewer --agent claude "Summarize current status."
```

`prompt` creates a transcript mark before sending by default. The mark is an out-of-band log offset, not text typed into the terminal. Use it to inspect only the response that followed the prompt:

```bash
agent-tmux read reviewer --since-mark <mark-id> --lines 120
agent-tmux wait reviewer "complete|failed" --since-mark <mark-id> --timeout 300
```

Use `action` when text is already present in the terminal UI or when you need a non-text key:

```bash
agent-tmux action reviewer submit --agent claude
agent-tmux action reviewer interrupt --agent claude
agent-tmux action reviewer escape --agent claude
```

Use raw keys only when the profile action does not exist:

```bash
agent-tmux keys reviewer Tab Enter
```

## Current Conservative Defaults

All built-in profiles currently share these stable actions:

```text
submit: Enter
interrupt: C-c
eof: C-d
escape: Escape
clear: C-l
```

Profiles are still valuable because they provide one place to document and change vendor-specific interaction behavior later.

## Adding Another CLI Agent

Keep profiles conservative. A profile should map stable input actions only:

```text
submit
interrupt
eof
escape
clear
```

Do not add task-status heuristics, auto-approval behavior, or UI text parsing to a profile. If a CLI changes its UI, update only the key sequence for the affected action and validate with a small live session.

Transcript readability is intentionally shared across agents. `read --since-mark` and `wait --from-now` normalize common terminal control sequences emitted by TUIs such as Claude Code, Codex CLI, and Gemini CLI. If a new CLI renders poorly, improve the terminal-sequence normalizer, not the agent profile, unless the problem is an input key.
