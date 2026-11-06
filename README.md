# next-agent

A self-hosted web console and PWA for AI agents. It has five bottom tabs: **Chat**, **Agents**, **Automations**, **Workflow** and **More**. Everything runs on your server, and you can use it from a phone or a desktop browser.

- Backend: FastAPI + `claude-agent-sdk` (`server/`). Frontend: Preact + Vite (`web/`). See `docs/architecture.md`.
- Data: `data/`, which is gitignored. It holds the config, sessions, uploads, the workflow database and the cookie secret.

## Features

- **Chat:** plain LLM chat against your own OpenAI- or Anthropic-format providers.
  - Assistant cards set the system prompt, model, effort and image uploads.
  - A "Temporary chat" card uses the defaults.
  - MCP servers can be set globally or per assistant, and switched on or off per chat.
- **Agents (Claude):** persistent Claude Code agents through the Agent SDK.
  - Agent settings: working directory, model, permissions, tools, CLAUDE.md, MCP servers and subagents.
  - Sessions with streaming tool cards, steering, approval cards, fork and rewind.
  - Turns keep running when the browser closes.
- **More Agents:** remote agents over ACP and native Codex agents through the Codex app-server. A Claude / More Agents / Running switch sits at the top of the tab; Running lists every working or waiting session across Claude and More Agents. More Agents sessions stream and survive disconnects.
- **Built-in MCP** (`next` server, for Claude agents only):
  - History: search an agent's own earlier sessions.
  - Collab: delegate to agents marked "available as a subagent" and watch them in a small live window.
  - Switches: a master switch, one per category and per-agent overrides.
- **Automations:** scheduled scripts, webhooks and one-off tasks.
- **Workflow:** a card-based workflow editor with runs, a console and plugins. Run history opens from the clock button at the top right.
  - Agent cards (temporary task, existing agent, More Agents task) run as normal Agents sessions through `core.bridge`.
  - Each card links to its chat page.
- **More:** Settings (your chat profile, then one page per module and category), Claude Code Memory, and About.

## Automations

Manage scheduled scripts, webhooks and one-off tasks in the Automations tab or with `autotask`. See the [Automations protocol](docs/protocol-automations.md) and the [autotask skill](skills/autotask/SKILL.md) for API and CLI guidance.

## Requirements

- Linux or macOS, Python 3.10+ with [uv](https://docs.astral.sh/uv/), Node.js 18+
- Claude Code credentials: log in with `claude` once, or put `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` in the `env` block of `~/.claude/settings.json`

## Quick start

```bash
git clone https://github.com/xm6661885/next-agent.git
cd next-agent
uv sync                          # backend dependencies
cd web && npm ci && npm run build && cd ..   # frontend, served from web/dist
uv run python -m server          # first start uses password 100200 (or NEXT_AGENT_PASSWORD) and writes data/config/
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

Settings live in `data/config/`. `core.toml` holds `[server]`: login, the external API and shared Claude CLI settings.
`agents.toml` holds defaults (including idle settings), agents, temporary-agent settings, groups, pricing, built-in MCP
and extensions. More Agents, Chat, Workflow, Automations, speech to text and image generation own `more_agents.toml`,
`chat.toml`, `workflow.toml`, `automations.toml`, `asr.toml` and `imagegen.toml`.

Edit these files through Settings or by hand; changes reload within 2 seconds and comments are preserved. Running
turns finish before changed launch options restart their CLI. Only split config files are supported. Before starting an existing installation, run
`scripts/migrate/core.py --data DIR` followed by `scripts/migrate/more_agents.py --data DIR` with `uv run python`
(see [data layout and migration](docs/protocol.md#data-layout)). `NEXT_AGENT_DATA` moves the whole data directory.

Credentials come from `~/.claude/settings.json` (the `env` block), so keep `"user"` in `setting_sources`.
