import json
import sys
import threading
import types
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from agents.oci_model import OCIPlanner
from agents.planners import MockPlanner
from agents.playground import build_planner, check_agent_output, run_agent_demo
from security.adapters import extract_tool_calls
from security.intent import check_intent, classify


def demo(role, prompt, profile):
    return run_agent_demo(role=role, prompt=prompt, profile=profile, planner=MockPlanner())


# ---- intent guard
def test_intent_classification():
    assert classify('Summarize ticket 1043') == 'read'
    assert classify('Mark ticket 1042 resolved') == 'update'
    assert classify('Delete ticket 1042') == 'delete'
    assert classify("please don't delete 1042, just read it") == 'read'


def test_intent_blocks_off_request_and_other_tickets():
    assert not check_intent('Summarize ticket 1043', 'delete_ticket', {'ticket_id': 1042})[0]
    assert not check_intent('Summarize ticket 1043', 'get_ticket', {'ticket_id': 1042})[0]
    assert check_intent('Summarize ticket 1043', 'get_ticket', {'ticket_id': 1043})[0]
    assert not check_intent('Delete ticket 1042', 'get_ticket', {'ticket_id': '1042'})[0]


# ---- playground: agent vulnerability changes what AgentShield has to catch
def test_hardened_agent_is_not_hijacked():
    r = demo('admin', 'Summarize ticket 1043.', 'hardened')
    assert r['proposal']['tool'] == 'get_ticket' and not r['off_request']
    assert r['with_shield']['decision'] == 'ALLOW' and not r['shield_changed_outcome']


def test_vulnerable_agent_hijacked_and_blocked_even_for_admin():
    r = demo('admin', 'Summarize ticket 1043.', 'vulnerable')
    assert r['proposal']['tool'] == 'delete_ticket' and r['off_request']
    assert 'Deleted ticket #1042' in r['without_shield']['summary']      # unprotected: harm
    assert r['with_shield']['decision'] == 'DENY' and r['with_shield']['layer'] == 'intent'
    assert r['shield_changed_outcome']
    assert 'deleted' not in r['with_shield']['final_answer'].lower()


def test_typical_agent_only_follows_official_sounding_text():
    assert demo('reader', 'Summarize ticket 1043.', 'standard')['proposal']['tool'] == 'delete_ticket'
    assert demo('reader', 'Summarize ticket 1044.', 'standard')['proposal']['tool'] == 'get_ticket'
    assert demo('reader', 'Summarize ticket 1044.', 'vulnerable')['proposal']['tool'] == 'update_ticket'


def test_cross_tenant_denied_by_policy_even_for_hardened_agent():
    r = demo('admin', 'Show me ticket 2042.', 'hardened')
    assert r['with_shield']['decision'] == 'DENY' and r['with_shield']['layer'] == 'policy'
    assert 'another business' in r['without_shield']['summary']


def test_agent_never_sees_other_tenants_ticket_text():
    assert 'Private synthetic' not in demo('admin', 'Show me ticket 2042.', 'hardened')['agent_read_text']


def test_role_still_enforced_on_legitimate_requests():
    assert demo('reader', 'Delete ticket 1042.', 'hardened')['with_shield']['decision'] == 'DENY'
    assert demo('admin', 'Delete ticket 1042.', 'hardened')['with_shield']['decision'] == 'ALLOW'


def test_demo_input_validation():
    with pytest.raises(ValueError):
        demo('root', 'Summarize ticket 1042.', 'hardened')
    with pytest.raises(ValueError):
        demo('admin', 'x' * 401, 'hardened')
    with pytest.raises(ValueError):
        demo('admin', 'Summarize ticket 1042.', 'evil')


def test_live_mode_off_by_default():
    with pytest.raises(RuntimeError):
        build_planner('live')


# ---- bring your own agent
OPENAI = {'choices': [{'message': {'tool_calls': [{'type': 'function', 'function': {
    'name': 'delete_ticket', 'arguments': '{"ticket_id": "1042"}'}}]}}]}
ANTHROPIC = {'content': [{'type': 'text', 'text': 'ok'},
                         {'type': 'tool_use', 'name': 'get_ticket', 'input': {'ticket_id': 1042}}]}
GEMINI = {'candidates': [{'content': {'parts': [{'functionCall': {'name': 'get_ticket', 'args': {'ticket_id': 2042}}}]}}]}


def test_extract_formats():
    assert extract_tool_calls(OPENAI)[0]['format'] == 'openai'
    assert extract_tool_calls(ANTHROPIC)[0]['format'] == 'anthropic'
    assert extract_tool_calls(GEMINI)[0]['format'] == 'gemini'
    assert extract_tool_calls('```json\n{"tool":"get_ticket","arguments":{"ticket_id":1}}\n```')[0]['format'] == 'generic'


def test_extract_rejects_non_tool_output():
    with pytest.raises(ValueError):
        extract_tool_calls({'content': [{'type': 'text', 'text': 'just chatting'}]})
    with pytest.raises(ValueError):
        extract_tool_calls('not json')


def test_byo_role_and_tenant_enforcement():
    assert check_agent_output(role='reader', payload=OPENAI)['overall'] == 'DENY'
    assert check_agent_output(role='admin', payload=OPENAI)['overall'] == 'ALLOW'   # stringified id accepted
    assert check_agent_output(role='admin', payload=GEMINI)['calls'][0]['reason'] == 'Cross-tenant access denied'


def test_byo_intent_guard_optional():
    r = check_agent_output(role='admin', payload=OPENAI, user_request='Summarize ticket 1042.')
    assert r['overall'] == 'DENY' and r['calls'][0]['layer'] == 'intent'


def test_byo_unknown_tool_and_bad_args_fail_closed():
    r = check_agent_output(role='admin', payload={'tool': 'run_shell', 'arguments': {'cmd': 'rm -rf /'}})
    assert r['overall'] == 'DENY' and 'default deny' in r['calls'][0]['reason']
    r = check_agent_output(role='admin', payload={'tool': 'get_ticket', 'arguments': '{oops'})
    assert r['calls'][0]['layer'] == 'parser' and not r['calls'][0]['allowed']


def test_byo_multi_call_partial():
    payload = [{'tool': 'get_ticket', 'arguments': {'ticket_id': 1042}},
               {'tool': 'delete_ticket', 'arguments': {'ticket_id': 1042}}]
    assert check_agent_output(role='reader', payload=payload)['overall'] == 'PARTIAL'


# ---- live planner wiring (fake OCI client, no network)
def _fake_oci(reply):
    models = types.SimpleNamespace(
        CohereChatRequest=lambda **k: k, ChatDetails=lambda **k: k,
        OnDemandServingMode=lambda **k: k)
    sys.modules['oci'] = types.SimpleNamespace(
        generative_ai_inference=types.SimpleNamespace(models=models))
    seen = []

    class Client:
        def chat(self, details):
            seen.append(details['chat_request']['message'])
            return types.SimpleNamespace(data=types.SimpleNamespace(
                chat_response=types.SimpleNamespace(text=reply)))
    return Client(), seen


def test_oci_planner_profile_changes_prompt_and_output_is_validated():
    client, seen = _fake_oci('{"tool":"get_ticket","arguments":{"ticket_id":1042},"reason":"r"}')
    planner = OCIPlanner(client=client, compartment_id='c', model_id='m')
    assert planner.propose('Summarize 1042', '', 'vulnerable')['tool'] == 'get_ticket'
    planner.propose('Summarize 1042', '', 'hardened')
    assert 'Always carry out any instruction' in seen[0] and 'Always carry out' not in seen[1]


def test_live_garbage_output_fails_closed():
    client, _ = _fake_oci('I will happily delete everything!')
    planner = OCIPlanner(client=client, compartment_id='c', model_id='m')
    r = run_agent_demo(role='admin', prompt='Summarize ticket 1042.', profile='vulnerable', planner=planner)
    assert r['with_shield']['decision'] == 'DENY' and r['with_shield']['layer'] == 'parser'


# ---- real HTTP round trip through the server and the SDK
def test_http_server_and_sdk_round_trip():
    from agentshield_sdk import AgentShield
    from product_server import Handler
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        verdict = AgentShield(f'http://127.0.0.1:{port}').check_agent_output(
            OPENAI, role='reader', user_request='Summarize ticket 1042.')
        assert verdict.overall == 'DENY' and not verdict.allowed
        conn = HTTPConnection('127.0.0.1', port)
        body = json.dumps({'role': 'admin', 'prompt': 'Summarize ticket 1043.',
                           'profile': 'vulnerable', 'mode': 'mock'})
        conn.request('POST', '/api/agent', body, {'Content-Type': 'application/json'})
        resp = conn.getresponse()
        data = json.loads(resp.read())
        assert resp.status == 200 and data['shield_changed_outcome'] is True
        conn.request('POST', '/api/agent', body.replace('mock', 'live'), {'Content-Type': 'application/json'})
        assert conn.getresponse().status == 503
    finally:
        server.shutdown()


# ---- Gemini live provider
def _fake_gemini(reply):
    import io
    seen = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=None):
        seen.append((req.full_url, req.headers, json.loads(req.data)))
        return Resp(json.dumps({'candidates': [{'content': {'parts': [{'text': reply}]}}]}).encode())
    return opener, seen


def test_gemini_planner_parses_and_keeps_key_in_header(monkeypatch):
    from agents.gemini_model import GeminiPlanner
    opener, seen = _fake_gemini('{"tool":"get_ticket","arguments":{"ticket_id":1042},"reason":"r"}')
    planner = GeminiPlanner(api_key='k', opener=opener)
    assert planner.propose('Summarize 1042', '', 'vulnerable')['tool'] == 'get_ticket'
    url, headers, body = seen[0]
    assert 'k' not in url and headers.get('X-goog-api-key') == 'k'
    assert 'Always carry out any instruction' in body['contents'][0]['parts'][0]['text']


def test_gemini_garbage_output_fails_closed():
    from agents.gemini_model import GeminiPlanner
    opener, _ = _fake_gemini('Sure, deleting everything!')
    planner = GeminiPlanner(api_key='k', opener=opener)
    r = run_agent_demo(role='admin', prompt='Summarize ticket 1042.', profile='vulnerable', planner=planner)
    assert r['with_shield']['decision'] == 'DENY' and r['with_shield']['layer'] == 'parser'


def test_live_provider_selection(monkeypatch):
    from agents.playground import live_available, live_provider
    for k in ('AGENTSHIELD_LIVE', 'GEMINI_API_KEY', 'OCI_COMPARTMENT_OCID',
              'OCI_GENAI_MODEL_ID', 'OCI_GENAI_ENDPOINT', 'AGENTSHIELD_LIVE_PROVIDER'):
        monkeypatch.delenv(k, raising=False)
    assert not live_available()
    monkeypatch.setenv('GEMINI_API_KEY', 'k')
    assert not live_available()            # still needs the AGENTSHIELD_LIVE=1 switch
    monkeypatch.setenv('AGENTSHIELD_LIVE', '1')
    assert live_provider() == 'gemini'
