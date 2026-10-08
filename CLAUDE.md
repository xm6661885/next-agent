# next-agent: maintainer notes

Web console for persistent Claude Agent SDK agents. See README.md for usage and operations.

## Read first
- `docs/protocol.md` is the REST + WebSocket contract between `server/` and `web/`. Change both sides together and update the doc.
- `docs/sdk-notes.md` has the SDK facts. Section 9 was verified against the real CLI and wins over the earlier sections.
- `docs/backend-spec.md` is the original backend design. The code is the source of truth now.

## Layout
- `server/runtime.py`: `SessionRuntime` (one per session) and `RuntimeManager` (concurrency gate, idle reaper, global feed). Each runtime has one worker task that owns the `ClaudeSDKClient`. All client calls must happen inside that task (SDK issue #576). Other code sends commands through `runtime.submit(...)`.
- `server/items.py`: converts SDK messages into transcript items and item/patch/delta events. `server/history.py` builds items from transcripts on disk (`get_session_messages`). Changes to one usually need the matching change in the other.
- `server/permissions.py`: `can_use_tool` creates a pending request and waits on a future with no timeout. It handles AskUserQuestion answers and ExitPlanMode.
- `server/options.py`: Agent + session overrides become `ClaudeAgentOptions`. It always sets `extra_args["replay-user-messages"]`, which steering confirmation needs.
- `server/extensions.py`: `ExtensionBus`, the hook point for future webhooks, notifications and agent groups. Events: `session_state`, `turn_result`, `permission_request`, `agent_changed`.
- `web/src/chat/conn.ts`: per-chat WebSocket. It resumes by `seq` and applies events to signals.
- `web/src/chat/`: chat UI (tools, request cards, composer). `web/src/pages/` holds the other pages. Styles live in `web/src/styles/` and use the CSS variables in `base.css`.

## Rules
- After a backend change, run `uv run pytest -q`, then restart the service.
- After a frontend change, run `cd web && npm run build`. Bump `CACHE` in `web/public/sw.js` when the shell itself changes.
- The UI must not use emoji. Icons are inline SVG in `web/src/components/icons.tsx`. Accent pink is `#fbc7d1`, the background is warm ivory, and dark mode follows `prefers-color-scheme`.
- Closing a WebSocket must never interrupt or stop a runtime. Only an explicit `interrupt`, the idle reaper or shutdown can do that.
- Tests mock the SDK; `scripts/e2e.py` is the only test that calls the real model.
- Treat `data/` as user data. It holds config, password hash, sessions and uploads.
- An empty model means the CLI default.
