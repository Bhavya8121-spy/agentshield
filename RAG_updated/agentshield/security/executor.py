"""The sole entry point for agent-proposed tool calls."""
from dataclasses import dataclass
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from security.policy_engine import Actor, authorize

class GetTicketArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    ticket_id: int = Field(gt=0)

class UpdateTicketArgs(GetTicketArgs):
    status: str

class DeleteTicketArgs(GetTicketArgs):
    pass

SCHEMAS = {'get_ticket': GetTicketArgs, 'update_ticket': UpdateTicketArgs, 'delete_ticket': DeleteTicketArgs}
VALID_STATUSES = frozenset({'OPEN', 'IN_PROGRESS', 'RESOLVED'})

@dataclass(frozen=True)
class ExecutionResult:
    allowed: bool
    reason: str
    result: Any = None


def execute(actor: Actor, tool_name: str, arguments: dict, store) -> ExecutionResult:
    schema = SCHEMAS.get(tool_name)
    if schema is None:
        return ExecutionResult(False, 'Unknown tool')
    try:
        args = schema.model_validate(arguments)
    except ValidationError:
        return ExecutionResult(False, 'Invalid tool arguments')
    if tool_name == 'update_ticket' and args.status not in VALID_STATUSES:
        return ExecutionResult(False, 'Invalid ticket status')

    # The tenant is read from the trusted database record, not model arguments.
    ticket = store.get_ticket(args.ticket_id)
    if ticket is None:
        return ExecutionResult(False, 'Ticket not found')
    decision = authorize(actor, tool_name, ticket['tenant_id'])
    if not decision.allowed:
        return ExecutionResult(False, decision.reason)
    if tool_name == 'get_ticket':
        return ExecutionResult(True, 'Authorized', ticket)
    if tool_name == 'update_ticket':
        changed = store.update_status(args.ticket_id, actor.tenant_id, args.status)
        return ExecutionResult(changed == 1, 'Updated' if changed == 1 else 'Update failed', {'rows_changed': changed})
    changed = store.delete_ticket(args.ticket_id, actor.tenant_id)
    return ExecutionResult(changed == 1, 'Deleted' if changed == 1 else 'Delete failed', {'rows_changed': changed})
