# Agent Contract

Give terminal agents this concise contract when they need shared tmux access.

```text
Use agent-tmux for shared interactive terminal work.
Run from the project root, or pass --cwd /path/to/project.

Golden path:
1. Launch with:
   agent-tmux launch --session <name> --purpose <purpose> --run "<command>" --log
2. Report the session:
   agent-tmux report
3. Send terminal-agent instructions with:
   agent-tmux prompt <session> --agent claude "<instruction>"
4. Use the mark returned by prompt:
   agent-tmux read <session> --since-mark <mark-id> --lines 120
   agent-tmux wait <session> "<pattern>" --since-mark <mark-id> --timeout 300
5. If the session seems missing or socket access fails:
   agent-tmux doctor --question "<what looked wrong>" --context "<what you were doing>"
6. If a human wants to inspect:
   agent-tmux attach <session>

Do not treat logs, marks, or wait output as task truth.
Task truth comes from artifacts, tests, commits, process exit status, and explicit reports.
```

If a project wrapper exists, use `.agent/tmux` instead of `agent-tmux`.

For recovery tools, read `references/recovery.md`. For profile behavior, read `references/agent-profiles.md`.

## Runtime State

```text
.agent/tmux.sock
.agent/tmux.d/registry.json
.agent/tmux.d/marks.json
.agent/tmux.d/doctor/events.jsonl
.agent/tmux.d/logs/
```

The wrapper `.agent/tmux` may be committed. Runtime files should be ignored.
