"""Deterministic default-deny policy; independent of any LLM."""
from dataclasses import dataclass
from typing import Literal

Role = Literal['reader', 'editor', 'admin']
ALLOWED_TOOLS = {
    'reader': frozenset({'get_ticket'}),
    'editor': frozenset({'get_ticket', 'update_ticket'}),
    'admin': frozenset({'get_ticket', 'update_ticket', 'delete_ticket'}),
}

EMAIL_ALLOWED_TOOLS = {
    'reader': frozenset({'read_email'}),
    'editor': frozenset({'read_email', 'send_email'}),
    'admin': frozenset({'read_email', 'send_email', 'delete_email'}),
}

@dataclass(frozen=True)
class Actor:
    actor_id: str
    tenant_id: int
    role: str

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def authorize(actor: Actor, tool_name: str, resource_tenant_id: int, permissions=None) -> Decision:
    if not isinstance(actor.tenant_id, int) or isinstance(actor.tenant_id, bool):
        return Decision(False, 'Invalid actor tenant')
    if not isinstance(resource_tenant_id, int) or isinstance(resource_tenant_id, bool):
        return Decision(False, 'Invalid resource tenant')
    if resource_tenant_id != actor.tenant_id:
        return Decision(False, 'Cross-tenant access denied')
    if tool_name not in (permissions or ALLOWED_TOOLS).get(actor.role, frozenset()):
        return Decision(False, 'Tool not permitted for role')
    return Decision(True, 'Authorized')
