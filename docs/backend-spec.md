# Backend implementation spec (for the implementer)

Read first, in this order: `docs/protocol.md` (the contract, follow it exactly), `docs/sdk-notes.md` (SDK facts; section 9 is
verified locally and overrides earlier sections), `scripts/probe_sdk.py` (working SDK usage). The SDK source is in
`.venv/lib/python3.13/site-packages/claude_agent_sdk/`. Read `types.py`, `client.py`, and `_internal/sessions.py` when
you need exact field names. Do not guess.

Stack: Python 3.13, FastAPI, uvicorn, pydantic v2, tomlkit, bcrypt, itsdangerous, and claude-agent-sdk==0.2.163 (already
in `pyproject.toml`, installed in `.venv`). Run everything with `uv run ...`. If you need a new dependency, pin an exact
version in pyproject and say so in your final report. 

Hard constraints:
- Keep resource use low. Do not install or launch browsers. Do not leave background processes running.
  Tests must not spawn the real CLI (mock the SDK client). Clean up any scratch files you create in /tmp.
- Do not touch `web/` (the frontend is written by someone else in parallel). Serve `web/dist` if it exists.
- English only in code, comments, and log messages. No emoji anywhere.
- Do not run `git commit`.

## Layout

```
server/
  __init__.py
  __main__.py      # `python -m server` -> uvicorn on config host/port (host "::"), proxy_headers, forwarded_allow_ips="*"
  app.py           # create_app(data_dir) factory: routes, static files, lifespan (start/stop managers)
  paths.py         # DataDir: data_dir resolution (env NEXT_AGENT_DATA, default <repo>/data), subpaths
  config.py        # pydantic models + ConfigStore (load/save/hot-reload of config.toml via tomlkit)
  auth.py          # password hash, signed cookie, login rate limit, FastAPI dependencies for HTTP and WS
  agents.py        # agent service: CRUD over ConfigStore, avatar, CLAUDE.md, computed status
  store.py         # SessionIndex (data/sessions.json, atomic writes) + upload records
  history.py       # transcript -> items conversion (uses SDK get_session_messages)
  items.py         # ItemBuilder: SDK live messages -> item/patch/delta events (shared conversion helpers with history.py)
  runtime.py       # SessionRuntime + RuntimeManager (concurrency semaphore, idle reaper, global event feed)
  permissions.py   # PendingPermission registry, can_use_tool factory, reply -> PermissionResult
  uploads.py       # save uploads, build SDK content blocks
  options.py       # build ClaudeAgentOptions from Agent + Session overrides + defaults
  extensions.py    # ExtensionBus: async hooks (see below)
  ws.py            # /ws/sessions/{sid} and /ws/events handlers
tests/
  conftest.py      # tmp data dir, fake SDK client, TestClient helpers
  test_config.py test_auth.py test_agents_api.py test_runtime.py test_permissions.py test_history.py test_ws.py
```

## Data dir (`data/`, gitignored)

```
data/config.toml
data/secret.key            # 32 random bytes hex, created on first start, mode 0600
data/sessions.json         # {"sessions": {sid: SessionRecord}, "uploads": {file_id: UploadRecord}}
data/agents/<id>/avatar.<ext>
data/agents/<id>/CLAUDE.md
data/uploads/<sid>/<file_id>-<safe_name>
```
Create directories with mode 0700 and files with mode 0600 (set `os.umask(0o077)` at startup).

## config.toml

On first start, if no config exists, write this. Generate a random password (or use `NEXT_AGENT_PASSWORD`), print it once, hash it with bcrypt and store the hash only.
Keep the comments, since they double as documentation for hand editing.

```toml
# next-agent configuration. Edited by the web UI and safe to edit by hand; changes are picked up automatically.
[server]
host = "::"
port = 18793
password_hash = "<bcrypt>"   # change via: uv run python -m server set-password
max_concurrent = 3           # max simultaneously connected Claude CLI processes (~200 MB each)
idle_timeout_min = 10        # disconnect an idle CLI after this many minutes (session resumes on next message)
cli_path = ""                # empty = CLI bundled with claude-agent-sdk

[defaults]                   # used when an agent field is empty
model = ""                   # empty = Claude Code default from ~/.claude/settings.json
effort = ""
permission_mode = "bypassPermissions"

[[agents]]
id = "claude"
name = "Claude"
avatar = "crab:pink"
cwd = "/home/you"
# ... all Agent fields from docs/protocol.md with their defaults
```

- `ConfigStore` holds the parsed tomlkit document plus validated pydantic models. Writes go through the tomlkit
  document, so comments and ordering survive. Write to a temp file and `os.replace`.
- Unknown keys are kept (forward compatible) and ignored.
- Hot reload: poll the file mtime every 2 s with an asyncio task (no watchdog dependency). If it changed and is valid, swap
  the models in and emit `agents_changed` on the global feed. If it is invalid, keep the old config and log a warning.
  Running sessions keep their options, and the new config applies at the next CLI start.
- CLI subcommand: `python -m server set-password` prompts twice via getpass and writes the hash.
  `python -m server` (no args) runs the server.

## Auth

- bcrypt check. Cookie value = itsdangerous `TimestampSigner(secret).sign(fingerprint)` where
  `fingerprint = sha256(password_hash)[:16]`. Max age 30 days. Rate limiting is an in-memory dict per IP, as described in protocol.md.
- Dependency `require_auth` for routers. For WS, check the cookie and Origin before `accept()`, and on failure accept then
  close with 4401/4403 (browsers can't read the HTTP status of a rejected upgrade).
- Static files and `/api/login` are public. Static means the SPA: serve `web/dist`, fall back to `index.html` for unknown
  non-`/api` and non-`/ws` paths, serve `sw.js` with `Cache-Control: no-cache`, and serve hashed assets under
  `/assets/` with a long cache.

## Options builder (options.py)

`build_options(agent, session, defaults, server_cfg, can_use_tool, resume: str|None, fork: bool, resume_at: str|None, new_session_id: str|None) -> ClaudeAgentOptions`
- `cwd=agent.cwd`. `model` = session override, else agent value, else defaults value, else None. Same for effort and permission_mode.
- `system_prompt`: for preset, `{"type":"preset","preset":"claude_code","append": X}`, where X joins agent.system_prompt and
  (when `claude_md == "custom"` and the file exists) `"# Agent instructions (CLAUDE.md)\n" + content`. Leave out `append` when
  it's empty. For custom, use the plain string.
- `thinking`: "" -> None; adaptive -> `{"type":"adaptive"}`; enabled -> `{"type":"enabled","budget_tokens": budget or 8000}`; disabled -> `{"type":"disabled"}`.
- `setting_sources=agent.setting_sources`. If `"user"` is missing, add it anyway and log a warning: credentials come from
  user settings (see sdk-notes section 9).
- `include_partial_messages=True`, `can_use_tool=...`, `enable_file_checkpointing=agent.enable_file_checkpointing`.
- `extra_args = {"replay-user-messages": None, **agent.extra_args}` (replay is required, see protocol.md `send`).
- `tools` only when non-empty. Also pass allowed/disallowed_tools, add_dirs, env, mcp_servers, agents (convert to
  `AgentDefinition`), max_turns/max_budget_usd (0 -> None), fallback_model ("" -> None), and cli_path ("" -> None).
- `stderr=` a callback that keeps the last 50 lines in the runtime, for error notices.
- For a new session, `session_id=new_session_id` so the CLI session id equals our session id. For an existing one,
  `resume=sdk_session_id`. For a fork, `resume=<source sdk id>, fork_session=True, resume_session_at=at_uuid`. Check
  `types.py` for the constraints between session_id, resume, and fork. If session_id can't be combined with a fork, let the
  CLI pick the id and record it from the first `init`/result message.

## SessionRuntime (runtime.py)

One per session while live. **All SDK client calls happen inside one dedicated asyncio task** (`_worker`), per SDK issue #576.

```
class SessionRuntime:
    state: str                     # protocol states
    seq: int; ring: deque(maxlen=2000) of event dicts
    subscribers: set[asyncio.Queue]   # one per websocket, maxsize 1000; if full, drop the subscriber (client will resume)
    commands: asyncio.Queue        # ("send", payload) | ("interrupt",) | ("set_mode", m) | ("set_model", m) | ("stop_task", id) | ("rewind", uuid) | ("shutdown",)
    items: ItemBuilder             # current-process live items, also used for snapshots
```
Worker lifecycle:
1. `queued`: acquire the manager semaphore (the queue position is the number of waiters ahead, exposed in `state` events).
2. `starting`: build options, `client = ClaudeSDKClient(options)`, `await client.connect()`. On failure, emit a `notice`
   error item with the stderr tail, release the slot, go `offline`, and fail the pending sends with an error notice.
3. Start a reader task, created from inside the worker so it runs in the same context chain. If that still hangs (see
   issue #576), restructure so a single task does both, e.g. the worker awaits `asyncio.wait({next_message, next_command})`.
   Read with `async for msg in client.receive_messages()` and never stop at ResultMessage. Feed every message to the
   ItemBuilder, which returns events to broadcast.
4. Commands are processed in order. `send` -> `client.query(AsyncIterable yielding one user message dict)`. The dict shape
   is in sdk-notes section 6, with `session_id` set. State goes to `running` when a send is written while idle. While
   running, the write simply happens (steer).
5. A `ResultMessage` -> state `idle`, unless more sends were written that the CLI hasn't consumed yet (track a counter of
   written vs echoed user messages). Update the session index: cost (`total_cost_usd` is cumulative per CLI process, so
   compute turn cost as the delta, and keep `session.total_cost_usd` as the sum of deltas across processes), turns,
   preview, updated_at, sdk_session_id. Then call `get_context_usage()` (wrap it in try/except and a timeout), store the
   summary `{used, max, percent}` in session.context, and emit a `session` event. Read `ContextUsageResponse` in types.py
   for the field names.
6. Idle reaper: the manager checks every 30 s. A runtime in `idle` with no open permission requests whose last activity
   is older than `idle_timeout_min` -> `shutdown`, which means `client.disconnect()`, release the slot, and go `offline`.
   The runtime object may stay in memory for its ring buffer, which lets reconnecting clients resume. Websocket
   subscribers have no effect on the reaper.
7. If the CLI process dies unexpectedly (the reader raises or ends), emit an error notice, resolve open permissions as
   cancelled, release the slot, and go `offline`. The next `send` restarts it with resume.
8. `interrupt` -> state `interrupting`, call `client.interrupt()`, cancel open permission futures (deny with
   `interrupt=True`). The ResultMessage that follows sets the state to idle. Emit a `notice` item "Interrupted".
9. `set_effort` and agent config edits don't touch a live client. Effort goes into overrides. If the runtime is idle,
   restart the CLI (disconnect and reconnect with resume) so it takes effect; if it's running, flag a restart for when the turn ends.

RuntimeManager:
- `get_or_create(sid)`, `semaphore = asyncio.Semaphore(max_concurrent)` (resizable when config changes: rebuild for new
  waiters). Global feed subscribers get `session_state` events whenever state, pending count, title, or preview change.
- On app shutdown, disconnect every client gracefully (with a timeout per client) and wait at most 10 s total.
- `memory_mb` in `/api/status` = this process RSS plus the RSS of its child processes, read from /proc.

## ItemBuilder (items.py)

Converts SDK messages into items, following the table in protocol.md. Rules:
- `StreamEvent` with `parent_tool_use_id` None or not:
  - `content_block_start` text -> new `text` item (streaming) keyed by `(message id, index)`; thinking -> `thinking` item;
    tool_use -> `tool` item with id = block id, `input_partial=""`.
  - `content_block_delta` `text_delta` / `thinking_delta` / `input_json_delta` -> `delta` event.
  - `content_block_stop` -> `patch streaming:false`. Tool input gets parsed from the partial JSON when it's done.
- `AssistantMessage` (complete): for each block, if a streamed item exists for it, patch it with the final text/input
  (authoritative). Otherwise create the item. This covers subagent text and cases where streaming was disabled.
  Assistant `error` field -> `notice` item.
- `UserMessage`: if content contains `ToolResultBlock`s -> patch the tool item's `result` (normalized like the protocol
  says, with `tool_use_result` ignored). Otherwise it's a replayed user prompt: match it FIFO to the oldest `pending` user
  item and patch `{pending:false, uuid}`. If there is none (e.g. a prompt from a different device in an earlier process),
  create a `user` item.
- `SystemMessage`: `init` -> `init` event if its content changed, and record sdk_session_id. `task_started` /
  `task_progress` / `task_notification` / `task_updated` -> update the tasks map and emit `tasks`. `status` -> ignore.
  `compact_boundary` or anything mentioning compaction -> `notice` "Conversation compacted". Unknown subtypes -> ignore,
  debug log.
- `ResultMessage` -> `result` item, plus `notice` error items for `errors`.
- `RateLimitEvent` -> `notice` warn. Other unknown message classes are ignored.
- Item ids: `uuid4().hex[:12]`, except tool items, which use tool_use_id.
- Keep at most 2000 items in memory per runtime. Older ones come from history.

## History (history.py)

`load_items(session, agent) -> list[item]` uses `get_session_messages(sdk_session_id, directory=agent.cwd)`. Check the
signature and SessionMessage fields in `_internal/sessions.py`. Convert with the same block helpers as ItemBuilder:
user string or text-block content -> `user` items, with attachment lines turned back into attachments;
tool_result content -> attach to the matching tool item; assistant blocks -> text/thinking/tool items;
`parent_tool_use_id` carried over. Cache the converted list per (sid, file mtime).

Snapshot for a WS client = history items + live items of the current runtime that aren't yet in the transcript. Simplest
correct approach: when a runtime is live, snapshot = history loaded at runtime start + all live items since then. When
offline = history. Paginate with `before`/`limit` (last 200 in the snapshot, `has_more`).

## Permissions (permissions.py)

`make_can_use_tool(runtime)` returns `async def can_use_tool(tool_name, input, ctx)`:
- kind = question for `AskUserQuestion`, plan for `ExitPlanMode`, otherwise tool.
- Create a PendingPermission with an asyncio Future. Emit a `permission` event, plus a `session_state` event on the global
  feed (pending count). Call the extension hook `on_permission_request`. Await the future with no timeout.
- Reply mapping:
  - tool + allow -> `PermissionResultAllow()`. allow_always -> `PermissionResultAllow(updated_permissions=ctx.suggestions)`
    when suggestions exist. Otherwise synthesize
    `PermissionUpdate(type="addRules", rules=[PermissionRuleValue(tool_name=tool_name)], behavior="allow", destination="session")`.
  - deny -> `PermissionResultDeny(message=message or "The user denied this action.")`.
  - question + allow -> `PermissionResultAllow(updated_input={"questions": input["questions"], "answers": answers})`.
    Deny -> `PermissionResultDeny(message=message or "The user declined to answer.")`.
  - plan + allow -> `PermissionResultAllow()`. If `mode` is given, queue a `set_mode` command for after the callback returns
    (don't call the client from inside the callback, since this runs in the SDK's control task), and persist the override.
    Deny -> `PermissionResultDeny(message=message or "The user rejected the plan. Ask what to change.")`.
- On interrupt, shutdown, or crash, resolve every pending request with Deny(interrupt=True) and emit `permission_resolved` with decision cancelled.
- Replying to an unknown or already resolved id -> `error` event to that socket only.

## Uploads (uploads.py)

- Store at `data/uploads/<sid>/<file_id>-<safe_name>`. `safe_name` keeps `[A-Za-z0-9._-]`, replaces everything else with
  `_`, and is at most 80 chars. Detect the mime from the filename (mimetypes), falling back to `application/octet-stream`.
- `build_content(text, attachments) -> list[block]` as protocol.md describes. Use absolute paths.

## ExtensionBus (extensions.py)

A small registry for future features (webhook notifications, agent groups). No behavior today besides logging at debug.
```python
class ExtensionBus:
    def on(self, event: str, handler: Callable[..., Awaitable[None]]): ...
    async def emit(self, event: str, **payload): ...  # never raises; errors are logged
# events: session_state(session_id, agent_id, state), turn_result(session_id, agent_id, result_item),
#         permission_request(session_id, agent_id, request), agent_changed(agent_id)
```
Also support `[extensions]` in config as a free-form table, passed to handlers as `config`. Leave a docstring describing
how a webhook notifier would plug in.

## Sessions API details

- Creating a session through the API only makes an index record, with `id = uuid4()`. The first `send` starts the CLI with
  `session_id=id`.
- Fork: `POST /fork` makes a new record with `fork_of = {session_id, at_uuid}` and `sdk_session_id = None`. Its first start
  uses resume+fork_session (+resume_session_at). Once the CLI reports the new session id, store it. Title = `"<source title> (fork)"`.
  Until the first message, the fork's snapshot shows the source history (up to at_uuid).
- Import: for each sdk id, make a record with `id = sdk id`, `sdk_session_id = sdk id`, `imported = true`, title = custom_title
  or summary or first_prompt (60 chars).
- Delete with purge: remove `~/.claude/projects/<encoded>/<sdk id>.jsonl`. Find the file via the SDK helper that resolves the
  project dir. If none exists, match the session id in `list_sessions` output and use the documented path rule.
- `/api/meta` `models`: `["", "opus", "sonnet", "haiku", "opus[1m]", "claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"]` (free text is allowed too).

## Tests (pytest, `uv run pytest -q`)

Write a `FakeClaudeSDKClient` in conftest that matches the methods the runtime uses, and monkeypatch it where runtime.py
imports it. It replays a scripted list of real SDK dataclass instances (StreamEvent, AssistantMessage, UserMessage with
ToolResultBlock, ResultMessage, and replayed UserMessage for each query). Required tests:
- config: first start creates the file with a hash (not the plaintext), keeps comments on round-trip, hot reload picks up a hand edit, an invalid edit is ignored.
- auth: login ok/fail, cookie required on /api and ws, rate limit, password change invalidates the old cookie.
- agents API: create/patch/delete/reorder, id slug derivation and conflict, avatar upload size/type limits, claude-md inherit vs custom paths.
- runtime: send -> state transitions queued/starting/running/idle and events in order; steer while running produces a pending user
  item, then patched with a uuid; interrupt; concurrency cap 1 with two sessions (second is queued, then runs after the first is reaped);
  the idle reaper disconnects (use a tiny timeout); the reader dying leads to offline + notice; turn cost delta accounting.
- permissions: tool allow/deny/allow_always (suggestions and synthesized), question answers shape, plan approve with a mode switch, cancellation on interrupt.
- history: conversion of a sample transcript (write a fixture jsonl, or monkeypatch get_session_messages), attachment line round-trip.
- ws: resume with an old seq replays only the newer events, with an evicted seq -> snapshot; two subscribers get the same events; disconnecting a subscriber doesn't stop the runtime.

## Final check before you finish

1. `uv run pytest -q` passes.
2. Smoke run: `NEXT_AGENT_DATA=$(mktemp -d) timeout 20 uv run python -m server &`, then curl `/api/login` with the
   password, `/api/agents`, and `/api/meta`. Make sure it listens on `[::]:18793` (use a different port via env
   `NEXT_AGENT_PORT` if it's taken; support that env override). Kill it afterwards and delete the temp dir.
3. Do not start a real Claude turn (that costs money). The lead developer will run the end-to-end tests.
4. Write a short final report: files, any deviations from this spec or protocol.md (there should be none without a good
   reason), known limitations, and anything the frontend developer must know.
