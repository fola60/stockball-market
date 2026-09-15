-- Expand the reviewed Bluesky registry beyond the four initial club accounts.
--
-- DIDs are pinned so a later handle takeover cannot silently change the source.
-- Custom-domain handles and Bluesky verification are treated as strong identity
-- evidence. Crystal Palace is additionally corroborated by a curated public
-- professional-football-club starter pack, so its slightly weaker identity proof
-- is reflected in the source trust weight.

WITH source_seed (
    id,
    external_source_id,
    display_handle,
    club,
    identity_basis,
    trust_weight
) AS (
    VALUES
        (
            '30317844-3125-52e3-b6a5-a24ebc966b1a'::uuid,
            'did:plc:jonvi4iruke6hrpofoswvugr',
            'brentfordfc.com',
            'Brentford',
            'Club-domain Bluesky handle',
            1.0000
        ),
        (
            'e7a67dab-7f20-5943-b9a5-ca247a60125f'::uuid,
            'did:plc:zyklbm6a5p3h4qesx524ptgf',
            'officialbha.bsky.social',
            'Brighton & Hove Albion',
            'Valid Bluesky verification issued by bsky.app and profile self-description',
            1.0000
        ),
        (
            'e4501749-c0f8-5980-bd21-b5463c9f9263'::uuid,
            'did:plc:zutenr6tt7vk7qxsqysa3pua',
            'fulhamfc.com',
            'Fulham',
            'Club-domain Bluesky handle and valid Bluesky verification issued by bsky.app',
            1.0000
        ),
        (
            '8e33eb4c-668f-55c2-a3f3-afd9e8d0e287'::uuid,
            'did:plc:pdfrjhvbb6r5bxfc27pocimy',
            'safc.com',
            'Sunderland',
            'Club-domain Bluesky handle and valid Bluesky verification issued by bsky.app',
            1.0000
        ),
        (
            'ba1c3adc-1e5c-5b95-a04c-fd60cdec7764'::uuid,
            'did:plc:saw6l6fvyixwgprce7uohrvg',
            'officialcpfc.bsky.social',
            'Crystal Palace',
            'Profile self-description corroborated by a curated professional-football-club starter pack',
            0.9000
        )
)
INSERT INTO social_sources (
    id,
    provider,
    external_source_id,
    display_handle,
    canonical_url,
    source_category,
    trust_weight,
    enabled,
    policy_status,
    terms_reviewed_at,
    retention_days,
    approved_by,
    approved_at,
    metadata
)
SELECT
    source_seed.id,
    'BLUESKY',
    source_seed.external_source_id,
    source_seed.display_handle,
    'https://bsky.app/profile/' || source_seed.display_handle,
    'OFFICIAL_CLUB',
    source_seed.trust_weight,
    true,
    'APPROVED',
    '2026-09-10T00:00:00Z',
    30,
    'repository-curated-source-review',
    '2026-09-10T00:00:00Z',
    jsonb_build_object(
        'club', source_seed.club,
        'identity_basis', source_seed.identity_basis,
        'terms_url', 'https://bsky.social/about/support/tos',
        'review_scope', 'Technical source and public-access review'
    )
FROM source_seed
ON CONFLICT (provider, external_source_id) DO UPDATE SET
    display_handle = EXCLUDED.display_handle,
    canonical_url = EXCLUDED.canonical_url,
    source_category = EXCLUDED.source_category,
    trust_weight = EXCLUDED.trust_weight,
    enabled = EXCLUDED.enabled,
    policy_status = EXCLUDED.policy_status,
    terms_reviewed_at = EXCLUDED.terms_reviewed_at,
    retention_days = EXCLUDED.retention_days,
    approved_by = EXCLUDED.approved_by,
    approved_at = EXCLUDED.approved_at,
    metadata = EXCLUDED.metadata,
    updated_at = now();

WITH subscription_seed (id, external_source_id) AS (
    VALUES
        (
            '5b4ef0cb-a4da-5309-b555-3180652fe9f9'::uuid,
            'did:plc:jonvi4iruke6hrpofoswvugr'
        ),
        (
            '3a184658-de04-5d03-be23-c6dd441f6962'::uuid,
            'did:plc:zyklbm6a5p3h4qesx524ptgf'
        ),
        (
            '64a3bd72-bc45-56e5-b1d7-a4d7bb4f4a88'::uuid,
            'did:plc:zutenr6tt7vk7qxsqysa3pua'
        ),
        (
            'd9ed7d53-81de-54fe-94cc-4a58df46e928'::uuid,
            'did:plc:pdfrjhvbb6r5bxfc27pocimy'
        ),
        (
            '732271f9-9cde-59a9-a318-e9683ec85e23'::uuid,
            'did:plc:saw6l6fvyixwgprce7uohrvg'
        )
)
INSERT INTO social_subscriptions (
    id,
    source_id,
    provider,
    mode,
    configuration,
    polling_interval_seconds,
    enabled,
    next_eligible_poll_at
)
SELECT
    subscription_seed.id,
    social_sources.id,
    'BLUESKY',
    'AUTHOR_FEED',
    jsonb_build_object('did', subscription_seed.external_source_id),
    300,
    true,
    now()
FROM subscription_seed
JOIN social_sources
  ON social_sources.provider = 'BLUESKY'
 AND social_sources.external_source_id = subscription_seed.external_source_id
ON CONFLICT (id) DO UPDATE SET
    source_id = EXCLUDED.source_id,
    provider = EXCLUDED.provider,
    mode = EXCLUDED.mode,
    configuration = EXCLUDED.configuration,
    polling_interval_seconds = EXCLUDED.polling_interval_seconds,
    enabled = EXCLUDED.enabled,
    next_eligible_poll_at = LEAST(
        social_subscriptions.next_eligible_poll_at,
        EXCLUDED.next_eligible_poll_at
    ),
    updated_at = now();
