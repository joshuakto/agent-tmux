# Native Hooks

Use native hooks when a manager agent needs reliable wakeups from a terminal-agent session. Claude Code, Codex CLI, OpenCode, and Pi are the native-event targets.

## Reliable Path

Use the canonical supervised worker loop in [SKILL.md](../SKILL.md#golden-path). This reference covers the hook-specific part of that loop: launch native-hook terminal agents with `--require-events`.

`--agent` is inferred from the `--run` binary basename when omitted; pass it explicitly to override. `--require-events` implies event wiring, verifies session-local hooks, and resolves the run binary. `--events` attempts the same wiring but lets launch continue if hooks are unavailable. Relative paths with separators (e.g. `./bin/claude`) are rejected; use a PATH-resolvable binary name or an absolute executable path.

The launch report prints exactly what got wired (settings file, plugin, wrapper, trust state, or profile-only status). Read that — do not assume from documentation. For which `--run` basenames are recognized and which support native hooks, see `references/wiring-internals.md`.

`prompt` infers the agent profile from the session registry, so `--agent` is only relevant at launch. With `--since-mark`, `events wait` infers the session from the mark. `events wait`/`list` default to the manager attention set; pass `--kind all` to widen.

## Hook Adapter

```bash
agent-tmux hooks ingest --agent <profile> --session reviewer --quiet
agent-tmux hooks status reviewer
agent-tmux hooks show-config --agent <profile> --session reviewer
```

`hooks ingest` reads vendor hook JSON from stdin and emits a canonical event. The canonical kinds are:

- `agent_stop` — turn ended
- `hook_error` — stop hook failure
- `needs_input` — agent is waiting on a notification
- `permission_request` — agent is asking the user to approve an action
- `session_started` — session lifecycle start
- `prompt_submitted` — user prompt was submitted
- `tool_event` — observability-only tool-call event
- `agent_event` — anything else

The default `--kind` filter for `events wait`/`list` is `board_post,needs_input,permission_request,agent_stop,hook_error`. The other kinds are observability records. Claude and Codex wire `UserPromptSubmit` so `prompt` can confirm delivery. Pi wires interactive `input` for the same confirmation and `agent_end` for turn completion; it does not currently add permission or needs-input events. OpenCode wires `session.idle`, `permission.asked`, and `session.error`. The adapter is observability-only — it never approves, denies, or changes a permission decision.

Native lifecycle events can be multiple per turn. Keep raw events intact and branch on the canonical kind; do not treat them as task truth. Use the mark returned by `prompt` with `events wait --since-mark` so older native events do not wake the manager.

## Recovery and Implementor Notes

Use `read`, `search`, and `attach` only for inherited sessions, debugging, or evidence checks. They are not the routine manager-agent notification path.

For the list of recognized `--run` binaries, per-vendor file layouts, the vendor-event → canonical-kind table, and the rules for adding a new vendor, see `references/wiring-internals.md`. Normal use does not need it.
