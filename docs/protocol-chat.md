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

[[providers]]
id = "deepseek"            # slug ^[a-z0-9-]{1,40}$
name = "DeepSeek"
format = "openai"          # openai (Chat Completions) | anthropic (Messages)
base_url = "https://api.deepseek.com/v1"
api_key = ""               # write-only in the API (api_key_set)
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
`uuid` on user items is the item id (used by `edit`).

## REST (cookie auth)
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/chat/meta` | | `{models: [{id: "<prov>/<model>", provider, model, format}], efforts, defaults, mcp_servers: [ids]}` |
| GET/PATCH | `/api/chat/config` | partial `{defaults, providers, mcp_servers}` (`providers` and `mcp_servers` replace whole lists/tables; omitted `api_key` keeps the stored one) | `{defaults, providers (api_key "" + api_key_set), mcp_servers}` |
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
`session {session}`, `error {message, req_id?}`.

Client -> server:
| type | payload | effect |
|---|---|---|
| `send` | `{client_id, text, attachments: [fid]}` | append user item, generate a reply. While running: `error` "Still replying" |
| `stop` | `{}` | cancel the HTTP stream; partial text stays, `notice` "Stopped" |
| `edit` | `{uuid, client_id, text, attachments}` | drop that user item and everything after it (`truncate {uuid}` event), then like `send` |
| `regenerate` | `{}` | drop items after the last user item (`truncate_after {uuid}`), generate again |
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
