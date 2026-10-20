import json
from pathlib import Path
from security.policy_engine import Actor
from security.executor import execute
from tools.ticket_tools import SQLiteTicketStore

store = SQLiteTicketStore()
store.seed(json.loads((Path(__file__).parent / 'fixtures' / 'tickets.json').read_text()))
reader = Actor('demo-user', 10, 'reader')
for name, args in [('get_ticket', {'ticket_id':1043}), ('delete_ticket', {'ticket_id':1042})]:
    result = execute(reader, name, args, store)
    print(f'{name}: allowed={result.allowed}, reason={result.reason}')
print('Ticket 1042 still exists:', store.get_ticket(1042) is not None)
