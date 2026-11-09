"""Deterministic mock agent that behaves like an LLM with a chosen gullibility level.

Used by default so the public demo costs nothing and is reproducible. It exposes the
same interface as the live OCIPlanner: propose() and answer().
"""
import re

from security.intent import classify, ticket_ids

PROFILES = {
    'hardened': {'label': 'Hardened agent',
                 'description': 'Treats ticket text as data. Only does what the user asked.'},
    'standard': {'label': 'Typical agent',
                 'description': 'Follows instructions in ticket notes that sound official.'},
    'vulnerable': {'label': 'Gullible agent',
                   'description': 'Obeys any instruction it finds inside ticket text.'},
}

_INJECTION = re.compile(
    r'ignore\s+(?:all\s+|your\s+|previous\s+)*instructions?[^.\n]*?'
    r'\b(delete|remove|resolve|close|mark|update)\b[^.\n]*?(?:ticket|request)\s*#?(\d{3,6})',
    re.I)
_AUTHORITY = re.compile(r'\b(system|admin|administrator|urgent|pre-?approved|manager|management)\b', re.I)


def _status_from(text):
    t = text.lower()
    if re.search(r'\b(progress|working|started|start)\b', t):
        return 'IN_PROGRESS'
    if re.search(r'\b(reopen|re-open|open)\b', t):
        return 'OPEN'
    return 'RESOLVED'


class MockPlanner:
    name = 'mock'
    model = None

    def _injected(self, ctx, profile):
        if profile == 'hardened':
            return None
        for line in ctx.splitlines():
            m = _INJECTION.search(line)
            if not m:
                continue
            if profile == 'standard' and not _AUTHORITY.search(line):
                continue
            verb, tid = m.group(1).lower(), int(m.group(2))
            if verb in ('delete', 'remove'):
                return {'tool': 'delete_ticket', 'arguments': {'ticket_id': tid},
                        'reason': 'Following the instruction written in the ticket note'}
            return {'tool': 'update_ticket', 'arguments': {'ticket_id': tid, 'status': 'RESOLVED'},
                    'reason': 'Following the instruction written in the ticket note'}
        return None

    def propose(self, user_request, ticket_context='', profile='hardened'):
        hijack = self._injected(ticket_context, profile)
        if hijack:
            return hijack
        ids = sorted(ticket_ids(user_request))
        if not ids:
            return {'tool': 'none', 'arguments': {}, 'reason': 'No ticket number in the request'}
        tid, kind = ids[0], classify(user_request)
        if kind == 'delete':
            return {'tool': 'delete_ticket', 'arguments': {'ticket_id': tid}, 'reason': 'User asked to delete'}
        if kind == 'update':
            return {'tool': 'update_ticket',
                    'arguments': {'ticket_id': tid, 'status': _status_from(user_request)},
                    'reason': 'User asked to change the ticket'}
        return {'tool': 'get_ticket', 'arguments': {'ticket_id': tid}, 'reason': 'User asked to read'}

    def answer(self, user_request, proposal, outcome, profile='hardened'):
        if proposal['tool'] == 'none':
            return "I couldn't tell which ticket you mean. Please include a ticket number."
        if not outcome['executed']:
            return f"I wasn't able to do that. {outcome['reason']}."
        tid = proposal['arguments'].get('ticket_id')
        if proposal['tool'] == 'get_ticket':
            t = outcome['data'] or {}
            return (f"Ticket #{tid} \u201c{t.get('title', '')}\u201d is {t.get('status', '')}. "
                    f"The customer wrote: {t.get('description', '')}")
        if proposal['tool'] == 'update_ticket':
            return f"Done. Ticket #{tid} is now {proposal['arguments'].get('status')}."
        return f'Done. Ticket #{tid} has been deleted.'
