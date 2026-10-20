from agentshield_sdk import AgentShield

shield = AgentShield()

# Offline: trusted application supplies authenticated role and resource tenant.
check = shield.check_local(role='reader', actor_tenant=10, resource_tenant=10, tool='delete_ticket')
print('Offline policy:', check.allowed, check.reason)

# Start product_server.py first. This checks only synthetic sample tickets.
check = shield.check_demo(role='reader', action='delete', ticket_id=1042)
print('Synthetic public demo:', check.allowed, check.reason)
