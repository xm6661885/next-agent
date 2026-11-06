from pydantic import BaseModel, Field, field_validator
from ..tomlstore import TomlFile

class AsrConfig(BaseModel):
    api_base: str = 'https://api.openai.com/v1'
    api_key: str = ''
    model: str = 'whisper-1'
    language: str = ''
    prompt: str = ''
    chunk_sec: int = Field(default=15, ge=5, le=60)
    retranscribe_on_finish: bool = False

    @field_validator('api_base')
    @classmethod
    def valid_base(cls, value):
        value = value.strip()
        if not value.startswith(('http://', 'https://')):
            raise ValueError('API base must start with http:// or https://')
        return value.rstrip('/')

    @field_validator('model', 'language')
    @classmethod
    def trimmed(cls, value):
        return value.strip()


TEMPLATE = '''api_base = "https://api.openai.com/v1"
api_key = ""
model = "whisper-1"
language = ""
prompt = ""
chunk_sec = 15
retranscribe_on_finish = false
'''

def config_file(core):
    config = TomlFile(core.paths.config_dir / 'asr.toml', AsrConfig, TEMPLATE)
    core.modules.setdefault('raw_configs', {})['asr'] = config
    return config
