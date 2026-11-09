"""The sole entry point for agent-proposed EMAIL actions.

Layers enforced here (all deterministic, none depend on the model):
  1. strict argument validation
  2. role permissions (read-only / can send / full access)
  3. mailbox ownership: the mailbox owner comes from the database, not the model
  4. outbound rule: mail may only go to the organization's own domain
"""
import re
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from security.constants import ORG_DOMAIN
from security.executor import ExecutionResult
from security.policy_engine import Actor, EMAIL_ALLOWED_TOOLS, authorize

ADDRESS = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$')


class ReadEmailArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    email_id: int = Field(gt=0)


class DeleteEmailArgs(ReadEmailArgs):
    pass


class SendEmailArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    to: str
    subject: str
    body: str


EMAIL_SCHEMAS = {'read_email': ReadEmailArgs, 'delete_email': DeleteEmailArgs, 'send_email': SendEmailArgs}


def execute_email(actor: Actor, tool_name: str, arguments: dict, store) -> ExecutionResult:
    schema = EMAIL_SCHEMAS.get(tool_name)
    if schema is None:
        return ExecutionResult(False, 'Unknown tool')
    try:
        args = schema.model_validate(arguments)
    except ValidationError:
        return ExecutionResult(False, 'Invalid tool arguments')

    if tool_name == 'send_email':
        if not ADDRESS.match(args.to) or not args.subject.strip() or len(args.subject) > 200 or len(args.body) > 2000:
            return ExecutionResult(False, 'Invalid tool arguments')
        decision = authorize(actor, tool_name, actor.tenant_id, EMAIL_ALLOWED_TOOLS)
        if not decision.allowed:
            return ExecutionResult(False, decision.reason)
        if not args.to.lower().endswith('@' + ORG_DOMAIN):
            return ExecutionResult(False, 'Recipient outside your organization needs human approval')
        sent_id = store.send_email(actor.tenant_id, args.to, args.subject, args.body)
        return ExecutionResult(True, 'Authorized', {'sent_id': sent_id, 'to': args.to})

    email = store.get_email(args.email_id)
    if email is None:
        return ExecutionResult(False, 'Email not found')
    decision = authorize(actor, tool_name, email['tenant_id'], EMAIL_ALLOWED_TOOLS)
    if not decision.allowed:
        return ExecutionResult(False, decision.reason)
    if tool_name == 'read_email':
        return ExecutionResult(True, 'Authorized', email)
    changed = store.delete_email(args.email_id, actor.tenant_id)
    return ExecutionResult(changed == 1, 'Deleted' if changed == 1 else 'Delete failed', {'rows_changed': changed})
