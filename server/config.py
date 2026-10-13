"""Validated TOML configuration with comment-preserving updates."""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import secrets
from typing import Any, Literal

import bcrypt
import tomlkit
from tomlkit.items import SingleKey, KeyType
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from .paths import DataDir, atomic_write

log = logging.getLogger(__name__)

DEFAULT_FILE_OUTPUT_PROMPT = '''# Sharing files with the user
The user reads your replies in a web chat that renders Markdown. When you create or find a file the user should see or
download (images, charts, screenshots, PDFs, archives, documents, generated code files), share it with an absolute
file URL in Markdown:
- Images (png, jpg, gif, webp) are shown inline: ![short caption](file:///absolute/path/to/image.png)
- Any other file becomes a download link: [report.pdf](file:///absolute/path/to/report.pdf)
Use the real absolute path on this machine and only link files that exist. Copy the path exactly as it is on disk:
keep non-ASCII characters (e.g. Chinese) as they are, and the only encoding allowed is replacing each space with %20
(also ( as %28 and ) as %29). Never percent-encode anything else. Do not paste
file contents just so the user can download them; link the file instead.'''

DEFAULT_GENUI_PROMPT = '''# Visual and interactive replies
The chat renders some fenced blocks as UI. Use them when showing beats telling; use plain Markdown otherwise,
and still say in text what the block shows.
Write ```genui, then the widget name on the first line, then its body. Other code blocks (```html included) stay
plain code, so use them only to show code. Pick the lightest widget that works:
- ask: a question card. Tapping an option sends it as the user's next message.
  ```genui
  ask
  {"question": "Which platform?", "options": ["Web", "Desktop", {"label": "Mobile", "description": "iOS and Android"}]}
  ```
  Optional: "multi": true for several picks, "other": false to hide the free-text field, "header": "Short tag".
  Several questions: {"questions": [{...}, {...}]}; the user answers all, then sends once.
  End your turn after an ask block and wait for the answer.
- chart: {"type": "line|bar|area|pie", "title": "...", "x": ["Jan", "Feb"], "series": [{"name": "Sales", "data": [3, 5]}], "unit": "%"}
  pie uses x as labels and the first series as values.
- mermaid: any Mermaid diagram (flowchart TD, sequenceDiagram, stateDiagram-v2, classDiagram, erDiagram, gantt,
  timeline, journey, pie, quadrantChart). A plain ```mermaid block works too. Prefer top-down (TD) flowcharts,
  short labels, and quote labels with punctuation: A["Load (cached)"].
- mindmap: an indented Markdown list; the first line is the root.
  ```genui
  mindmap
  - Topic
    - Branch
      - Leaf
  ```
- svg: a static <svg viewBox="..."> illustration (no script). Use currentColor or var(--fg) var(--muted) var(--accent)
  var(--border) var(--bg) so it follows dark mode; no fixed width.
- html: a self-contained HTML fragment in a sandboxed frame. Only when you need custom interaction the
  widgets above can't do (calculators, sliders, simulations, games, sortable/filterable tables).
  ```genui
  html
  <div id="app">...</div><style>...</style><script>...</script>
  ```
  Markup first, <style>/<script> last (it renders live while you write; scripts run when the block is complete).
  No fetch or storage; scripts may load from https://cdn.jsdelivr.net or https://unpkg.com.
  Colors: var(--bg) var(--fg) var(--muted) var(--border) var(--accent) (dark mode safe).
  Bridge: host.send(text) sends text as the user's next message (only on an explicit click; include the values),
  host.copy(text), host.open(url). Keep local interactions local.

Everything shows on phones (~360px wide): no fixed pixel widths, no inner scrolling, tap targets at least 40px.
Keep blocks compact and valid; JSON must parse.'''

GROUPS = {'model':('model','effort','fallback_model','thinking','thinking_budget'), 'permissions':('permission_mode',),
          'system_prompt':('system_prompt_mode','system_prompt'),
          'file_output':('file_output','file_output_prompt'), 'genui':('genui','genui_prompt'),
          'idle':('idle_mode','idle_timeout_min','adaptive_keep')}

def claude_code_defaults():
    """Model and effort from ~/.claude/settings.json, used wherever a value would otherwise be empty."""
    try: data = json.loads((Path.home()/'.claude'/'settings.json').read_text())
    except Exception: data = {}
    effort = data.get('effortLevel') if data.get('effortLevel') in EFFORT_VALUES else 'high'
    return {'model': data.get('model') or 'opus', 'effort': effort}

EFFORT_VALUES = ('low', 'medium', 'high', 'xhigh', 'max')
THINKING_VALUES = ('adaptive', 'enabled', 'disabled')

def now():
    return datetime.now(timezone.utc).isoformat()

class ServerConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    host: str = '::'
    port: int = Field(default=18793, ge=1, le=65535)
    password_hash: str
    max_concurrent: int = Field(default=3, ge=1)
    cli_path: str = ''
    api_key: str = ''
    anthropic_base_url: str = ''
    anthropic_api_key: str = ''

    @field_validator('password_hash')
    @classmethod
    def valid_hash(cls, value):
        if value != '***' and not re.fullmatch(r'\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}', value):
            raise ValueError('password_hash must be a bcrypt hash')
        return value

class Defaults(BaseModel):
    model_config = ConfigDict(extra='ignore')
    model: str = Field(default_factory=lambda: claude_code_defaults()['model'], min_length=1)
    effort: str = Field(default_factory=lambda: claude_code_defaults()['effort'])
    fallback_model: str = ''
    thinking: str = 'adaptive'
    thinking_budget: int = Field(default=8000, ge=0)
    permission_mode: str = 'bypassPermissions'
    system_prompt_mode: Literal['preset','custom'] = 'preset'
    system_prompt: str = ''
    custom_models: list[str] = Field(default_factory=list)
    file_output: StrictBool = True
    file_output_prompt: str = DEFAULT_FILE_OUTPUT_PROMPT
    genui: StrictBool = True
    genui_prompt: str = DEFAULT_GENUI_PROMPT
    idle_mode: Literal['timer','adaptive','never'] = 'timer'
    idle_timeout_min: float = Field(default=10, ge=0)
    adaptive_keep: int = Field(default=1, ge=1)
    artifacts: StrictBool = True

    @field_validator('custom_models')
    @classmethod
    def clean_models(cls, value):
        return list(dict.fromkeys(v.strip() for v in value if v.strip()))

    @field_validator('file_output_prompt')
    @classmethod
    def prompt_default(cls, value):
        return value or DEFAULT_FILE_OUTPUT_PROMPT

    @field_validator('genui_prompt')
    @classmethod
    def genui_default(cls, value):
        return value or DEFAULT_GENUI_PROMPT

    @field_validator('effort')
    @classmethod
    def valid_effort(cls, value):
        if value not in EFFORT_VALUES:
            raise ValueError('invalid effort')
        return value

    @field_validator('thinking')
    @classmethod
    def valid_thinking(cls, value):
        if value not in THINKING_VALUES:
            raise ValueError('invalid thinking mode')
        return value

    @field_validator('permission_mode')
    @classmethod
    def valid_mode(cls, value):
        if value not in ('default', 'acceptEdits', 'plan', 'bypassPermissions', 'dontAsk', 'auto'):
            raise ValueError('invalid permission mode')
        return value

class AgentSettings(BaseModel):
    model_config = ConfigDict(extra='ignore')
    name: str = Field(min_length=1)
    avatar: str = 'crab:pink'
    description: str = ''
    group: str = ''
    override_groups: list[str] = Field(default_factory=list)
    model: str = Field(default_factory=lambda: claude_code_defaults()['model'], min_length=1)
    fallback_model: str = ''
    effort: str = Field(default_factory=lambda: claude_code_defaults()['effort'])
    thinking: str = 'adaptive'
    thinking_budget: int = Field(default=8000, ge=0)
    permission_mode: str = 'bypassPermissions'
    system_prompt_mode: str = 'preset'
    system_prompt: str = ''
    claude_md: str = 'inherit'
    setting_sources: list[str] = Field(default_factory=lambda: ['user', 'project', 'local'])
    tools: list[str] = Field(default_factory=lambda: ['*'])
    auto_memory: StrictBool = True
    allowed_tools: list[str] = Field(default_factory=list)
    disallowed_tools: list[str] = Field(default_factory=list)
    add_dirs: list[str] = Field(default_factory=list)
    max_turns: int = Field(default=0, ge=0)
    max_budget_usd: float = Field(default=0, ge=0)
    env: dict[str, str] = Field(default_factory=dict)
    mcp_servers: dict[str, Any] = Field(default_factory=dict)
    agents: dict[str, dict[str, Any]] = Field(default_factory=dict)
    enable_file_checkpointing: bool = True
    file_output: StrictBool = True
    file_output_prompt: str = ''
    genui: StrictBool = True
    genui_prompt: str = ''
    idle_mode: Literal['timer','adaptive','never'] = 'timer'
    idle_timeout_min: float = Field(default=10, ge=0)
    adaptive_keep: int = Field(default=1, ge=1)
    extra_args: dict[str, str | None] = Field(default_factory=dict)

    @field_validator('override_groups')
    @classmethod
    def valid_groups(cls, value):
        if any(group not in GROUPS for group in value): raise ValueError('invalid override group')
        return list(dict.fromkeys(value))

    @field_validator('permission_mode')
    @classmethod
    def valid_mode(cls, v):
        if v not in ('default', 'acceptEdits', 'plan', 'bypassPermissions', 'dontAsk', 'auto'):
            raise ValueError('invalid permission mode')
        return v

    @field_validator('effort')
    @classmethod
    def valid_effort(cls, v):
        if v not in EFFORT_VALUES:
            raise ValueError('invalid effort')
        return v

    @field_validator('claude_md')
    @classmethod
    def valid_md(cls, v):
        if v not in ('inherit', 'custom'):
            raise ValueError('invalid claude_md')
        return v

    @field_validator('avatar')
    @classmethod
    def valid_avatar(cls, value):
        if value not in ('file', 'crab:pink', 'crab:orange', 'crab:blue', 'crab:green', 'crab:purple', 'crab:gray'):
            raise ValueError('invalid avatar')
        return value

    @field_validator('thinking')
    @classmethod
    def valid_thinking(cls, value):
        if value not in THINKING_VALUES:
            raise ValueError('invalid thinking mode')
        return value

    @field_validator('system_prompt_mode')
    @classmethod
    def valid_prompt_mode(cls, value):
        if value not in ('preset', 'custom'):
            raise ValueError('invalid system prompt mode')
        return value

    @field_validator('setting_sources')
    @classmethod
    def valid_sources(cls, value):
        if any(source not in ('user', 'project', 'local') for source in value):
            raise ValueError('invalid setting source')
        return value

class Agent(AgentSettings):
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    cwd: str = Field(min_length=1)
    created_at: str = Field(default_factory=now)
    order: int = 0

class TempAgent(AgentSettings):
    name: str = Field(default='Claude Code', min_length=1)
    avatar: str = 'crab:gray'

TEMP_AGENT = '_temp'

def effective(agent, defaults):
    values = {name:getattr(agent if group in agent.override_groups else defaults,name)
              for group, names in GROUPS.items() for name in names}
    for name, builtin in (('file_output_prompt',DEFAULT_FILE_OUTPUT_PROMPT),('genui_prompt',DEFAULT_GENUI_PROMPT)):
        values[name] = values[name] or builtin
    return values

def temp_agent(config):
    settings = config.temp_agent or TempAgent()
    return Agent.model_construct(**settings.model_dump(), id=TEMP_AGENT, cwd=str(Path.home()), created_at='', order=0)

class Price(BaseModel):
    model_config = ConfigDict(extra='ignore')
    input: float = Field(default=0, ge=0)
    output: float = Field(default=0, ge=0)
    cache_write: float = Field(default=0, ge=0)
    cache_read: float = Field(default=0, ge=0)

class Config(BaseModel):
    model_config = ConfigDict(extra='ignore')
    server: ServerConfig
    defaults: Defaults = Field(default_factory=Defaults)
    pricing: dict[str, Price] = Field(default_factory=dict)
    groups: list[str] = Field(default_factory=list)
    agents: list[Agent] = Field(default_factory=list)
    temp_agent: TempAgent | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)

DEFAULT = '''# next-agent configuration. Edited by the web UI and safe to edit by hand; changes are picked up automatically.
[server]
host = "::"
port = 18793
password_hash = "HASH"   # change via: uv run python -m server set-password
max_concurrent = 3           # max simultaneously connected Claude CLI processes (~200 MB each)
cli_path = ""                # empty = CLI bundled with claude-agent-sdk
api_key = ""                 # key for /api/external/send; empty = external API disabled
anthropic_base_url = ""      # ANTHROPIC_BASE_URL for every CLI; empty = CLI default
anthropic_api_key = ""       # ANTHROPIC_API_KEY for every CLI; empty = CLI login

[defaults]                   # used unless an agent overrides a group
model = "MODEL"
effort = "EFFORT"
fallback_model = ""          # empty = no fallback
thinking = "adaptive"        # adaptive | enabled | disabled
thinking_budget = 8000       # tokens when thinking = "enabled"
permission_mode = "bypassPermissions"
system_prompt_mode = "preset"
system_prompt = ""
custom_models = []          # extra model IDs in the picker
file_output = true          # share files with file URLs
file_output_prompt = ""    # empty = built-in prompt
genui = true                # interactive UI blocks in replies
genui_prompt = ""          # empty = built-in prompt
idle_mode = "timer"         # timer | adaptive | never
idle_timeout_min = 10       # 0 disables timer sleep
adaptive_keep = 1           # live CLIs kept per agent in adaptive mode
artifacts = true            # show conversation artifacts in the client

[[agents]]
id = "claude"
name = "Claude"
avatar = "crab:pink"
cwd = "HOME_DIR"
description = ""
override_groups = []
model = "MODEL"
fallback_model = ""
effort = "EFFORT"
thinking = "adaptive"
thinking_budget = 8000
permission_mode = "bypassPermissions"
system_prompt_mode = "preset"
system_prompt = ""
claude_md = "inherit"
setting_sources = ["user", "project", "local"]
tools = ["*"]                # "*" = all built-in tools, [] = none
auto_memory = true
allowed_tools = []
disallowed_tools = []
add_dirs = []
max_turns = 0
max_budget_usd = 0
enable_file_checkpointing = true
file_output = true
file_output_prompt = ""    # empty = built-in prompt when overridden
genui = true
genui_prompt = ""          # empty = built-in prompt when overridden
idle_mode = "timer"
idle_timeout_min = 10
adaptive_keep = 1
order = 0
created_at = "CREATED_AT"

[agents.env]

[agents.mcp_servers]

[agents.agents]

[agents.extra_args]
'''

class ConfigStore:
    def __init__(self, paths: DataDir):
        self.paths = paths
        paths.prepare()
        if not paths.config.exists():
            password = os.environ.get('NEXT_AGENT_PASSWORD') or secrets.token_urlsafe(12)
            cc = claude_code_defaults()
            password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            print(f'next-agent: first start, generated login password: {password} (change it with: uv run python -m server set-password)', flush=True)
            atomic_write(paths.config, DEFAULT.replace('HOME_DIR', str(Path.home())).replace('HASH', password_hash).replace('CREATED_AT', now()).replace('MODEL', cc['model']).replace('EFFORT', cc['effort']))
        self.doc = None
        self.config = None
        self.mtime = 0
        self.load()

    def parse(self, content: str):
        doc = tomlkit.parse(content)
        config = Config.model_validate(doc.unwrap())
        ids = [a.id for a in config.agents]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate agent id')
        if len(config.groups) != len(set(config.groups)) or any(not g.strip() for g in config.groups):
            raise ValueError('invalid groups')
        if any(a.group and a.group not in config.groups for a in config.agents):
            raise ValueError('agent group not in groups')
        return doc, config

    def migrate(self, doc):
        changed = False
        if 'defaults' not in doc:
            doc['defaults'] = tomlkit.table()
            changed = True
        defaults = doc['defaults']
        server = doc['server']
        for key in ('idle_mode','idle_timeout_min','adaptive_keep'):
            if key in server:
                if key not in defaults: defaults[key] = server[key]
                del server[key]
                changed = True
        cc = claude_code_defaults()
        fill = {'model':cc['model'],'effort':cc['effort'],'thinking':'adaptive'}
        for key, value in fill.items():
            if not defaults.get(key): defaults[key] = value; changed = True
        values = Defaults.model_validate(defaults.unwrap() if hasattr(defaults,'unwrap') else dict(defaults))
        tables = list(doc.get('agents',[])) + ([doc['temp_agent']] if 'temp_agent' in doc else [])
        for entry in tables:
            # tools = [] used to mean all tools; now it means none.
            if 'tools' in entry and len(entry['tools']) == 0 and 'auto_memory' not in entry:
                entry['tools'] = ['*']; entry['auto_memory'] = True; changed = True
            if 'override_groups' not in entry: continue
            groups = list(entry['override_groups'])
            # Fallback model and thinking joined the model group; keep agents that set them on their own values.
            if 'model' not in groups and (entry.get('fallback_model') or entry.get('thinking')):
                for key in ('model','effort'): entry[key] = getattr(values,key)
                groups.append('model'); entry['override_groups'] = groups; changed = True
            for key in ('model','effort','thinking'):
                if key in entry and not entry[key]:
                    entry[key] = getattr(values,key) if key != 'thinking' else 'adaptive'; changed = True
        for entry in doc.get('agents',[]):
            if 'override_groups' in entry: continue
            groups = []
            if entry.get('model') or entry.get('effort'): groups.append('model')
            if entry.get('permission_mode') and entry['permission_mode'] != values.permission_mode: groups.append('permissions')
            if entry.get('system_prompt') or entry.get('system_prompt_mode') == 'custom': groups.append('system_prompt')
            for group in ('file_output','genui'):
                old = entry.get(group,'')
                if old in ('on','off') or entry.get(group+'_prompt'): groups.append(group)
                if old in ('on','off',''): entry[group] = {'on':True,'off':False,'':getattr(values,group)}[old]
            for key in ('model','effort','permission_mode'):
                if not entry.get(key): entry[key] = getattr(values,key)
            for key in GROUPS['idle']: entry[key] = getattr(values,key)
            entry['override_groups'] = groups
            changed = True
        return changed

    def load(self):
        doc = tomlkit.parse(self.paths.config.read_text())
        changed = self.migrate(doc)
        doc, config = self.parse(tomlkit.dumps(doc))
        if changed: atomic_write(self.paths.config,self.tidy(doc))
        self.doc, self.config = doc, config
        self.mtime = self.stamp()

    def tidy(self, doc):
        # Rewrite agent tables in field order: identity first, scalars, then sub-tables, one blank line apart.
        head = ['id','name','avatar','description','group','cwd','created_at','order']
        order = head + [k for k in Agent.model_fields if k not in head]
        def table(entry):
            data = entry.unwrap() if hasattr(entry, 'unwrap') else dict(entry)
            keys = [k for k in order if k in data] + [k for k in data if k not in order]
            out = tomlkit.table()
            for k in keys:
                if not isinstance(data[k], dict): out[k] = data[k]
            for k in keys:
                if isinstance(data[k], dict):
                    sub = tomlkit.table()
                    for sk, sv in data[k].items(): sub[sk] = sv
                    out[k] = sub
            return out
        if 'agents' in doc:
            arr = tomlkit.aot()
            for entry in doc['agents']: arr.append(table(entry))
            doc['agents'] = arr
        if 'temp_agent' in doc: doc['temp_agent'] = table(doc['temp_agent'])
        content = tomlkit.dumps(doc)
        return re.sub(r'\n{3,}', '\n\n', re.sub(r'\n(\[\[agents\]\]|\[temp_agent\]|\[pricing\])', r'\n\n\1', content))

    def save(self):
        content = self.tidy(self.doc)
        self.doc = tomlkit.parse(content)
        _, config = self.parse(content)
        atomic_write(self.paths.config, content)
        self.config = config
        self.mtime = self.stamp()

    def replace_raw(self, content: str):
        doc, config = self.parse(content)
        self.doc, self.config = doc, config
        self.save()

    def masked(self):
        doc = tomlkit.parse(tomlkit.dumps(self.doc))
        doc['server']['password_hash'] = '***'
        return tomlkit.dumps(doc)

    def form(self):
        return {'server':self.config.server.model_dump(exclude={'password_hash'}),
                'defaults':self.config.defaults.model_dump(),
                'pricing':{k:v.model_dump() for k,v in self.config.pricing.items()},
                'default_file_output_prompt':DEFAULT_FILE_OUTPUT_PROMPT,
                'default_genui_prompt':DEFAULT_GENUI_PROMPT}

    def update_form(self, data):
        if not isinstance(data, dict): raise ValueError('Expected a JSON object')
        values = self.config.model_dump(mode='json')
        for section, allowed in (('server',{'max_concurrent','cli_path','api_key','anthropic_base_url','anthropic_api_key'}),
                                 ('defaults',set(Defaults.model_fields))):
            if section in data:
                if not isinstance(data[section],dict): raise ValueError(f'{section} must be an object')
                values[section].update({k:v for k,v in data[section].items() if k in allowed})
        if 'pricing' in data:
            if not isinstance(data['pricing'],dict): raise ValueError('pricing must be an object')
            values['pricing']={k.strip():v for k,v in data['pricing'].items() if isinstance(k,str) and k.strip()}
        try:
            validated = Config.model_validate(values)
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        doc = tomlkit.parse(tomlkit.dumps(self.doc))
        for section, allowed in (('server',{'max_concurrent','cli_path','api_key','anthropic_base_url','anthropic_api_key'}),
                                 ('defaults',set(Defaults.model_fields))):
            if section in data:
                if section not in doc: doc[section]=tomlkit.table()
                for key in data[section]:
                    if key in allowed:
                        value=getattr(getattr(validated,section),key)
                        if section=='defaults' and key in ('file_output_prompt','genui_prompt') and data[section][key]=='': value=''
                        doc[section][key]=value
        if 'pricing' in data:
            if 'pricing' in doc: del doc['pricing']
            pricing=tomlkit.table()
            for key, value in validated.pricing.items():
                pricing.append(SingleKey(key,KeyType.Basic),tomlkit.table())
                for field, number in value.model_dump().items(): pricing[key][field]=number
            doc['pricing']=pricing
        self.parse(tomlkit.dumps(doc))
        self.doc=doc
        self.save()

    def stamp(self):
        # Size too: rewrites inside one timestamp tick keep the same mtime.
        st = self.paths.config.stat()
        return (st.st_mtime_ns, st.st_size)

    async def watch(self, on_change, interval=2):
        while True:
            await asyncio.sleep(interval)
            try:
                mtime = self.stamp()
                if mtime != self.mtime:
                    self.load()
                    await on_change()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning('Invalid config reload: %s', exc)
                self.mtime = self.stamp()
