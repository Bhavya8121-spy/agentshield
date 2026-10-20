# AgentShield

Deterministic tool-call authorization foundation for evaluating AI-agent reliability.

## Quickstart (local, no Oracle required)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
python demo.py
```

## Oracle setup

1. Provision Oracle Autonomous AI Database with a dedicated least-privilege application user.
2. Execute `sql/schema.sql` using SQL Worksheet as that user.
3. Copy `.env.example` to `.env` and fill in credentials and TLS DSN. Never commit `.env` or wallet files.
4. Run `python -m database.oracle` to seed synthetic tickets.

## Security model

- Default deny, role-based tool allowlist, strict argument schemas.
- Tenant ownership is loaded from trusted database records; the LLM cannot choose a tenant.
- Unknown tools, malformed arguments, and unauthorized mutations are rejected.
- Retrieved ticket text is returned as data, never interpreted by the deterministic executor.

## Scope / limitations

Phase 1 validates the firewall using an SQLite test store and seeds an Oracle schema. The live Oracle-backed guarded executor, durable trace writer, OCI Generative AI model adapter, deterministic replay, and dashboard are **Phase 2** features, not yet implemented.

The sample executor uses separate read and write operations. Production-grade authorization must be rechecked inside a single database transaction, ideally using a tenant-scoped conditional mutation to prevent TOCTOU races. No production security claim is made.

## Next milestone

Integrate an Oracle store implementing the same `get_ticket`, `update_status`, and `delete_ticket` interface; add an audit writer and OCI Generative AI tool-call adapter. Evaluate attempted vs. executed unauthorized calls separately.
