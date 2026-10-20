"""Release regression tests, no OCI credentials required."""
import sqlite3
import pytest
from evaluation.phase4 import scenarios, select_cases
from database.audit import audited_execute
from security.policy_engine import Actor
from security.executor import ExecutionResult


def test_balanced_four_categories():
    cases = select_cases(scenarios(), 4)
    assert [c['category'] for c in cases] == [
        'legitimate', 'unauthorized', 'injection', 'cross_tenant'
    ]
    assert len({(c['request'], c['context']) for c in cases}) == 4


def test_diverse_twenty_cases():
    cases = scenarios()
    assert len(cases) == 100
    assert len({c['id'] for c in cases}) == 100
    assert len({(c['request'], c['context']) for c in cases}) == 100


class OracleTicketStore:
    """Small transactional stand-in, intentionally named for audited executor detection."""
    def __init__(self, connection):
        self.connection = connection
        self.commit_mutations = True

    def get_ticket(self, ticket_id):
        row = self.connection.execute(
            'SELECT ticket_id, tenant_id, status FROM tickets WHERE ticket_id=?',
            (ticket_id,)).fetchone()
        return dict(zip(('ticket_id', 'tenant_id', 'status'), row)) if row else None

    def update_status(self, ticket_id, tenant_id, status):
        cursor = self.connection.execute(
            'UPDATE tickets SET status=? WHERE ticket_id=? AND tenant_id=?',
            (status, ticket_id, tenant_id))
        if self.commit_mutations:
            self.connection.commit()
        return cursor.rowcount

    def delete_ticket(self, ticket_id, tenant_id):
        cursor = self.connection.execute(
            'DELETE FROM tickets WHERE ticket_id=? AND tenant_id=?',
            (ticket_id, tenant_id))
        if self.commit_mutations:
            self.connection.commit()
        return cursor.rowcount


class FakeAudit:
    def __init__(self, connection, fail=False):
        self.connection = connection
        self.fail = fail

    def record(self, *args, commit=True):
        if self.fail:
            raise RuntimeError('Simulated audit insertion failure')
        self.connection.execute('INSERT INTO traces(message) VALUES (?)', ('recorded',))
        if commit:
            self.connection.commit()


def setup():
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE tickets(ticket_id INT, tenant_id INT, status TEXT)')
    connection.execute('CREATE TABLE traces(message TEXT)')
    connection.execute('INSERT INTO tickets VALUES (1042, 10, "OPEN")')
    connection.commit()
    return connection, OracleTicketStore(connection)


def test_atomic_mutation_and_trace_commit():
    connection, store = setup()
    result = audited_execute(Actor('test', 10, 'editor'), 'update_ticket',
                             {'ticket_id': 1042, 'status': 'RESOLVED'},
                             store, FakeAudit(connection), 'run', 1)
    assert result.allowed
    assert store.get_ticket(1042)['status'] == 'RESOLVED'
    assert connection.execute('SELECT COUNT(*) FROM traces').fetchone()[0] == 1
    assert store.commit_mutations is True
    connection.close()


def test_atomic_rollback_on_audit_failure():
    connection, store = setup()
    with pytest.raises(RuntimeError, match='audit insertion failure'):
        audited_execute(Actor('test', 10, 'editor'), 'update_ticket',
                        {'ticket_id': 1042, 'status': 'RESOLVED'},
                        store, FakeAudit(connection, fail=True), 'run', 1)
    assert store.get_ticket(1042)['status'] == 'OPEN'
    assert connection.execute('SELECT COUNT(*) FROM traces').fetchone()[0] == 0
    assert store.commit_mutations is True
    connection.close()


def test_atomic_connection_mismatch_rejected():
    connection, store = setup()
    other = sqlite3.connect(':memory:')
    with pytest.raises(ValueError, match='same Oracle connection'):
        audited_execute(Actor('test', 10, 'editor'), 'update_ticket',
                        {'ticket_id': 1042, 'status': 'RESOLVED'},
                        store, FakeAudit(other), 'run', 1)
    connection.close()
    other.close()
