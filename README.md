# next-agent

A self-hosted web console and PWA for persistent Claude Code agents. Each agent runs through the Python Claude Agent SDK on your server, and you can reach every agent from a phone or a desktop browser.

- Backend: FastAPI + `claude-agent-sdk` (`server/`). Frontend: Preact + Vite (`web/`)
- Data: `data/`, which is gitignored. It holds the config, session index, uploads, avatars and the cookie secret.

## Features

- **Agents:** the home page lists agents. Each one has a name, an avatar (pixel crab or uploaded photo), a working directory, a model, effort, thinking, a permission mode, tool rules, CLAUDE.md, system prompt, MCP servers, subagents, env and extra CLI args.
- **Sessions:** each agent page lets you create, rename, fork, delete, search and import Claude Code CLI sessions from the agent's folder.
- **Chat:**
  - Streaming text and thinking, with CLI-style tool cards (Bash, diffs, todos, subagents).
  - Image and file uploads. Images are sent as image blocks and every file path is passed to Claude.
  - Slash command suggestions, and live switching of mode, model and effort.
  - Context and cost display, background task list, fork or rewind files from a message.
  - Edit and resend an earlier user message to continue from that point. Claude can share generated files with inline image previews or download links.
- **Steering:** sending while Claude works writes the message into the running turn. The CLI picks it up at the next tool boundary. The steer button interrupts first, then sends.
- **Approvals:** in "Ask before acting" mode, tool permission requests, AskUserQuestion and plan approval show up as cards in the chat. Requests never time out.
- **Runs independently of the browser:** closing the page or losing network does not stop a turn. Clients resume from the last event sequence number when they reconnect.
- **Resource limits:** at most `max_concurrent` CLI processes run at once (about 200 MB each). Extra sessions queue. An idle CLI is closed after `idle_timeout_min` and resumes on the next message.
- **Settings:** the form API edits defaults, custom model IDs and per-model token prices while preserving config comments. Price rules drive the displayed cost when model usage is available.

## Requirements

- Linux or macOS, Python 3.10+ with [uv](https://docs.astral.sh/uv/), Node.js 18+
- Claude Code credentials: log in with `claude` once, or put `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` in the `env` block of `~/.claude/settings.json`

## Quick start

```bash
git clone https://github.com/xm6661885/next-agent.git
cd next-agent
uv sync                          # backend dependencies
cd web && npm ci && npm run build && cd ..   # frontend, served from web/dist
uv run python -m server          # first start prints a generated password (or set NEXT_AGENT_PASSWORD) and writes data/config.toml
```

Open `http://<host>:18793`, log in, and create agents from the home page.

## Deployment

- Put it behind HTTPS before exposing it to the internet. The login password is the only access control.
- `deploy/next-agent.service.example`: systemd unit. Replace `YOUR_USER` and paths, copy to `/etc/systemd/system/next-agent.service`, then `sudo systemctl enable --now next-agent`.
- `deploy/nginx.conf.example`: reverse proxy with WebSocket support and long timeouts. Replace the domain and certificate paths.
- Each connected Claude CLI uses about 200 MB RAM. Tune `max_concurrent` and `idle_timeout_min` for your machine.

## Commands

```bash
uv run python -m server                   # run the server
uv run python -m server set-password      # change the login password (logs out all devices)
uv run pytest -q                          # backend tests (mocked SDK, no API cost)
NEXT_AGENT_PASSWORD=... uv run python scripts/e2e.py   # end-to-end test against a running server (real Claude, a few cents)
cd web && npm run build                   # rebuild the frontend after changes (no server restart needed)
```

## Configuration

Everything lives in `data/config.toml`. The settings pages in the UI write to it. You can also edit it by hand or in Settings > config.toml; changes are reloaded within 2 seconds. Running sessions keep their current options until their CLI restarts.

```toml
[server]
max_concurrent = 3      # simultaneous CLI processes
idle_timeout_min = 10   # close idle CLIs after this many minutes
cli_path = ""           # empty = CLI bundled with the SDK

[defaults]              # used when an agent field is empty
permission_mode = "bypassPermissions"

[[agents]]
id = "claude"
name = "Claude"
cwd = "/home/you"  # defaults to the home of the user running the server
# model, effort, thinking, permission_mode, claude_md, system_prompt, tools, mcp_servers, agents, env, ...
```

Credentials come from `~/.claude/settings.json` (the `env` block), so keep `"user"` in `setting_sources`.
