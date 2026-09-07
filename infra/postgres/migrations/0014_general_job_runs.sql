ALTER TABLE dev_operation_runs RENAME TO job_runs;

ALTER TABLE job_runs
    ADD COLUMN source text NOT NULL DEFAULT 'MANUAL'
        CHECK (source IN ('MANUAL', 'SCHEDULED')),
    ADD COLUMN schedule_name text,
    ADD COLUMN schedule_window_key text,
    ADD CONSTRAINT job_runs_schedule_metadata_check CHECK (
        (source = 'MANUAL' AND schedule_name IS NULL AND schedule_window_key IS NULL)
        OR
        (source = 'SCHEDULED' AND schedule_name IS NOT NULL AND schedule_window_key IS NOT NULL)
    );

ALTER INDEX dev_operation_runs_enqueued_at_idx
    RENAME TO job_runs_enqueued_at_idx;
ALTER INDEX dev_operation_runs_status_idx
    RENAME TO job_runs_status_idx;

CREATE UNIQUE INDEX job_runs_schedule_window_idx
    ON job_runs (schedule_name, schedule_window_key)
    WHERE source = 'SCHEDULED';
