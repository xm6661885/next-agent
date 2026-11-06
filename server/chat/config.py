"""Chat configuration and per-reply settings."""
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from ..tomlstore import TomlFile

Effort = Literal['off', 'low', 'medium', 'high', 'max']


def now():
    return datetime.now(timezone.utc).isoformat()


class Settings(BaseModel):
    model: str = ''
    effort: Literal['', 'off', 'low', 'medium', 'high', 'max'] = ''
    system_prompt: str = ''
    temperature: float = Field(default=-1, ge=-1, le=2, allow_inf_nan=False)
    max_tokens: int = Field(default=0, ge=0)


class Defaults(Settings):
    effort: Effort = 'medium'
    mcp: list[str] = Field(default_factory=list)


class Switch(BaseModel):
    enabled: bool = True


class Titles(Switch):
    model: str = ''
    prompt: str = ''


class Profile(BaseModel):
    name: str = Field(default='You', min_length=1)
    avatar: str = ''


class DefaultAssistant(Settings):
    name: str = Field(default='Temporary chat', min_length=1)
    avatar: str = 'crab:gray'
    description: str = ''
    files: bool = True
    memory: bool = False
    mcp: list[str] = Field(default_factory=list)


class Assistant(DefaultAssistant):
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    name: str = Field(min_length=1)
    created_at: str = Field(default_factory=now)
    order: int = 0


class Provider(BaseModel):
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    name: str = Field(min_length=1)
    format: Literal['openai', 'anthropic']
    base_url: str = Field(pattern=r'^https?://[^/\s]+')
    api_key: str = ''
    models: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)


class McpServer(BaseModel):
    type: Literal['stdio', 'http', 'sse'] = 'stdio'
    command: str = ''
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ''
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def transport(self):
        if self.type=='stdio' and not self.command: raise ValueError('MCP command is required')
        if self.type!='stdio' and not self.url.startswith(('https://', 'http://')):
            raise ValueError('MCP HTTP URL is required')
        return self


class ChatConfig(BaseModel):
    defaults: Defaults = Field(default_factory=Defaults)
    titles: Titles = Field(default_factory=Titles)
    files: Switch = Field(default_factory=Switch)
    memory: Switch = Field(default_factory=Switch)
    profile: Profile = Field(default_factory=Profile)
    providers: list[Provider] = Field(default_factory=list)
    mcp_servers: dict[str, McpServer] = Field(default_factory=dict)
    default_assistant: DefaultAssistant = Field(default_factory=DefaultAssistant)
    assistants: list[Assistant] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_ids(self):
        for entries in (self.providers, self.assistants):
            if len({e.id for e in entries})!=len(entries): raise ValueError('Duplicate id')
        return self


TEMPLATE = '''providers = []
assistants = []

[defaults]
model = ""
effort = "medium"
system_prompt = ""
temperature = -1
max_tokens = 0
mcp = []

[titles]
enabled = true
model = ""
prompt = ""

[files]
enabled = true

[memory]
enabled = true

[profile]
name = "You"
avatar = ""

[default_assistant]
name = "Temporary chat"
avatar = "crab:gray"
description = ""
files = true
memory = false
model = ""
effort = ""
system_prompt = ""
temperature = -1
max_tokens = 0
mcp = []

[mcp_servers]
'''


def config_file(core):
    config = TomlFile(core.paths.config_dir / 'chat.toml', ChatConfig, TEMPLATE)
    core.modules.setdefault('raw_configs', {})['chat'] = config
    return config
