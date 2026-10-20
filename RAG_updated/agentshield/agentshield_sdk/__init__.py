"""Small dependency-free AgentShield SDK (demo API + local policy checks)."""
from .client import AgentShield, Decision, AgentShieldError
__all__ = ['AgentShield', 'Decision', 'AgentShieldError']
