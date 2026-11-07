CREATE TABLE blind_market_rounds (
    day date PRIMARY KEY,
    week_start date NOT NULL,
    closes_at timestamptz NOT NULL,
    weekly_topup numeric(20, 4) NOT NULL CHECK (weekly_topup > 0),
    cards jsonb NOT NULL CHECK (jsonb_array_length(cards) = 3),
    answers jsonb NOT NULL CHECK (jsonb_array_length(answers) = 3)
);

CREATE INDEX blind_market_rounds_week_idx ON blind_market_rounds (week_start, day);

CREATE TABLE blind_market_entries (
    account_id uuid NOT NULL REFERENCES accounts(id),
    day date NOT NULL REFERENCES blind_market_rounds(day),
    guesses jsonb NOT NULL CHECK (jsonb_array_length(guesses) = 3),
    score smallint NOT NULL CHECK (score BETWEEN 0 AND 6),
    reward numeric(20, 4) NOT NULL CHECK (reward >= 0),
    claimed_at timestamptz,
    PRIMARY KEY (account_id, day)
);
