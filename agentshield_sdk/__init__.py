"""Small dependency-free AgentShield SDK (demo API + local policy checks)."""
from .client import AgentShield, AgentOutputResult, Decision, AgentShieldError
__all__ = ['AgentShield', 'AgentOutputResult', 'Decision', 'AgentShieldError']
