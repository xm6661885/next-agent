# next-agent architecture

One FastAPI process (`server/`) and one Preact PWA (`web/`). The app has four independent modules, shown as the
bottom tabs **Chat · Agents · Workflow · More**. Modules do not import each other's internals; the only shared code
is the core (auth, paths, TOML store helpers, global event feed) and a few narrow bridges listed below.

| Module | Backend | Frontend | Config file | Data |
|---|---|---|---|---|
| core | `server/app.py`, `auth.py`, `paths.py`, `tomlstore.py`, `feed.py` | `web/src/lib`, `web/src/components` | `data/config/core.toml` | `data/secret.key` |
| Agents (Claude) | `server/*.py` (runtime, items, history, options, ...) | `web/src/modules/agents` | `data/config/agents.toml` | `data/sessions.json`, `data/agents/`, `data/uploads/` |
| Agents (ACP) | `server/acp/` | `web/src/modules/agents/acp` | `data/config/agents.toml` (`acp_*`) | `data/acp/` |
| Built-in MCP | `server/builtin/` | settings pages + tool cards in the Claude chat | `data/config/agents.toml` (`builtin_mcp`) | `data/schedules.json` |
| Chat | `server/chat/` | `web/src/modules/chat` | `data/config/chat.toml` | `data/chat/` |
| Workflow | `server/workflow/` | `web/src/modules/workflow` | `data/config/workflow.toml` | `data/workflow/` |
| Settings / More | `server/settings.py` | `web/src/modules/settings`, `web/src/modules/more` | all of the above | |

## Shared Claude CLI
Agents and Workflow share one Claude Code CLI setup (`[claude]` in core.toml: cli path, concurrency, API base URL/key).
Workflow never starts a CLI itself: its agent cards create normal Agents sessions through `server/bridge.py`
(`AgentBridge`), so the concurrency gate, idle reaper and chat UI are the Agents ones.

## Bridges (the only cross-module calls)
- `server/bridge.py` `AgentBridge`: run a turn on a Claude session (temporary or a named agent) or an ACP session and
  wait for the result. Used by Workflow cards, the scheduler and the built-in collaboration tools.
- `server/feed.py` `Feed`: the `/ws/events` broadcaster. Every module emits `session_state` events tagged with `module`.

## Frontend rule
Each module owns a full copy of the chat UI it needs (`modules/*/chat/`). Copies may diverge; never import a chat
component from another module. Shared primitives (buttons, sheets, icons, avatars, markdown renderer is NOT shared)
live in `web/src/components`.

## Contracts
- `docs/protocol.md`: core + Agents (Claude) REST/WS, config layout and migration, settings API.
- `docs/protocol-acp.md`, `docs/protocol-chat.md`, `docs/protocol-workflow.md`, `docs/builtin-mcp.md`.
