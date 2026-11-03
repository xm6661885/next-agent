# next-agent: maintainer notes

Web console with four modules (Chat, Agents incl. ACP, Workflow, More) plus a built-in MCP server. See README.md for usage and `docs/architecture.md` for the module map.

## Read first
- `docs/protocol.md` (core + Claude agents), `protocol-acp.md`, `protocol-chat.md`, `protocol-workflow.md` and `builtin-mcp.md` are the contracts between `server/` and `web/`. Change both sides together and update the doc.
- Modules never import each other's internals. Cross-module work goes through `core.bridge` (`server/bridge.py`); Workflow cards, schedules and collab tools never start their own CLI.
- `docs/sdk-notes.md` has the SDK facts. Section 9 was verified against the real CLI and wins over the earlier sections.
- `docs/backend-spec.md` is the original backend design. The code is the source of truth now.

## Layout
- `server/runtime.py`: `SessionRuntime` (one per session) and `RuntimeManager` (concurrency gate, idle reaper, global feed). Each runtime has one worker task that owns the `ClaudeSDKClient`. All client calls must happen inside that task (SDK issue #576). Other code sends commands through `runtime.submit(...)`.
- `server/items.py`: converts SDK messages into transcript items and item/patch/delta events. `server/history.py` builds items from transcripts on disk (`get_session_messages`). Changes to one usually need the matching change in the other.
- `server/permissions.py`: `can_use_tool` creates a pending request and waits on a future with no timeout. It handles AskUserQuestion answers and ExitPlanMode.
- `server/options.py`: Agent + session overrides become `ClaudeAgentOptions`. It always sets `extra_args["replay-user-messages"]` (steering confirmation needs it) and `allow-dangerously-skip-permissions` (so a session can switch to bypassPermissions later).
- `server/extensions.py`: `ExtensionBus`, the hook point for future webhooks, notifications and agent groups. Events: `session_state`, `turn_result`, `permission_request`, `agent_changed`.
- `server/acp/`, `server/chat/`, `server/workflow/`, `server/builtin/`: one package per module, each with `mount(app, core)` and its own `data/config/*.toml`.
- `web/src/modules/<module>/`: each module's pages and its own copy of the chat UI (`chat/`, with `conn.ts` resuming by `seq`). Never import chat components across modules. Shared primitives live in `web/src/components` and `web/src/lib`. Styles live in `web/src/styles/` and use the CSS variables in `base.css`.
- Tab roots are listed in `isTabRoot` (`web/src/lib/router.ts`); the route wrapper adds `with-tabbar`, so pages must not add it again.

## Rules
- After a backend change, run `uv run pytest -q`, then restart the service.
- After a frontend change, run `cd web && npm run build`. Bump `CACHE` in `web/public/sw.js` when the shell itself changes.
- The UI must not use emoji. Icons are inline SVG in `web/src/components/icons.tsx`. Accent pink is `#fbc7d1`, the background is warm ivory, and dark mode follows `prefers-color-scheme`.
- Closing a WebSocket must never interrupt or stop a runtime. Only an explicit `interrupt`, the idle reaper or shutdown can do that.
- Tests mock the SDK; `scripts/e2e.py` is the only test that calls the real model.
- Treat `data/` as user data. It holds config, password hash, sessions and uploads.
- An empty model means the CLI default.
