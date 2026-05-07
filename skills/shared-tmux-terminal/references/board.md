# Board

Use the board for concise, durable memos between agents and humans.

## Commands

```bash
agent-tmux board post --topic exp12-next-steps --from claude-roadmap --body-file memo.md
agent-tmux board post --topic exp12-next-steps --from claude-roadmap "Short memo."
agent-tmux board list --topic exp12-next-steps
agent-tmux board read <message-id>
```

`board post` writes one immutable Markdown file and emits a `board_post` event.
When run inside a managed tmux pane, it auto-associates the post with that session. Use `--session` only when posting from outside the pane or overriding the association.

## Storage

```text
.agent/board/threads/<topic>/<message-id>.md
```

Rules:

- One message per file.
- Do not edit old messages; post a correction instead.
- Do not treat board messages as task truth.
- Reference artifacts, commands, branches, tests, and tmux sessions from the memo.

The board avoids scraping long TUI output when a worker agent can publish a clean result.
