"""Atomic session and upload index."""
import json
from uuid import uuid4
from .paths import atomic_write
from .config import now

class SessionIndex:
    def __init__(self, paths):
        self.paths = paths
        self.data = json.loads(paths.sessions.read_text()) if paths.sessions.exists() else {'sessions': {}, 'uploads': {}}
        self.data.setdefault('sessions', {})
        self.data.setdefault('uploads', {})
        if not paths.sessions.exists():
            self.save()

    @property
    def sessions(self):
        return self.data['sessions']

    @property
    def uploads(self):
        return self.data['uploads']

    def save(self):
        atomic_write(self.paths.sessions, json.dumps(self.data, indent=2))

    def create(self, agent_id, title='', **extras):
        sid = str(uuid4())
        session = dict(id=sid, agent_id=agent_id, sdk_session_id=None, title=title, preview='',
                       created_at=now(), updated_at=now(), total_cost_usd=0.0, turns=0,
                       fork_of=None, imported=False,
                       overrides={'model': None, 'effort': None, 'permission_mode': None}, context=None)
        session.update(extras)
        self.sessions[sid] = session
        self.save()
        return session

    def update(self, sid, **values):
        self.sessions[sid].update(values)
        self.sessions[sid]['updated_at'] = now()
        self.save()
        return self.sessions[sid]
