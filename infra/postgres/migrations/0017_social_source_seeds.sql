-- Curated, technically verified public sources for the provider-neutral social pipeline.
--
-- Approval here covers source identity, public endpoint availability, attribution, and
-- conservative 30-day text retention. It is not a substitute for organisation-specific
-- legal review. Revoke or expire a source if its publisher policy changes.

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
) VALUES
    (
        'cd55bf43-34f8-56f7-89c8-77397773665d',
        'RSS',
        'bbc-football',
        'BBC Sport Football',
        'https://www.bbc.com/sport/football',
        'NEWS_ORGANISATION',
        0.8000,
        true,
        'APPROVED',
        '2026-09-10T00:00:00Z',
        30,
        'repository-curated-source-review',
        '2026-09-10T00:00:00Z',
        jsonb_build_object(
            'coverage', 'Football news',
            'feed_url', 'https://feeds.bbci.co.uk/sport/football/rss.xml',
            'terms_url', 'https://www.bbc.co.uk/usingthebbc/terms/',
            'attribution', 'Preserve the BBC canonical article URL',
            'review_scope', 'Technical source and public-access review'
        )
    ),
    (
        '0be6287d-babc-538a-b7d4-15c4c35d3ca9',
        'RSS',
        'guardian-football',
        'The Guardian Football',
        'https://www.theguardian.com/football',
        'NEWS_ORGANISATION',
        0.8000,
        true,
        'APPROVED',
        '2026-09-10T00:00:00Z',
        30,
        'repository-curated-source-review',
        '2026-09-10T00:00:00Z',
        jsonb_build_object(
            'coverage', 'Football news',
            'feed_url', 'https://www.theguardian.com/football/rss',
            'terms_url', 'https://www.theguardian.com/help/terms-of-service',
            'attribution', 'Preserve The Guardian canonical article URL',
            'review_scope', 'Technical source and public-access review'
        )
    ),
    (
        'ba5b201e-da52-5bcc-bb76-fcbb12209225',
        'RSS',
        'le-monde-football-en',
        'Le Monde Football (English)',
        'https://www.lemonde.fr/en/football/',
        'NEWS_ORGANISATION',
        0.7500,
        true,
        'APPROVED',
        '2026-09-10T00:00:00Z',
        30,
        'repository-curated-source-review',
        '2026-09-10T00:00:00Z',
        jsonb_build_object(
            'coverage', 'English-language football news',
            'feed_url', 'https://www.lemonde.fr/en/football/rss_full.xml',
            'terms_url', 'https://www.lemonde.fr/en/about-us/article/2022/06/13/terms-and-conditions-of-use_5986602_115.html',
            'attribution', 'Preserve the Le Monde canonical article URL',
            'review_scope', 'Technical source and public-access review'
        )
    ),
    (
        'f0f61a7d-6bd7-5400-8ac1-0f755fcd7aad',
        'BLUESKY',
        'did:plc:6mb4szcdermfvwvorc4tfztv',
        'evertonfc.com',
        'https://bsky.app/profile/evertonfc.com',
        'OFFICIAL_CLUB',
        1.0000,
        true,
        'APPROVED',
        '2026-09-10T00:00:00Z',
        30,
        'repository-curated-source-review',
        '2026-09-10T00:00:00Z',
        jsonb_build_object(
            'club', 'Everton',
            'identity_basis', 'Club-domain Bluesky handle and profile self-description',
            'terms_url', 'https://bsky.social/about/support/tos',
            'review_scope', 'Technical source and public-access review'
        )
    ),
    (
        'a9bc9f7f-a123-536f-8fde-b19e8d8456bd',
        'BLUESKY',
        'did:plc:lim2lg7owxl6o6r7fnjs7bwn',
        'newcastleunited.com',
        'https://bsky.app/profile/newcastleunited.com',
        'OFFICIAL_CLUB',
        1.0000,
        true,
        'APPROVED',
        '2026-09-10T00:00:00Z',
        30,
        'repository-curated-source-review',
        '2026-09-10T00:00:00Z',
        jsonb_build_object(
            'club', 'Newcastle United',
            'identity_basis', 'Club-domain Bluesky handle and profile self-description',
            'terms_url', 'https://bsky.social/about/support/tos',
            'review_scope', 'Technical source and public-access review'
        )
    ),
    (
        '5d2040d6-4fe3-5ba8-9275-c0ca1aa6d877',
        'BLUESKY',
        'did:plc:zi55hvfbtohpdx7y35viqqma',
        'mancity.com',
        'https://bsky.app/profile/mancity.com',
        'OFFICIAL_CLUB',
        1.0000,
        true,
        'APPROVED',
        '2026-09-10T00:00:00Z',
        30,
        'repository-curated-source-review',
        '2026-09-10T00:00:00Z',
        jsonb_build_object(
            'club', 'Manchester City',
            'identity_basis', 'Club-domain Bluesky handle and profile self-description',
            'terms_url', 'https://bsky.social/about/support/tos',
            'review_scope', 'Technical source and public-access review'
        )
    ),
    (
        '5559456f-f15f-582d-bfdc-330176b5593d',
        'BLUESKY',
        'did:plc:oehqmmuvgd6dyful4fakeaif',
        'tottenhamhotspur.com',
        'https://bsky.app/profile/tottenhamhotspur.com',
        'OFFICIAL_CLUB',
        1.0000,
        true,
        'APPROVED',
        '2026-09-10T00:00:00Z',
        30,
        'repository-curated-source-review',
        '2026-09-10T00:00:00Z',
        jsonb_build_object(
            'club', 'Tottenham Hotspur',
            'identity_basis', 'Club-domain Bluesky handle',
            'terms_url', 'https://bsky.social/about/support/tos',
            'review_scope', 'Technical source and public-access review'
        )
    ),
    (
        'd03c6e53-6328-5163-bfe5-15092b1462cd',
        'MASTODON',
        'mastodon.social:109539226778042515',
        '@footiebuzz@mastodon.social',
        'https://mastodon.social/@footiebuzz',
        'COMMUNITY',
        0.3500,
        true,
        'APPROVED',
        '2026-09-10T00:00:00Z',
        30,
        'repository-curated-source-review',
        '2026-09-10T00:00:00Z',
        jsonb_build_object(
            'coverage', 'Aggregated football links and discussion',
            'identity_basis', 'Active public Mastodon profile; not an official club or publisher source',
            'terms_url', 'https://mastodon.social/terms',
            'evidence_policy', 'Aggregate sentiment and attention only',
            'review_scope', 'Technical source and public-access review'
        )
    )
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

WITH subscription_seed (
    id,
    provider,
    external_source_id,
    mode,
    configuration,
    polling_interval_seconds
) AS (
    VALUES
        (
            'a8374af9-f6c7-5ef2-9c7f-862a8b4b163c'::uuid,
            'RSS',
            'bbc-football',
            'RSS_FEED',
            jsonb_build_object('url', 'https://feeds.bbci.co.uk/sport/football/rss.xml'),
            900
        ),
        (
            '7b7343a2-7bc2-5d43-a755-e647c9741a7f'::uuid,
            'RSS',
            'guardian-football',
            'RSS_FEED',
            jsonb_build_object('url', 'https://www.theguardian.com/football/rss'),
            900
        ),
        (
            'dd7ea5dd-3ef3-599f-b295-aabb2c7007f3'::uuid,
            'RSS',
            'le-monde-football-en',
            'RSS_FEED',
            jsonb_build_object('url', 'https://www.lemonde.fr/en/football/rss_full.xml'),
            900
        ),
        (
            'ab428088-13bd-539f-8db1-d3bec671b04f'::uuid,
            'BLUESKY',
            'did:plc:6mb4szcdermfvwvorc4tfztv',
            'AUTHOR_FEED',
            jsonb_build_object('did', 'did:plc:6mb4szcdermfvwvorc4tfztv'),
            300
        ),
        (
            '026c49e1-a5e7-5aa2-b06d-d5b10ffe8150'::uuid,
            'BLUESKY',
            'did:plc:lim2lg7owxl6o6r7fnjs7bwn',
            'AUTHOR_FEED',
            jsonb_build_object('did', 'did:plc:lim2lg7owxl6o6r7fnjs7bwn'),
            300
        ),
        (
            '8cd19e77-acc5-54a1-be4b-e0a692ced292'::uuid,
            'BLUESKY',
            'did:plc:zi55hvfbtohpdx7y35viqqma',
            'AUTHOR_FEED',
            jsonb_build_object('did', 'did:plc:zi55hvfbtohpdx7y35viqqma'),
            300
        ),
        (
            '9e1fb0f3-4f94-5194-866c-7545c0886c10'::uuid,
            'BLUESKY',
            'did:plc:oehqmmuvgd6dyful4fakeaif',
            'AUTHOR_FEED',
            jsonb_build_object('did', 'did:plc:oehqmmuvgd6dyful4fakeaif'),
            300
        ),
        (
            'ee2190ff-5aac-5fc4-bdd8-d8559c65aa1e'::uuid,
            'MASTODON',
            'mastodon.social:109539226778042515',
            'AUTHOR_FEED',
            jsonb_build_object(
                'instance_url', 'https://mastodon.social',
                'account_id', '109539226778042515'
            ),
            300
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
    subscription_seed.provider,
    subscription_seed.mode,
    subscription_seed.configuration,
    subscription_seed.polling_interval_seconds,
    true,
    now()
FROM subscription_seed
JOIN social_sources
  ON social_sources.provider = subscription_seed.provider
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
