"""Workflow settings, shared by the form and raw TOML editor."""
from pydantic import BaseModel, Field, field_validator
from ..tomlstore import TomlFile


class Server(BaseModel):
    agent_concurrency: int = Field(default=1, ge=1, le=16)
    run_retention: int = Field(default=100, ge=0)
    plugin_watch: bool = False
    default_cwd: str = ''


class WorkflowConfig(BaseModel):
    server: Server = Field(default_factory=Server)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator('env')
    @classmethod
    def valid_env(cls, env):
        if any(not key or '=' in key or '\0' in key+value for key, value in env.items()):
            raise ValueError('Invalid environment variable')
        return env


TEMPLATE = '''[server]
agent_concurrency = 1
run_retention = 100
plugin_watch = false
default_cwd = ""

[env]
'''


def config_file(core):
    config = TomlFile(core.paths.config_dir / 'workflow.toml', WorkflowConfig, TEMPLATE)
    core.modules.setdefault('raw_configs', {})['workflow'] = config
    return config
