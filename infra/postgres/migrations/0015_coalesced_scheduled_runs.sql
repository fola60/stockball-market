ALTER TABLE job_runs
    DROP CONSTRAINT dev_operation_runs_status_check;

ALTER TABLE job_runs
    ADD CONSTRAINT job_runs_status_check CHECK (
        status IN (
            'QUEUED',
            'RUNNING',
            'RETRYING',
            'SUCCEEDED',
            'FAILED',
            'SUPERSEDED'
        )
    );

WITH pending_runs AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY schedule_name
            ORDER BY enqueued_at DESC, id DESC
        ) AS pending_position,
        first_value(id) OVER (
            PARTITION BY schedule_name
            ORDER BY enqueued_at DESC, id DESC
        ) AS newest_run_id
    FROM job_runs
    WHERE source = 'SCHEDULED'
      AND status IN ('QUEUED', 'RETRYING')
      AND schedule_name IN (
          'synthetic-trader-ticks',
          'daily-player-stats',
          'bet365-odds',
          'bet365-live-odds',
          'twitter-injury-intelligence'
      )
)
UPDATE job_runs AS run
SET status = 'SUPERSEDED',
    error_message = 'Superseded by a newer scheduled run before execution',
    metrics = run.metrics || jsonb_build_object(
        'superseded_by_run_id', pending.newest_run_id::text,
        'superseded_reason', 'newer_scheduled_run'
    ),
    completed_at = now(),
    updated_at = now()
FROM pending_runs AS pending
WHERE run.id = pending.id
  AND pending.pending_position > 1;

CREATE INDEX job_runs_pending_schedule_idx
    ON job_runs (schedule_name, enqueued_at DESC)
    WHERE source = 'SCHEDULED'
      AND status IN ('QUEUED', 'RETRYING');
