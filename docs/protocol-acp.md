# ACP agents protocol

External agents that speak Agent Client Protocol v1 over TCP. Backend `server/acp/`, frontend
`web/src/modules/agents/acp/`. Config `data/config/acp.toml`, data `data/acp/`.

## Wire transport (client side, verified against the android-agent server)
- TCP to `host:port`. If the agent has a `token`, the first line written is `AUTH <token>\n`. No reply to it.
- Then newline-delimited JSON-RPC 2.0, one message per line, both directions. Request ids from us are integers;
  the server's own request ids may be strings (e.g. `"agent-1"`).
- `initialize` params: `{protocolVersion: 1, clientCapabilities: {fs: {readTextFile: false, writeTextFile: false},
  terminal: false}, clientInfo: {name: "next-agent", version}}`. Result has `agentCapabilities`
  (`loadSession`, `promptCapabilities.{image,embeddedContext}`, `sessionCapabilities.list`) and `agentInfo`.
- `session/new {cwd, mcpServers: []}` -> `{sessionId, modes?: {currentModeId, availableModes:[{id,name}]},
  configOptions?: [ConfigOption]}`. `ConfigOption` = `{id, name, category?, type: "select", currentValue,
  options: [{value, name, description?}]}` (seen: `model`, `effort` with category `thought_level`).
- `session/load {sessionId, cwd, mcpServers: []}`: the server first replays the history as `session/update`
  notifications, then answers `{modes?, configOptions?}`. Unknown session: JSON-RPC error `-32602`.
- `session/list {}` -> `{sessions: [{sessionId, cwd, title, updatedAt}]}` (only when `sessionCapabilities.list`).
- `session/set_config_option {sessionId, configId, value}` -> `{configOptions}`.
- `session/set_mode {sessionId, modeId}` -> `{}`.
- `session/prompt {sessionId, prompt: [ContentBlock]}` -> `{stopReason}` when the turn ends
  (`end_turn | max_tokens | max_turn_requests | refusal | cancelled`). Updates stream before it.
- `session/cancel {sessionId}` is a notification (no id). The pending prompt then answers `stopReason: "cancelled"`.
- Server -> client request `session/request_permission {sessionId, toolCall, options: [{optionId, name, kind}]}`
  (`kind`: `allow_once | allow_always | reject_once | reject_always`). Answer
  `{outcome: {outcome: "selected", optionId}}` or `{outcome: {outcome: "cancelled"}}`.
  Any other server request (fs/*, terminal/*) is answered with JSON-RPC error `-32601`.
- `session/update {sessionId, update}`, `update.sessionUpdate` is one of:
  `user_message_chunk | agent_message_chunk | agent_thought_chunk` (`content` ContentBlock),
  `tool_call` (`toolCallId, title, kind, status, rawInput?, content?, locations?`),
  `tool_call_update` (same fields, all optional except `toolCallId`; `content: [{type:"content", content: ContentBlock}
  | {type:"diff", path, oldText, newText} | {type:"terminal", terminalId}]`, `rawOutput?`),
  `plan` (`entries: [{content, priority, status}]`), `available_commands_update` (`availableCommands: [{name, description}]`),
  `current_mode_update` (`currentModeId`), `config_option_update` (`configOptions`), `session_info_update` (`title?`),
  `usage_update` (`used?, size?, cost?`). Unknown kinds are ignored.
- ContentBlock out: `{type:"text", text}`, `{type:"image", mimeType, data(base64)}`,
  `{type:"resource", resource:{uri, mimeType, text}}`.

## Config: `data/config/acp.toml`
```toml
groups = []                 # ACP agent groups on the Agents tab (independent of Claude groups)
[server]
idle_timeout_min = 10       # close an idle TCP connection after this; 0 = never
[[agents]]
id = "phone"                # slug ^[a-z0-9-]{1,40}$, immutable
name = "Phone"
avatar = "crab:blue"        # same rules as Claude agents; "file" = data/acp/avatars/<id>
description = ""
group = ""
host = "mi-10"
port = 8788
token = ""                  # sent as AUTH line when non-empty; never returned by the API (see token_set)
cwd = "/"                   # passed to session/new and session/load
config_defaults = {}        # configId -> value applied with set_config_option right after session/new
as_subagent = false         # allowed as a subagent by the built-in collaboration tools
created_at = "..."
order = 0
```
`[server]` in acp.toml is ACP-only (no Claude CLI involved). `token` is write-only in the API: GET returns
`token: ""` and `token_set: bool`; PATCH with `token` omitted or `null` keeps it, `""` clears it.

## Data shapes
### AcpAgent (API view)
All config fields above (token masked) plus computed `kind: "acp"`, `status: {running, live, pending, last_session}`
(same meaning as Claude agents; `live` = sessions with an open TCP connection) and `info: {name, title, version} | null`
(`agentInfo` from the last successful initialize, cached in memory).

### AcpSession (index entry, `data/acp/sessions.json`)
```jsonc
{"id": "uuid", "agent_id": "phone", "remote_id": "4" /* ACP sessionId, null until first connect */,
 "title": "", "preview": "", "created_at": "...", "updated_at": "...", "turns": 0, "unread": false,
 "origin": "ui",            // ui | workflow | schedule | subagent | external
 "parent": null,            // subagent: {session_id, module: "agents"|"acp", task_id}
 "config_options": [],      // last ConfigOption list seen, for the picker while offline
 "modes": null,             // last {currentModeId, availableModes}
 "commands": [],            // last available_commands_update
 // computed:
 "state": "offline", "pending": 0}
```
States: `offline | connecting | idle | running | interrupting` (no queue: ACP has no concurrency gate).

### Items
Same item model as Claude sessions (`docs/protocol.md` "Items") so the chat UI can be a stripped copy. Mapping:
- `user`: our own message (`text`, `attachments`), `pending` true until the prompt is written, `queued` true while
  it waits for the running turn to end (ACP cannot steer; queued messages are sent in order after `stopReason`).
- `agent_message_chunk` text -> `text` item (consecutive chunks append via `delta`, `streaming` true until the next
  non-text update or the end of the turn). Image chunks -> `text` item with a Markdown `![](data:...)`.
- `agent_thought_chunk` -> `thinking` item, same streaming rule.
- `tool_call` -> `tool` item: `tool_use_id = toolCallId`, `name = title`, `acp_kind = kind`, `input = rawInput or {}`,
  `status`, `locations`. `tool_call_update` patches those fields; when `status` becomes `completed`/`failed`, `result =
  {content: <text of all text content blocks joined, else rawOutput as JSON>, is_error: status=="failed", images: [],
  diffs: [{path, old_text, new_text}]}`.
- `plan` -> one `plan` item per turn (`entries`), replaced in place on each update.
- end of turn -> `result` item `{stop_reason, duration_ms}`. Errors -> `notice` items.
Items are persisted per session in `data/acp/items/<sid>.jsonl` (one JSON item per line, rewritten when an item is
patched at most once per second and at turn end). The remote replay during `session/load` is discarded.

### Permission request
`{id, session_id, tool_call: {...as sent}, options: [{option_id, name, kind}], created_at}`. Never times out.

## REST (cookie auth)
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/acp/agents` | | `[AcpAgent]` by `order`, `created_at` |
| POST | `/api/acp/agents` | partial AcpAgent (`name`, `host`, `port` required; `id` optional, derived like Claude agents) | `AcpAgent` (`409` id exists, `422` invalid) |
| GET/PATCH/DELETE | `/api/acp/agents/{id}` | partial AcpAgent | `AcpAgent` / `{ok}` (DELETE stops sessions and removes their index entries and items) |
| POST | `/api/acp/agents/reorder` | `{ids}` | `{ok}` |
| GET/PUT | `/api/acp/groups` | `{groups, renames?}` | `{groups}` same rules as `/api/groups` |
| GET/POST | `/api/acp/agents/{id}/avatar` | multipart `file` | bytes / `AcpAgent` |
| POST | `/api/acp/agents/{id}/test` | | `{ok, info, config_options, error?}`: connect, initialize, `session/new`, read options, close. Never `5xx` for a connection failure: `{ok:false, error}` |
| GET | `/api/acp/agents/{id}/sessions` | | `[AcpSession]` newest first |
| POST | `/api/acp/agents/{id}/sessions` | `{title?}` | `AcpSession` (offline) |
| GET/PATCH/DELETE | `/api/acp/sessions/{sid}` | PATCH `{title?}` | `AcpSession` / `{ok}` |
| POST | `/api/acp/sessions/{sid}/read` | | `AcpSession` |
| POST | `/api/acp/sessions/{sid}/sleep` | | `AcpSession` (closes the TCP connection; never while running: `409`) |
| GET | `/api/acp/sessions/{sid}/items` | `?before=&limit=200` | `{items, has_more}` |
| POST | `/api/acp/sessions/{sid}/uploads` | multipart `files` | `[Attachment]` stored in `data/acp/uploads/<sid>/` |
| GET | `/api/acp/uploads/{sid}/{fid}` | | bytes |
| GET | `/api/acp/agents/{id}/search` | `?q=` | `[{session, snippet}]` over persisted items |

Attachments sent to the agent: images (png/jpeg/gif/webp, at most 3.75 MB, only when `promptCapabilities.image`)
become `image` blocks; other text files at most 200 kB become `resource` blocks when `embeddedContext`, else a text
line `The user sent a file: <name>`.

## WebSocket `/ws/acp/{sid}`
Same envelope, `seq`, ring buffer (500), `resume`/`resumed`/`snapshot`/`ping`/`pong` rules as `/ws/sessions/{sid}`.
Closing a socket never affects the runtime; a turn keeps running server-side.

Server -> client: `snapshot {session, state, items, has_more, permissions, elapsed_ms}`, `item`, `patch`, `delta`,
`state {state, elapsed_ms}`, `permission {request}`, `permission_resolved {id, option_id|null}`, `session {session}`,
`error {message, req_id?}`.

Client -> server:
| type | payload | effect |
|---|---|---|
| `send` | `{client_id, text, attachments: [fid]}` | connect if offline; idle: start `session/prompt`; running: queue (`queued:true`) |
| `cancel_queued` | `{id}` | drop a queued user item (`patch {cancelled:true}`) |
| `interrupt` | `{}` | `session/cancel`; open permission requests answer `cancelled` |
| `permission_reply` | `{id, option_id}` | answer the request (`option_id` null = cancelled) |
| `set_config` | `{config_id, value}` | `session/set_config_option` (connects if offline); updates `config_options`, emits `session` |
| `set_mode` | `{mode_id}` | `session/set_mode` |

## Connection lifecycle
One TCP connection per session runtime, opened on demand by a single worker task that owns it. On open:
initialize, then `session/load` when `remote_id` is set and `loadSession` is true, else `session/new` (+ apply
`config_defaults`, store `remote_id`). If `session/load` fails, create a new remote session and add a `notice`
(warn) "Remote session was gone; started a new one (earlier context is not available to the agent)". If the
connection drops mid-turn: `notice` error, state `offline`, the turn's `result` item gets `stop_reason: "disconnected"`.
The idle reaper closes connections idle longer than `[server].idle_timeout_min`.

## Python API for other modules (`core.modules['acp']`, class `AcpManager`)
```python
async def run_turn(agent_id, prompt: str, *, session_id=None, title='', origin='workflow', parent=None) -> dict
    # create a session unless session_id is given, send prompt (queued behind a running turn), wait for the end
    # returns {session_id, text (all agent text of this turn), stop_reason}
def start_turn(agent_id, prompt, *, session_id=None, title='', origin='subagent', parent=None) -> str  # session_id, does not wait
async def send(session_id, prompt) -> None      # like the composer `send`
async def stop(session_id) -> None              # interrupt if running
def view(session_id) -> dict                    # AcpSession
def items(session_id) -> list                   # all items
def agents() -> list                            # [AcpAgent]
```
Permission requests raised by a non-UI origin are left open for the user (they show in the ACP chat page and as
`pending` on the agent card).

## /ws/events
ACP sessions emit `{type:"session_state", module:"acp", session_id, agent_id, state, pending, unread, title,
updated_at, preview}` and `{type:"acp_agents_changed"}`. The hello message gets `acp_sessions: [{id, agent_id, state,
pending, unread}]`.
