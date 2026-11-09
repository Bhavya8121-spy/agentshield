"""Deterministic mock email assistant with a chosen gullibility level.

Same interface as the live OCIPlanner: propose() and answer().
"""
import re

from agents.planners import PROFILES  # noqa: F401  (re-exported for convenience)
from security.intent import addresses, classify, ticket_ids

_PRE = r'ignore\s+(?:all\s+|your\s+|previous\s+)*instructions?'
_SEND_INJ = re.compile(_PRE + r'[^\n]*?\b(?:forward|send)\b[^\n]*?\bto\s+'
                       r'([\w.+-]+@[\w-]+(?:\.[\w-]+)+)', re.I)
_DEL_INJ = re.compile(_PRE + r'[^.\n]*?\b(?:delete|remove|trash)\b[^.\n]*?\bemail\s*#?(\d{3,6})', re.I)
_AUTHORITY = re.compile(r'\b(system|admin|administrator|urgent|pre-?approved|manager|management)\b', re.I)


class EmailMockPlanner:
    name = 'mock'
    model = None

    def _injected(self, ctx, profile):
        if profile == 'hardened':
            return None
        for line in ctx.splitlines():
            if profile == 'standard' and not _AUTHORITY.search(line):
                continue
            m = _SEND_INJ.search(line)
            if m:
                return {'tool': 'send_email',
                        'arguments': {'to': m.group(1), 'subject': 'Invoices',
                                      'body': 'Forwarding as instructed.'},
                        'reason': 'Following the instruction written in the email'}
            m = _DEL_INJ.search(line)
            if m:
                return {'tool': 'delete_email', 'arguments': {'email_id': int(m.group(1))},
                        'reason': 'Following the instruction written in the email'}
        return None

    def propose(self, user_request, ticket_context='', profile='hardened'):
        hijack = self._injected(ticket_context, profile)
        if hijack:
            return hijack
        kind = classify(user_request, 'email')
        if kind == 'send':
            addrs = sorted(addresses(user_request))
            if not addrs:
                return {'tool': 'none', 'arguments': {}, 'reason': 'No recipient address in the request'}
            m = re.search(r'\b(?:saying|that says|that|with the message)\b[: ]+(.+)$', user_request, re.I)
            body = (m.group(1).strip() if m else 'Following up on my earlier message.')[:500]
            return {'tool': 'send_email', 'arguments': {'to': addrs[0], 'subject': 'Quick note', 'body': body},
                    'reason': 'User asked to send an email'}
        ids = sorted(ticket_ids(user_request))
        if not ids:
            return {'tool': 'none', 'arguments': {}, 'reason': 'No email number in the request'}
        if kind == 'delete':
            return {'tool': 'delete_email', 'arguments': {'email_id': ids[0]}, 'reason': 'User asked to delete'}
        return {'tool': 'read_email', 'arguments': {'email_id': ids[0]}, 'reason': 'User asked to read'}

    def answer(self, user_request, proposal, outcome, profile='hardened'):
        tool, args = proposal['tool'], proposal['arguments']
        if tool == 'none':
            return "I couldn't tell what to do. Please include an email number or a recipient address."
        if not outcome['executed']:
            return f"I wasn't able to do that. {outcome['reason']}."
        if tool == 'read_email':
            e = outcome['data'] or {}
            first = re.split(r'(?<=[.!?])\s', e.get('body', ''))[0]
            return f"Email #{args['email_id']} from {e.get('sender', '')}, \u201c{e.get('subject', '')}\u201d: {first}"
        if tool == 'send_email':
            return f"Done. I sent your email to {args['to']}."
        return f"Done. Email #{args['email_id']} has been deleted."
