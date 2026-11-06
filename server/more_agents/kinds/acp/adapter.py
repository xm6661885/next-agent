from ...runtime import AcpRuntime
from .client import AcpConnection, AcpError

class AcpAdapter:
    """ACP transport adapter marker; session lifecycle remains in AcpRuntime."""
    capabilities = {'images': True, 'steer': False, 'modes': True, 'local_cwd': False}
