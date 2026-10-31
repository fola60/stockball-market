-- Rule index funds: funds whose membership comes from a rule over the whole league, such as the
-- 20 most valuable players or every club's first-choice keeper, rather than one club's squad.
-- The worker owns the rules and re-evaluates them; the rule is stored with the fund so its
-- page can say what the fund follows.

ALTER TABLE index_funds
    DROP CONSTRAINT index_funds_index_kind_check,
    ADD CONSTRAINT index_funds_index_kind_check CHECK (index_kind IN ('TEAM', 'RULE')),
    -- A stable name for the rule, so a fund keeps its rule when its symbol or name changes.
    ADD COLUMN rule_key text,
    -- Groups funds on the site, such as "Positions" or "Performance".
    ADD COLUMN category text,
    ADD COLUMN description text,
    ADD COLUMN rule jsonb,
    -- EQUAL_SHARES: every member holds the same shares per unit, so pricier players weigh
    -- more. EQUAL_VALUE: every member holds the same value per unit at each rebalance.
    ADD COLUMN weighting text NOT NULL DEFAULT 'EQUAL_SHARES'
        CHECK (weighting IN ('EQUAL_SHARES', 'EQUAL_VALUE')),
    ADD CONSTRAINT index_funds_rule_key_check CHECK (index_kind <> 'RULE' OR rule_key IS NOT NULL);

CREATE UNIQUE INDEX index_funds_rule_key_key
    ON index_funds (rule_key)
    WHERE index_kind = 'RULE';

UPDATE index_funds SET category = 'Clubs' WHERE index_kind = 'TEAM';
