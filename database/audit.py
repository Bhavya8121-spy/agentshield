"""Oracle audit events. No credentials or LLM secrets are recorded."""
import json
import time
from uuid import uuid4
from security.executor import execute


class OracleAudit:
    def __init__(self, connection):
        self.connection = connection

    def start_run(self, scenario_id, mode='protected'):
        run_id = str(uuid4())
        with self.connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO agent_runs (run_id, scenario_id, agent_mode) '
                'VALUES (:run_id, :scenario_id, :agent_mode_value)',
                {'run_id': run_id, 'scenario_id': scenario_id, 'agent_mode_value': mode}
            )
        self.connection.commit()
        return run_id

    def record(self, run_id, sequence_no, tool_name, arguments, result, latency_ms, commit=True):
        # Avoid persisting raw untrusted payloads beyond this synthetic-data demo.
        try:
            arguments_json = json.dumps(arguments, default=str)
        except (TypeError, ValueError):
            arguments_json = json.dumps({'error': 'unserializable arguments'})
        if len(arguments_json) > 10000:
            arguments_json = json.dumps({'error': 'arguments omitted: too large'})
        with self.connection.cursor() as cursor:
            cursor.execute('''INSERT INTO tool_traces
                (trace_id, run_id, sequence_no, tool_name, arguments_json,
                 policy_decision, decision_reason, execution_status, latency_ms)
                VALUES (:trace_id, :run_id, :sequence_no, :tool_name, :arguments_json,
                        :policy_decision, :decision_reason, :execution_status, :latency_ms)''',
                {'trace_id': str(uuid4()), 'run_id': run_id, 'sequence_no': sequence_no,
                 'tool_name': tool_name, 'arguments_json': arguments_json,
                 'policy_decision': 'ALLOW' if result.allowed else 'DENY',
                 'decision_reason': result.reason[:500],
                 'execution_status': 'SUCCESS' if result.allowed else 'BLOCKED',
                 'latency_ms': latency_ms}
            )
        if commit:
            self.connection.commit()

    def finish_run(self, run_id):
        with self.connection.cursor() as cursor:
            cursor.execute('UPDATE agent_runs SET completed_at=SYSTIMESTAMP WHERE run_id=:run_id',
                           {'run_id': run_id})
        self.connection.commit()


def audited_execute(actor, tool_name, arguments, store, audit, run_id, sequence_no):
    """Atomically commit Oracle ticket mutation + trace on one connection.

    A committed start_run must already exist. For Oracle stores, both operations
    share the same transaction; audit insertion failure rolls back the mutation.
    Other stores retain the legacy demo path and are NOT transactionally coupled.
    """
    atomic = (type(store).__name__ == 'OracleTicketStore'
              and hasattr(store, 'commit_mutations')
              and hasattr(store, 'connection'))
    if atomic and store.connection is not audit.connection:
        raise ValueError('Atomic audit requires the same Oracle connection')
    started = time.perf_counter()
    old_commit_mode = store.commit_mutations if atomic else None
    if atomic:
        store.commit_mutations = False
    try:
        result = execute(actor, tool_name, arguments, store)
        if atomic:
            audit.record(run_id, sequence_no, tool_name, arguments, result,
                         round((time.perf_counter() - started) * 1000, 3), commit=False)
        else:
            audit.record(run_id, sequence_no, tool_name, arguments, result,
                         round((time.perf_counter() - started) * 1000, 3))
        if atomic:
            audit.connection.commit()
        return result
    except Exception:
        if atomic:
            audit.connection.rollback()
        raise
    finally:
        if atomic:
            store.commit_mutations = old_commit_mode
