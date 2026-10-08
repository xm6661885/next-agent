"""Validated TOML configuration with comment-preserving updates."""
import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import secrets
from typing import Any

import bcrypt
import tomlkit
from tomlkit.items import SingleKey, KeyType
from pydantic import BaseModel, ConfigDict, Field, field_validator
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

def now():
    return datetime.now(timezone.utc).isoformat()

class ServerConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    host: str = '::'
    port: int = Field(default=18793, ge=1, le=65535)
    password_hash: str
    max_concurrent: int = Field(default=3, ge=1)
    idle_timeout_min: float = Field(default=10, ge=0)
    cli_path: str = ''
    api_key: str = ''

    @field_validator('password_hash')
    @classmethod
    def valid_hash(cls, value):
        if value != '***' and not re.fullmatch(r'\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}', value):
            raise ValueError('password_hash must be a bcrypt hash')
        return value

class Defaults(BaseModel):
    model_config = ConfigDict(extra='ignore')
    model: str = ''
    effort: str = ''
    permission_mode: str = 'bypassPermissions'
    custom_models: list[str] = Field(default_factory=list)
    file_output: bool = True
    file_output_prompt: str = DEFAULT_FILE_OUTPUT_PROMPT

    @field_validator('custom_models')
    @classmethod
    def clean_models(cls, value):
        return list(dict.fromkeys(v.strip() for v in value if v.strip()))

    @field_validator('file_output_prompt')
    @classmethod
    def prompt_default(cls, value):
        return value or DEFAULT_FILE_OUTPUT_PROMPT

    @field_validator('effort')
    @classmethod
    def valid_effort(cls, value):
        if value not in ('', 'low', 'medium', 'high', 'xhigh', 'max'):
            raise ValueError('invalid effort')
        return value

    @field_validator('permission_mode')
    @classmethod
    def valid_mode(cls, value):
        if value not in ('default', 'acceptEdits', 'plan', 'bypassPermissions', 'dontAsk', 'auto'):
            raise ValueError('invalid permission mode')
        return value

class Agent(BaseModel):
    model_config = ConfigDict(extra='ignore')
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    name: str = Field(min_length=1)
    avatar: str = 'crab:pink'
    description: str = ''
    cwd: str = Field(min_length=1)
    model: str = ''
    fallback_model: str = ''
    effort: str = ''
    thinking: str = ''
    thinking_budget: int = Field(default=0, ge=0)
    permission_mode: str = 'bypassPermissions'
    system_prompt_mode: str = 'preset'
    system_prompt: str = ''
    claude_md: str = 'inherit'
    setting_sources: list[str] = Field(default_factory=lambda: ['user', 'project', 'local'])
    tools: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    disallowed_tools: list[str] = Field(default_factory=list)
    add_dirs: list[str] = Field(default_factory=list)
    max_turns: int = Field(default=0, ge=0)
    max_budget_usd: float = Field(default=0, ge=0)
    env: dict[str, str] = Field(default_factory=dict)
    mcp_servers: dict[str, Any] = Field(default_factory=dict)
    agents: dict[str, dict[str, Any]] = Field(default_factory=dict)
    enable_file_checkpointing: bool = True
    file_output: str = ''
    file_output_prompt: str = ''
    extra_args: dict[str, str | None] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now)
    order: int = 0

    @field_validator('permission_mode')
    @classmethod
    def valid_mode(cls, v):
        if v not in ('', 'default', 'acceptEdits', 'plan', 'bypassPermissions', 'dontAsk', 'auto'):
            raise ValueError('invalid permission mode')
        return v

    @field_validator('effort')
    @classmethod
    def valid_effort(cls, v):
        if v not in ('', 'low', 'medium', 'high', 'xhigh', 'max'):
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
        if value not in ('', 'adaptive', 'enabled', 'disabled'):
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

    @field_validator('file_output')
    @classmethod
    def valid_file_output(cls, value):
        if value not in ('', 'on', 'off'):
            raise ValueError('invalid file_output')
        return value

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
    agents: list[Agent] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)

DEFAULT = '''# next-agent configuration. Edited by the web UI and safe to edit by hand; changes are picked up automatically.
[server]
host = "::"
port = 18793
password_hash = "HASH"   # change via: uv run python -m server set-password
max_concurrent = 3           # max simultaneously connected Claude CLI processes (~200 MB each)
idle_timeout_min = 10        # disconnect an idle CLI after this many minutes (session resumes on next message); 0 disables
cli_path = ""                # empty = CLI bundled with claude-agent-sdk
api_key = ""                 # key for /api/external/send; empty = external API disabled

[defaults]                   # used when an agent field is empty
model = ""                   # empty = Claude Code default from ~/.claude/settings.json
effort = ""
permission_mode = "bypassPermissions"
custom_models = []          # extra model IDs in the picker
file_output = true          # share files with file URLs
file_output_prompt = ""    # empty = built-in prompt

[[agents]]
id = "claude"
name = "Claude"
avatar = "crab:pink"
cwd = "HOME_DIR"
description = ""
model = ""
fallback_model = ""
effort = ""
thinking = ""
thinking_budget = 0
permission_mode = "bypassPermissions"
system_prompt_mode = "preset"
system_prompt = ""
claude_md = "inherit"
setting_sources = ["user", "project", "local"]
tools = []
allowed_tools = []
disallowed_tools = []
add_dirs = []
max_turns = 0
max_budget_usd = 0
enable_file_checkpointing = true
file_output = ""           # empty = follow defaults
file_output_prompt = ""    # empty = follow defaults
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
            password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            print(f'next-agent: first start, generated login password: {password} (change it with: uv run python -m server set-password)', flush=True)
            atomic_write(paths.config, DEFAULT.replace('HOME_DIR', str(Path.home())).replace('HASH', password_hash).replace('CREATED_AT', now()))
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
        return doc, config

    def load(self):
        doc, config = self.parse(self.paths.config.read_text())
        self.doc, self.config = doc, config
        self.mtime = self.paths.config.stat().st_mtime_ns

    def save(self):
        content = tomlkit.dumps(self.doc)
        _, config = self.parse(content)
        atomic_write(self.paths.config, content)
        self.config = config
        self.mtime = self.paths.config.stat().st_mtime_ns

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
                'default_file_output_prompt':DEFAULT_FILE_OUTPUT_PROMPT}

    def update_form(self, data):
        if not isinstance(data, dict): raise ValueError('Expected a JSON object')
        values = self.config.model_dump(mode='json')
        for section, allowed in (('server',{'max_concurrent','idle_timeout_min','cli_path','api_key'}),
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
        for section, allowed in (('server',{'max_concurrent','idle_timeout_min','cli_path','api_key'}),
                                 ('defaults',set(Defaults.model_fields))):
            if section in data:
                if section not in doc: doc[section]=tomlkit.table()
                for key in data[section]:
                    if key in allowed:
                        value=getattr(getattr(validated,section),key)
                        if section=='defaults' and key=='file_output_prompt' and data[section][key]=='': value=''
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

    async def watch(self, on_change, interval=2):
        while True:
            await asyncio.sleep(interval)
            try:
                mtime = self.paths.config.stat().st_mtime_ns
                if mtime != self.mtime:
                    self.load()
                    await on_change()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning('Invalid config reload: %s', exc)
                self.mtime = self.paths.config.stat().st_mtime_ns
