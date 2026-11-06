from typing import Literal
from pydantic import BaseModel, Field, field_validator
from ..tomlstore import TomlFile

class ImageConfig(BaseModel):
    api_base: str = 'https://api.openai.com/v1'
    api_key: str = ''
    models: list[str] = Field(default_factory=lambda: ['gpt-image-2'])
    default_model: str = 'gpt-image-2'
    reference_mode: Literal['auto', 'edits', 'generations'] = 'generations'
    timeout: int = Field(default=300, ge=1)

    @field_validator('api_base')
    @classmethod
    def base(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError('API base must start with http:// or https://')
        return v.rstrip('/')

    @field_validator('models')
    @classmethod
    def clean_models(cls, v):
        return list(dict.fromkeys((x.strip() for x in v if x.strip())))


TEMPLATE = '''api_base = "https://api.openai.com/v1"
api_key = ""
models = ["gpt-image-2"]
default_model = "gpt-image-2"
reference_mode = "generations"
timeout = 300
'''

def config_file(core):
    config = TomlFile(core.paths.config_dir / 'imagegen.toml', ImageConfig, TEMPLATE)
    core.modules.setdefault('raw_configs', {})['imagegen'] = config
    return config
