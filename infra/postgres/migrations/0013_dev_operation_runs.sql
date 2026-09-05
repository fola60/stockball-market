CREATE TABLE dev_operation_runs (
    id uuid PRIMARY KEY,
    operation_type text NOT NULL,
    job_type text NOT NULL,
    status text NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'RETRYING', 'SUCCEEDED', 'FAILED')),
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    attempt integer NOT NULL DEFAULT 0,
    successful_items bigint NOT NULL DEFAULT 0,
    skipped_items bigint NOT NULL DEFAULT 0,
    failed_items bigint NOT NULL DEFAULT 0,
    retryable_failures bigint NOT NULL DEFAULT 0,
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_message text,
    enqueued_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX dev_operation_runs_enqueued_at_idx
    ON dev_operation_runs (enqueued_at DESC);

CREATE INDEX dev_operation_runs_status_idx
    ON dev_operation_runs (status, enqueued_at DESC);
