import pytest
from paste_check import check_pasted_proposal


def test_reader_can_read():
    result = check_pasted_proposal('reader', '{"tool":"get_ticket","arguments":{"ticket_id":"1042"}}')
    assert result['decision'] == 'ALLOW'


def test_reader_cannot_delete():
    result = check_pasted_proposal('reader', '```json\n{"tool":"delete_ticket","arguments":{"ticket_id":1042}}\n```')
    assert result['decision'] == 'DENY'


def test_tenant_isolation():
    result = check_pasted_proposal('admin', '{"tool":"get_ticket","arguments":{"ticket_id":2042}}')
    assert result['decision'] == 'DENY'


def test_unknown_tool_denied():
    result = check_pasted_proposal('admin', '{"tool":"run_shell","arguments":{}}')
    assert result['decision'] == 'DENY'


@pytest.mark.parametrize('proposal', [
    'not json',
    '{"tool":"delete_ticket","arguments":{"ticket_id":9999}}',
    '{"tool":"get_ticket","arguments":{"ticket_id":true}}',
    '{"tool":"get_ticket","arguments":{"ticket_id":1042},"extra":1}',
    '{"tool":"update_ticket","arguments":{"ticket_id":1042,"status":"CLOSED"}}',
])
def test_invalid_proposals(proposal):
    with pytest.raises(ValueError):
        check_pasted_proposal('reader', proposal)


def test_isolated_mutation():
    assert check_pasted_proposal('admin', '{"tool":"delete_ticket","arguments":{"ticket_id":1042}}')['allowed']
    assert check_pasted_proposal('reader', '{"tool":"get_ticket","arguments":{"ticket_id":1042}}')['allowed']
