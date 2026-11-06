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

[titles]
enabled = true
model = ""                 # "" = the conversation's effective model
prompt = ""                # "" = built-in title instruction (see Generation)

[files]
enabled = true             # effective = global AND assistant.files

[memory]
enabled = true             # effective = global AND assistant.memory

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
files = true               # assistant text files and session text uploads/tools
memory = false             # durable memory prompt and tools
model = ""                 # "" = [defaults].model
effort = ""                # "" = [defaults].effort
system_prompt = ""         # "" = [defaults].system_prompt
temperature = -1           # -1 = defaults
mcp = []                   # extra MCP server ids available to this assistant (on top of defaults.mcp)
created_at = "..."
order = 0
```
There is always a built-in assistant `_default` ("Temporary chat", avatar `crab:gray`) stored as `[default_assistant]` with the
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
`thinking {text, streaming, duration_ms?}`, `tool {tool_use_id, name, input, streaming, result}` (local tools use their plain name; MCP tools use
`mcp__<server>__<tool>`), `notice`, `result {duration_ms, usage: {input, output}, model, stop_reason}`.
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
| GET/PATCH | `/api/chat/config` | partial `{defaults, titles, files, memory, providers, mcp_servers, profile}` (`providers` and `mcp_servers` replace whole lists/tables; omitted `api_key` keeps the stored one) | `{defaults, titles, files, memory, providers (with api_key), mcp_servers, profile}` |
| POST | `/api/chat/providers/models` | `Provider` (unsaved form; when `api_key` is omitted or `""` and a stored provider has the same `id`, its key is used) | `{models: [ids sorted]}`; errors `502 {detail}`. openai: `GET {base_url}/models`; anthropic: `GET {base_url}/models` with `x-api-key` + `anthropic-version: 2023-06-01`. Reads `data[].id` |
| GET/POST | `/api/chat/profile/avatar` | multipart `file` (image, at most 2 MB) | bytes / `{profile}` (sets `avatar = "file"`) |
| POST | `/api/chat/providers/{id}/test` | | `{ok, error?, models?}` (openai: GET `/models`; anthropic: a 1-token message) |
| GET | `/api/chat/assistants` | | `[Assistant]` with computed `status {running, last_session}` and `recent: [ChatSession]` |
| POST/GET/PATCH/DELETE | `/api/chat/assistants[/{id}]` | | Assistant with `files: bool = true`, `memory: bool = false`, computed `status` and `recent` (`_default` can be GET/PATCH, not DELETE) |
| POST | `/api/chat/assistants/reorder` | `{ids}` | `{ok}` |
| GET/POST | `/api/chat/assistants/{id}/avatar` | multipart | bytes / Assistant |
| GET | `/api/chat/assistants/{id}/sessions` | | `[ChatSession]` newest first |
| POST | `/api/chat/assistants/{id}/sessions` | `{title?}` | `ChatSession` |
| GET/PATCH/DELETE | `/api/chat/sessions/{sid}` | PATCH `{title?, overrides?, mcp?}` | |
| POST | `/api/chat/sessions/{sid}/read` | | `ChatSession` |
| POST | `/api/chat/sessions/{sid}/uploads` | multipart `files` (images: png/jpeg/gif/webp, at most 10 MiB; UTF-8 text without NUL: at most 2 MiB, refused with 415 when effective files are off) | `[Attachment]` in `data/chat/uploads/<sid>/` |
| GET | `/api/chat/uploads/{sid}/{fid}` | | bytes |
| GET | `/api/chat/sessions/{sid}/items` | `?before=&limit=200` | `{items, has_more}` |
| GET | `/api/chat/assistants/{id}/search` | `?q=` | `[{session, snippet}]` |

### Assistant files and memory
Assistant `recent` contains up to five full session views, newest `updated_at` first (same order and shape as
`GET /api/chat/assistants/{aid}/sessions`); empty when none. This applies to `_default` too.
`status.last_session` keeps its existing summary shape. The new config tables PATCH by merging provided fields,
like `defaults` and `profile`.

All routes below require cookie auth, validate the assistant (including `_default`), and return 404 for unknown
assistants, files or memories. Files and memory remain manageable through REST when their prompt/tool switches
are off. Deleting an assistant removes its sessions, file folder and memory file.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/chat/assistants/{aid}/files` | | `[AssistantFile]` |
| POST | `/api/chat/assistants/{aid}/files` | multipart `files` | `[AssistantFile]` added |
| GET | `/api/chat/assistants/{aid}/files/{fid}` | | raw text download, `text/plain`, filename from metadata |
| PATCH | `/api/chat/assistants/{aid}/files/{fid}` | `{name}` (1..200 chars) | renamed `AssistantFile` |
| DELETE | `/api/chat/assistants/{aid}/files/{fid}` | | `{ok: true}` |
| GET | `/api/chat/assistants/{aid}/memory` | | `[Memory]` |
| POST | `/api/chat/assistants/{aid}/memory` | `{text}` | added `Memory`, source `user` |
| PATCH | `/api/chat/assistants/{aid}/memory/{id}` | `{text}` | updated `Memory` (source preserved) |
| DELETE | `/api/chat/assistants/{aid}/memory/{id}` | | `{ok: true}` |
| DELETE | `/api/chat/assistants/{aid}/memory` | | clear all, `{ok: true}` |

`AssistantFile = {id, name, size, chars, lines, created_at}`. Stored under
`data/chat/assistants/<aid>/files/<fid>`, with an `index.json` list of metadata. Uploads must decode as UTF-8,
contain no NUL (415 otherwise), be at most 2 MiB each (413), and total at most 100 files per assistant (409).
A rejected multipart batch writes no assistant files. Filenames retain Unicode; directory components and NUL
are removed, names are capped at 200 characters. File size is bytes, chars is decoded character count, lines is
`splitlines()` count (empty file: zero). Renaming changes only metadata.

Session text attachment records extend existing image records:
`{id, name, mime: "text/plain", size, path, url, is_image: false, is_text: true, chars, lines}`.
They live in `data/chat/uploads/<sid>/` and are removed with the session. Only uploaded IDs from the current
session may be attached. Each text attachment becomes a text block in that user message in both provider
formats: `<file name="escaped filename">\ncontent\n</file>`. The first 50,000 characters of content are included;
longer files append `The rest of this file can be read with file_read.` on a new line before the closing tag.
Images retain their existing provider image blocks and 10 MiB upload limit.

`Memory = {id, text, created_at, updated_at, source: "assistant" | "user"}`. Stored as a JSON list in
`data/chat/memory/<aid>.json`, isolated per assistant. Text must have 1..1000 characters (422); at most 200 entries
per assistant (409). Updates preserve the original source and creation time. Every REST/tool memory mutation
emits `/ws/events` `{type: "chat_changed", scope: "memory", assistant_id: aid}`.

### Local tools and prompt assembly
The effective system prompt keeps the existing override → assistant → defaults resolution. Append, in order,
a `Files` section (assistant filenames, byte sizes, line counts, and tool instructions) when effective files are
on and assistant files exist, then a `Memory` section when effective memory is on. The latter lists every
`[id] text` and instructs saving durable user facts/preferences with the tools, without saving secrets.
Join nonempty parts with blank lines. Switches affect prompt sections and tool availability independently.

The provider tool list is local tools followed by MCP tools. Dispatch uses the plain local name or the MCP
prefix; local calls render as ordinary `tool` items with the same `{content, is_error, images: []}` result envelope.
Invalid local arguments, unknown files/memories and entry limits produce error tool results.

| Tool | Arguments | Offered when / result |
|---|---|---|
| `file_read` | `{name, offset?: 1, limit?: 400}` (1-based offset; limit 1..2000) | Effective files on and assistant/session text files exist. `Total lines: N` followed by `line: text` lines. |
| `file_search` | `{query, name?}` (nonempty substring) | Same switch; case-insensitive search, up to 50 `name:line: text` hits. Empty result when none. |
| `memory_add` | `{text}` | Effective memory on; JSON `{id}` of added Memory, source `assistant`. |
| `memory_update` | `{id, text}` | Effective memory on; JSON `{id}` of updated Memory, source preserved. |
| `memory_delete` | `{id}` | Effective memory on; JSON `{ok: true}`. |

File tools see the assistant's persistent files and this session's uploaded text files, even if not yet attached
to a message. Session files win on a name clash; within either collection the last uploaded matching name wins.
They cannot access another assistant's or session's files and never accept filesystem paths.

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
One asyncio task per running reply. History = all items converted to the provider format (user text + image/text
blocks from attachments; assistant text; tool calls and results; thinking is not sent back). MCP tools of the
enabled servers are listed (connect per reply with the `mcp` Python client: stdio, streamable HTTP or SSE; tool list
cached per server for 10 minutes) and offered as function tools; the loop runs tool calls until the model stops
or 20 rounds. Streaming uses SSE with `httpx` (proxy from env).

Sending a message to a session with an empty title immediately sets and emits a first-sentence title: text up
to the first `。！？.!?` or newline, whitespace collapsed, at most 60 characters. With no text, use the first
attachment's name (also at most 60 characters). If `titles.enabled`, a separate background task starts one
nonstreaming request with the first user text, the configured model (empty = conversation's effective model),
and `titles.prompt` or the built-in instruction: "Write only a short title for this conversation, at most 30
characters, in the language of the message." It never delays the reply and its usage is not counted.
Normalize generated whitespace, strip surrounding straight/curly quotes, and cap at 30 characters; only a
nonempty result replaces the first-sentence title, and only while that title is still unchanged. Failures/empty
results keep the first-sentence title; manual renames win. Delete/shutdown cancels the title task; stopping the
reply or closing its socket leaves title generation running.

Run `uv run python scripts/migrate/chat.py --data DIR [--dry-run]` at deployment to move
`defaults.title_model` to `titles.model` in `DIR/config/chat.toml` with tomlkit formatting preservation. Default
DIR is this checkout's `data/`. It is idempotent and adds no other defaults. A preexisting conflicting
`titles.model` stops migration without writing; resolve the conflict before rerunning.

Emits `/ws/events` `{type:"session_state", module:"chat", session_id, assistant_id, state, unread, title,
updated_at, preview}` and `{type:"chat_changed"}` on config/assistant changes.
