---
name: shared-tmux-terminal
description: Launch, inspect, attach, and manage project-local tmux sessions for shared human-agent terminals. Use when an agent needs a visible terminal a human can watch, attach to, interrupt, or inspect while preserving shell state across multiple parallel sessions.
---

# Shared Tmux Terminal

Use this skill when a task needs a live terminal that both the agent and a human can share.

## Core Model

- One tmux server per project, usually at `./.agent/tmux.sock`.
- Multiple tmux sessions inside that server, one per agent or task.
- Humans can attach to any session and interfere live.
- Every agent uses the same vendor-neutral `agent-tmux` CLI for launch, read, send, report, and management.

## Default Workflow

1. Find the project root.
2. Launch or reuse the project tmux server.
3. Create a named session for the task.
4. Report the socket, session name, attach command, and current pane state.
5. Use the same session for follow-up sends, reads, and interrupts.

## Use The Helper Script

Prefer the CLI over ad hoc tmux commands:

```bash
agent-tmux launch --purpose build --run "claude --name build"
agent-tmux list
agent-tmux report
```

When a project has a wrapper, prefer the shorter form:

```bash
.agent/tmux launch --purpose build --run "claude --name build"
.agent/tmux list
.agent/tmux report
.agent/tmux send build-123 "npm test"
.agent/tmux read build-123 --lines 120
.agent/tmux interrupt build-123
.agent/tmux attach build-123
```

Install the wrapper in a project with:

```bash
agent-tmux install-wrapper
```

The wrapper must stay dumb: it only resolves and forwards to `agent-tmux`.

For Claude Code or other terminal agents, load `references/agent-contract.md` when you need a concise reusable instruction block.

## Reporting Contract

After every session launch or topology change, report:

- project root
- socket path
- session name(s)
- windows and panes
- active pane
- attach command
- a short visible-output sample from each pane

Keep the report compact. The goal is to make it easy for a human to join and easy for the agent to recover the current state.

## Management Rules

- Prefer one tmux server per project, not one server per agent.
- Use stable, descriptive session names.
- Treat the tmux session as shared state: humans may attach concurrently and change focus or input.
- Use `send` for literal commands, `keys` for raw tmux key sequences, and `interrupt` for Ctrl-C.
- If sessions need to be rearranged, use the helper script to move or join windows and panes rather than recreating them.
- Commit `.agent/tmux` if a project wants the convenience command; do not commit `.agent/tmux.sock` or `.agent/tmux.d/`.

## When To Use Extra Tmux Operations

- Split a session into more panes when the human should observe multiple tasks side by side.
- Move or join windows when you want a clean shared layout without restarting the running process.
- Kill only the session or pane you no longer need; do not destroy a live session just to relabel it.

## Notes

- The socket path is project-local, but tmux persistence still depends on the tmux server process staying alive.
- This skill is for shared live terminals, not for recording or replaying terminal history after reboot.
- Distribution is the vendor-neutral `agent-tmux` CLI plus optional per-project wrapper. The Codex skill is only one adapter around the same CLI.
