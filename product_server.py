"""Demonstration server for AgentShield's real deterministic firewall.

Run from the AgentShield repository root: python product_server.py

Endpoints (all run against disposable synthetic SQLite data, never Oracle):
  POST /api/check, /api/paste-check   original one-action demos
  POST /api/agent                     an agent (mock by default, live OCI opt-in) proposes an
                                      action; shown with and without AgentShield
  POST /api/v1/check                  bring your own agent: send its raw tool-call output
  GET  /api/agent/config?domain=email profiles, scenarios, and whether live mode is enabled
  (agent endpoints take an optional "domain": "email" (the headline demo) or "ticket" (default))
Live model calls require AGENTSHIELD_LIVE=1 plus OCI_* variables; otherwise mock only.
"""
import json
import os
import time
import threading
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from security.executor import execute
from security.policy_engine import Actor
from tools.ticket_tools import SQLiteTicketStore

HOST = os.getenv('AGENTSHIELD_HOST', '127.0.0.1')
PORT = int(os.getenv('PORT', '8765'))
_RATE_LOCK = threading.Lock()
_REQUESTS = defaultdict(deque)
_MAX_REQUESTS = 40
_WINDOW_SECONDS = 60
ROOT = Path(__file__).resolve().parent
PAGE = ROOT / 'web' / 'index.html'
ROLES = frozenset({'reader', 'editor', 'admin'})
MAX_BODY = {'/api/agent': 2048, '/api/v1/check': 16384}
ACTIONS = {'view': 'get_ticket', 'edit': 'update_ticket', 'delete': 'delete_ticket'}
TICKETS = [
    {'ticket_id': 1042, 'tenant_id': 10, 'customer_id': 1,
     'title': 'Password reset', 'description': 'Expired password reset token', 'status': 'OPEN'},
    {'ticket_id': 2042, 'tenant_id': 20, 'customer_id': 2,
     'title': 'Other business record', 'description': 'Private synthetic fixture', 'status': 'OPEN'},
]


def check_action(role, action, ticket_id):
    """Execute a proposed action against a fresh disposable SQLite fixture."""
    if role not in ROLES or action not in ACTIONS:
        raise ValueError('Invalid role or action')
    if type(ticket_id) is not int or ticket_id not in (1042, 2042):
        raise ValueError('Invalid demonstration ticket')
    store = SQLiteTicketStore()
    try:
        store.seed(TICKETS)
        args = {'ticket_id': ticket_id}
        if action == 'edit':
            args['status'] = 'IN_PROGRESS'
        result = execute(Actor('public-demo', 10, role), ACTIONS[action], args, store)
        return {
            'allowed': result.allowed,
            'decision': 'ALLOW' if result.allowed else 'DENY',
            'reason': result.reason,
            'tool': ACTIONS[action],
            'ticket_id': ticket_id,
            'demo_only': True,
            'isolated': True,
        }
    finally:
        store.connection.close()


class Handler(BaseHTTPRequestHandler):
    def _rate_limited(self):
        # Basic per-IP throttling, best effort only; hosting provider may proxy IPs.
        ip = self.client_address[0]
        now = time.monotonic()
        with _RATE_LOCK:
            q = _REQUESTS[ip]
            while q and now - q[0] > _WINDOW_SECONDS:
                q.popleft()
            if len(q) >= _MAX_REQUESTS:
                return True
            q.append(now)
            # Keep memory bounded for this small public demo.
            if len(_REQUESTS) > 2000:
                for key in list(_REQUESTS)[:500]:
                    if not _REQUESTS[key] or now - _REQUESTS[key][-1] > _WINDOW_SECONDS:
                        del _REQUESTS[key]
            return False

    def respond(self, status, payload):
        raw = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(raw)

    def _agent(self, data):
        from agents.playground import build_planner, run_agent_demo
        if not {'role', 'prompt', 'profile', 'mode'} <= set(data) or set(data) - {'role', 'prompt', 'profile', 'mode', 'domain'}:
            raise ValueError('Unexpected request fields')
        domain = data.get('domain', 'ticket')
        try:
            planner = build_planner(data['mode'], domain)
        except RuntimeError as exc:
            return self.respond(503, {'error': str(exc)})
        try:
            result = run_agent_demo(role=data['role'], prompt=data['prompt'],
                                    profile=data['profile'], planner=planner, domain=domain)
        except Exception as exc:
            if isinstance(exc, (ValueError, TypeError)):
                raise

            import traceback
            print("\n========== AGENT ERROR ==========")
            print(f"Exception type: {type(exc).__name__}")
            print(f"Exception message: {exc}")
            traceback.print_exc()
            print("=================================\n")

            return self.respond(502, {
                "error": "Agent execution failed",
                "error_type": type(exc).__name__
            })
        self.respond(200, result)

    def _byo(self, data):
        from agents.playground import check_agent_output
        if not {'role', 'payload'} <= set(data) or set(data) - {'role', 'payload', 'user_request', 'domain'}:
            raise ValueError('Unexpected request fields')
        self.respond(200, check_agent_output(role=data['role'], payload=data['payload'],
                                             user_request=data.get('user_request'),
                                             domain=data.get('domain', 'ticket')))

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            raw = PAGE.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)
        elif self.path in (
            '/assets/agentshield-logo-horizontal.svg',
            '/assets/agentshield-mark.svg',
            '/assets/agentshield-app-icon.svg',
        ):
            asset = ROOT / 'web' / self.path.lstrip('/')
            raw = asset.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'image/svg+xml')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(raw)
        elif self.path == '/api/health':
            self.respond(200, {'status': 'ok', 'mode': 'isolated-demo'})
        elif self.path.split('?')[0] == '/api/agent/config':
            from urllib.parse import parse_qs, urlsplit
            from agents.planners import PROFILES
            from agents.playground import ROLES as AGENT_ROLES, get_domain, live_available
            try:
                domain = get_domain(parse_qs(urlsplit(self.path).query).get('domain', ['ticket'])[0])
            except ValueError:
                return self.respond(400, {'error': 'Invalid domain'})
            self.respond(200, {'domain': domain.name, 'live_available': live_available(),
                               'roles': list(AGENT_ROLES),
                               'profiles': [{'id': k, **v} for k, v in PROFILES.items()],
                               'scenarios': domain.scenarios})
        else:
            self.respond(404, {'error': 'Not found'})

    def do_POST(self):
        if self._rate_limited():
            return self.respond(429, {'error': 'Too many demo requests; please wait a minute'})
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            return self.respond(415, {'error': 'JSON requests only'})
        if self.path not in ('/api/check', '/api/paste-check', '/api/agent', '/api/v1/check'):
            return self.respond(404, {'error': 'Not found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 1 or size > MAX_BODY.get(self.path, 4096):
                return self.respond(413, {'error': 'Invalid request size'})
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Invalid JSON request')
            if self.path == '/api/agent':
                return self._agent(data)
            if self.path == '/api/v1/check':
                return self._byo(data)
            if self.path == '/api/paste-check':
                if set(data) != {'role', 'proposal'} or data['role'] not in ROLES:
                    raise ValueError('Unexpected request fields')
                from paste_check import check_pasted_proposal
                return self.respond(200, check_pasted_proposal(data['role'], data['proposal']))
            if set(data) != {'role', 'action', 'ticket_id'}:
                raise ValueError('Unexpected request fields')
            self.respond(200, check_action(data['role'], data['action'], data['ticket_id']))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.respond(400, {'error': 'Invalid demonstration request'})


if __name__ == '__main__':
    print(f'AgentShield synthetic demo listening at http://{HOST}:{PORT}')
    print('Isolated synthetic data only. Press Ctrl+C to stop.')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
