CREATE TABLE runtime_settings (
    setting_key text PRIMARY KEY,
    value jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL,
    reason text NOT NULL,
    CHECK (jsonb_typeof(value) IN ('number', 'boolean', 'string'))
);

CREATE TABLE admin_audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor text NOT NULL,
    action text NOT NULL,
    target_type text NOT NULL,
    target_key text NOT NULL,
    before_value jsonb,
    after_value jsonb,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX admin_audit_events_created_at_idx
    ON admin_audit_events (created_at DESC);

CREATE INDEX admin_audit_events_target_idx
    ON admin_audit_events (target_type, target_key, created_at DESC);
