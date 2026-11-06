# More Agents protocol

`server/more_agents/` hosts `acp` (remote TCP ACP endpoints) and `codex` (local Codex app-server) behind a shared
session coordinator. The module key is `more_agents`, config/raw-editor key is `more_agents`, config lives in
`data/config/more_agents.toml`, and all module data lives in `data/more_agents/`. There are no legacy ACP routes or aliases.

## Configuration and discovery

`MoreAgentsConfig` is `{groups:[], server:{idle_timeout_min:10}, agents:[AcpAgent|CodexAgent]}`; the agent union is
discriminated by required `kind`. Idle timeout applies to both kinds; zero disables it. Common fields:
`id, kind, name, avatar='crab:blue', description='', group='', order=0, as_subagent=false, created_at, cwd`.
IDs match `^[a-z0-9-]{1,40}$`; omitted IDs on creation are derived from the name. `id` and `kind` are immutable.

| kind | Additional fields and defaults |
|---|---|
| `acp` | `host` (required), `port` (required, 1..65535), `token=''`, `cwd='/'`, `config_defaults={}` |
| `codex` | `command='codex'`, `args=[]`, `env={}`, `cwd='~'`, `model=''`, `effort=''`, `mode='full-access'`, `instructions=''` |

Empty model means the CLI default; empty effort means model default. `args` are extra **app-server** arguments.
Authenticated APIs return token and environment values in clear. ACP PATCH with token omitted/null preserves it; empty clears it.

Agent views contain all stored fields plus `status:{running,live,pending,last_session}`, `info`,
`capabilities:{images,steer,modes,local_cwd}`, and `recent` (five newest session views). `last_session` is
`{id,title,updated_at,preview}` or null. `pending` counts permissions plus questions. ACP has `steer:false,local_cwd:false`;
Codex has both true. `info` is ACP initialize metadata or null. `GET /api/more-agents/kinds` returns
`[{kind,name,description}]` for the add-agent menu.

## Sessions, preload and storage

Session view:
```text
{id, agent_id, kind, cwd, remote_id, title, preview, created_at, updated_at, turns, unread, origin, parent,
 config_options, modes, commands, usage?, context?, state, pending}
```
`kind` and `cwd` are fixed for a session. UI creation accepts `{cwd?,title?}`, defaulting cwd to agent.cwd.
ACP accepts any nonempty remote path unchanged. Codex expands `~`, resolves the path and requires an existing local
directory (400 otherwise). New sessions created by bridge/subagent callers require explicit cwd.
`remote_id` is ACP sessionId or Codex threadId, initially null. States: `offline|connecting|idle|running|interrupting`.
`origin` is usually `ui|workflow|schedule|subagent`; parent records the calling workflow or subagent task.

Creation and every authenticated WS attachment enqueue `prepare` immediately. Connection runs in the background; a failed
preload adds an error notice and returns to offline. Opening the page never starts a model turn. Closing its WS never stops
work. Idle reaping disconnects sessions after the configured timeout. Codex unsubscribes each thread, then closes/reaps the
agent's process when its last connected session disconnects. Process exit cancels prompts, emits notices, marks all connected
sessions offline and completes active turns with `disconnected`.

Storage: `sessions.json` (session map), `items/<sid>.jsonl` (normalized transcript), `uploads/<sid>/<fid>` and
`uploads/<sid>/index.json`, `avatars/<aid>` plus `<aid>.mime`, `models/<aid>.json` (Codex model cache).
Items flush at most once per second during streaming and immediately at turn end/disconnect. Restart clears stale streaming
flags and cancels pending user items; it never re-executes persisted messages.

`config_options` uses `{id,name,category?,type:'select',currentValue,options:[{value,name,description?}]}`.
Codex exposes `model` (category `model`) and `effort` (category `thought_level`). The effort list follows the selected model;
changing model resets an unsupported effort to its default. Choices persist and apply on the next turn.
`GET /agents/{aid}/models` returns the raw Codex `model/list.data` cache (ACP returns `[]`), refreshed on every process start;
a cache miss starts and then closes an unused process. Model entries include `id,model,displayName,description,
supportedReasoningEfforts:[{reasoningEffort,description}],defaultReasoningEffort` and native extra fields.

`modes` is `{currentModeId,availableModes:[{id,name,description}]}`. Codex modes apply on the next turn:

| Mode | Sandbox | Approval policy |
|---|---|---|
| `full-access` | danger-full-access | never |
| `auto` | workspace-write; writable root is session cwd | on-request, reviewer user |
| `read-only` | read-only | on-request, reviewer user |

## Normalized transcript

Every item starts with `{id,kind,ts}`. Native item IDs are kept in `tool_use_id` for tools; UI IDs are local.

| kind | Fields |
|---|---|
| `user` | `text,attachments,pending,queued,client_id,cancelled?,steered?` |
| `text` | `text,streaming,phase:'commentary'|'final'|null` (ACP phase is null) |
| `thinking` | `text,streaming` |
| `tool` | `tool_use_id,name,tool_kind,input,status,locations,result,streaming` |
| `plan` | `entries:[{content,status,priority?}],explanation?`; one per turn, patched |
| `notice` | `level:'info'|'warn'|'error',text` |
| `result` | `stop_reason,duration_ms,usage?` |

Tool kind is `read|edit|delete|move|search|execute|think|fetch|mcp|other`. Status is
`pending|in_progress|completed|failed`; plan status is `pending|in_progress|completed`.
Tool result is null or `{content,is_error,images,diffs:[{path,old_text,new_text}]}`.
Codex adds:

- Command executions: `command,cwd,output,exit_code,duration_ms`; output streams as `delta` field `output`.
- File changes: `changes:[{path,kind:'add'|'delete'|'update',move_path,diff}]`; patch notifications replace this list.
  `diff` is unified text, also joined in result.content. `result.diffs` is empty because complete old/new files are not supplied.
- MCP calls: `server,tool`; input is arguments, result.content joins text blocks, `raw` retains the full native result.
- Web search: `query,url`; open-page actions use `fetch`, other searches use `search`.
- Unknown native items: `tool_kind:'other'`, name is the native type, input preserves the item JSON.

Native userMessage echoes are ignored. Completed text/tool items update the existing item authoritatively, without duplicating
it. ACP concatenates text deltas and maps tool updates/plans as before. Usage is `{input,cached_input,output,reasoning}`;
Codex result usage is the cumulative-token difference for that turn, session usage is the latest total, and
context is `{used,max}` when supplied. Native errors produce notices; terminal turn/completed determines Codex completion,
not thread idle. Stop reasons: ACP `end_turn|max_tokens|max_turn_requests|refusal|cancelled`, Codex
`completed|interrupted`, plus shared `error|disconnected` and queued-message `cancelled` results.

Permission request:
```text
{id,session_id,tool_call:{title,tool_kind,command?,cwd?,reason?,changes?,input?},
 options:[{option_id,name,kind}],created_at}
```
ACP option IDs are opaque remote IDs. Codex IDs are native decisions: `accept`, `acceptForSession`, `decline`, `cancel`
when offered. Their kinds are `allow_once`, `allow_always`, `reject_once`, `reject_once`. Labels are Allow, Allow for this
session, Decline, Cancel. Null replies cancel. Permission-profile approval grants the requested permissions for a turn/session;
rejection/cancellation grants an empty profile (the native schema has no cancel decision for this request).

Question request:
```text
{id,session_id,questions:[{id,header,question,options:[{label,description}],is_other,is_secret}],created_at}
```
Questions and permissions have no timeout. Interrupt, turn completion, disconnect, or native serverRequest/resolved clears
pending prompts. Unsupported Codex server requests produce a warn notice and JSON-RPC -32601.

## REST (cookie authentication)

All paths below are under `/api/more-agents`.

| Method | Path | Body / response |
|---|---|---|
| GET | `/kinds` | `[{kind,name,description}]` |
| GET/POST | `/agents` | List agent views / create discriminated agent (kind/name required; ACP host/port required) |
| GET/PATCH/DELETE | `/agents/{aid}` | Agent view / partial stored fields / `{ok:true}` |
| POST | `/agents/reorder` | `{ids}` containing every agent exactly once -> `{ok:true}` |
| GET/PUT | `/groups` | `{groups,renames?}` -> `{groups}` |
| GET/PATCH | `/settings` | `{idle_timeout_min}` |
| GET/POST | `/agents/{aid}/avatar` | Image bytes / multipart `file` (2 MiB max) -> agent view |
| POST | `/agents/{aid}/test` | `{ok,info,config_options,error?,models?}`; failures return ok:false |
| GET | `/agents/{aid}/models` | Cached native model list, ACP `[]` |
| GET/POST | `/agents/{aid}/sessions` | Session views newest first / `{cwd?,title?}` -> session view, preload scheduled |
| GET | `/agents/{aid}/search?q=` | `[{session,snippet}]` over persisted items |
| GET/PATCH/DELETE | `/sessions/{sid}` | Session view / `{title?}` / `{ok:true}` |
| POST | `/sessions/{sid}/read` | Session view with unread false |
| POST | `/sessions/{sid}/sleep` | Disconnect -> session view; 409 when busy |
| POST | `/sessions/{sid}/connect?fresh=false` | Connect -> session view; fresh replaces connection, 409 when busy |
| GET | `/sessions/{sid}/items?before=&limit=200` | `{items,has_more}`; limit 1..200 |
| POST | `/sessions/{sid}/uploads` | multipart `files` (50 MiB each) -> attachment records |
| GET | `/uploads/{sid}/{fid}` | Uploaded bytes |

Attachment record: `{id,name,mime,size,path,url,is_image}`. ACP sends images <=3.75 MB as base64 only if supported;
UTF-8 files <=200 kB as embedded resources only if supported, otherwise filename text. Codex sends images as localImage paths
and appends `Attached file: <absolute path>` for other attachments. Delete removes local session data/uploads; it does not
archive/delete remote Codex threads.

## WebSocket `/ws/more-agents/{sid}`

First command is `{type:'resume',seq}`. Events have increasing `seq`; the 500-event ring replays when possible, otherwise sends
a snapshot. Both paths end in `resumed {seq}`. Slow subscribers overflow and close (1013) to allow resync.
Snapshot: `{type,seq,session,state,items,has_more,permissions,questions,elapsed_ms}`.
Events: `item {item}`, `patch {id,patch}`, `delta {id,field:'text'|'output',text}`, `state {state,elapsed_ms}`,
`session {session}`, `permission {request}`, `permission_resolved {id,option_id}`, `question {request}`,
`question_resolved {id}`, `error {message,req_id?}`, `pong {seq}`, `snapshot`, `resumed`.

| Command | Payload | Effect |
|---|---|---|
| `resume` | `{seq}` | Replay or snapshot |
| `ping` | `{}` | pong |
| `send` | `{client_id?,text,attachments:[fid]}` | Start or queue; Codex steers a running turn and marks user steered:true |
| `cancel_queued` | `{id}` | Cancel undelivered user item |
| `interrupt` | `{}` | Cancel prompts, interrupt native turn, wait for native completion |
| `permission_reply` | `{id,option_id:string|null}` | Answer permission |
| `question_reply` | `{id,answers:{question_id:[string]}|null}` | Answer question, null cancels |
| `set_config` | `{config_id,value}` | Connect if needed; store/apply setting |
| `set_mode` | `{mode_id}` | Connect if needed; store/apply mode |
| `connect` | `{}` | Connect/load metadata |

Controls accept optional `req_id` for error correlation. Codex steer uses expectedTurnId; if the turn has ended, the message
queues as a normal turn. Bridge run/start always queue separate turns. Closing the browser does not cancel any work.

## Native transports and public API

ACP retains newline JSON-RPC over TCP with optional `AUTH <token>\n`, initialize protocol version 1 (filesystem and terminal
capabilities disabled), session/new or session/load using **session.cwd**, config_defaults on new sessions, session/prompt,
session/cancel, session/set_config_option and session/set_mode. Load replay is suppressed. Failed native load adds a notice
and starts a fresh remote session, preserving local history.

Codex starts `command app-server --listen stdio:// -c analytics.enabled=false *args`, inheriting environment plus env,
with a 64 MiB stdout line limit and drained stderr. Initialize enables experimentalApi. One process per agent multiplexes
threads. Start/resume reapplies cwd, sandbox/approvals, developerInstructions, and reasoning config; resume uses excludeTurns:true.
Missing threads add a notice and start fresh. Turn/start sends input/cwd/model/effort/summary:auto and mode settings;
turn/steer and turn/interrupt use the current native turn ID. Local normalized history is authoritative for rendering.

Other modules use `core.bridge.run_more/start_more/wait_more`, or manager public methods
`agents,agent,create_agent,patch_agent,delete_agent,sessions,create_session,prepare,start_turn,run_turn,wait_turn,send,stop,
set_option,set_mode,view,items,running,kinds,models,cached_models`. Bridge results always contain
`{session_id,text,stop_reason,is_error,error}`. `on_session` runs before enqueue. New subagent sessions require cwd;
existing sessions retain theirs. Model/effort overrides select config options by category model/thought_level (ACP skips
unoffered options). `wait_more` waits for the latest submitted turn future, including queued turns.

`running()` returns `{module:'more_agents',session_id,agent_id,agent_name,avatar,title,state,pending,unread,updated_at,preview,cwd}`
for running/interrupting sessions or those with pending prompts. The core track owns the aggregate REST endpoint.
Global events: `session_state` with module `more_agents` and session_id/agent_id/state/pending/unread/title/updated_at/preview;
`more_agents_changed` invalidates agents. Hello adds `more_agents_sessions:[{id,agent_id,state,pending,unread}]`.
Overview contributes `more_agents_agents` and `sessions` to the Agents counters.

## Migration

Run `uv run python scripts/migrate/core.py --data DIR` first. Then preview with
`uv run python scripts/migrate/more_agents.py --data DIR --dry-run` and rerun without dry-run during deployment.
It moves config/acp.toml and acp/, adds kind/cwd, renames tool_kind, normalizes unknown tool kinds, updates upload URLs/paths,
workflow card types, schedule target modules, and Claude parent links. TOML comments and tokens are preserved.
Affected workflows are printed by ID/name for manual cwd completion; no cwd is invented for workflow cards or schedules.
Both old and new paths existing is an explicit collision error. Repeat runs are idempotent. The core migration moves the
legacy schedules file into builtin/; this migration handles either location.
