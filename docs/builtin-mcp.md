# Built-in MCP

An in-process MCP server (`claude_agent_sdk.create_sdk_mcp_server`) named **`next`** that the Agents module injects
into Claude sessions. Tools appear to the model as `mcp__next__<tool>`. More Agents agents never get it. Code: `server/builtin/`.

## Config
Global, in `agents.toml`:
```toml
[builtin_mcp]
enabled = false      # master switch
schedules = true     # category switches (only matter when enabled)
history = true
collab = true
```
Per agent (`[[agents]]` and `[temp_agent]`), new `AgentSettings` fields:
- `builtin_mcp: {enabled?, schedules?, history?, collab?}`: each key that is present overrides the global value;
  absent keys follow the global value. Default `{}`.
- `as_subagent: bool = false`: whether collaboration tools may start tasks on this agent. More Agents agents use the existing
  `as_subagent` in `more_agents.toml`.

Effective categories for a session = master && category, after the agent override. If none are on, no server is
injected. Sessions with `origin == "subagent"` never get `collab` (no nested delegation). Every `mcp__next__*` tool is
added to `allowed_tools`, so it never asks for permission. The in-process server instance is excluded from
`options_key`; the effective category set stands in for it, so toggling a category restarts an idle CLI like any other
option change.

Each session gets its own server instance whose tools close over the calling session (`module "agents"`, agent id,
session id).

## Tools
Results are JSON text (`{"content":[{"type":"text","text": json}]}`). Errors return `is_error: true` with a message.

### schedules
| Tool | Input | Result |
|---|---|---|
| `schedule_create` | `{prompt, title?, cron?, at?, target?: {module?: "agents"\|"more_agents", agent_id?, session?: "new"\|"this"\|<session id>, cwd?}, model?, effort?}` | `Schedule` |
| `schedule_list` | `{}` | `[Schedule]` created by this agent |
| `schedule_delete` | `{id}` | `{ok: true}` (only schedules created by this agent) |

Exactly one of `cron` (5-field, server local time, via `croniter`) or `at` (ISO 8601 local datetime, must be in the
future) is required. `target` defaults to this agent and `session: "new"`. `"this"` means the calling session and is
only valid for this agent; it is stored as the concrete session id. For More Agents targets, `session` is `"new"` or a More Agents
session id of that agent, and `model`/`effort` are applied as More Agents config options (`model`, `effort`) when the agent
offers them (ACP uses categories `model` / `thought_level`). New More Agents targets require `target.cwd`; existing sessions retain their cwd. Claude targets reject cwd. A `cron` schedule fires repeatedly; an `at` schedule fires once and then sets `enabled = false`.

`Schedule`:
```json
{"id": "s_ab12cd", "title": "", "prompt": "...", "cron": "0 9 * * *" | null, "at": "2026-11-05T09:00" | null,
 "target": {"module": "agents", "agent_id": "dev", "session": "new" | "<sid>"},
 "model": "", "effort": "", "enabled": true,
 "created_by": {"module": "agents", "agent_id": "dev", "session_id": "<sid>"} | null,
 "created_at": 0, "next_run": 0 | null, "last_run": 0 | null,
 "last_result": {"session_id": "...", "is_error": false, "error": null} | null}
```
Times are epoch seconds. Stored in `data/builtin/schedules.json` (atomic writes). Schedules created in the UI have
`created_by: null`.

**Scheduler**: one background task (`core.background`) sleeps until the earliest `next_run` (re-checks at most every
30 s and immediately on any change). A due schedule fires through `core.bridge.start_claude` / `start_more` with
`origin = "schedule"`, `title = schedule.title or "Scheduled: <first 40 chars of prompt>"`, the stored session id
when `session` is not `"new"`, and `overrides = {model, effort}` (empty values = agent default; Claude only). It does
not wait for the turn; it waits for the result in a separate task and stores `last_result`. A missed run (server was
down) fires once at startup if it was due less than 1 hour ago, otherwise it is skipped to the next time. A target
that no longer exists sets `last_result.error` and disables the schedule.

### history (same agent only)
| Tool | Input | Result |
|---|---|---|
| `history_list` | `{limit?: 20, before?: <epoch>}` | `[{session_id, title, preview, updated_at, origin}]` of this agent, newest first, excluding the calling session |
| `history_search` | `{query, limit?: 20}` | `[{session_id, title, snippet, updated_at}]` (same search as `GET /api/agents/{id}/search`) |
| `history_read` | `{session_id, offset?: 0, limit?: 40}` | `{title, total, items: [{role: "user"\|"assistant"\|"tool", text}]}` |

`history_read` flattens items: user and assistant `text` items keep their text (each cut to 4000 chars); a tool call
becomes `"<tool name>: <one-line input summary>"`; thinking and other kinds are dropped. Reading a session of another
agent is an error. For the temporary agent "same agent" means every `_temp` session.

### collab (other agents as subagents)
| Tool | Input | Result |
|---|---|---|
| `agents_list` | `{}` | `[{module, agent_id, name, description, kind, needs_cwd, models?}]`: Claude agents with `as_subagent`, More Agents agents with `as_subagent`, never the caller's own agent |
| `task_create` | `{module, agent_id, prompt, title?, wait?: false, model?, effort?, cwd?}` | `Task` (when `wait`, after the turn ends) |
| `task_status` | `{task_id}` | `Task` plus `last_text` (last assistant text, up to 4000 chars) |
| `task_send` | `{task_id, prompt}` | `Task`. Sends a follow-up message into the task's session |
| `task_stop` | `{task_id}` | `Task` |
| `task_list` | `{}` | `[Task]` started by the calling session |

`agents_list.kind` is `claude|acp|codex`; `needs_cwd` is true for More Agents. Codex rows include cached
`models:[{id,name,efforts:[string],default_effort}]` when available. `task_create.cwd` is required for More Agents and
rejected for Claude named agents, whose cwd is fixed. Both kinds accept optional model and effort. Results always
include stop_reason (Claude defaults to completed when no native reason is available).

A task is one session on the target agent, created by `core.bridge.start_claude` / `start_more` with
`origin = "subagent"` and `parent = {module: "agents", session_id: <caller>, task_id}`. `Task`:
`{task_id, module, agent_id, session_id, title, state, result: {text, stop_reason, is_error, error} | null, created_at}`; `state`
is the target session state. Tasks live in memory in the builtin module (the session itself is durable, and
`parent` on it records the link); after a restart `task_status` falls back to looking up sessions by `parent`.

## REST
| Method | Path | Body | Result |
|---|---|---|---|
| GET | `/api/builtin/schedules` | | `[Schedule]` |
| POST | `/api/builtin/schedules` | `Schedule` fields (no id/created_*) | `Schedule` |
| PATCH | `/api/builtin/schedules/{id}` | any of `title, prompt, cron, at, target, model, effort, enabled` | `Schedule` |
| DELETE | `/api/builtin/schedules/{id}` | | `{ok: true}` |
| POST | `/api/builtin/schedules/{id}/run` | | `{session_id}` (fire now, keeps the timetable) |
| GET | `/api/builtin/tasks?session_id=<sid>` | | `[Task]` started by that session (small-window list in the chat) |

The global switches go through the existing `PATCH /api/config` (`builtin_mcp`); the per-agent fields through the
normal agent PATCH. Global `/ws/events` gets `{"type": "schedules_changed", "module": "builtin"}` after any change
or run.

## Chat UI
`mcp__next__task_*` tool items show a compact card with the target agent avatar and state; tapping opens the
subagent session in a bottom sheet (read-only live view through the normal session socket of the target module).
