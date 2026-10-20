# AgentShield: attack diversity + atomic Oracle audit patch

## Contents

- `evaluation/phase4.py`: 20 distinct synthetic prompts, balanced category selection by default.
- `database/oracle_store.py`: optional `commit_mutations` flag. The audited Oracle execution path disables store-level commits temporarily.
- `database/audit.py`: `OracleAudit.record(commit=False)` and `audited_execute()` share a single Oracle connection and commit mutation + trace together; rolls back on error. Also renames the problematic Oracle `:mode` bind to `:agent_mode_value`.
- `tests/test_release.py`: five local tests, including commit, rollback and connection mismatch.

## Install

From the parent of your `agentshield` folder:

```bash
cd ~/Documents/Project/RAG_updated
cp -R agentshield agentshield_backup_before_release
unzip -o ~/Downloads/agentshield-attack-atomic-patch.zip
cd agentshield
source .venv/bin/activate
python -m pytest -q
python -m evaluation.phase4 --mode replay --limit 4
```

## Live sampling

```bash
python -m evaluation.phase4 --mode live --limit 4
```

This performs four OCI inference calls (one per category). Verify the CLI authentication and model settings first. You can use `--sampling sequential` to restore the original ordering.

## Oracle smoke test (read-only and denied action)

```bash
python demo_oracle.py
```

Then query your Autonomous Database:

```sql
SELECT r.scenario_id, t.sequence_no, t.tool_name,
       t.policy_decision, t.execution_status
FROM agent_runs r
JOIN tool_traces t ON t.run_id = r.run_id
WHERE r.scenario_id = 'phase2_oracle_smoke'
ORDER BY t.created_at DESC, t.sequence_no;
```

## Transaction behavior

`OracleAudit.start_run()` commits the parent run first. For an `OracleTicketStore` passed to `audited_execute`, both the ticket mutation and the corresponding `tool_traces` insertion use the **same connection** and a **single commit**. A trace insertion failure rolls back the mutation. The connection mismatch is rejected. `finish_run()` commits separately.

Do **not** call `store.update_status()` or `store.delete_ticket()` directly if you require an atomic audit. Direct calls still commit by default for backward compatibility. Route model tool calls through `audited_execute()` and ensure `OracleTicketStore(connection)` and `OracleAudit(connection)` share the same connection. This design assumes one invocation at a time per connection; do not share that connection concurrently.

This patch does not implement tamper-proof or immutable auditing, independent audit storage, or durable recording of crashes before an audit transaction commits. It also does not prove that a model-generated natural-language answer is correct. The synthetic replay injection rate is 100% by construction; report live results separately.

## Failure-injection test

The included `test_atomic_rollback_on_audit_failure` uses SQLite to simulate an audit insertion error and verifies that the ticket status remains unchanged. Before claiming production-grade Oracle guarantees, perform a controlled live Oracle rollback test using a disposable synthetic ticket, a deliberately failing audit insertion, and a transaction-safe harness.
