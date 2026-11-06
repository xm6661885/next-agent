"""Automations TOML and the fixed module data layout."""
import os
import secrets
from pathlib import Path
from pydantic import BaseModel, Field
from ..paths import DataDir
from ..tomlstore import TomlFile


class AutomationsConfig(BaseModel):
    model_config = {'extra': 'forbid'}
    scripts_dir: str = 'automations/scripts'
    python_bin: str = 'automations/venv/bin/python'
    shell_bin: str = '/bin/bash'
    webhook_secret: str = ''
    poll_interval_sec: float = Field(default=2, gt=0, allow_inf_nan=False)


TEMPLATE = '''scripts_dir = "automations/scripts"
python_bin = "automations/venv/bin/python"
shell_bin = "/bin/bash"
webhook_secret = ""
poll_interval_sec = 2
'''


def open_config(paths):
    config = TomlFile(paths.config_dir / 'automations.toml', AutomationsConfig, TEMPLATE)
    if not config.data.webhook_secret:
        config.doc['webhook_secret'] = os.environ.get('AUTOTASK_WEBHOOK_SECRET') or secrets.token_urlsafe(32)
        config.save()
    return config


def config_file(core):
    config = open_config(core.paths)
    core.modules.setdefault('raw_configs', {})['automations'] = config
    return config


def resolved(config, data_root):
    def path(value):
        p = Path(value).expanduser()
        return str((p if p.is_absolute() else Path(data_root) / p).resolve())
    return {**config.model_dump(), 'scripts_dir': path(config.scripts_dir),
            'python_bin': path(config.python_bin), 'shell_bin': path(config.shell_bin),
            'data_dir': str(Path(data_root) / 'automations')}


def ensure_dirs(cfg):
    for directory in (Path(cfg['data_dir']) / 'logs', Path(cfg['data_dir']) / 'tmp',
                      *(Path(cfg['scripts_dir']) / name for name in ('cron', 'once', 'lib'))):
        directory.mkdir(parents=True, exist_ok=True)


def load_config():
    paths = DataDir()
    config = open_config(paths)
    cfg = resolved(config.data, paths.root)
    ensure_dirs(cfg)
    return cfg, config.path
