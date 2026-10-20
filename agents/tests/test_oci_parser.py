import pytest

from agents.oci_model import parse_proposal


def test_markdown_json_proposal():
    raw = '''```json
{"tool":"get_ticket","arguments":{"ticket_id":"1042"},"reason":"Read ticket"}
```'''

    result = parse_proposal(raw)

    assert result["tool"] == "get_ticket"
    assert result["arguments"]["ticket_id"] == 1042


def test_unknown_tool_rejected():
    raw = (
        '{"tool":"execute_shell",'
        '"arguments":{},'
        '"reason":"Run a command"}'
    )

    with pytest.raises(ValueError):
        parse_proposal(raw)


def test_empty_response_rejected():
    with pytest.raises(ValueError):
        parse_proposal("")


def test_invalid_ticket_id_rejected():
    raw = (
        '{"tool":"get_ticket",'
        '"arguments":{"ticket_id":"1042 OR 1=1"},'
        '"reason":"Read ticket"}'
    )

    with pytest.raises(ValueError):
        parse_proposal(raw)