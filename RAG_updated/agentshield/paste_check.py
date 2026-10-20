"""Conservative local-only assessment of a user-supplied proposed action.

This is not an agent connector or a prompt-injection detector.
"""
import json
from product_server import check_action

TOOLS = {'get_ticket': 'view', 'update_ticket': 'edit', 'delete_ticket': 'delete'}
MAX_TEXT = 5000


def check_pasted_proposal(role, raw):
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_TEXT:
        raise ValueError('Paste a JSON action (up to 5000 characters)')
    text = raw.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        if len(lines) < 3 or lines[0].strip().lower() not in ('```', '```json') or lines[-1].strip() != '```':
            raise ValueError('Invalid JSON code fence')
        text = '\n'.join(lines[1:-1]).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError('Paste a JSON object with tool and arguments') from exc
    if not isinstance(obj, dict) or not {'tool', 'arguments'} <= set(obj) or set(obj) - {'tool', 'arguments', 'reason'}:
        raise ValueError('Only tool, arguments, and optional reason are accepted')
    tool = obj['tool']
    args = obj['arguments']
    if not isinstance(tool, str) or not isinstance(args, dict):
        raise ValueError('Invalid tool proposal')
    if tool not in TOOLS:
        return {'decision': 'DENY', 'allowed': False, 'reason': 'Tool not recognized in this demo', 'demo_only': True, 'isolated': True}
    expected = {'ticket_id', 'status'} if tool == 'update_ticket' else {'ticket_id'}
    if set(args) != expected:
        raise ValueError('Unexpected or missing tool arguments')
    ticket_id = args['ticket_id']
    if isinstance(ticket_id, str) and ticket_id.isascii() and ticket_id.isdecimal():
        ticket_id = int(ticket_id)
    if type(ticket_id) is not int or ticket_id not in (1042, 2042):
        raise ValueError('Use sample ticket 1042 or 2042; no real records are accessed')
    if tool == 'update_ticket' and args['status'] != 'IN_PROGRESS':
        raise ValueError('For this demo, use status IN_PROGRESS')
    result = check_action(role, TOOLS[tool], ticket_id)
    return {**result, 'note': 'Only this pasted action was checked against sample permissions. Your own AI system was not connected or tested.'}
