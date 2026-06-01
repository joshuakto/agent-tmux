# Recovery Reference

Use this only when the golden path is not enough.

## Missing Or Confusing Sessions

If a session is `Dead but registered`, use the printed hint or run:

```bash
agent-tmux launch --session <session>
```

This recreates the tmux session from the saved launch intent and replays the run command, starting the agent **fresh**: it restores neither the old terminal scrollback nor the agent's prior conversation. agent-tmux injects no `--resume`/`--continue` of its own (it replays your saved launch command as-is), and a new timestamped transcript is started, so a recovered session answers your next prompt with no stale context. Treat recovery as a clean restart — task truth comes from board memos and artifacts, not the prior transcript.

```bash
agent-tmux report
agent-tmux list
agent-tmux status <session>
agent-tmux doctor --question "<what looked wrong>" --context "<what you were doing>"
```

- Run from the project root or pass `--cwd`.
- If a human can see a session but `list` cannot, use `doctor` before concluding it is gone.
- If active pane may have changed, use `status` or pass an explicit `--pane <session>:<window>.<pane>`.
- `list`, `report`, and `status` flag sessions in the registry that no longer exist in tmux as `Dead but registered` (typically killed externally). `status <session>` distinguishes this from a never-existed session and prints the registry entry plus a recovery hint.

## Stale History Or Viewport Confusion

Prefer mark/new-output reads first:

```bash
agent-tmux read --since-mark <mark-id> --lines 120
agent-tmux wait --since-mark <mark-id> "<pattern>" --timeout 300
agent-tmux wait <session> "<pattern>" --from-now --timeout 300
```

Use deeper history only when inheriting an old session or debugging missed context:

```bash
agent-tmux read <session> --lines 500
agent-tmux read <session> --all --number
agent-tmux search <session> "error|failed|stuck" --ignore-case --context 3
agent-tmux dump <session> --all
```

`read --all` and `dump --all` can be large. Use them to inspect, not as routine context.

## Stuck Or Wrong Process

```bash
agent-tmux read --since-mark <mark-id> --lines 120
agent-tmux search <session> "error|failed|permission|approval" --ignore-case --context 3
agent-tmux interrupt <session>
```

Interrupt only the target session/pane. If unsure which pane is active, run `status` first.
If an interactive agent remains wedged after one interrupt, especially during a vendor tool call, preserve the pane for inspection and launch a fresh session with a shorter corrected prompt. Do not keep layering prompts into a stuck TUI.

## Terminal-Agent UI Edge Cases

Use profile actions before raw keys:

```bash
agent-tmux action <session> submit
agent-tmux action <session> interrupt
agent-tmux action <session> escape
```

`action` (and `prompt`) infer the agent profile from the session registry; pass `--agent` only to override.

Use raw keys only as an escape hatch:

```bash
agent-tmux raw keys <session> Tab Enter
agent-tmux raw keys <session> C-c
```

## Logs And Marks

```bash
agent-tmux log status <session>
agent-tmux log start <session>
agent-tmux log stop <session>
agent-tmux mark <session> --label before-action
```

Like `prompt`, `mark` prints the bare mark id on stdout (receipt to stderr), so `MARK=$(agent-tmux mark <session>)` captures just the id with no flag or `jq`; pass `--json` for the full receipt.

Logs and marks are navigation aids. Task completion still comes from artifacts, tests, commits, process exit status, and explicit reports.

## Layout Recovery

Use pane/window operations to preserve running processes while making them easier to inspect:

```bash
agent-tmux split <session> --horizontal
agent-tmux join-pane <source-pane> <target-pane>
agent-tmux move-window <source-window> <target-session>:
```

For raw window close, drop to tmux: `tmux -S .agent/tmux.sock kill-window -t <session>:<window>`.

After changing one session, run `status <session>` and tell the human the attach command. Use `report` only after cross-session rearrangement or when reviewing multiple sessions.

## Cleanup

Use `kill <session>` to drop a session you no longer need. It removes the registry entry whether or not the session is live in tmux; for a live session it also tears down the pane. `kill` refuses attached or multi-window live sessions unless `--force` is passed — that guard exists so a confused agent does not destroy work the human is watching. Dead-but-registered sessions are dropped without `--force`.
