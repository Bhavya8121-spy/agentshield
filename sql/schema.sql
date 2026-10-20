-- Run in your dedicated application schema (Oracle Autonomous AI Database).
CREATE TABLE support_tickets (
    ticket_id NUMBER PRIMARY KEY,
    tenant_id NUMBER NOT NULL,
    customer_id NUMBER NOT NULL,
    title VARCHAR2(255) NOT NULL,
    description CLOB,
    status VARCHAR2(30) DEFAULT 'OPEN' NOT NULL,
    CONSTRAINT ck_ticket_status CHECK (status IN ('OPEN','IN_PROGRESS','RESOLVED'))
);
CREATE INDEX idx_tickets_tenant ON support_tickets(tenant_id, ticket_id);
CREATE TABLE agent_runs (
    run_id VARCHAR2(36) PRIMARY KEY,
    scenario_id VARCHAR2(100) NOT NULL,
    agent_mode VARCHAR2(20) NOT NULL,
    started_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
    completed_at TIMESTAMP
);
CREATE TABLE tool_traces (
    trace_id VARCHAR2(36) PRIMARY KEY,
    run_id VARCHAR2(36) NOT NULL REFERENCES agent_runs(run_id),
    sequence_no NUMBER NOT NULL,
    tool_name VARCHAR2(100) NOT NULL,
    arguments_json CLOB CHECK (arguments_json IS JSON),
    policy_decision VARCHAR2(20) NOT NULL,
    decision_reason VARCHAR2(500) NOT NULL,
    execution_status VARCHAR2(30) NOT NULL,
    latency_ms NUMBER,
    created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT ck_policy_decision CHECK (policy_decision IN ('ALLOW','DENY')),
    CONSTRAINT uq_run_sequence UNIQUE (run_id, sequence_no)
);
