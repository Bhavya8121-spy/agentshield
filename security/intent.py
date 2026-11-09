"""Intent-scope guard: an action must match what the USER asked for.

Role-based access control answers "may this role ever do X?". It cannot tell
whether X is what the user actually wanted. If an owner asks an agent to
*summarize* an email and hidden text in that email makes the agent propose
`send_email` to an attacker, RBAC alone could allow it. This guard closes that
gap deterministically:
  * a read-style request may only lead to reads,
  * the record (ticket/email) must be one the user mentioned,
  * an email may only be sent to an address the user wrote in the request.

It is a conservative keyword heuristic (fail-closed: when unsure, read-only).
It is not a language-understanding model and does not replace RBAC; both layers
must pass.
"""
import re
from dataclasses import dataclass

DOMAINS = {
    'ticket': {
        'verbs': {
            'delete': ('delete', 'remove', 'erase', 'purge', 'destroy', 'discard'),
            'update': ('update', 'change', 'set', 'mark', 'resolve', 'resolved', 'close',
                       'closed', 'reopen', 'edit', 'modify', 'escalate'),
        },
        'kinds': {'read': {'get_ticket'},
                  'update': {'get_ticket', 'update_ticket'},
                  'delete': {'get_ticket', 'delete_ticket'}},
        'id_arg': 'ticket_id',
        'id_tools': {'get_ticket', 'update_ticket', 'delete_ticket'},
    },
    'email': {
        'verbs': {
            'delete': ('delete', 'remove', 'erase', 'trash', 'discard'),
            'send': ('send', 'forward', 'reply', 'compose', 'write', 'notify'),
        },
        'kinds': {'read': {'read_email'},
                  'send': {'read_email', 'send_email'},
                  'delete': {'read_email', 'delete_email'}},
        'id_arg': 'email_id',
        'id_tools': {'read_email', 'delete_email'},
    },
}
_NEGATION = re.compile(r"(?:don'?t|do not|never|not|without)\s+(?:\w+\s+){0,2}$", re.I)
_ID = re.compile(r'(?<!\d)\d{3,6}(?!\d)')
_ADDR = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')


@dataclass(frozen=True)
class Scope:
    kind: str                 # 'read' | 'update' | 'send' | 'delete'
    tools: frozenset
    ticket_ids: frozenset     # ids of the record type for this domain
    addresses: frozenset = frozenset()


def _spec(domain):
    if domain not in DOMAINS:
        raise ValueError('Unknown domain')
    return DOMAINS[domain]


def _has_verb(text, words):
    for m in re.finditer(r'\b(' + '|'.join(words) + r')\b', text, re.I):
        if not _NEGATION.search(text[:m.start()][-30:]):
            return True
    return False


def classify(text, domain='ticket'):
    """Return the kind of request; 'read' is the safe default. Delete outranks the rest."""
    text = text if isinstance(text, str) else ''
    verbs = _spec(domain)['verbs']
    for kind in ('delete',) + tuple(k for k in verbs if k != 'delete'):
        if _has_verb(text, verbs[kind]):
            return kind
    return 'read'


def ticket_ids(text):
    return frozenset(int(x) for x in _ID.findall(text if isinstance(text, str) else ''))


def addresses(text):
    return frozenset(a.lower() for a in _ADDR.findall(text if isinstance(text, str) else ''))


def scope_of(text, domain='ticket'):
    kind = classify(text, domain)
    return Scope(kind, frozenset(_spec(domain)['kinds'][kind]), ticket_ids(text), addresses(text))


def check_intent(user_request, tool, arguments, domain='ticket'):
    """Return (allowed, reason). Fails closed on anything unexpected."""
    spec = _spec(domain)
    scope = scope_of(user_request, domain)
    if tool not in scope.tools:
        return False, f'Action goes beyond the request (you only asked to {scope.kind})'
    if not isinstance(arguments, dict):
        return False, 'Arguments missing or invalid'
    if tool in spec['id_tools']:
        rid = arguments.get(spec['id_arg'])
        noun = spec['id_arg'].split('_')[0]
        if type(rid) is not int:
            return False, f'{noun.capitalize()} id missing or invalid'
        if rid not in scope.ticket_ids:
            return False, f'That {noun} was not mentioned in the user request'
    if tool == 'send_email':
        to = arguments.get('to')
        if not isinstance(to, str) or to.lower() not in scope.addresses:
            return False, 'Recipient was not written in the user request'
    return True, 'Matches the user request'
