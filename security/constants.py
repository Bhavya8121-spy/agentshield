"""Single source of truth for values shared by the model parser and the executor.

Keeping these in one place prevents the two validation layers from drifting
apart (e.g. the parser accepting a status the executor rejects).
"""

# Must match the CHECK constraint in sql/schema.sql (ck_ticket_status).
VALID_STATUSES = frozenset({'OPEN', 'IN_PROGRESS', 'RESOLVED'})

TICKET_TOOLS = frozenset({'get_ticket', 'update_ticket', 'delete_ticket'})

# ---- email assistant domain
EMAIL_TOOLS = frozenset({'read_email', 'send_email', 'delete_email'})
ORG_DOMAIN = 'acme.com'   # demo organization; sends outside it need human approval
