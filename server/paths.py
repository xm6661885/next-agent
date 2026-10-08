"""Private filesystem layout for the backend."""
import os
from pathlib import Path

class DataDir:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv('NEXT_AGENT_DATA') or Path(__file__).resolve().parents[1] / 'data').expanduser().resolve()
        self.config = self.root / 'config.toml'
        self.secret = self.root / 'secret.key'
        self.sessions = self.root / 'sessions.json'
        self.agents = self.root / 'agents'
        self.uploads = self.root / 'uploads'

    def prepare(self):
        os.umask(0o077)
        for path in (self.root, self.agents, self.uploads):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)


def atomic_write(path: Path, content: str | bytes):
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(content.encode() if isinstance(content, str) else content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
