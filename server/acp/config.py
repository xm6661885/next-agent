"""ACP configuration, independent of the Claude module."""
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator, model_validator
from ..tomlstore import TomlFile


def now():
    return datetime.now(timezone.utc).isoformat()


class AcpAgent(BaseModel):
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    name: str = Field(min_length=1)
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    avatar: str = 'crab:blue'
    description: str = ''
    group: str = ''
    token: str = ''
    cwd: str = '/'
    config_defaults: dict[str, str] = Field(default_factory=dict)
    as_subagent: bool = False
    created_at: str = Field(default_factory=now)
    order: int = 0

    @field_validator('token')
    @classmethod
    def auth_line(cls, value):
        if '\n' in value or '\r' in value: raise ValueError('token must be a single line')
        return value


class AcpServer(BaseModel):
    idle_timeout_min: float = Field(default=10, ge=0, allow_inf_nan=False)


class AcpConfig(BaseModel):
    groups: list[str] = Field(default_factory=list)
    server: AcpServer = Field(default_factory=AcpServer)
    agents: list[AcpAgent] = Field(default_factory=list)

    @field_validator('groups')
    @classmethod
    def group_names(cls, groups):
        groups = [g.strip() for g in groups]
        if any(not g or len(g)>40 for g in groups) or len(groups)!=len(set(groups)):
            raise ValueError('group names must be unique, non-empty and at most 40 characters')
        return groups

    @model_validator(mode='after')
    def agents_valid(self):
        if len({a.id for a in self.agents}) != len(self.agents): raise ValueError('Duplicate agent id')
        if any(a.group and a.group not in self.groups for a in self.agents): raise ValueError('Unknown group')
        return self


def config_file(core):
    directory = getattr(core.paths, 'config_dir', core.paths.root / 'config')
    directory.mkdir(parents=True, exist_ok=True)
    config = TomlFile(directory / 'acp.toml', AcpConfig, 'groups = []\n\n[server]\nidle_timeout_min = 10\n')
    if isinstance(core.modules.get('raw_configs'), dict): core.modules['raw_configs']['acp'] = config
    return config
