import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError

import pytest
from agentshield_sdk import AgentShield, AgentShieldError
from product_server import Handler


def test_offline_authorization():
    s = AgentShield()
    assert s.check_local(role='reader', actor_tenant=10, resource_tenant=10, tool='get_ticket').allowed
    assert not s.check_local(role='reader', actor_tenant=10, resource_tenant=10, tool='delete_ticket').allowed
    assert not s.check_local(role='admin', actor_tenant=10, resource_tenant=20, tool='get_ticket').allowed
    assert not s.check_local(role='admin', actor_tenant=True, resource_tenant=1, tool='get_ticket').allowed
    assert not s.check_local(role='unknown', actor_tenant=10, resource_tenant=10, tool='get_ticket').allowed


def test_remote_requires_https():
    with pytest.raises(ValueError):
        AgentShield('http://example.com')


def test_real_demo_http():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        shield = AgentShield(f'http://127.0.0.1:{server.server_port}')
        blocked = shield.check_demo(role='reader', action='delete', ticket_id=1042)
        assert not blocked.allowed and blocked.demo_only
        allowed = shield.check_demo(role='reader', action='view', ticket_id=1042)
        assert allowed.allowed
        other = shield.check_demo(role='admin', action='view', ticket_id=2042)
        assert not other.allowed
        pasted = shield.check_pasted_demo(role='reader', proposal=json.dumps({'tool':'delete_ticket','arguments':{'ticket_id':1042}}))
        assert not pasted.allowed
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
