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
  "id": "crab",                 // slug [a-z0-9-]{1,40}, immutable
  "name": "Crab",
  "avatar": "crab:pink",        // "crab:<color>" built-in pixel crab (colors: pink, orange, blue, green, purple, gray)
                                // or "file" = uploaded image at GET /api/agents/{id}/avatar
  "description": "",
  "cwd": "/home/you",
  "model": "",                  // "" = defaults.model ("" there = CLI default)
  "fallback_model": "",
  "effort": "",                 // "" | low | medium | high | xhigh | max
  "thinking": "",               // "" (CLI default) | adaptive | enabled | disabled
  "thinking_budget": 0,         // used when thinking == "enabled"
  "permission_mode": "bypassPermissions", // default | acceptEdits | plan | bypassPermissions | dontAsk | auto
  "system_prompt_mode": "preset", // preset = Claude Code prompt + append, custom = replace entirely
  "system_prompt": "",          // append text (preset) or full prompt (custom)
  "claude_md": "inherit",       // inherit = CLAUDE.md files from cwd/user as Claude Code normally does
                                // custom = also inject data/agents/<id>/CLAUDE.md into the system prompt append
  "setting_sources": ["user", "project", "local"],
  "tools": [],                  // [] = all built-in tools, else explicit base tool list
  "allowed_tools": [],
  "disallowed_tools": [],
  "add_dirs": [],
  "max_turns": 0,               // 0 = unlimited
  "max_budget_usd": 0,          // 0 = unlimited
  "env": {},
  "mcp_servers": {},            // passed straight to ClaudeAgentOptions.mcp_servers
  "agents": {},                 // subagent definitions: name -> {description, prompt, tools?, model?}
  "enable_file_checkpointing": true,
  "file_output": "",            // "" = follow defaults.file_output | "on" | "off" (inject the file-sharing prompt)
  "file_output_prompt": "",     // "" = use defaults.file_output_prompt, else this agent's own prompt text
  "extra_args": {},
  "created_at": "...",
  "order": 0,
  // read-only, computed (not stored in config):
  "status": {
    "running": 1,               // sessions with state running/interrupting
    "live": 2,                  // sessions with a connected CLI
    "pending": 1,               // open permission/question/plan requests across sessions
    "last_session": {"id": "...", "title": "...", "updated_at": "...", "preview": "..."} // or null
  }
}
```

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
  "imported": false,            // true when imported from CLI history
  "overrides": {"model": null, "effort": null, "permission_mode": null},
  "context": null,              // last get_context_usage() summary {used, max, percent} or null
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
| POST | `/api/agents` | partial Agent (`name` and `cwd` required, `id` optional, derived from name) | `Agent` (`409` if the id exists) |
| GET | `/api/agents/{id}` | | `Agent` |
| PATCH | `/api/agents/{id}` | partial Agent | `Agent` |
| DELETE | `/api/agents/{id}` | | `{ok}` (stops live sessions, removes it from config and its index entries; transcripts are kept) |
| POST | `/api/agents/reorder` | `{ids: [..]}` | `{ok}` |
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
| POST | `/api/sessions/{sid}/fork` | `{at_uuid?: string}` | new `Session` (`fork_of` set) |
| GET | `/api/sessions/{sid}/items` | `?before=<item_id>&limit=200` | `{items, has_more}` (older history pages) |
| POST | `/api/sessions/{sid}/uploads` | multipart `files` (each at most 50 MB) | `[Attachment]` |
| GET | `/api/uploads/{sid}/{file_id}` | | file bytes (`Content-Disposition: inline`) |
| GET | `/api/status` | | `{live: n, max_concurrent, queued: n, sessions: [{id, agent_id, state, pending}], memory_mb}` |
| GET | `/api/meta` | | `{models: [..], efforts: [..], permission_modes: [..], version, defaults}`. `models` = built-in list followed by `defaults.custom_models` (deduplicated, `""` first). |
| GET | `/api/sessions/{sid}/files` | `?path=<absolute path>&download=0\|1` | File bytes for a `file://` path that appears in an assistant `text` item of this session (see "Files from Claude"). `inline`, or `attachment` with `download=1`. `404` when the path is not referenced in the session, missing, or not a regular file. |
| GET | `/api/sessions/{sid}/files/stat` | `?path=<absolute path>` | `{name, size, mime, is_image}` with the same access rule, else `404` |
| GET | `/api/config` | | `ConfigForm` (below) |
| PATCH | `/api/config` | partial `ConfigForm` (`server` and `defaults` merge key by key; `pricing` replaces the whole table; `host`, `port` and `default_file_output_prompt` are ignored) | `ConfigForm`. `422 {detail}` on invalid values. Comments in config.toml are kept. |
| GET/PUT | `/api/config/raw` | PUT `{content}` | `{content}`. Raw config.toml text with `password_hash` masked as `"***"`. PUT validates, keeps the existing hash when it sees `"***"`, and returns `400 {detail}` on invalid TOML or schema. |

| GET/POST | `/api/external/send` | `prompt`, `agent_id`, `key` (query, form or JSON; key may also be `X-API-Key`), optional `session_id` | No cookie. Plain text `Message Sent` immediately, header `X-Session-Id`. Creates a session unless `session_id` is given. `403` when `server.api_key` is empty, `401` bad key, `404` unknown agent/session. Per agent, external messages run strictly in order: each waits until the previous turn finishes (and until the target session is idle). |

Errors use the FastAPI `{detail}` format.

### ConfigForm
```jsonc
{
  "server": {"host": "::", "port": 18793, "max_concurrent": 3, "idle_timeout_min": 10, "cli_path": "", "api_key": ""},
  "defaults": {
    "model": "", "effort": "", "permission_mode": "bypassPermissions",
    "custom_models": ["my-relay-model"],     // extra model IDs offered in every model picker
    "file_output": true,                     // inject the file-sharing prompt unless an agent says "off"
    "file_output_prompt": "..."              // the injected text (defaults to the built-in prompt)
  },
  "pricing": {                               // USD per million tokens; overrides the CLI's cost for that model
    "claude-opus-5-5": {"input": 5, "output": 25, "cache_write": 6.25, "cache_read": 0.5}
  },
  "default_file_output_prompt": "..."        // read-only: the built-in prompt, for a "reset" button
}
```
In config.toml these live in `[defaults]` and in `[pricing."<model id>"]` tables.

**Cost with pricing.** On each `ResultMessage` the server computes the CLI process's cumulative cost as the sum over
`model_usage` entries: if the model has a pricing entry, `(inputTokens*input + outputTokens*output +
cacheCreationInputTokens*cache_write + cacheReadInputTokens*cache_read) / 1e6`, else that entry's `costUSD`. When
`model_usage` is missing it uses `total_cost_usd`. Pricing lookup: exact model id, then the id without a trailing
`[...]` suffix (e.g. `[1m]`), then case-insensitive. Turn and session cost are deltas of that value, as before.

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
| `set_model` | `{model}` | `set_model` live, and persists `overrides.model` ("" clears it) |
| `set_effort` | `{effort}` | persists `overrides.effort`. Takes effect on the next CLI start, so the server restarts the CLI when idle. |
| `stop_task` | `{task_id}` | `client.stop_task` |
| `edit` | `{uuid, client_id, text, attachments: [attachment_id], rewind_files: bool}` | Edit an earlier top-level user message and continue from there (like the CLI's `/rewind`). Only when the state is `offline` or `idle` and the session has an `sdk_session_id`, else an error. With `rewind_files` (and file checkpointing on) it first calls `rewind_files(uuid)`. The server emits `truncate {uuid}`, restarts the CLI resumed at the transcript entry just before that message (a fresh CLI session when it was the first message), then sends the new text like `send` (pending `user` item, then patch). The dropped turns stay in the transcript file as an abandoned branch. |
| `rewind` | `{uuid}` | `client.rewind_files(uuid)` (needs file checkpointing), then a `notice` item |
| `ping` | `{}` | `pong` |

## WebSocket: `/ws/events`

Global feed for the home page and session lists. On connect the server sends
`{type:"hello", agents:[{id, status}], sessions:[{id, agent_id, state, pending}]}`.
After that it sends `{type:"session_state", session_id, agent_id, state, pending, title, updated_at, preview}` whenever any of those change, and
`{type:"agents_changed"}` after any agent config change (including a hot reload). No replay; clients refetch on reconnect.

## Files from Claude

When file output is on, the system prompt (append for `preset`, appended text for `custom`) gets the file-output prompt.
It asks Claude to reference files with Markdown and absolute `file://` URLs:
`![caption](file:///abs/path.png)` for images and `[name](file:///abs/path.pdf)` for downloads. The web UI rewrites
those URLs to `/api/sessions/{sid}/files?path=...`. The server only serves paths that occur, percent-decoded, in a
`file://` URL inside one of the session's assistant `text` items.

## Attachments sent to Claude

For `send` with attachments, the user message content is:
1. `{"type":"text","text": <user text>}` (omitted if empty)
2. for each image with mime png/jpeg/gif/webp and size at most 3.75 MB: an `image` base64 block
3. one final text block with one line per attachment: `The user sent a file: <absolute path>`

When reading history, lines matching `^The user sent a file: (.+)$` are removed from the displayed text and turned back
into `attachments` (matched to upload records when the path lies under `data/uploads/`). Image blocks in history user
messages are not shown separately.
