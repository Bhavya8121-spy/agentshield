import json
from pathlib import Path
import pytest
from security.policy_engine import Actor, authorize
from security.executor import execute
from tools.ticket_tools import SQLiteTicketStore

@pytest.fixture
def store():
    db = SQLiteTicketStore()
    db.seed(json.loads((Path(__file__).resolve().parents[1] / 'fixtures' / 'tickets.json').read_text()))
    yield db
    db.connection.close()

READER = Actor('alice', 10, 'reader')
EDITOR = Actor('bob', 10, 'editor')
ADMIN = Actor('carol', 10, 'admin')
OTHER = Actor('eve', 20, 'admin')

@pytest.mark.parametrize('actor,tool,tenant,expected', [
    (READER,'get_ticket',10,True), (READER,'update_ticket',10,False),
    (READER,'delete_ticket',10,False), (EDITOR,'update_ticket',10,True),
    (EDITOR,'delete_ticket',10,False), (ADMIN,'delete_ticket',10,True),
    (ADMIN,'delete_ticket',20,False), (Actor('x',10,'unknown'),'get_ticket',10,False),
    (ADMIN,'nonexistent',10,False),
])
def test_policy(actor, tool, tenant, expected):
    assert authorize(actor,tool,tenant).allowed is expected

def test_reader_can_read(store):
    result = execute(READER,'get_ticket',{'ticket_id':1042},store)
    assert result.allowed and result.result['ticket_id'] == 1042

def test_reader_cannot_mutate(store):
    result = execute(READER,'delete_ticket',{'ticket_id':1042},store)
    assert not result.allowed and store.get_ticket(1042) is not None

def test_cross_tenant_admin_blocked(store):
    result = execute(OTHER,'delete_ticket',{'ticket_id':1042},store)
    assert not result.allowed and store.get_ticket(1042) is not None

def test_editor_updates(store):
    result = execute(EDITOR,'update_ticket',{'ticket_id':1042,'status':'RESOLVED'},store)
    assert result.allowed and store.get_ticket(1042)['status'] == 'RESOLVED'

def test_editor_cannot_delete(store):
    assert not execute(EDITOR,'delete_ticket',{'ticket_id':1042},store).allowed

def test_admin_deletes(store):
    assert execute(ADMIN,'delete_ticket',{'ticket_id':1042},store).allowed
    assert store.get_ticket(1042) is None

def test_malformed_arguments_blocked(store):
    for args in ({'ticket_id':'1042'}, {'ticket_id':1042,'tenant_id':10}, {'ticket_id':-1}, {'ticket_id':True}, []):
        assert not execute(ADMIN,'delete_ticket',args,store).allowed
    assert store.get_ticket(1042) is not None

def test_invalid_status_blocked(store):
    assert not execute(EDITOR,'update_ticket',{'ticket_id':1042,'status':'HACKED'},store).allowed

def test_unknown_tool_blocked(store):
    assert not execute(ADMIN,'run_shell',{'command':'rm -rf /'},store).allowed

def test_injection_is_data_not_instruction(store):
    ticket = execute(READER,'get_ticket',{'ticket_id':1043},store)
    assert ticket.allowed and 'delete ticket 1042' in ticket.result['description']
    assert store.get_ticket(1042) is not None

def test_nonexistent_ticket_blocked(store):
    assert not execute(ADMIN,'delete_ticket',{'ticket_id':9999},store).allowed
