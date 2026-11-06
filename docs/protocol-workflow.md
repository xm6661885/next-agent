# Workflow module

Card-based workflows (iOS Shortcuts style), ported from the old next-workflow project. Backend `server/workflow/`,
frontend `web/src/modules/workflow/`, config `data/config/workflow.toml`, data `data/workflow/` (`app.db` SQLite,
`plugins/` user plugins, `workspace/` default card cwd). The old project's data is not migrated.

Workflow never starts a Claude CLI or More Agents connection itself. Every agent card runs through `core.bridge`
(`server/bridge.py`), so the session is a normal Agents/More Agents session: it shows in that agent's session list
(origin `workflow`, `parent = {run_id, block_id}`) and opens in the normal chat page.

Removed from the old project: its auth, API keys, settings table, env table, `agent_sessions` table and the
`AgentManager` (engine/agents.py). Cookie auth delegates to `core.require`; workflow routes also accept a
`[server].api_key` bearer token (the shared `core.require` currently checks cookies only).

## Config: `data/config/workflow.toml`
```toml
[server]
agent_concurrency = 1     # cards with uses_agent_slot run at most this many at once (1..16)
run_retention = 100       # finished runs kept; 0 = keep all
plugin_watch = false      # hot reload data/workflow/plugins
default_cwd = ""          # empty = data/workflow/workspace; relative card cwd resolves against it

[env]                     # global environment variables for every card (shell cards, @env refs, plugin requires_env)
# KEY = "value"
```
Registered in `core.modules['raw_configs']['workflow']` for the raw editor. Edits apply at once (concurrency limit,
plugin watch).

## Storage (`data/workflow/app.db`)
Tables as before minus `settings`, `env_vars`, `api_keys`, `agent_sessions`: `groups`, `workflows`, `runs`,
`run_events`, `step_outputs`. Run event and definition formats are unchanged (see the legacy `docs/api.md` reference below).

## Agent cards (all `uses_agent_slot`, all through `core.bridge`)
| Card id | Name | Inputs | Bridge call |
|---|---|---|---|
| `builtin.temp_task` | Temporary task | `prompt`*, `cwd`, `model`, `effort`, `permission_mode`, `append_system_prompt`, `output_schema` (json), `allowed_tools`, `disallowed_tools`, `add_dirs`, `max_turns`, `max_budget_usd`, `env` (json), `session_id` | `run_claude('_temp', ...)` |
| `builtin.agent_task` | Agent task | `agent`* (type `agent`), `prompt`*, `session_id`, `model`, `effort`, `append_system_prompt`, `output_schema` | `run_claude(agent, ...)` |
| `builtin.more_agent_task` | More Agents agent task | `agent`* (type `more_agent`), `prompt`*, `cwd` (required for new sessions), `model`, `effort`, `session_id` | `run_more(agent, cwd=..., ...)` |

Empty inputs mean "use the agent's own setting" (for the temporary task: the temporary chat agent settings in
Agents settings). `cwd` empty = the temp agent default (home); relative = against `default_cwd`. `model`, `effort`,
`permission_mode` go in `overrides`; the rest go in `extra` (`append_system_prompt`, `output_schema`,
`allowed_tools`, `disallowed_tools`, `add_dirs`, `max_turns`, `max_budget_usd`, `env`) exactly as `Session.extra`
in `docs/protocol.md`. `session_id` continues an existing session of that agent instead of creating one.
Every session gets `origin = "workflow"`, `title = card note or "<workflow name>: <card name>"`,
`parent = {module: "workflow", run_id, block_id}`.

Outputs: `result` (text, default), `structured` (json, Claude only), `session_id`, `cost_usd` (Claude only).
`is_error` results raise `StepError(error)`.

As soon as the session id is known (before the turn starts; `run_claude`/`run_more` take an
`on_session(sid)` callback for this) the card emits run event `agent_session`
`{module: "agents"|"more_agents", agent_id, session_id}`; the Run page links to the normal chat page of that session.
Cancelling the run calls `core.bridge.stop(module, sid)` for a running card.

New plugin input types for the editor: `agent` (Claude agent id incl. `_temp`, options from `/api/agents`) and
`more_agent` (options from `/api/more-agents/agents`).
For `builtin.more_agent_task`, cwd is required unless session_id is supplied. ACP paths are remote and passed unchanged;
Codex expands/resolves them locally and requires an existing directory. Model, effort and session_id are advanced inputs;
effort choices are empty, low, medium, high, xhigh, max. Outputs are result and session_id.

Other cards are unchanged from next-workflow (text, show, alert, ask_input, var_define, var_set, split_text,
get_time, save_file, shell, run_workflow, stop_output; containers `core.if` / `core.repeat` / `core.repeat_each`).
User plugins import `from server.workflow.sdk import Plugin, Input, Output, StepError`.

## REST (prefix `/api/workflow`, `core.require`; a bearer `[server].api_key` request sets run `trigger = "api"`)
| Method | Path | Notes |
|---|---|---|
| GET/POST | `/groups` | `[{id, name, sort}]`; POST `{name}` |
| PUT | `/groups/reorder` | `{ids}` |
| PUT/DELETE | `/groups/{gid}` | PUT `{name}` |
| GET/POST | `/workflows` | list `[Workflow]` (with `last_status`, `last_run_at`); POST `{name?, group_id?, icon?, color?, definition?}` |
| PUT | `/workflows/reorder` | `{ids}` |
| POST | `/workflows/import` | export JSON |
| GET/PUT/DELETE | `/workflows/{wid}` | PUT `{name?, group_id?, clear_group?, icon?, color?, sort?, definition?}` |
| POST | `/workflows/{wid}/duplicate` | |
| GET | `/workflows/{wid}/export` | `{format: "next-workflow/1", name, icon, color, definition}` |
| POST | `/workflows/{wid}/run` | `{inputs, wait?, timeout?, base_run_id?, from_block?, only_block?, stop_after?}` |
| GET | `/runs` | `?workflow_id=&status=&finished=&limit=&offset=` |
| GET/DELETE | `/runs/{rid}` | |
| GET | `/runs/{rid}/outputs` | |
| GET | `/runs/{rid}/events` | SSE, `?after=` or `Last-Event-ID` |
| POST | `/runs/{rid}/cancel`, `/runs/{rid}/input` `{values}`, `/runs/{rid}/rerun?from_block=` | |
| GET | `/plugins` | `{plugins, containers, markers, errors, watching}` |
| POST | `/plugins/reload`, `/plugins/install-deps` `{folder}` | |
| GET | `/console` | `{runs: [active runs], sessions: [active workflow-origin sessions {module, agent_id, session_id, title, state, parent}]}` |
| GET/PATCH | `/settings` | `{agent_concurrency, run_retention, plugin_watch, default_cwd, env: {k: v}}` (writes workflow.toml) |

`Workflow`, `Run`, definitions, variable tokens and run event types are exactly as in next-workflow `docs/api.md`,
plus the `agent_session` event above. The old `text_delta`/`tool_use`/`tool_result`/`agent_text` events are no longer
produced by agent cards (the chat page shows that).

## Global feed (`/ws/events`)
- `{type: "run_state", module: "workflow", run_id, workflow_id, status}` on every run status change.
- `{type: "workflow_changed", module: "workflow"}` after workflow or group create/update/delete/reorder.
- `core.modules['overview_workflow']() -> {workflows, runs}`.
