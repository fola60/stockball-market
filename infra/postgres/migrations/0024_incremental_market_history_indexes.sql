-- Support the worker's rolling market-history cache, which refreshes all
-- instruments by a narrow time window and orders equal timestamps by UUID.

CREATE INDEX price_snapshots_captured_at_id_idx
    ON price_snapshots(captured_at, id);

CREATE INDEX trades_executed_at_id_idx
    ON trades(executed_at, id);
