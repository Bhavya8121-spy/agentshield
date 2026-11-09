"""Normalize tool calls from common AI-provider response shapes.

Lets someone paste (or POST) the raw output of their own agent. Supported:
  * generic            {"tool": "...", "arguments": {...}}  /  {"name": ..., "input": ...}
  * OpenAI Chat        choices[].message.tool_calls[].function{name, arguments(JSON string)}
  * OpenAI legacy      message.function_call{name, arguments}
  * OpenAI Responses   output[] items of type "function_call"
  * Anthropic          content[] blocks of type "tool_use"
  * Google Gemini      candidates[].content.parts[].functionCall{name, args}
  * a list of any of the above, or a JSON string / ```json fenced string

Parsing never executes or trusts anything: it only extracts (tool, arguments).
"""
import json

MAX_CALLS = 10
MAX_DEPTH = 8
_ARG_KEYS = ('arguments', 'input', 'args', 'parameters')


def _args(value):
    """Return (arguments_dict_or_None, error_or_None)."""
    if value is None:
        return {}, None
    if isinstance(value, dict):
        return value, None
    if isinstance(value, str):
        if not value.strip():
            return {}, None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None, 'Arguments are not valid JSON'
        if isinstance(parsed, dict):
            return parsed, None
    return None, 'Arguments must be a JSON object'


def _call(fmt, name, raw_args):
    arguments, error = _args(raw_args)
    return {'tool': name if isinstance(name, str) else '', 'arguments': arguments,
            'error': error, 'format': fmt}


def _match(node):
    """If this dict is itself a tool call, return it; else None."""
    fn = node.get('function')
    if isinstance(fn, dict) and 'name' in fn:
        return _call('openai', fn['name'], fn.get('arguments'))
    fc = node.get('function_call')
    if isinstance(fc, dict) and 'name' in fc:
        return _call('openai-legacy', fc['name'], fc.get('arguments'))
    fc = node.get('functionCall')
    if isinstance(fc, dict) and 'name' in fc:
        return _call('gemini', fc['name'], fc.get('args'))
    kind = node.get('type')
    if kind == 'tool_use' and 'name' in node:
        return _call('anthropic', node['name'], node.get('input'))
    if kind == 'function_call' and 'name' in node:
        return _call('openai-responses', node['name'], node.get('arguments'))
    if isinstance(node.get('tool'), str):
        key = next((k for k in _ARG_KEYS if k in node), None)
        return _call('generic', node['tool'], node.get(key) if key else None)
    if isinstance(node.get('name'), str):
        key = next((k for k in _ARG_KEYS if k in node), None)
        if key:
            return _call('generic', node['name'], node[key])
    return None


def _walk(node, out, depth):
    if depth > MAX_DEPTH or len(out) > MAX_CALLS:
        return
    if isinstance(node, dict):
        found = _match(node)
        if found is not None:
            out.append(found)
            return
        for value in node.values():
            _walk(value, out, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _walk(item, out, depth + 1)


def extract_tool_calls(payload):
    """Return a list of {tool, arguments, error, format}. Raises ValueError if none."""
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith('```'):
            lines = text.splitlines()
            if len(lines) < 3 or lines[-1].strip() != '```':
                raise ValueError('Malformed code fence')
            text = '\n'.join(lines[1:-1]).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError('Agent output is not valid JSON') from exc
    if not isinstance(payload, (dict, list)):
        raise ValueError('Agent output must be a JSON object or list')
    calls = []
    _walk(payload, calls, 0)
    if not calls:
        raise ValueError('No tool call found in the agent output')
    if len(calls) > MAX_CALLS:
        raise ValueError(f'Too many tool calls (max {MAX_CALLS})')
    return calls


def coerce_ids(arguments, keys=('ticket_id', 'email_id')):
    """Accept '1042' as 1042 (LLMs often stringify numbers); reject everything odd."""
    if not isinstance(arguments, dict):
        return arguments
    out = dict(arguments)
    for key in keys:
        val = out.get(key)
        if isinstance(val, str) and val.isascii() and val.isdecimal() and len(val) <= 9:
            out[key] = int(val)
    return out


def coerce_ticket_id(arguments):
    return coerce_ids(arguments, ('ticket_id',))
