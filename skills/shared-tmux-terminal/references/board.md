# Board

Use the board for concise, durable memos between agents and humans.

## Commands

```bash
agent-tmux board post --topic exp12-next-steps "Short memo."
agent-tmux board post --topic exp12-next-steps --body-file memo.md
agent-tmux board post --topic exp12-next-steps --from manager "Short memo from outside tmux."
agent-tmux board list --topic exp12-next-steps --limit 5
agent-tmux board read <message-id>
```

`board post` writes one immutable Markdown file and emits a `board_post` event.
When run inside a managed tmux pane, it infers the poster and session from that pane. Outside a managed pane, pass `--from <name>`. Use `--session` only when posting from outside the pane or overriding the association.
For long memos, prefer `--body-file` or stdin over a shell-quoted one-liner.

## Storage

```text
.agent/board/threads/<topic>/<message-id>.md
```

Topic names are slugified on disk: lowercased, spaces and non-alphanumeric characters replaced with hyphens. `"My Review"` becomes `my-review`.

Rules:

- One message per file.
- Do not edit old messages; post a correction instead.
- Do not treat board messages as task truth.
- Reference artifacts, commands, branches, tests, and tmux sessions from the memo.

The board avoids scraping long TUI output when a worker agent can publish a clean result.
