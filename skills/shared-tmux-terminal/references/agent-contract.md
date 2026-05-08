# Agent Contract

Give terminal agents this concise contract when they need shared tmux access.

```text
Use agent-tmux for shared interactive terminal work.
Run from the project root, or pass --cwd /path/to/project.

Golden path for supervising terminal agents:
1. Launch with:
   agent-tmux launch --session <name> --agent claude --events --require-events --purpose <purpose> --run "claude --name <name>" --log
2. Report the session:
   agent-tmux report
3. Send terminal-agent instructions with:
   agent-tmux prompt <session> --agent claude "<instruction; when finished or blocked, run: agent-tmux board post --topic <topic> \"concise status memo\">"
4. Use the mark returned by prompt to wait for new attention events:
   agent-tmux events wait --session <session> --kind board_post,needs_input,permission_request,agent_stop,hook_error --since-mark <mark-id> --ack --json --timeout 1800
5. If the event is board_post, read the memo:
   agent-tmux board read <message-id>
6. Use transcript reads only for recovery or evidence:
   agent-tmux read <session> --since-mark <mark-id> --lines 120
7. If the session seems missing or socket access fails:
   agent-tmux doctor --question "<what looked wrong>" --context "<what you were doing>"
8. If a human wants to inspect:
   agent-tmux attach <session>

Do not treat logs, marks, or wait output as task truth.
Task truth comes from artifacts, tests, commits, process exit status, and explicit reports.
```

If a project wrapper exists, use `.agent/tmux` instead of `agent-tmux`.

## Manager-Agent Contract

When supervising another terminal agent, use events and board messages to avoid repeated pane polling:

```text
Launch with native event wiring when supported:
agent-tmux launch --session <name> --agent claude --events --require-events --purpose <purpose> --run "claude --name <name>" --log
agent-tmux launch --session <name> --agent codex --events --require-events --purpose <purpose> --run "codex" --log

Send work:
agent-tmux prompt <session> --agent claude "<instruction; when finished or blocked, run: agent-tmux board post --topic <topic> \"concise status memo\">"
agent-tmux prompt <session> --agent codex "<instruction; when finished or blocked, run: agent-tmux board post --topic <topic> \"concise status memo\">"

Wait for the next attention event:
agent-tmux events wait --session <session> --kind board_post,needs_input,permission_request,agent_stop,hook_error --since-mark <mark-id> --ack --json --timeout 1800

If the event is board_post, read the referenced board memo:
agent-tmux board read <message-id>

Use transcript reads only for recovery or evidence checks.
```

Events are wakeups. Board posts are durable memos and infer poster/session from the current managed tmux pane. Neither is task truth.

For recovery tools, read `references/recovery.md`. For profile behavior, read `references/agent-profiles.md`.

## Runtime State

```text
.agent/tmux.sock
.agent/tmux.d/registry.json
.agent/tmux.d/marks.json
.agent/tmux.d/events/
.agent/tmux.d/hooks/
.agent/tmux.d/doctor/events.jsonl
.agent/tmux.d/logs/
.agent/board/
```

The wrapper `.agent/tmux` may be committed. Runtime files should be ignored.
