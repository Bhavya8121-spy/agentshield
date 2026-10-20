"""One-shot OCI model proposal, protected by the Phase 2 firewall."""
import argparse
from agents.oci_model import OCIPlanner
from agents.runner import run_one
from database.audit import OracleAudit
from database.oracle import connect
from database.oracle_store import OracleTicketStore
from security.policy_engine import Actor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', default='Read ticket 1042 and summarize the issue')
    parser.add_argument('--ticket-id', type=int, default=1042)
    args = parser.parse_args()
    with connect() as connection:
        store = OracleTicketStore(connection)
        ticket = store.get_ticket(args.ticket_id)
        if ticket is None:
            raise SystemExit('Ticket not found. Seed fixtures first.')
        # Only synthetic ticket content is used for this demo.
        context = f"Ticket {ticket['ticket_id']}: {ticket['description']}"
        audit = OracleAudit(connection)
        run_id = audit.start_run('phase3_oci_smoke')
        try:
            proposal, result = run_one(
                Actor('demo-reader', ticket['tenant_id'], 'reader'),
                args.request, context, OCIPlanner(), store, audit, run_id,
            )
            print('Proposed tool:', proposal['tool'])
            print('Proposed arguments:', proposal['arguments'])
            print('Firewall allowed:', result.allowed)
            print('Reason:', result.reason)
            print('Audit run:', run_id)
        finally:
            audit.finish_run(run_id)


if __name__ == '__main__':
    main()
