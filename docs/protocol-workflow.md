# Workflow module

Card-based workflows (iOS Shortcuts style), ported from the old next-workflow project. Backend `server/workflow/`,
frontend `web/src/modules/workflow/`, config `data/config/workflow.toml`, data `data/workflow/` (`app.db` SQLite,
`plugins/` user plugins, `workspace/` default card cwd). The old project's data is not migrated.

Workflow never starts a Claude CLI or ACP connection itself. Every agent card runs through `core.bridge`
(`server/bridge.py`), so the session is a normal Agents/ACP session: it shows in that agent's session list
(origin `workflow`, `parent = {run_id, block_id}`) and opens in the normal chat page.

Removed from the old project: its auth, API keys, settings table, env table, `agent_sessions` table and the
`AgentManager` (engine/agents.py). Cookie auth delegates to `core.require`; authenticated workflow routes also accept a
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
`run_events`, `step_outputs`, plus `triggers(workflow_id TEXT PRIMARY KEY, enabled INTEGER, token TEXT,
created_at REAL, last_used_at REAL)`. Trigger timestamps are epoch seconds; `last_used_at` starts null and is updated
when a valid request starts a run. The table is added automatically at schema setup; its workflow foreign key
cascades on deletion. Tokens are stored and returned in clear. Run event and definition formats are unchanged
(see the legacy `docs/api.md` reference below).

## Agent cards (all `uses_agent_slot`, all through `core.bridge`)
| Card id | Name | Inputs | Bridge call |
|---|---|---|---|
| `builtin.temp_task` | Temporary task | `prompt`*, `cwd`, `model`, `effort`, `permission_mode`, `append_system_prompt`, `output_schema` (json), `allowed_tools`, `disallowed_tools`, `add_dirs`, `max_turns`, `max_budget_usd`, `env` (json), `session_id` | `run_claude('_temp', ...)` |
| `builtin.agent_task` | Agent task | `agent`* (type `agent`), `prompt`*, `session_id`, `model`, `effort`, `append_system_prompt`, `output_schema` | `run_claude(agent, ...)` |
| `builtin.acp_task` | ACP agent task | `agent`* (type `acp_agent`), `prompt`*, `session_id` | `run_acp(agent, ...)` |

Empty inputs mean "use the agent's own setting" (for the temporary task: the temporary chat agent settings in
Agents settings). `cwd` empty = the temp agent default (home); relative = against `default_cwd`. `model`, `effort`,
`permission_mode` go in `overrides`; the rest go in `extra` (`append_system_prompt`, `output_schema`,
`allowed_tools`, `disallowed_tools`, `add_dirs`, `max_turns`, `max_budget_usd`, `env`) exactly as `Session.extra`
in `docs/protocol.md`. `session_id` continues an existing session of that agent instead of creating one.
Every session gets `origin = "workflow"`, `title = card note or "<workflow name>: <card name>"`,
`parent = {module: "workflow", run_id, block_id}`.

Outputs: `result` (text, default), `structured` (json, Claude only), `session_id`, `cost_usd` (Claude only).
`is_error` results raise `StepError(error)`.

As soon as the session id is known (before the turn starts; `run_claude`/`run_acp` take an
`on_session(sid)` callback for this) the card emits run event `agent_session`
`{module: "agents"|"acp", agent_id, session_id}`; the Run page links to the normal chat page of that session.
Cancelling the run calls `core.bridge.stop(module, sid)` for a running card.

New plugin input types for the editor: `agent` (Claude agent id incl. `_temp`, options from `/api/agents`) and
`acp_agent` (options from `/api/acp/agents`).

Other cards are unchanged from next-workflow (text, show, alert, ask_input, var_define, var_set, split_text,
get_time, save_file, shell, run_workflow, stop_output; containers `core.if` / `core.repeat` / `core.repeat_each`).
User plugins import `from server.workflow.sdk import Plugin, Input, Output, StepError`.

## Plugin sources and extras
`GET /api/workflow/plugins` returns `{plugins, containers, markers, errors, watching}`. Each regular plugin
entry includes `id`, `name`, `icon`, `color`, `category`, `description`, `version` (default `"1.0.0"`),
`inputs`, `outputs`, `default_output`, `container: false`, `source`, `requires_env` (environment variable names),
`missing_env` (required names absent from nonempty workflow env), and `uses_agent_slot` (boolean).
Group cards by the first component of `source`:

| Source | Editor group | Scan root |
|---|---|---|
| `core/<folder>` | Built-in | `server/workflow/plugins_core/<folder>/plugin.py` |
| `extra/<folder>` | Extras | `server/workflow/plugins_extra/<folder>/plugin.py` |
| `user/<folder>` | User plugins | `data/workflow/plugins/<folder>/plugin.py` |

Extras are shipped first-party cards with IDs prefixed `extra.`. All three sources load at startup and on
`POST /plugins/reload`. Watching and dependency installation remain limited to user plugins.

### Notify card: `extra.notify`
Category `Notify`, icon `bell`, color `pink`; no agent slot or required environment variables.

| Input | Type/default | Meaning |
|---|---|---|
| `text` | text, required | Multiline, supports magic variables |
| `title` | text, optional | Supports magic variables; when nonempty stdin is `title + "\n" + text` |
| `markdown` | bool, false | Adds `--markdown` |
| `attachment` | select, `none` | `none`, `image`, or `file` |
| `path` | text, optional | Supports magic variables; required for an attachment, absolute or relative to the run's `default_cwd` |
| `topic` | text, optional, advanced | Appends ` #topic` to the final text line (trailing newlines are removed first) |

Executes `notify - [--markdown] [--image PATH | --file PATH]` without a shell, with UTF-8 stdin and the
inherited process environment plus the run's environment. Attachments must be regular files and at most
10 MiB for images or 50 MiB for files. The command has a 150-second timeout; timeout/cancellation kills
and reaps the process. Exit 0 returns `{ok: true, output: <stdout text>}` (`ok` is the default output).
A nonzero exit raises `StepError` containing stdout followed by stderr; timeout raises `StepError`.
Success means accepted by the notify service; delivery occurs afterwards.

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
| GET/PATCH | `/workflows/{wid}/trigger` | Trigger config; PATCH `{enabled: boolean}` |
| POST | `/workflows/{wid}/trigger/regenerate` | Rotate the trigger token |
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

## External HTTP triggers
The three trigger management routes above require login or the shared `[server].api_key` Bearer token.
GET creates a disabled trigger on first access with a random 32-byte URL-safe token. PATCH enables/disables
it; POST regenerate replaces its token immediately, preserving enabled state and timestamps. PATCH/regenerate
also create a disabled record if none exists yet. All three return the same shape:

```json
{"enabled": false, "token": "<clear token>", "path": "/api/workflow/trigger/wf_123", "last_used_at": null}
```

The UI builds the full URL using `location.origin + path`. Duplicating/importing a workflow does not copy
its trigger or token. Deleting a workflow deletes its trigger record.

`POST /api/workflow/trigger/{wid}` is public, requiring only the enabled workflow's token, with no login
cookie. Supply `Authorization: Bearer <token>`, `X-Workflow-Token: <token>`, or `?token=<token>`. Bearer takes
precedence, then the dedicated header, then query; comparison uses constant-time byte comparison. The shared
server API key does not authorize this endpoint.

The body is an optional JSON object whose top-level keys fill declared workflow inputs; unknown keys are
ignored. An empty body is `{}`; JSON null/arrays/scalars are invalid. Defaults, type coercion, and `required`
validation use the same input preparation as UI runs. Required inputs reject null, empty text and empty lists
after coercion; false and zero remain valid. These required checks also apply to UI runs.

Without `wait`, returns HTTP 202 `{run_id, status: "queued"}`. With `?wait=1`, waits up to `timeout` seconds
(default 60, positive and at most 300) and returns HTTP 200 with the same run summary as `/workflows/{wid}/run`
with `wait: true`: `id`, `workflow_id`, `workflow_name`, `status`, `inputs`, `result`, `error`, `cost_usd`,
`trigger`, `base_run_id`, `created_at`, `started_at`, `finished_at`, plus `run_id` and `done`. `snapshot` is omitted.
`done: false` means the wait expired; execution continues. Every triggered run has `trigger: "webhook"`.
It emits the existing run events and `run_state` feed events; there are no new event types or config keys.

Errors: 404 unknown workflow; 403 disabled/unconfigured trigger; 401 missing/invalid token;
400 malformed/non-object JSON or invalid inputs; 413 body over 1 MiB (checked while reading, including
requests without Content-Length); 422 invalid wait/timeout query parameters. `last_used_at` only updates
after a run starts, including runs whose execution later fails.

```bash
curl -X POST 'https://your-server/api/workflow/trigger/wf_123?wait=1&timeout=60' \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '{"name":"Sam"}'
```

## Global feed (`/ws/events`)
- `{type: "run_state", module: "workflow", run_id, workflow_id, status}` on every run status change.
- `{type: "workflow_changed", module: "workflow"}` after workflow or group create/update/delete/reorder.
- `core.modules['overview_workflow']() -> {workflows, runs}`.
