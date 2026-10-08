"""Password authentication and signed cookies."""
import hashlib
import secrets
import time
from fastapi import HTTPException, Request, WebSocket
from itsdangerous import TimestampSigner, BadSignature, SignatureExpired
from .paths import atomic_write

COOKIE = 'na_auth'
AGE = 30 * 86400

class Auth:
    def __init__(self, paths, config):
        self.config = config
        if not paths.secret.exists():
            atomic_write(paths.secret, secrets.token_hex(32))
        self.signer = TimestampSigner(paths.secret.read_text().strip())
        self.failures = {}

    def fingerprint(self):
        return hashlib.sha256(self.config.config.server.password_hash.encode()).hexdigest()[:16]

    def token(self):
        return self.signer.sign(self.fingerprint()).decode()

    def valid(self, token):
        if not token:
            return False
        try:
            return self.signer.unsign(token, max_age=AGE).decode() == self.fingerprint()
        except (BadSignature, SignatureExpired):
            return False

    def ip(self, request):
        return request.headers.get('x-real-ip') or (request.client.host if request.client else 'unknown')

    def check_login(self, request, password):
        import bcrypt
        ip = self.ip(request)
        recent = [t for t in self.failures.get(ip, []) if time.monotonic()-t < 600]
        self.failures[ip] = recent
        if len(recent) > 8:
            raise HTTPException(429, 'Too many login attempts')
        if not bcrypt.checkpw(password.encode(), self.config.config.server.password_hash.encode()):
            recent.append(time.monotonic())
            raise HTTPException(401, 'Invalid password')
        self.failures.pop(ip, None)

    def require_auth(self, request: Request):
        if not self.valid(request.cookies.get(COOKIE)):
            raise HTTPException(401, 'Authentication required')

    async def require_ws(self, ws: WebSocket):
        if not self.valid(ws.cookies.get(COOKIE)):
            await ws.accept()
            await ws.close(code=4401)
            return False
        from urllib.parse import urlsplit
        origin = ws.headers.get('origin')
        if not origin or urlsplit(origin).netloc.lower() != ws.headers.get('host', '').lower():
            await ws.accept()
            await ws.close(code=4403)
            return False
        return True
