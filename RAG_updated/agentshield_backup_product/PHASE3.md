# Phase 3: OCI Generative AI planner

This is an additive patch: copy files into the existing AgentShield repository.

## Requirements

Install `oci` with `python -m pip install oci`. Ensure your `~/.oci/config`
profile authenticates to OCI, and your tenancy has permission to call the
Generative AI inference service in the chosen region.

Add to your local `.env` (never commit it):

```ini
OCI_COMPARTMENT_OCID=ocid1.compartment.oc1..YOUR_VALUE
OCI_GENAI_MODEL_ID=YOUR_AVAILABLE_COHERE_CHAT_MODEL_ID
OCI_GENAI_ENDPOINT=https://inference.generativeai.us-chicago-1.oci.oraclecloud.com
OCI_PROFILE=DEFAULT
```

**Important:** The OCI region must support your chosen model. Select an
available **Cohere chat** model for this specific adapter. This adapter does
not support Llama or other model families without modifications.

Run tests: `python -m pytest -q tests/test_phase3.py`.
Run the live demo: `python demo_oci.py`.

This MVP asks OCI Generative AI to propose one tool call as JSON, then uses
AgentShield's deterministic policy firewall and Phase 2 Oracle audit trail.
It is NOT native OCI tool calling or a multi-step agent loop.

## Known limitations

- The current Phase 2 Oracle audit and mutation commits are not atomic.
- `none` proposals and invalid model responses do not create a tool trace.
- JSON-only prompting is not guaranteed; malformed responses fail closed.
- OCI API usage may incur charges; check quotas and credit balance.
- The model must never receive wallet files, credentials, or production ticket data.
- For a reproducible benchmark, replay captured tool proposals with the mock planner.
