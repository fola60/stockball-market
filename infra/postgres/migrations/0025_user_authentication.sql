CREATE TABLE auth_credentials (
    account_id uuid PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    CHECK (length(token_hash) = 64)
);

CREATE INDEX user_sessions_account_id_expires_at_idx
    ON user_sessions(account_id, expires_at DESC);

ALTER TABLE cash_ledger_entries
    DROP CONSTRAINT cash_ledger_entries_reason_check;

ALTER TABLE cash_ledger_entries
    ADD CONSTRAINT cash_ledger_entries_reason_check CHECK (
        reason IN (
            'TRADE_BUY_DEBIT',
            'TRADE_SELL_CREDIT',
            'WEEKLY_TOPUP',
            'MONTHLY_TOPUP',
            'OPENING_BALANCE',
            'ADMIN_ADJUSTMENT',
            'REVERSAL'
        )
    );

ALTER TABLE cash_ledger_entries
    DROP CONSTRAINT cash_ledger_entries_amount_delta_check;

ALTER TABLE cash_ledger_entries
    ADD CONSTRAINT cash_ledger_entries_amount_delta_check CHECK (amount_delta <> 0),
    ADD CONSTRAINT cash_ledger_entries_buy_debit_check CHECK (
        (reason = 'TRADE_BUY_DEBIT' AND amount_delta < 0)
        OR (reason <> 'TRADE_BUY_DEBIT')
    );

ALTER TABLE cash_ledger_entries
    DROP CONSTRAINT cash_ledger_entries_check;

ALTER TABLE cash_ledger_entries
    ADD CONSTRAINT cash_ledger_entries_check CHECK (
        (
            reason IN (
                'TRADE_SELL_CREDIT',
                'WEEKLY_TOPUP',
                'MONTHLY_TOPUP',
                'OPENING_BALANCE'
            )
            AND amount_delta > 0
        )
        OR reason NOT IN (
            'TRADE_SELL_CREDIT',
            'WEEKLY_TOPUP',
            'MONTHLY_TOPUP',
            'OPENING_BALANCE'
        )
    );
