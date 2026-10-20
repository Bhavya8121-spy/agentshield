# AgentShield: Python SDK + public recruiter demo

This patch is meant to be copied into your **existing AgentShield project root**.
It does not deploy automatically. The site is a **synthetic, read-only-in-effect demo**: every API call uses fresh fictional SQLite tickets. No Oracle credentials or OCI API keys are needed.

## 1. Install / test locally

```bash
cp product_server.py product_server.py.backup
cp web/index.html web/index.html.backup
# Extract patch ZIP into this directory, preserving web/index.html
python -m pip install -r requirements-demo.txt pytest
python -m pip install -e .
python -m pytest tests/test_sdk.py -q
python product_server.py
```

Open http://127.0.0.1:8765 . Test front desk / owner, cross-tenant access, and paste-a-proposal.

## 2. SDK usage

```python
from agentshield_sdk import AgentShield
shield = AgentShield()
# Local, deterministic reference policy; application must verify actor and resource owner itself.
result = shield.check_local(role='reader', actor_tenant=10, resource_tenant=10, tool='delete_ticket')
print(result.allowed, result.reason)
# Synthetic demo API; never treat as a production authorization decision.
result = shield.check_demo(role='reader', action='delete', ticket_id=1042)
```

The SDK has no OCI dependency. Its `check_local()` method is an illustrative policy implementation, not an identity provider or enterprise enforcement point. The `check_demo()` method ONLY calls the sample API, which accepts fictional tickets 1042/2042.

## 3. Publish a live recruiter website (Render)

1. Commit the full AgentShield project to a **private GitHub repository first**. Confirm `.env`, `wallet/`, `.oci/`, and `*.pem` are ignored and NOT tracked (`git ls-files`); remove any leaked secrets and rotate them before making the repo public.
2. Ensure repository root contains this patch's `Dockerfile`, `render.yaml`, `requirements-demo.txt`, `product_server.py`, `paste_check.py`, `web/index.html`, `security/`, and `tools/`.
3. Visit https://dashboard.render.com/ and create a **Blueprint** from your GitHub repository using `render.yaml`. Review the plan and pricing before approving. Hosting availability and free-tier policies may change.
4. After build and health check, Render provides a URL such as `https://<your-service>.onrender.com`. Copy the **actual** URL into your GitHub README and resume. Do not assume a URL until it exists.
5. Check `https://<actual-url>/api/health`, then test the site on your phone and in a private browser window.

The Docker image intentionally does **not** include your OCI config, wallet, `.env`, Oracle client, or live model inference. Do not add them to this public demo. Public hosting can still incur costs; use your host's limits and monitoring.

## 4. Optional Docker local run

```bash
docker build -t agentshield-demo .
docker run --rm -p 8765:8765 agentshield-demo
```

## 5. Scope and security limitations

- This is a demonstration API, not a general-purpose authorization gateway. User-supplied roles are untrusted and only used for fictional tickets.
- In-memory rate limiting is best-effort per process; it is not distributed, bot-resistant, or sufficient for production.
- The SDK local policy cannot independently establish identity or database ownership; production requires trusted identity, tenant lookups, durable logs, and a properly designed policy service.
- No login, persistent customer accounts, billing, or actual external agent connection.
- Website benchmark counts describe previously reported runs and should be updated from checked-in evidence; do not imply the public demo itself ran those OCI evaluations.
