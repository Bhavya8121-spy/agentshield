"""Client for the PUBLIC SYNTHETIC demo and a standalone local policy helper.

Not a production identity or authorization service. The caller must authenticate
actors and fetch resource ownership from its own trusted storage.
"""
from dataclasses import dataclass
import json
from urllib import request, error, parse


class AgentShieldError(RuntimeError):
    """Raised on transport, malformed response, or unavailable demo service."""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    tool: str = ''
    demo_only: bool = False


PERMISSIONS = {
    'reader': frozenset({'get_ticket'}),
    'editor': frozenset({'get_ticket', 'update_ticket'}),
    'admin': frozenset({'get_ticket', 'update_ticket', 'delete_ticket'}),
}


class AgentShield:
    def __init__(self, base_url='http://127.0.0.1:8765', timeout=5):
        parsed = parse.urlsplit(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('base_url must be an http(s) origin')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Remote connections require HTTPS')
        if not 0 < timeout <= 30:
            raise ValueError('timeout must be between 0 and 30 seconds')
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    @staticmethod
    def check_local(*, role, actor_tenant, resource_tenant, tool):
        """Deterministic reference policy, not identity verification or resource lookup."""
        if type(actor_tenant) is not int or type(resource_tenant) is not int or actor_tenant < 1 or resource_tenant < 1:
            return Decision(False, 'Invalid tenant')
        if actor_tenant != resource_tenant:
            return Decision(False, 'Cross-tenant access denied', tool)
        if tool not in PERMISSIONS.get(role, frozenset()):
            return Decision(False, 'Tool not permitted for role', tool)
        return Decision(True, 'Authorized', tool)

    def _post(self, endpoint, payload):
        data = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        if len(data) > 4096:
            raise ValueError('Request exceeds demo limit')
        req = request.Request(self.base_url + endpoint, data=data, headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                result = json.load(response)
        except (error.URLError, ValueError, OSError) as exc:
            raise AgentShieldError('Demo service unavailable or rejected the request') from exc
        if type(result) is not dict or type(result.get('allowed')) is not bool or not isinstance(result.get('reason'), str):
            raise AgentShieldError('Invalid demo response')
        return Decision(result['allowed'], result['reason'], str(result.get('tool', '')), True)

    def check_demo(self, *, role, action, ticket_id):
        """Only checks fictional tickets 1042/2042; never a real customer's agent."""
        if role not in PERMISSIONS or action not in ('view', 'edit', 'delete') or type(ticket_id) is not int or ticket_id not in (1042, 2042):
            raise ValueError('Invalid synthetic demo input')
        return self._post('/api/check', {'role': role, 'action': action, 'ticket_id': ticket_id})

    def check_pasted_demo(self, *, role, proposal):
        """Submit a synthetic JSON tool proposal to the demo policy only."""
        if role not in PERMISSIONS or not isinstance(proposal, str) or not proposal.strip() or len(proposal) > 3000:
            raise ValueError('Invalid demo proposal')
        return self._post('/api/paste-check', {'role': role, 'proposal': proposal})
