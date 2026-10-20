# Phase 2: Oracle execution and traces

This update **does not overwrite** `database/oracle.py` or `.env`: keep your working wallet-enabled connection.

Copy `database/oracle_store.py`, `database/audit.py`, `demo_oracle.py`, and `tests/test_oracle_phase2.py` into the same locations in your existing project.

From the repository root:

```bash
source .venv/bin/activate
python -m pytest -q
python demo_oracle.py
```

Prerequisites: `sql/schema.sql` tables already created and `python -m database.oracle` successfully seeded fixtures.

Verify Oracle trace rows:

```sql
SELECT r.scenario_id, t.sequence_no, t.tool_name,
       t.policy_decision, t.decision_reason, t.execution_status, t.latency_ms
FROM agent_runs r JOIN tool_traces t ON r.run_id = t.run_id
WHERE r.scenario_id = 'phase2_oracle_smoke'
ORDER BY t.created_at DESC, t.sequence_no;
```

## Scope and limitations

* The demo is read-only or denied, so it is safe to repeat on synthetic fixtures.
* The existing Phase 1 executor authorizes reads and then performs tenant-filtered writes. The tenant filter protects the write, but the read and write are not a single locked transaction.
* The existing executor commits mutations before the audit writer commits. This is **best-effort audit**, not atomic audit: an audit failure could occur after a successful mutation. Do not claim tamper-proof or guaranteed-complete traces yet. Phase 2b should move execution and audit into one Oracle transaction, add error outcome handling, and implement an outbox if needed.
* `execution_status=BLOCKED` currently also covers missing tickets and failed updates; inspect `decision_reason` to distinguish these. `policy_decision=ALLOW` currently denotes a successful permitted execution, not every intermediate policy authorization decision.
* The mock-based tests do not prove connectivity or transactions against a live Oracle instance. `python demo_oracle.py` is the live integration smoke test.
* Do not run with production data or real customer tickets. Do not commit wallet or `.env`.
