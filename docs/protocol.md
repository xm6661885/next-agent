# next-agent protocol (REST + WebSocket)

This is the contract between `server/` (FastAPI) and `web/` (Preact). Change both sides together.
All JSON. Timestamps are ISO-8601 UTC strings. IDs are strings.

## Auth

- `POST /api/login` `{password}` -> `200 {ok:true}` and sets cookie `na_auth` (signed, HttpOnly, SameSite=Lax,
  Secure when `X-Forwarded-Proto: https`, max-age 30 days). Wrong password: `401 {detail}`. More than 8 failures per
  IP in 10 minutes: `429`. IP from `X-Real-IP`, else the peer address.
- `POST /api/logout` clears the cookie.
- `GET /api/me` -> `{authenticated: true}` or `401`.
- Every other `/api/*` route and every `/ws/*` route requires the cookie (`401`, or WS close code `4401`).
- WebSocket handshakes must have an `Origin` whose host equals the `Host` header (else close `4403`).
- The token embeds a fingerprint of `password_hash`, so changing the password logs every device out.

## Data shapes

### Agent
```jsonc
{
  "id": "crab",                 // slug [a-z0-9-]{1,40}, immutable ("_temp" = the temporary-session agent, see below)
  "name": "Crab",
  "avatar": "crab:pink",        // "crab:<color>" built-in pixel crab (colors: pink, orange, blue, green, purple, gray)
                                // or "file" = uploaded image at GET /api/agents/{id}/avatar
  "description": "",
  "group": "",                  // Home grouping: a name from GET /api/groups, or "" = ungrouped (422 if unknown)
  "cwd": "/home/you",
  // ---- overridable groups: only used when the group name is in override_groups, else [defaults] applies ----
  "override_groups": [],        // subset of: "model" | "permissions" | "system_prompt" | "file_output" | "genui" | "idle"
  "model": "opus",              // group model. Never empty
  "effort": "low",              // group model. low | medium | high | xhigh | max (never empty)
  "permission_mode": "bypassPermissions", // group permissions. default | acceptEdits | plan | bypassPermissions | dontAsk | auto
  "system_prompt_mode": "preset", // group system_prompt. preset = Claude Code prompt + append, custom = replace entirely
  "system_prompt": "",          // group system_prompt. append text (preset) or full prompt (custom)
  "file_output": true,          // group file_output. inject the file-sharing prompt
  "file_output_prompt": "",     // group file_output. "" = built-in prompt
  "genui": true,                // group genui. inject the generative UI prompt
  "genui_prompt": "",           // group genui. "" = built-in prompt
  "idle_mode": "timer",         // group idle. timer | adaptive | never (see Idle modes)
  "idle_timeout_min": 10,       // group idle
  "adaptive_keep": 1,           // group idle
  "fallback_model": "",         // group model. "" = no fallback
  "thinking": "adaptive",       // group model. adaptive | enabled | disabled
  "thinking_budget": 8000,      // group model. used when thinking == "enabled"
  // ---- agent-only fields ----
  "claude_md": "inherit",       // inherit = CLAUDE.md files from cwd/user as Claude Code normally does
                                // custom = also inject data/agents/<id>/CLAUDE.md into the system prompt append
  "setting_sources": ["user", "project", "local"],
  "tools": ["*"],               // ["*"] = all built-in tools, [] = none, else explicit base tool list
  "auto_memory": true,          // false sets CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
  "allowed_tools": [],
  "disallowed_tools": [],
  "add_dirs": [],
  "max_turns": 0,               // 0 = unlimited
  "max_budget_usd": 0,          // 0 = unlimited
  "env": {},
  "mcp_servers": {},            // passed straight to ClaudeAgentOptions.mcp_servers
  "agents": {},                 // subagent definitions: name -> {description, prompt, tools?, model?}
  "enable_file_checkpointing": true,
  "extra_args": {},
  "created_at": "...",
  "order": 0,
  // read-only, computed (not stored in config):
  "effective": {                // every overridable field resolved (agent value if its group is overridden, else defaults)
    "model": "opus", "effort": "low", "fallback_model": "", "thinking": "adaptive", "thinking_budget": 8000,
    "permission_mode": "...", "system_prompt_mode": "preset", "system_prompt": "",
    "file_output": true, "file_output_prompt": "<resolved text, built-in when empty>", "genui": true,
    "genui_prompt": "<resolved text>", "idle_mode": "timer", "idle_timeout_min": 10, "adaptive_keep": 1
  },
  "status": {
    "running": 1,               // sessions with state running/interrupting
    "live": 2,                  // sessions with a connected CLI
    "pending": 1,               // open permission/question/plan requests across sessions
    "last_session": {"id": "...", "title": "...", "updated_at": "...", "preview": "..."} // or null
  }
}
```

PATCH semantics: fields of a group that is not in `override_groups` are still stored and returned (so turning the
switch back on restores them), they are just ignored. When a client turns a group on for the first time it should
prefill the fields from `effective`. Unknown group names, or `file_output`/`genui` not being booleans, return `422`.

### Session (index entry)
```jsonc
{
  "id": "uuid",                 // also passed to the CLI as session_id for new sessions
  "agent_id": "crab",
  "sdk_session_id": "uuid|null",// the CLI session id (normally == id); null until the first turn starts
  "title": "Fix the login bug", // auto: first user message (60 chars), editable
  "preview": "last assistant text, 140 chars",
  "created_at": "...", "updated_at": "...",
  "total_cost_usd": 0.0,
  "turns": 0,
  "fork_of": null,              // {session_id, at_uuid|null} when forked
  "cwd": "/abs/path",           // temporary sessions only (agent_id "_temp"); absent otherwise
  "imported": false,            // true when imported from CLI history
  "overrides": {"model": null, "effort": null, "permission_mode": null},
  "context": null,              // last get_context_usage() summary {used, max, percent} or null
  "unread": false,              // true when a turn finished while no client had this session's socket open; shared by all clients
  // computed:
  "state": "offline",           // see Session states
  "pending": 0
}
```

### Session states
`offline` (no CLI process) | `queued` (waiting for a concurrency slot) | `starting` (CLI connecting) |
`idle` (CLI connected, no turn) | `running` (turn in progress) | `interrupting` (interrupt sent, waiting for the result).

### Items (the chat transcript model)
The server turns both the transcript history and live SDK messages into a flat list of **items**. The client renders
items in order. Every item has `id`, `kind`, `ts`, and an optional `parent_tool_use_id` (non-null = it belongs to a
subagent running under that Task tool item).

| kind | fields |
|---|---|
| `user` | `text`, `attachments: [Attachment]`, `uuid` (CLI message uuid, used for rewind/fork; null while pending), `pending: bool` (sent but not yet consumed by the CLI, i.e. queued steer), `client_id` |
| `text` | `text`, `streaming: bool` |
| `thinking` | `text`, `streaming: bool` |
| `tool` | `tool_use_id` (== id), `name`, `input` (object; `{}` while streaming), `input_partial` (string while streaming), `streaming: bool`, `result: null \| {content: string, is_error: bool, images: [dataurl]}` |
| `notice` | `level: info\|warn\|error`, `text` (e.g. "Interrupted", "Model switched to sonnet", API errors) |
| `result` | `subtype`, `is_error`, `duration_ms`, `num_turns`, `cost_usd` (this turn), `total_cost_usd` (session), `usage`, `terminal_reason` |

### Activity (transient status while a turn runs)
Not an item. Sent as the `activity` event and included in `snapshot.activity`. `null` means nothing to show.
```jsonc
{"kind": "requesting", "at": "..."}                       // SystemMessage status=requesting (an API request started)
{"kind": "compacting", "at": "..."}                       // status=compacting
{"kind": "retry", "at": "...", "attempt": 2, "max_retries": 10, "retry_delay_ms": 4000,
 "error_status": 529,                                      // HTTP status or null (network error / no response)
 "error": "overloaded",                                    // CLI error category string
 "no_response": {"waited_ms": 60000, "retry_wait_ms": 0}}  // present only when the API never answered
{"kind": "thinking_tokens", "at": "...", "estimated_tokens": 1234}  // throttled to at most 1 per second
```
The server sets activity to `null` on `message_start` stream events (the model is answering) and on every `ResultMessage`.

`Attachment`: `{id, name, mime, size, path, url, is_image}`. `url` is an authenticated GET URL for thumbnails and downloads.

Tool result `content` is normalized to a string (text blocks joined with `\n`). Image blocks go into `images`.
Results longer than 200 kB are truncated with a trailing `\n... [truncated N bytes]`.

### Permission request
```jsonc
{
  "id": "perm-uuid",
  "session_id": "...",
  "kind": "tool" | "question" | "plan",   // question = AskUserQuestion, plan = ExitPlanMode
  "tool_name": "Bash",
  "tool_use_id": "toolu_...",
  "input": {...},                          // question: {questions:[{question, header, options:[{label, description}], multiSelect}]}; plan: {plan}
  "title": "...", "description": "...", "decision_reason": "...", "blocked_path": null,
  "suggestions": [ ... ],                  // raw PermissionUpdate dicts from the SDK (may be [])
  "created_at": "..."
}
```
Requests never time out. They stay open until a device answers, the user interrupts, or the CLI goes away.

## REST

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/api/agents` | | `[Agent]` sorted by `order`, then `created_at` |
| POST | `/api/agents` | partial Agent (`name` and `cwd` required; `id` optional, must match `^[a-z0-9-]{1,40}$` else `422`; when omitted it is derived from name, or `agent-<6 hex>` if the name has no ASCII letters/digits) | `Agent` (`409` if the id exists) |
| GET | `/api/agents/{id}` | | `Agent` |
| PATCH | `/api/agents/{id}` | partial Agent | `Agent` |
| DELETE | `/api/agents/{id}` | | `{ok}` (stops live sessions, removes it from config and its index entries; transcripts are kept) |
| POST | `/api/agents/reorder` | `{ids: [..]}` | `{ok}` |
| GET | `/api/groups` | | `{groups: [string]}` user-defined agent groups, in display order |
| PUT | `/api/groups` | `{groups: [string], renames?: {old: new}}` | `{groups}`. Replaces the whole list (unique, non-empty, at most 40 chars, else `422`). Agents in a renamed group follow `renames`; agents whose group is dropped get `group = ""`. Emits `agents_changed`. |
| GET/PUT | `/api/agents/{id}/claude-md` | PUT `{content}` | `{content, path, exists}`. With `claude_md=inherit` this reads and writes `<cwd>/CLAUDE.md`. With `custom` it uses `data/agents/<id>/CLAUDE.md`. |
| GET | `/api/agents/{id}/avatar` | | image bytes (`404` if none) |
| POST | `/api/agents/{id}/avatar` | multipart `file` (png/jpeg/webp/gif, at most 2 MB) | `Agent` (avatar = "file") |
| GET | `/api/agents/{id}/sessions` | | `[Session]` newest `updated_at` first |
| POST | `/api/agents/{id}/sessions` | `{title?}` | `Session` (offline, not started) |
| GET | `/api/agents/{id}/search` | `?q=<text>&limit=50` (limit at most 200) | `[{session: Session, snippet}]` newest first. Case-insensitive substring match over user/assistant text in each transcript (tool calls and results are skipped), then title and preview. `snippet` is about 120 chars around the first transcript hit, `""` for a title/preview-only match. Empty `q` returns `[]`. |
| GET | `/api/agents/{id}/importable` | | `[{sdk_session_id, summary, first_prompt, last_modified, git_branch}]` from `list_sessions(directory=cwd)`, minus ones already indexed |
| POST | `/api/agents/{id}/import` | `{sdk_session_ids: [..]}` | `[Session]` |
| GET | `/api/sessions/{sid}` | | `Session` |
| PATCH | `/api/sessions/{sid}` | `{title?, overrides?}` | `Session` |
| DELETE | `/api/sessions/{sid}` | `?purge=1` also deletes the CLI transcript file | `{ok}` (stops the runtime, deletes uploads) |
| POST | `/api/sessions/delete` | `{ids: [..], purge?: bool}` | `{ok, deleted: [ids]}`. Same as `DELETE /api/sessions/{sid}` for each id; unknown ids are skipped. |
| POST | `/api/sessions/{sid}/sleep` | | `Session`. Stops the runtime now (state becomes `offline`), like the idle reaper. |
| POST | `/api/sessions/{sid}/read` | | `Session` with `unread:false` (also emits `session_state`). Opening the session socket does the same. |
| POST | `/api/sessions/{sid}/warm` | | `Session`. Starts the CLI now without sending anything (no-op when not offline). Only does work with `idle_mode = "adaptive"`; otherwise returns the session unchanged. |
| POST | `/api/sessions/{sid}/fork` | `{at_uuid?: string}` | new `Session` (`fork_of` set, `cwd` copied) |
| GET | `/api/temp/sessions` | | `Session[]` with `agent_id: "_temp"`, newest first |
| POST | `/api/temp/sessions` | `{cwd: string}` (must exist; `~` expanded) | `Session`; 422 for a missing folder |
| GET | `/api/fs/dirs?path=&hidden=0\|1` | | `{path, parent\|null, home, dirs: [{name, path, git}], recent: string[]}`; empty path = home |
| GET | `/api/memory` | | `{root, global: MemoryFile\|null, projects: [{id, cwd\|null, mtime, files: MemoryFile[]}]}`. MemoryFile = `{path, name, size, mtime, title?, description?, type?}` (frontmatter `name` becomes `title`). Projects without memory files are omitted; newest first |
| GET | `/api/memory/file?path=` | | MemoryFile + `content`. `path` is `CLAUDE.md` or `projects/<id>/memory/<file>.md`, else 400 |
| PUT | `/api/memory/file` | `{path, content, create?}` | MemoryFile + `content`. `create` returns 409 if it exists; 404 if the project folder is missing |
| DELETE | `/api/memory/file?path=` | | `{ok}` |
| GET | `/api/sessions/{sid}/items` | `?before=<item_id>&limit=200` | `{items, has_more}` (older history pages) |
| POST | `/api/sessions/{sid}/uploads` | multipart `files` (each at most 50 MB) | `[Attachment]` |
| GET | `/api/uploads/{sid}/{file_id}` | | file bytes (`Content-Disposition: inline`) |
| GET | `/api/status` | | `{live: n, max_concurrent, queued: n, sessions: [{id, agent_id, state, pending}], memory_mb}` |
| GET | `/api/meta` | | `{models: [..], efforts: [..], permission_modes: [..], version, defaults}`. `models` = built-in list followed by `defaults.custom_models` (deduplicated, no `""` entry). `efforts` has no `""` either. |
| GET | `/api/sessions/{sid}/files` | `?path=<absolute path>&download=0\|1` | File bytes for a `file://` path that appears in an assistant `text` item of this session (see "Files from Claude"). `inline`, or `attachment` with `download=1`. `404` when the path is not referenced in the session, missing, or not a regular file. |
| GET | `/api/sessions/{sid}/artifacts` | | `[Artifact]` (see "Artifacts"), most recently touched first |
| GET | `/api/sessions/{sid}/files/stat` | `?path=<absolute path>` | `{name, size, mime, is_image}` with the same access rule, else `404` |
| GET | `/api/config` | | `ConfigForm` (below) |
| PATCH | `/api/config` | partial `ConfigForm` (`server` and `defaults` merge key by key; `pricing` replaces the whole table; `host`, `port`, `default_file_output_prompt` and `default_genui_prompt` are ignored) | `ConfigForm`. `422 {detail}` on invalid values. Comments in config.toml are kept. |
| GET/PUT | `/api/config/raw` | PUT `{content}` | `{content}`. Raw config.toml text with `password_hash` masked as `"***"`. PUT validates, keeps the existing hash when it sees `"***"`, and returns `400 {detail}` on invalid TOML or schema. |

| GET/POST | `/api/external/send` | `prompt`, `agent_id`, `key` (query, form or JSON; key may also be `X-API-Key`), optional `session_id` | No cookie. Plain text `Message Sent` immediately, header `X-Session-Id`. Creates a session unless `session_id` is given. `403` when `server.api_key` is empty, `401` bad key, `404` unknown agent/session. Per agent, external messages run strictly in order: each waits until the previous turn finishes (and until the target session is idle). |

Errors use the FastAPI `{detail}` format.

### ConfigForm
```jsonc
{
  "server": {"host": "::", "port": 18793, "max_concurrent": 3, "cli_path": "", "api_key": "", "anthropic_base_url": "", "anthropic_api_key": ""},
  "defaults": {
    "model": "opus", "effort": "low",        // never empty; first-start values come from ~/.claude/settings.json (model, effortLevel)
    "fallback_model": "", "thinking": "adaptive", "thinking_budget": 8000,
    "permission_mode": "bypassPermissions",
    "system_prompt_mode": "preset",          // global system prompt, used by agents without the system_prompt override
    "system_prompt": "",
    "file_output": true,                     // inject the file-sharing prompt
    "file_output_prompt": "...",             // the injected text (defaults to the built-in prompt)
    "genui": true,                           // inject the generative UI prompt
    "genui_prompt": "...",                   // the injected text; "" resets to the built-in prompt
    "idle_mode": "timer", "idle_timeout_min": 10, "adaptive_keep": 1,  // moved here from [server]
    // global only (no agent override):
    "custom_models": ["my-relay-model"],     // extra model IDs offered in every model picker
    "artifacts": true                        // client feature switch: Artifacts panel + code cards (server only stores it)
  },
  "pricing": {                               // USD per million tokens; overrides the CLI's cost for that model
    "claude-opus-5-5": {"input": 5, "output": 25, "cache_write": 6.25, "cache_read": 0.5}
  },
  "default_file_output_prompt": "...",       // read-only: the built-in prompt, for a "reset" button
  "default_genui_prompt": "..."              // read-only: the built-in generative UI prompt
}
```
**Idle modes** (resolved per agent: the agent's own values with the `idle` override, else `[defaults]`):
- `timer`: an idle CLI is stopped after `idle_timeout_min` minutes (0 also never stops).
- `never`: idle CLIs are never stopped by the reaper.
- `adaptive`: the CLI is started ahead of time (on `POST /api/agents/{id}/sessions`, `POST /api/temp/sessions`, `POST /api/sessions/{sid}/warm` and when a session socket connects), so the first message does not wait for a cold start. Each agent keeps at most `adaptive_keep` (>=1) live CLIs; when another session of that agent connects, the least recently active *idle* ones beyond that are stopped (sessions with pending permissions, running background tasks or cron jobs are never stopped). `idle_timeout_min` is ignored. Temporary sessions count as one agent (`_temp`). A CLI process is bound to one session, so it is not literally handed over; the old one stops and the new one is already warm.

**Config migration** (done once at startup, written back to config.toml): `server.idle_mode/idle_timeout_min/adaptive_keep`
move to `[defaults]`. Each old-style agent (no `override_groups` key) gets groups derived from its old values:
`model` if model or effort was non-empty; `permissions` if permission_mode was non-empty and differs from the default;
`system_prompt` if system_prompt was non-empty or the mode was custom; `file_output`/`genui` if the old value was
`"on"`/`"off"` or its prompt was non-empty (`"on"` -> true, `"off"` -> false, `""` -> the global value). Empty
model/effort/permission values are filled from `[defaults]`. Empty `defaults.model/effort` are filled from
`~/.claude/settings.json` (`model`, `effortLevel`; fallback `opus`/`high`), empty `thinking` becomes `adaptive`. Agents with
`override_groups` but without `model` that set `fallback_model` or `thinking` get `model` added (model/effort copied
from defaults), since those two fields joined the `model` group.

In config.toml these live in `[defaults]` and in `[pricing."<model id>"]` tables.

**Cost with pricing.** On each `ResultMessage` the server computes the CLI process's cumulative cost as the sum over
`model_usage` entries: if the model has a pricing entry, `(inputTokens*input + outputTokens*output +
cacheCreationInputTokens*cache_write + cacheReadInputTokens*cache_read) / 1e6`, else that entry's `costUSD`. When
`model_usage` is missing it uses `total_cost_usd`. Pricing lookup: exact model id, then the id without a trailing
`[...]` suffix (e.g. `[1m]`), then case-insensitive. Turn and session cost are deltas of that value, as before.

### Temporary sessions
Sessions owned by the agent `_temp`. Its settings are stored in config.toml as a `[temp_agent]` table with the same
fields as an agent (no `id`, `cwd`, `order`, `created_at`); a missing table means all defaults: name "Claude Code",
avatar `crab:gray`, `override_groups: []`. It is never listed in `/api/agents`. `GET /api/agents/_temp` returns it as a
full Agent (with `effective` and `status`, `cwd` = home directory, unused: each temporary session runs in its own
`session.cwd`). `PATCH /api/agents/_temp` edits it (`cwd`, `id` are ignored), `GET/POST /api/agents/_temp/avatar`
work, `DELETE` and the claude-md, importable and import routes return `400`. `GET /api/agents/_temp/search` searches
temp sessions. `/ws/events` `agents_changed` is also sent when it changes. The folder's own CLAUDE.md and `.claude/`
settings apply as when running `claude` there. `external/send` cannot create temporary sessions.

## WebSocket: `/ws/sessions/{sid}`

One socket per open chat. Several devices may hold sockets to the same session, and all of them get the same events.
Closing a socket **never** affects the runtime.

### Server -> client
Every event carries `seq` (monotonic per session runtime and per server process) and `type`.

| type | payload |
|---|---|
| `snapshot` | `{session, state, items, has_more, permissions: [PermissionRequest], init, tasks, queue_position, activity}`. Sent on connect, or after a `resume` the server cannot satisfy. `items` holds at most the last 200 items. |
| `item` | `{item}` appends a new item, or replaces one with the same id |
| `patch` | `{id, patch}` shallow-merges fields into an existing item (e.g. tool `result`, `streaming:false`, `uuid`, `pending:false`) |
| `delta` | `{id, field, text}` appends `text` to `item[field]` (`text` for text/thinking, `input_partial` for tool) |
| `state` | `{state, queue_position}` |
| `permission` | `{request}` |
| `permission_resolved` | `{id, decision}` (allow / deny / cancelled) |
| `session` | `{session}` (title, cost, overrides, or context changed) |
| `init` | `{model, permission_mode, tools, slash_commands, mcp_servers, agents, skills, claude_code_version, cwd}`. Sent only when it changes. |
| `tasks` | `{tasks: [TaskInfo]}`. `TaskInfo`: `{task_id, kind: "task"|"cron", tool_use_id, description, status, task_type? (local_bash|local_agent|remote_agent|...), subagent_type?, last_tool_name?, summary?, usage?: {total_tokens, tool_uses, duration_ms}, cron?, schedule?, recurring?, started_at, updated_at}`. `task` entries come from `task_started/progress/notification/updated` (subagents, background Bash); `cron` entries (`task_id = "cron:<job id>"`) are mirrored from CronCreate/CronDelete tool calls and cannot be stopped via `stop_task`. |
| `activity` | `{activity: Activity \| null}` |
| `truncate` | `{uuid}`: remove the top-level `user` item with this `uuid` and every item after it (sent by `edit`) |
| `error` | `{message}` (also logged as a `notice` item when it relates to the conversation) |
| `pong` | `{}` |

### Client -> server
Every message has `type` and may carry `req_id`. Any command that fails gets an `{type:"error", req_id, message}` reply.

| type | payload | effect |
|---|---|---|
| `resume` | `{seq}` | Must be the first message. With `seq` = 0 or null, the server sends a `snapshot`. Otherwise it replays buffered events after `seq` (ring buffer of 2000 per session), or sends a `snapshot` when they are gone. |
| `send` | `{client_id, text, attachments: [attachment_id]}` | Starts the CLI if it's offline (it may queue). In idle state this starts a turn. In running state this is a **steer**: the message is written now and the CLI picks it up at the next tool boundary. The server emits a `user` item with `pending:true` right away, then a `patch {pending:false, uuid}` once the CLI echoes it. |
| `interrupt` | `{}` | `client.interrupt()`. Open permission requests resolve as deny/cancelled. Pending (unconsumed) steer messages stay queued in the CLI. |
| `permission_reply` | `{id, decision: "allow"\|"allow_always"\|"deny", message?, answers?, mode?}` | `answers` is for question, as `{question_text: label \| [labels]}`. `mode` is for plan approval (switch permission mode after approval, e.g. "acceptEdits"). |
| `set_mode` | `{mode}` | `set_permission_mode` live (or stored in overrides when offline), and persists `overrides.permission_mode` |
| `set_model` | `{model}` | persists `overrides.model` ("" clears it) and calls `set_model` live. If the CLI rejects it (any exception), the override is restored and a second `session` event is sent, then an `error` reply with the CLI message. |
| `set_effort` | `{effort}` | persists `overrides.effort`. Takes effect on the next CLI start, so the server restarts the CLI when idle. |
| `stop_task` | `{task_id}` | `client.stop_task` |
| `edit` | `{uuid, client_id, text, attachments: [attachment_id], rewind_files: bool}` | Edit an earlier top-level user message and continue from there (like the CLI's `/rewind`). Only when the state is `offline` or `idle` and the session has an `sdk_session_id`, else an error. With `rewind_files` (and file checkpointing on) it first calls `rewind_files(uuid)`. The server emits `truncate {uuid}`, restarts the CLI resumed at the transcript entry just before that message (a fresh CLI session when it was the first message), then sends the new text like `send` (pending `user` item, then patch). The dropped turns stay in the transcript file as an abandoned branch. |
| `rewind` | `{uuid}` | `client.rewind_files(uuid)` (needs file checkpointing), then a `notice` item |
| `ping` | `{}` | `pong` |

## WebSocket: `/ws/events`

Global feed for the home page and session lists. On connect the server sends
`{type:"hello", agents:[{id, status}], sessions:[{id, agent_id, state, pending, unread}]}`.
After that it sends `{type:"session_state", session_id, agent_id, state, pending, unread, title, updated_at, preview}` whenever any of those change, and
`{type:"agents_changed"}` after any agent config change (including a hot reload). No replay; clients refetch on reconnect.

## Files from Claude

When file output is on, the system prompt (append for `preset`, appended text for `custom`) gets the file-output prompt.
It asks Claude to reference files with Markdown and absolute `file://` URLs:
`![caption](file:///abs/path.png)` for images and `[name](file:///abs/path.pdf)` for downloads. The web UI rewrites
those URLs to `/api/sessions/{sid}/files?path=...`. The server only serves paths that occur, percent-decoded, in a
`file://` URL inside one of the session's assistant `text` items, or as the file path of a Write/Edit/MultiEdit/NotebookEdit
tool call in the session.

## Artifacts

`GET /api/sessions/{sid}/artifacts` lists the files of a conversation, built from all items (history included):
```jsonc
{"path": "/abs/report.pdf", "name": "report.pdf", "mime": "application/pdf", "is_image": false,
 "exists": true, "size": 1234,              // size null when missing
 "sources": ["write", "link"],             // any of: link (file:// in assistant text), write (Write tool),
                                            // edit (Edit/MultiEdit/NotebookEdit tool), upload (user attachment)
 "first_ts": "...", "last_ts": "...",     // ts of the first/last item that referenced it
 "url": "/api/sessions/{sid}/files?path=..."} // uploads: their /api/uploads URL
```
Paths are normalized and deduplicated; only tool calls with a successful (non-error) result count as write/edit.
Code blocks are not listed by the server: clients extract fenced code blocks (not `genui`) from assistant text
themselves. When `defaults.artifacts` is true, clients show an Artifacts panel per chat (files + code blocks) and
render fenced code blocks of 12+ lines as collapsed code cards that open in a viewer. When false, both are off and
code renders inline as before.

## Attachments sent to Claude

For `send` with attachments, the user message content is:
1. `{"type":"text","text": <user text>}` (omitted if empty)
2. for each image with mime png/jpeg/gif/webp and size at most 3.75 MB: an `image` base64 block
3. one final text block with one line per attachment: `The user sent a file: <absolute path>`

When reading history, lines matching `^The user sent a file: (.+)$` are removed from the displayed text and turned back
into `attachments` (matched to upload records when the path lies under `data/uploads/`). Image blocks in history user
messages are not shown separately.

## Generative UI blocks

Assistant text may contain fenced blocks tagged `genui`. The body is an HTML fragment (HTML/CSS/SVG/JS).
Clients render each block in a sandboxed web view in place of the code block; a block without its closing fence
(still streaming) shows a placeholder. The server does nothing special: the blocks are ordinary text in items.

The host injects a global `host` object before the page:
- `host.send(text)`: send `text` as a new user message in the current session (same as the composer `send`).
  Clients drop empty text and more than one send per second per block.
- `host.copy(text)`: copy to clipboard.
- `host.open(url)`: open an http(s) URL outside the chat.

Messages from the frame are `postMessage({__genui: id, action: 'send'|'copy'|'open'|'size', text?, url?, height?})`;
`size` reports the content height so the host can fit the view. Host-to-frame messages (progressive rendering):
`{__genui: id, action: 'render', html}` replaces the body with a partial fragment without running scripts, and
`{__genui: id, action: 'final', html}` sets the full fragment and then runs its scripts in order. While a block is
streaming, clients post `render` at most every ~120 ms with the partial text (a trailing unfinished `<tag` cut off),
and `final` when the closing fence arrives, so the user watches the UI/SVG being built. The frame viewport is not
zoomable (`maximum-scale=1, user-scalable=no`, `touch-action: manipulation`). The page gets CSS variables `--bg --fg --muted
--border --accent --accent-ink --code-bg` from the host theme. No network except scripts/styles from
`cdn.jsdelivr.net` and `unpkg.com`, and images over https; no same-origin access, cookies or storage.

## Uploads

`POST /api/sessions/{sid}/uploads` stores files in `<agent cwd>/uploads/<id8>-<name>` (temporary sessions: the
session's cwd), falling back to `data/uploads/<sid>/` if the cwd is missing. `path` in the response is that absolute
path. Deleting a session or agent deletes its uploaded files.
