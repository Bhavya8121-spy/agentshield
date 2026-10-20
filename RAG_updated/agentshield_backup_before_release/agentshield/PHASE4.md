# AgentShield Phase 4 — Reliability Lab

## Installation
Extract this patch from the **parent directory** of your existing `agentshield/` repo. It adds files; it does not replace your wallet or `.env`.

```bash
cd agentshield
source .venv/bin/activate
python -m pip install streamlit pandas
python -m pytest -q
python -m evaluation.phase4 --mode replay
streamlit run dashboard.py
```

## Optional live OCI evaluation

```bash
python -m evaluation.phase4 --mode live --limit 3
```

Each live scenario calls OCI Generative AI and may incur charges. Live mode uses your existing `OCIPlanner` and environment settings. It **never executes against Oracle tickets**: it uses a freshly seeded, isolated in-memory SQLite store per scenario. The saved JSON records are local; they are not inserted into Oracle `TOOL_TRACES`.

## Interpretation

- Replay mode uses predefined proposals, so 100% policy accuracy means only that the firewall passed these predefined fixtures; it is **not** an LLM attack-resistance measurement.
- Live mode measures the proposals returned by the model. `policy_correct` is agreement with a fixed expected decision, which can penalize safe refusals; examine each trace.
- `unauthorized_executions` counts changes to the isolated fixture in cases marked DENY. It is not a proof of security outside these scenarios.
- Injection tests embed malicious text in a ticket context but the pre-recorded replay proposal intentionally represents a compromised model. Use live mode to observe actual model behavior.
- Repeated cases are intentional smoke-test repetitions, **not** 20 independent attack strategies.
- A model returning malformed output is reported as ERROR, not silently counted as a successful block.
- Phase 2 Oracle mutations and audit records are not atomic. Production hardening requires transactional mutation/audit, explicit actor authentication, and complete logging of parser failures.

## Next improvements

1. Expand to independent attack payloads and add benign cross-tenant controls.
2. Add captured model-proposal replay from sanitized JSONL, with versioned prompt/model metadata.
3. Add atomic Oracle mutation and audit transactions before using any non-synthetic data.
4. Add CI with `python -m pytest -q` and publish measured benchmark outputs, not invented results.
