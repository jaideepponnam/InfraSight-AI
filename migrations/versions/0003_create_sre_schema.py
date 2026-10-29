"""Add isolated SRE incident tables; preserve all existing telemetry and views.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Frozen PostgreSQL DDL, independent of mutable application model definitions.
SQL = r"""
CREATE TABLE sre_services (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    service_key TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_sre_services PRIMARY KEY (id),
    CONSTRAINT uq_sre_services_key UNIQUE (service_key),
    CONSTRAINT ck_sre_services_approved_service CHECK (service_key =
'controlled-application-dependency')
);

CREATE TABLE sre_demo_runs (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    service_id UUID NOT NULL,
    scenario TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT DEFAULT 'ACTIVE' NOT NULL,
    phase TEXT DEFAULT 'CREATED' NOT NULL,
    probe_token_hash TEXT NOT NULL,
    fault_enabled BOOLEAN DEFAULT false NOT NULL,
    fault_expires_at TIMESTAMP WITH TIME ZONE,
    fault_cleared_at TIMESTAMP WITH TIME ZONE,
    deadline_at TIMESTAMP WITH TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITH TIME ZONE,
    error_code TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_sre_demo_runs PRIMARY KEY (id),
    CONSTRAINT ck_sre_demo_runs_approved_scenario CHECK (scenario = 'http-503'),
    CONSTRAINT ck_sre_demo_runs_valid_status CHECK (status IN
('ACTIVE','SUCCEEDED','FAILED','INTERRUPTED')),
    CONSTRAINT ck_sre_demo_runs_valid_phase CHECK (phase IN
('CREATED','BASELINE','FAULT','DETECTED','RECOVERY','COMPLETE')),
    CONSTRAINT ck_sre_demo_runs_deadline_order CHECK (deadline_at > created_at),
    CONSTRAINT ck_sre_demo_runs_fault_deadline CHECK (fault_expires_at IS NULL OR
fault_expires_at <= deadline_at),
    CONSTRAINT ck_sre_demo_runs_terminal_finished CHECK (status = 'ACTIVE' OR finished_at IS NOT
NULL),
    CONSTRAINT uq_sre_demo_runs_request UNIQUE (service_id, idempotency_key),
    CONSTRAINT fk_sre_demo_runs_service_id_sre_services FOREIGN KEY(service_id) REFERENCES
sre_services (id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ix_sre_demo_runs_active_service ON sre_demo_runs (service_id) WHERE status =
'ACTIVE';

CREATE INDEX ix_sre_demo_runs_created_at ON sre_demo_runs (created_at);

CREATE TABLE sre_incidents (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    service_id UUID NOT NULL,
    run_id UUID NOT NULL,
    fingerprint TEXT NOT NULL,
    title TEXT NOT NULL,
    severity TEXT DEFAULT 'SEV3' NOT NULL,
    state TEXT DEFAULT 'DETECTED' NOT NULL,
    policy_version TEXT NOT NULL,
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    version INTEGER DEFAULT 1 NOT NULL,
    CONSTRAINT pk_sre_incidents PRIMARY KEY (id),
    CONSTRAINT ck_sre_incidents_valid_state CHECK (state IN
('DETECTED','ACKNOWLEDGED','INVESTIGATING','MITIGATING','VERIFYING','RESOLVED')),
    CONSTRAINT ck_sre_incidents_valid_severity CHECK (severity = 'SEV3'),
    CONSTRAINT ck_sre_incidents_resolved_timestamp CHECK (state <> 'RESOLVED' OR resolved_at IS
NOT NULL),
    CONSTRAINT ck_sre_incidents_resolved_order CHECK (resolved_at IS NULL OR resolved_at >=
detected_at),
    CONSTRAINT fk_sre_incidents_service_id_sre_services FOREIGN KEY(service_id) REFERENCES
sre_services (id) ON DELETE RESTRICT,
    CONSTRAINT fk_sre_incidents_run_id_sre_demo_runs FOREIGN KEY(run_id) REFERENCES
sre_demo_runs (id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ix_sre_incidents_active_fingerprint ON sre_incidents (fingerprint) WHERE
state <> 'RESOLVED';

CREATE INDEX ix_sre_incidents_detected_at ON sre_incidents (detected_at);

CREATE TABLE sre_probe_results (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    run_id UUID NOT NULL,
    phase TEXT NOT NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    duration_ms NUMERIC(12, 3) NOT NULL,
    http_status INTEGER,
    outcome TEXT NOT NULL,
    target_request_id UUID,
    request_id UUID NOT NULL,
    evidence JSONB NOT NULL,
    CONSTRAINT pk_sre_probe_results PRIMARY KEY (id),
    CONSTRAINT ck_sre_probe_results_valid_phase CHECK (phase IN
('BASELINE','DETECTION','VERIFICATION')),
    CONSTRAINT ck_sre_probe_results_valid_outcome CHECK (outcome IN
('HEALTHY','HTTP_503','UNEXPECTED_HTTP','TIMEOUT','TRANSPORT_ERROR','INVALID_RESPONSE')),
    CONSTRAINT ck_sre_probe_results_positive_duration CHECK (duration_ms >= 0),
    CONSTRAINT ck_sre_probe_results_valid_http CHECK (http_status IS NULL OR http_status BETWEEN
100 AND 599),
    CONSTRAINT fk_sre_probe_results_run_id_sre_demo_runs FOREIGN KEY(run_id) REFERENCES
sre_demo_runs (id) ON DELETE RESTRICT
);

CREATE INDEX ix_sre_probe_results_run_observed ON sre_probe_results (run_id, observed_at);

CREATE TABLE sre_incident_events (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    incident_id UUID NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    request_id UUID NOT NULL,
    evidence JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_sre_incident_events PRIMARY KEY (id),
    CONSTRAINT uq_sre_incident_events_sequence UNIQUE (incident_id, sequence),
    CONSTRAINT ck_sre_incident_events_positive_sequence CHECK (sequence > 0),
    CONSTRAINT ck_sre_incident_events_valid_actor CHECK (actor IN
('admin-key','admin-exercise-runner','system')),
    CONSTRAINT fk_sre_incident_events_incident_id_sre_incidents FOREIGN KEY(incident_id)
REFERENCES sre_incidents (id) ON DELETE RESTRICT
);

CREATE TABLE sre_recovery_attempts (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    incident_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT DEFAULT 'RUNNING' NOT NULL,
    error_code TEXT,
    action_applied BOOLEAN DEFAULT false NOT NULL,
    evidence JSONB NOT NULL,
    request_id UUID NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    finished_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_sre_recovery_attempts PRIMARY KEY (id),
    CONSTRAINT uq_sre_recovery_attempts_request UNIQUE (incident_id, idempotency_key),
    CONSTRAINT ck_sre_recovery_attempts_approved_action CHECK (action =
'clear-controlled-dependency-fault'),
    CONSTRAINT ck_sre_recovery_attempts_valid_status CHECK (status IN
('RUNNING','SUCCEEDED','FAILED','INTERRUPTED')),
    CONSTRAINT ck_sre_recovery_attempts_terminal_finished CHECK (status = 'RUNNING' OR
finished_at IS NOT NULL),
    CONSTRAINT fk_sre_recovery_attempts_incident_id_sre_incidents FOREIGN KEY(incident_id)
REFERENCES sre_incidents (id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ix_sre_recovery_attempts_active_incident ON sre_recovery_attempts
(incident_id) WHERE status = 'RUNNING';
"""


def upgrade():
    for statement in SQL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    op.drop_table("sre_recovery_attempts")
    op.drop_table("sre_incident_events")
    op.drop_table("sre_probe_results")
    op.drop_table("sre_incidents")
    op.drop_table("sre_demo_runs")
    op.drop_table("sre_services")
