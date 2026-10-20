"""Run read-only Oracle scenarios; safe to repeat."""
from database.oracle import connect
from database.oracle_store import OracleTicketStore
from database.audit import OracleAudit, audited_execute
from security.policy_engine import Actor


def main():
    connection = connect()
    try:
        store = OracleTicketStore(connection)
        audit = OracleAudit(connection)
        run_id = audit.start_run('phase2_oracle_smoke')
        reader = Actor('alice', 10, 'reader')
        scenarios = [
            ('get_ticket', {'ticket_id': 1042}),
            ('delete_ticket', {'ticket_id': 1042}),
            ('get_ticket', {'ticket_id': 1043}),
        ]
        try:
            for sequence, (tool, arguments) in enumerate(scenarios, start=1):
                result = audited_execute(reader, tool, arguments, store, audit, run_id, sequence)
                print(f'{sequence}. {tool}: allowed={result.allowed}, reason={result.reason}')
        finally:
            audit.finish_run(run_id)
        print('Audit run:', run_id)
        print('Ticket 1042 still exists:', store.get_ticket(1042) is not None)
    finally:
        connection.close()


if __name__ == '__main__':
    main()
