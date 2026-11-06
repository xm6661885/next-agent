# Chat module protocol

Plain LLM chat (no Claude Code). Backend `server/chat/`, frontend `web/src/modules/chat/`. Config
`data/config/chat.toml`, data `data/chat/`. Fully independent of Agents: own providers, models, MCP servers, sessions.

## Config: `data/config/chat.toml`
```toml
[defaults]
model = ""                 # "<provider id>/<model id>"; "" = first model of the first provider
effort = "medium"          # off | low | medium | high | max
system_prompt = ""
temperature = -1           # -1 = provider default
max_tokens = 0             # 0 = provider default (anthropic: 8192)
mcp = []                   # ids from [mcp_servers] enabled for every assistant (on by default in a new chat)
title_model = ""           # model for auto titles; "" = the chat's model

[profile]                  # the user as shown in chat
name = "You"
avatar = ""                # "" = first letter of name; "crab:<color>"; "file" = data/chat/avatars/_user

[[providers]]
id = "deepseek"            # slug ^[a-z0-9-]{1,40}$
name = "DeepSeek"
format = "openai"          # openai (Chat Completions) | anthropic (Messages)
base_url = "https://api.deepseek.com/v1"
api_key = ""               # returned as stored
models = ["deepseek-chat"] # model ids offered in pickers
headers = {}               # extra HTTP headers

[mcp_servers.fetch]        # same shape as Claude mcp_servers: stdio {command, args, env} or {type:"http"|"sse", url, headers}
type = "http"
url = "https://example/mcp"

[[assistants]]
id = "writer"
name = "Writer"
avatar = "crab:pink"       # "file" = data/chat/avatars/<id>
description = ""
model = ""                 # "" = [defaults].model
effort = ""                # "" = [defaults].effort
system_prompt = ""         # "" = [defaults].system_prompt
temperature = -1           # -1 = defaults
mcp = []                   # extra MCP server ids available to this assistant (on top of defaults.mcp)
created_at = "..."
order = 0
```
There is always a built-in assistant `_default` ("Chat", avatar `crab:gray`) stored as `[default_assistant]` with the
same fields minus id/order/created_at. It is the "temporary" card on the Chat tab and is not in `/api/chat/assistants`.

## Effort mapping
- openai format: `off` sends nothing; `low|medium|high` send `reasoning_effort` as is; `max` sends `"high"`.
  Streamed `delta.reasoning_content` (DeepSeek and most relays) or `delta.reasoning` becomes the thinking item.
- anthropic format: `off` = no `thinking`; `low|medium|high|max` = `thinking: {type:"enabled", budget_tokens:
  2048|8192|16384|32000}`, and `max_tokens` is raised to budget + 8192 when smaller.

## Data shapes
### ChatSession (`data/chat/sessions.json` index; messages in `data/chat/messages/<sid>.jsonl`)
```jsonc
{"id": "uuid", "assistant_id": "_default", "title": "", "preview": "", "created_at": "...", "updated_at": "...",
 "overrides": {"model": null, "effort": null}, "mcp": ["fetch"] /* servers ON in this chat */,
 "usage": {"input": 0, "output": 0}, "unread": false,
 "state": "idle" /* computed: idle | running */}
```
`mcp` starts as `defaults.mcp + assistant.mcp` (deduplicated) when the session is created; the chat page toggles it.

### Items
Same item model as Agents so the chat UI is a copy: `user {text, attachments, uuid}`, `text {text, streaming}`,
`thinking {text, streaming, duration_ms?}`, `tool {tool_use_id, name, input, streaming, result}` (MCP tool calls,
`name` = `mcp__<server>__<tool>`), `notice`, `result {duration_ms, usage: {input, output}, model, stop_reason}`.
`uuid` on user items is the item id (used by `edit`). Every item has `ts`.

### Versions (branches)
Retry, editing a user message and editing a reply never delete anything: they create a new **version** at a fork
point, and the chat shows one branch at a time. `items` is always the active branch, and it is exactly what is sent to
the model.

Fork points are keyed by position:
- `u:<group>`: the versions of one user message. A user item has `group` (its first version's id; new user items get
  `group = id`). Each version is the suffix of the branch starting at that user item.
- `r:<user item id>`: the versions of the reply to one user item. Each version is the suffix starting right after it.

Stored in `data/chat/messages/<sid>.forks.json`: `{"<key>": {"active": i, "versions": [[item, ...] | null, ...]}}`.
The slot of the active version is `null` (its items are the live list). Groups of deeper forks are unique ids, so
forks inside an inactive suffix keep their own versions.

Computed on the live items (persisted, recomputed after every fork change):
- user item `version: [index, count]` for `u:<group>` (`[0, 1]` when there is no fork),
- user item `reply_version: [index, count]` for `r:<id>`.

Operations (all refused while running):
- `edit {uuid}` (user): the suffix from that user item becomes an inactive version of `u:<group>`; a new user item
  with the same `group` is appended and a reply is generated.
- `regenerate {uuid?}` (default: last user item): the suffix after it becomes an inactive version of `r:<uuid>`; a new
  reply is generated.
- `edit_reply {id, text}`: `id` is a `text` item. The suffix after its user item becomes an inactive version of
  `r:<user uuid>`; the new active version is a copy of that turn's items up to the next user item (fresh ids), with
  that text item's `text` replaced, and a `result` item `{duration_ms: 0, usage: {input: 0, output: 0}, model: "",
  stop_reason: "edited"}` replacing the old result. Later turns are dropped from the new branch. No generation.
- `switch {key, index}`: store the live suffix in the active slot, load slot `index`, set `active`.

After any of these the server sends `items {items, has_more}` (same paging as `snapshot`), which replaces the client
list, followed by the normal events of the new reply if one is generated.

## REST (cookie auth)
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/chat/meta` | | `{models: [{id: "<prov>/<model>", provider, model, format}], efforts, defaults, mcp_servers: [ids], profile}` |
| GET/PATCH | `/api/chat/config` | partial `{defaults, providers, mcp_servers, profile}` (`providers` and `mcp_servers` replace whole lists/tables; omitted `api_key` keeps the stored one) | `{defaults, providers (with api_key), mcp_servers, profile}` |
| POST | `/api/chat/providers/models` | `Provider` (unsaved form; when `api_key` is omitted or `""` and a stored provider has the same `id`, its key is used) | `{models: [ids sorted]}`; errors `502 {detail}`. openai: `GET {base_url}/models`; anthropic: `GET {base_url}/models` with `x-api-key` + `anthropic-version: 2023-06-01`. Reads `data[].id` |
| GET/POST | `/api/chat/profile/avatar` | multipart `file` (image, at most 2 MB) | bytes / `{profile}` (sets `avatar = "file"`) |
| POST | `/api/chat/providers/{id}/test` | | `{ok, error?, models?}` (openai: GET `/models`; anthropic: a 1-token message) |
| GET | `/api/chat/assistants` | | `[Assistant]` + computed `status {running, last_session}` |
| POST/GET/PATCH/DELETE | `/api/chat/assistants[/{id}]` | | like Claude agents (`_default` can be GET/PATCH, not DELETE) |
| POST | `/api/chat/assistants/reorder` | `{ids}` | `{ok}` |
| GET/POST | `/api/chat/assistants/{id}/avatar` | multipart | bytes / Assistant |
| GET | `/api/chat/assistants/{id}/sessions` | | `[ChatSession]` newest first |
| POST | `/api/chat/assistants/{id}/sessions` | `{title?}` | `ChatSession` |
| GET/PATCH/DELETE | `/api/chat/sessions/{sid}` | PATCH `{title?, overrides?, mcp?}` | |
| POST | `/api/chat/sessions/{sid}/read` | | `ChatSession` |
| POST | `/api/chat/sessions/{sid}/uploads` | multipart `files` (images only: png/jpeg/gif/webp, at most 10 MB) | `[Attachment]` in `data/chat/uploads/<sid>/` |
| GET | `/api/chat/uploads/{sid}/{fid}` | | bytes |
| GET | `/api/chat/sessions/{sid}/items` | `?before=&limit=200` | `{items, has_more}` |
| GET | `/api/chat/assistants/{id}/search` | `?q=` | `[{session, snippet}]` |

## WebSocket `/ws/chat/{sid}`
Envelope, `seq`, ring buffer, `resume`/`resumed`/`snapshot`/`ping` as in `docs/protocol.md`. A reply keeps
generating server-side when every socket is closed.

Server -> client: `snapshot {session, state, items, has_more}`, `item`, `patch`, `delta`, `state {state}`,
`session {session}`, `items {items, has_more}` (replace the list, see Versions), `error {message, req_id?}`.

Client -> server:
| type | payload | effect |
|---|---|---|
| `send` | `{client_id, text, attachments: [fid]}` | append user item, generate a reply. While running: `error` "Still replying" |
| `stop` | `{}` | cancel the HTTP stream; partial text stays, `notice` "Stopped" |
| `edit` | `{uuid, client_id, text, attachments}` | new version of that user message (see Versions), then generate |
| `regenerate` | `{uuid?}` | new reply version for that user item (default the last one), generate |
| `edit_reply` | `{id, text}` | new reply version with edited text, no generation |
| `switch` | `{key, index}` | show another version |
| `set_model` | `{model}` | `overrides.model` ("" clears) |
| `set_effort` | `{effort}` | `overrides.effort` |
| `set_mcp` | `{mcp: [ids]}` | which servers are on in this chat |

## Generation
One asyncio task per running reply. History = all items converted to the provider format (user text + image
blocks from attachments; assistant text; tool calls and results; thinking is not sent back). MCP tools of the
enabled servers are listed (connect per reply with the `mcp` Python client: stdio, streamable HTTP or SSE; tool list
cached per server for 10 minutes) and offered as function tools; the loop runs tool calls until the model stops
or 20 rounds. Streaming uses SSE with `httpx` (proxy from env). A title is generated after the first reply when
the title is empty (one non-streamed request, at most 30 chars, falls back to the first 60 chars of the user text).
Emits `/ws/events` `{type:"session_state", module:"chat", session_id, assistant_id, state, unread, title,
updated_at, preview}` and `{type:"chat_changed"}` on config/assistant changes.
