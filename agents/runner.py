"""Route untrusted model proposals exclusively through Phase 2 audited executor."""
from database.audit import audited_execute
from security.executor import ExecutionResult


def run_one(actor, user_request, ticket_context, planner, store, audit, run_id, sequence_no=1):
    proposal = planner.propose(user_request, ticket_context)
    if proposal['tool'] == 'none':
        return proposal, ExecutionResult(False, 'No tool proposed')
    result = audited_execute(
        actor, proposal['tool'], proposal['arguments'], store, audit, run_id, sequence_no,
    )
    return proposal, result
