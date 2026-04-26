CREATE TABLE worker_topup_policies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id uuid NOT NULL REFERENCES accounts(id),
    portfolio_id uuid NOT NULL REFERENCES portfolios(id),
    cadence text NOT NULL,
    amount numeric(20, 4) NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (account_id, portfolio_id, cadence),
    CHECK (cadence IN ('WEEKLY', 'MONTHLY')),
    CHECK (amount > 0)
);

CREATE INDEX worker_topup_policies_enabled_cadence_idx
    ON worker_topup_policies(enabled, cadence);

CREATE TABLE worker_topup_records (
    request_id text PRIMARY KEY,
    account_id uuid NOT NULL REFERENCES accounts(id),
    portfolio_id uuid NOT NULL REFERENCES portfolios(id),
    cadence text NOT NULL,
    amount numeric(20, 4) NOT NULL,
    window_start timestamptz NOT NULL,
    window_end_exclusive timestamptz NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    ledger_entry_id uuid REFERENCES cash_ledger_entries(id),
    applied_at timestamptz,
    retryable boolean NOT NULL DEFAULT false,
    failure_code text,
    failure_message text,
    CHECK (cadence IN ('WEEKLY', 'MONTHLY')),
    CHECK (amount > 0),
    CHECK (status IN ('PLANNED', 'APPLIED', 'FAILED')),
    CHECK (window_end_exclusive > window_start)
);

CREATE INDEX worker_topup_records_window_idx
    ON worker_topup_records(cadence, window_start DESC);

CREATE INDEX worker_topup_records_account_idx
    ON worker_topup_records(account_id, window_start DESC);
