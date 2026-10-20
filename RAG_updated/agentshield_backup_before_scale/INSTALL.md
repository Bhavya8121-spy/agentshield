# AgentShield Product Website (Local MVP)

This is a **working local demonstration**, not a hosted multi-tenant security SaaS. It adapts the supplied HTML marketing site and connects its interactive demo to AgentShield's real `security.executor.execute()` implementation. No OCI credentials, LLM calls, or Oracle database are needed.

## Install into your existing AgentShield project

1. Back up the existing project.
2. Copy `product_server.py` to your project root, `web/index.html` to a new `web/` folder, and `tests/test_product_server.py` into your existing `tests/` folder.
3. Activate your existing `.venv` and install the project's requirements.
4. Run `python -m pytest -q` and `python product_server.py`.
5. Open `http://127.0.0.1:8765` (do not open `web/index.html` directly, because it requires the API).

## How it works

- `POST /api/check` accepts only `{ "role": "reader|editor|admin", "action": "view|edit|delete", "ticket_id": 1042|2042 }`.
- Each request creates a fresh in-memory SQLite fixture and invokes the **actual** guarded executor.
- Tenant 10 owns ticket 1042, tenant 20 owns ticket 2042; the demo actor belongs to tenant 10.
- There is no persistent mutation and no actual LLM invocation. This is a policy demonstration, not a prompt-injection model test.
- The existing Streamlit Reliability Lab remains separate; use it for real evaluation JSON evidence.

## Before public hosting

Do not expose this development server publicly. Replace it with a production ASGI server, add authentication and server-side identity, rate limiting, CORS/CSRF policy, monitoring, abuse prevention, data protection, and secure deployment. Remove placeholder sales claims; only offer a trial when it exists. The calculator is illustrative, not an estimate of verified savings.
