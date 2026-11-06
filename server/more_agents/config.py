"""More Agents configuration for ACP and native Codex agents."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from ..tomlstore import TomlFile


def now(): return datetime.now(timezone.utc).isoformat()

class AgentCommon(BaseModel):
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    kind: Literal['acp', 'codex']
    name: str = Field(min_length=1)
    avatar: str = 'crab:blue'
    description: str = ''
    group: str = ''
    order: int = 0
    as_subagent: bool = False
    created_at: str = Field(default_factory=now)
    cwd: str

class AcpAgent(AgentCommon):
    kind: Literal['acp'] = 'acp'
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    token: str = ''
    cwd: str = '/'
    config_defaults: dict[str, str] = Field(default_factory=dict)
    @field_validator('token')
    @classmethod
    def auth_line(cls, value):
        if '\n' in value or '\r' in value: raise ValueError('token must be a single line')
        return value

class CodexAgent(AgentCommon):
    kind: Literal['codex'] = 'codex'
    command: str = 'codex'
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = '~'
    model: str = ''
    effort: str = ''
    mode: Literal['full-access', 'auto', 'read-only'] = 'full-access'
    instructions: str = ''
    @field_validator('env')
    @classmethod
    def env_values(cls, value):
        if any('\x00' in k or '\x00' in v or '=' in k for k, v in value.items()): raise ValueError('Invalid environment')
        return value

Agent = Annotated[AcpAgent | CodexAgent, Field(discriminator='kind')]

class MoreAgentsServer(BaseModel):
    idle_timeout_min: float = Field(default=10, ge=0, allow_inf_nan=False)

class MoreAgentsConfig(BaseModel):
    groups: list[str] = Field(default_factory=list)
    server: MoreAgentsServer = Field(default_factory=MoreAgentsServer)
    agents: list[Agent] = Field(default_factory=list)
    @field_validator('groups')
    @classmethod
    def group_names(cls, groups):
        groups = [g.strip() for g in groups]
        if any(not g or len(g)>40 for g in groups) or len(groups)!=len(set(groups)): raise ValueError('group names must be unique, non-empty and at most 40 characters')
        return groups
    @model_validator(mode='after')
    def agents_valid(self):
        if len({a.id for a in self.agents}) != len(self.agents): raise ValueError('Duplicate agent id')
        if any(a.group and a.group not in self.groups for a in self.agents): raise ValueError('Unknown group')
        return self


def config_file(core):
    directory = getattr(core.paths, 'config_dir', core.paths.root / 'config')
    directory.mkdir(parents=True, exist_ok=True)
    config = TomlFile(directory / 'more_agents.toml', MoreAgentsConfig,
                      'groups = []\n\n[server]\nidle_timeout_min = 10\n')
    if isinstance(core.modules.get('raw_configs'), dict): core.modules['raw_configs']['more_agents'] = config
    return config
