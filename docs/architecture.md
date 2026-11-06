# next-agent architecture

One FastAPI process (`server/`) and one Preact PWA (`web/`). The app is made of independent modules, shown as the
bottom tabs **Chat · Agents · Automations · Workflow · More**. Modules do not import each other's internals; the only shared code
is the core (auth, paths, TOML store helpers, global event feed) and a few narrow bridges listed below.

| Module | Backend | Frontend | Config file | Data |
|---|---|---|---|---|
| core | `server/app.py`, `core.py`, `auth.py`, `paths.py`, `tomlstore.py`, `bridge.py` | `web/src/lib`, `web/src/components` | `data/config/core.toml` | `data/core/secret.key` |
| Agents (Claude) | `server/*.py` (runtime, items, history, options, ...) | `web/src/modules/agents` | `data/config/agents.toml` | `data/agents/sessions.json`, `data/agents/profiles/<agent-id>/`, `data/agents/uploads/<session-id>/` (fallback uploads) |
| Agents (ACP) | `server/acp/` | `web/src/modules/acp` | `data/config/acp.toml` | `data/acp/` |
| Built-in MCP | `server/builtin/` | settings pages + tool cards in the Claude chat | `data/config/agents.toml` (`builtin_mcp`) | `data/builtin/schedules.json` |
| Chat | `server/chat/` | `web/src/modules/chat` | `data/config/chat.toml` | `data/chat/` (sessions/messages/uploads; `assistants/<aid>/files/`; `memory/<aid>.json`) |
| Workflow | `server/workflow/` (core/extra/user cards, HTTP triggers) | `web/src/modules/workflow` | `data/config/workflow.toml` | `data/workflow/` (`app.db` incl. per-workflow trigger tokens, `plugins/`, `workspace/`) |
| Speech to text | `server/asr/` | More tab | `data/config/asr.toml` | `data/asr/` |
| Image generation | `server/imagegen/` | More tab | `data/config/imagegen.toml` | `data/imagegen/` |
| Settings / More | `/api/settings/*` in `server/app.py` | `web/src/modules/settings`, `web/src/modules/more` | all of the above | |

## Shared Claude CLI
Agents and Workflow share one Claude Code CLI setup (`[server]` in core.toml: cli path, concurrency, API base URL/key).
Workflow never starts a CLI itself: its agent cards create normal Agents sessions through `server/bridge.py`
(`AgentBridge`), so the concurrency gate, idle reaper and chat UI are the Agents ones.
Workflow scans shipped `plugins_core/` and `plugins_extra/` cards plus `data/workflow/plugins/` user cards.
The `extra.notify` card invokes the local notification CLI without a shell. Public HTTP triggers authenticate
with per-workflow tokens stored in `app.db`'s `triggers` table; their management uses normal Workflow auth.

## Bridges (the only cross-module calls)
- `server/bridge.py` `AgentBridge`: run a turn on a Claude session (temporary or a named agent) or an ACP session and
  wait for the result. Used by Workflow cards, the scheduler and the built-in collaboration tools.
- `core.emit` (`server/core.py`, served by `/ws/events` in `app.py`): the global feed. Every module emits `session_state` events tagged with `module`.
- `GET /api/running`: combines the synchronous `running()` providers exposed by `core.modules`, including Agents, and sorts their session rows by `updated_at` descending. See `docs/protocol.md` for the row contract.

## Frontend rule
Each module owns a full copy of the chat UI it needs (`modules/*/chat/`). Copies may diverge; never import a chat
component from another module. Shared primitives (buttons, sheets, icons, avatars, markdown renderer is NOT shared)
live in `web/src/components`.

## Contracts
- `docs/protocol.md`: core + Agents (Claude) REST/WS, config layout and migration, settings API.
- `docs/protocol-acp.md`, `docs/protocol-chat.md`, `docs/protocol-workflow.md`, `docs/protocol-apps.md`, `docs/builtin-mcp.md`.

## AgentBridge (`server/bridge.py`, `core.bridge`)
Runs work on Agents-module sessions for other modules. Claude sessions go through the normal `RuntimeManager`
(same concurrency gate, idle reaper, transcripts, chat page); ACP sessions go through `core.modules['acp']`.
```python
async def run_claude(agent_id, prompt, *, session_id=None, title='', origin='workflow', parent=None,
                     cwd=None, overrides=None, extra=None) -> dict
    # agent_id '_temp' (or None) = temporary session in `cwd` (default home) using the temp agent settings.
    # overrides: {model, effort, permission_mode} (None/'' = agent value); extra: see Session.extra.
    # Creates a session unless session_id is given; sends prompt (waits behind a running turn); waits for the result.
    # -> {session_id, text, structured, cost_usd, is_error, error}
def start_claude(...same args...) -> str        # session id; does not wait
async def wait_claude(session_id) -> dict       # wait for the current/next turn result, same dict
async def run_acp(agent_id, prompt, *, session_id=None, title='', origin='workflow', parent=None) -> dict
    # -> {session_id, text, stop_reason, is_error, error}
def start_acp(...) -> str
async def send(module, session_id, prompt)      # module 'agents' | 'acp'; like typing in the chat
async def stop(module, session_id)              # interrupt
def view(module, session_id) -> dict            # Session / AcpSession
def items(module, session_id) -> list           # transcript items (Claude: history + live)
```
`text` is `ResultMessage.result` when non-empty, else the top-level `text` items produced in that turn joined by
blank lines. `is_error` is true on a failed result, a CLI connection failure or a disconnect.

## More tab apps
Speech to text keeps recording metadata and audio under `data/asr/recordings/<id>/`; its `routes.py`, `jobs.py`,
`store.py` and `transcribe.py` separate HTTP contracts, resumable processing, locked metadata and upstream/audio work.
Image generation keeps job JSON, references/masks and outputs under `data/imagegen/jobs/<id>/`; `routes.py`,
`jobs.py` and `client.py` separate validation, the two-job concurrency gate and OpenAI-compatible requests.
Both register TOML files in the raw editor, honor HTTP proxy environment variables and invalidate the global feed
with `asr_changed` / `imagegen_changed`. ASR resumes interrupted/stale work; image jobs interrupted by a restart
become errors for explicit retry. Full client contracts are in `docs/protocol-apps.md`.
