from unittest.mock import MagicMock
from database.audit import OracleAudit, audited_execute
from security.policy_engine import Actor
from tools.ticket_tools import SQLiteTicketStore


def test_audit_writes_expected_sql_and_values():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    audit = OracleAudit(connection)
    run_id = audit.start_run('test')
    assert len(run_id) == 36
    assert 'INSERT INTO agent_runs' in cursor.execute.call_args.args[0]
    audit.finish_run(run_id)
    assert 'UPDATE agent_runs' in cursor.execute.call_args.args[0]


def test_denied_call_is_recorded_without_mutation():
    store = SQLiteTicketStore()
    store.seed([{'ticket_id': 1042, 'tenant_id': 10, 'customer_id': 1,
                 'title': 'Example', 'description': 'Text', 'status': 'OPEN'}])
    connection = MagicMock()
    audit = OracleAudit(connection)
    result = audited_execute(Actor('reader1', 10, 'reader'), 'delete_ticket',
                             {'ticket_id': 1042}, store, audit, 'test-run', 1)
    assert not result.allowed
    assert store.get_ticket(1042) is not None
    cursor = connection.cursor.return_value.__enter__.return_value
    sql, params = cursor.execute.call_args.args
    assert 'INSERT INTO tool_traces' in sql
    assert params['policy_decision'] == 'DENY'
    assert params['execution_status'] == 'BLOCKED'
    store.connection.close()


def test_allowed_read_is_recorded():
    store = SQLiteTicketStore()
    store.seed([{'ticket_id': 1042, 'tenant_id': 10, 'customer_id': 1,
                 'title': 'Example', 'description': 'Text', 'status': 'OPEN'}])
    connection = MagicMock()
    result = audited_execute(Actor('reader1', 10, 'reader'), 'get_ticket',
                             {'ticket_id': 1042}, store, OracleAudit(connection), 'test-run', 1)
    assert result.allowed
    cursor = connection.cursor.return_value.__enter__.return_value
    assert cursor.execute.call_args.args[1]['policy_decision'] == 'ALLOW'
    store.connection.close()
