-- Team-specific RSS sources verified as publicly reachable on 2026-09-12.
--
-- Team feeds carry an explicit club hint for entity resolution. Independent fan/community
-- publishers are deliberately low-trust and aggregate-only; established news publishers
-- retain NEWS_ORGANISATION weighting. Feed URLs are also the stable external source IDs.

CREATE TEMP TABLE team_rss_seed (
    club text,
    display_handle text NOT NULL,
    feed_url text NOT NULL,
    canonical_url text NOT NULL,
    source_category text NOT NULL,
    trust_weight numeric(5, 4) NOT NULL,
    terms_url text NOT NULL
);

INSERT INTO team_rss_seed VALUES
    -- BBC team feeds (all supported clubs).
    ('Bournemouth', 'BBC Sport: Bournemouth', 'https://feeds.bbci.co.uk/sport/football/teams/afc-bournemouth/rss.xml', 'https://www.bbc.com/sport/football/teams/afc-bournemouth', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Arsenal', 'BBC Sport: Arsenal', 'https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml', 'https://www.bbc.com/sport/football/teams/arsenal', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Aston Villa', 'BBC Sport: Aston Villa', 'https://feeds.bbci.co.uk/sport/football/teams/aston-villa/rss.xml', 'https://www.bbc.com/sport/football/teams/aston-villa', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Brentford', 'BBC Sport: Brentford', 'https://feeds.bbci.co.uk/sport/football/teams/brentford/rss.xml', 'https://www.bbc.com/sport/football/teams/brentford', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Brighton & Hove Albion', 'BBC Sport: Brighton & Hove Albion', 'https://feeds.bbci.co.uk/sport/football/teams/brighton-and-hove-albion/rss.xml', 'https://www.bbc.com/sport/football/teams/brighton-and-hove-albion', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Chelsea', 'BBC Sport: Chelsea', 'https://feeds.bbci.co.uk/sport/football/teams/chelsea/rss.xml', 'https://www.bbc.com/sport/football/teams/chelsea', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Coventry City', 'BBC Sport: Coventry City', 'https://feeds.bbci.co.uk/sport/football/teams/coventry-city/rss.xml', 'https://www.bbc.com/sport/football/teams/coventry-city', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Crystal Palace', 'BBC Sport: Crystal Palace', 'https://feeds.bbci.co.uk/sport/football/teams/crystal-palace/rss.xml', 'https://www.bbc.com/sport/football/teams/crystal-palace', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Everton', 'BBC Sport: Everton', 'https://feeds.bbci.co.uk/sport/football/teams/everton/rss.xml', 'https://www.bbc.com/sport/football/teams/everton', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Fulham', 'BBC Sport: Fulham', 'https://feeds.bbci.co.uk/sport/football/teams/fulham/rss.xml', 'https://www.bbc.com/sport/football/teams/fulham', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Hull City', 'BBC Sport: Hull City', 'https://feeds.bbci.co.uk/sport/football/teams/hull-city/rss.xml', 'https://www.bbc.com/sport/football/teams/hull-city', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Ipswich Town', 'BBC Sport: Ipswich Town', 'https://feeds.bbci.co.uk/sport/football/teams/ipswich-town/rss.xml', 'https://www.bbc.com/sport/football/teams/ipswich-town', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Leeds United', 'BBC Sport: Leeds United', 'https://feeds.bbci.co.uk/sport/football/teams/leeds-united/rss.xml', 'https://www.bbc.com/sport/football/teams/leeds-united', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Liverpool', 'BBC Sport: Liverpool', 'https://feeds.bbci.co.uk/sport/football/teams/liverpool/rss.xml', 'https://www.bbc.com/sport/football/teams/liverpool', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Manchester City', 'BBC Sport: Manchester City', 'https://feeds.bbci.co.uk/sport/football/teams/manchester-city/rss.xml', 'https://www.bbc.com/sport/football/teams/manchester-city', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Manchester United', 'BBC Sport: Manchester United', 'https://feeds.bbci.co.uk/sport/football/teams/manchester-united/rss.xml', 'https://www.bbc.com/sport/football/teams/manchester-united', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Newcastle United', 'BBC Sport: Newcastle United', 'https://feeds.bbci.co.uk/sport/football/teams/newcastle-united/rss.xml', 'https://www.bbc.com/sport/football/teams/newcastle-united', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Nottingham Forest', 'BBC Sport: Nottingham Forest', 'https://feeds.bbci.co.uk/sport/football/teams/nottingham-forest/rss.xml', 'https://www.bbc.com/sport/football/teams/nottingham-forest', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Sunderland', 'BBC Sport: Sunderland', 'https://feeds.bbci.co.uk/sport/football/teams/sunderland/rss.xml', 'https://www.bbc.com/sport/football/teams/sunderland', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),
    ('Tottenham Hotspur', 'BBC Sport: Tottenham Hotspur', 'https://feeds.bbci.co.uk/sport/football/teams/tottenham-hotspur/rss.xml', 'https://www.bbc.com/sport/football/teams/tottenham-hotspur', 'NEWS_ORGANISATION', 0.8000, 'https://www.bbc.co.uk/usingthebbc/terms/'),

    -- Guardian team feeds (Brighton currently has no working Guardian team feed).
    ('Bournemouth', 'The Guardian: Bournemouth', 'https://www.theguardian.com/football/bournemouth/rss', 'https://www.theguardian.com/football/bournemouth', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Arsenal', 'The Guardian: Arsenal', 'https://www.theguardian.com/football/arsenal/rss', 'https://www.theguardian.com/football/arsenal', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Aston Villa', 'The Guardian: Aston Villa', 'https://www.theguardian.com/football/aston-villa/rss', 'https://www.theguardian.com/football/aston-villa', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Brentford', 'The Guardian: Brentford', 'https://www.theguardian.com/football/brentford/rss', 'https://www.theguardian.com/football/brentford', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Chelsea', 'The Guardian: Chelsea', 'https://www.theguardian.com/football/chelsea/rss', 'https://www.theguardian.com/football/chelsea', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Coventry City', 'The Guardian: Coventry City', 'https://www.theguardian.com/football/coventry/rss', 'https://www.theguardian.com/football/coventry', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Crystal Palace', 'The Guardian: Crystal Palace', 'https://www.theguardian.com/football/crystalpalace/rss', 'https://www.theguardian.com/football/crystalpalace', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Everton', 'The Guardian: Everton', 'https://www.theguardian.com/football/everton/rss', 'https://www.theguardian.com/football/everton', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Fulham', 'The Guardian: Fulham', 'https://www.theguardian.com/football/fulham/rss', 'https://www.theguardian.com/football/fulham', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Hull City', 'The Guardian: Hull City', 'https://www.theguardian.com/football/hullcity/rss', 'https://www.theguardian.com/football/hullcity', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Ipswich Town', 'The Guardian: Ipswich Town', 'https://www.theguardian.com/football/ipswichtown/rss', 'https://www.theguardian.com/football/ipswichtown', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Leeds United', 'The Guardian: Leeds United', 'https://www.theguardian.com/football/leedsunited/rss', 'https://www.theguardian.com/football/leedsunited', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Liverpool', 'The Guardian: Liverpool', 'https://www.theguardian.com/football/liverpool/rss', 'https://www.theguardian.com/football/liverpool', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Manchester City', 'The Guardian: Manchester City', 'https://www.theguardian.com/football/manchestercity/rss', 'https://www.theguardian.com/football/manchestercity', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Manchester United', 'The Guardian: Manchester United', 'https://www.theguardian.com/football/manchester-united/rss', 'https://www.theguardian.com/football/manchester-united', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Newcastle United', 'The Guardian: Newcastle United', 'https://www.theguardian.com/football/newcastleunited/rss', 'https://www.theguardian.com/football/newcastleunited', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Nottingham Forest', 'The Guardian: Nottingham Forest', 'https://www.theguardian.com/football/nottinghamforest/rss', 'https://www.theguardian.com/football/nottinghamforest', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Sunderland', 'The Guardian: Sunderland', 'https://www.theguardian.com/football/sunderland/rss', 'https://www.theguardian.com/football/sunderland', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),
    ('Tottenham Hotspur', 'The Guardian: Tottenham Hotspur', 'https://www.theguardian.com/football/tottenham-hotspur/rss', 'https://www.theguardian.com/football/tottenham-hotspur', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service'),

    -- One active independent or local feed per club.
    ('Bournemouth', 'Vital Bournemouth', 'https://vitalfootball.co.uk/vital-bournemouth/feed/', 'https://vitalfootball.co.uk/vital-bournemouth/', 'COMMUNITY', 0.4000, 'https://vitalfootball.co.uk/terms-and-conditions/'),
    ('Arsenal', 'Arseblog News', 'https://arseblog.news/feed/', 'https://arseblog.news/', 'COMMUNITY', 0.4000, 'https://arseblog.news/'),
    ('Aston Villa', 'Aston Villa Review', 'https://www.astonvillareview.com/feed', 'https://www.astonvillareview.com/', 'COMMUNITY', 0.4000, 'https://www.astonvillareview.com/'),
    ('Brentford', 'Beesotted', 'https://beesotted.com/feed/', 'https://beesotted.com/', 'COMMUNITY', 0.4000, 'https://beesotted.com/'),
    ('Brighton & Hove Albion', 'The Argus: Albion', 'https://www.theargus.co.uk/sport/albion/rss/', 'https://www.theargus.co.uk/sport/albion/', 'NEWS_ORGANISATION', 0.7000, 'https://www.theargus.co.uk/terms/'),
    ('Chelsea', 'The Chelsea Chronicle', 'https://www.thechelseachronicle.com/feed/', 'https://www.thechelseachronicle.com/', 'COMMUNITY', 0.4000, 'https://www.thechelseachronicle.com/'),
    ('Coventry City', 'Coventry Telegraph: Coventry City', 'https://www.coventrytelegraph.net/all-about/coventry-city-fc/?service=rss', 'https://www.coventrytelegraph.net/all-about/coventry-city-fc/', 'NEWS_ORGANISATION', 0.7000, 'https://www.coventrytelegraph.net/terms-conditions/'),
    ('Crystal Palace', 'We Are Palace', 'https://www.wearepalace.uk/feed/', 'https://www.wearepalace.uk/', 'COMMUNITY', 0.4000, 'https://www.wearepalace.uk/'),
    ('Everton', 'EFC Statto', 'https://www.efcstatto.com/feed/', 'https://www.efcstatto.com/', 'COMMUNITY', 0.4000, 'https://www.efcstatto.com/'),
    ('Fulham', 'Fulhamish', 'https://www.fulhamish.co.uk/feed', 'https://www.fulhamish.co.uk/', 'COMMUNITY', 0.4000, 'https://www.fulhamish.co.uk/'),
    ('Hull City', 'Hull Daily Mail: Hull City', 'https://www.hulldailymail.co.uk/all-about/hull-city/?service=rss', 'https://www.hulldailymail.co.uk/all-about/hull-city/', 'NEWS_ORGANISATION', 0.7000, 'https://www.hulldailymail.co.uk/terms-conditions/'),
    ('Ipswich Town', 'TWTD', 'https://www.twtd.co.uk/rss/news', 'https://www.twtd.co.uk/', 'COMMUNITY', 0.4000, 'https://www.twtd.co.uk/page/terms'),
    ('Leeds United', 'MOT Leeds News', 'https://motleedsnews.com/feed', 'https://motleedsnews.com/', 'COMMUNITY', 0.4000, 'https://motleedsnews.com/'),
    ('Liverpool', 'This Is Anfield', 'https://www.thisisanfield.com/feed/', 'https://www.thisisanfield.com/', 'COMMUNITY', 0.4000, 'https://www.thisisanfield.com/terms-and-conditions/'),
    ('Manchester City', 'Bitter and Blue', 'https://bitterandblue.sbnation.com/rss/index.xml', 'https://bitterandblue.sbnation.com/', 'COMMUNITY', 0.4000, 'https://www.voxmedia.com/legal/terms-of-use'),
    ('Manchester United', 'The Busby Babe', 'https://thebusbybabe.sbnation.com/rss/index.xml', 'https://thebusbybabe.sbnation.com/', 'COMMUNITY', 0.4000, 'https://www.voxmedia.com/legal/terms-of-use'),
    ('Newcastle United', 'NUFC Blog', 'https://nufcblog.co.uk/news.rss', 'https://nufcblog.co.uk/', 'COMMUNITY', 0.4000, 'https://nufcblog.co.uk/'),
    ('Nottingham Forest', 'Nottingham Forest News', 'https://www.nottinghamforest.news/feed/', 'https://www.nottinghamforest.news/', 'COMMUNITY', 0.4000, 'https://www.nottinghamforest.news/'),
    ('Sunderland', 'Roker Report', 'https://rokerreport.sbnation.com/rss/index.xml', 'https://rokerreport.sbnation.com/', 'COMMUNITY', 0.4000, 'https://www.voxmedia.com/legal/terms-of-use'),
    ('Tottenham Hotspur', 'Cartilage Free Captain', 'https://cartilagefreecaptain.sbnation.com/rss/index.xml', 'https://cartilagefreecaptain.sbnation.com/', 'COMMUNITY', 0.4000, 'https://www.voxmedia.com/legal/terms-of-use'),

    -- Useful broad feeds with complementary breaking-news and transfer coverage.
    (NULL, 'Sky Sports Football', 'https://www.skysports.com/rss/12040', 'https://www.skysports.com/football', 'NEWS_ORGANISATION', 0.7500, 'https://www.skysports.com/terms-and-conditions'),
    (NULL, 'ESPN Soccer', 'https://www.espn.com/espn/rss/soccer/news', 'https://www.espn.com/soccer/', 'NEWS_ORGANISATION', 0.7500, 'https://disneytermsofuse.com/'),
    (NULL, 'The Guardian: Transfer Window', 'https://www.theguardian.com/football/transfer-window/rss', 'https://www.theguardian.com/football/transfer-window', 'NEWS_ORGANISATION', 0.8000, 'https://www.theguardian.com/help/terms-of-service');

INSERT INTO social_sources (
    id, provider, external_source_id, display_handle, canonical_url, source_category,
    trust_weight, enabled, policy_status, terms_reviewed_at, retention_days,
    approved_by, approved_at, metadata
)
SELECT
    md5('stockball.market/source/rss:' || feed_url)::uuid,
    'RSS',
    feed_url,
    display_handle,
    canonical_url,
    source_category,
    trust_weight,
    true,
    'APPROVED',
    '2026-09-12T00:00:00Z',
    30,
    'repository-curated-source-review',
    '2026-09-12T00:00:00Z',
    jsonb_strip_nulls(jsonb_build_object(
        'club', club,
        'feed_url', feed_url,
        'terms_url', terms_url,
        'identity_basis', 'Public publisher-operated RSS endpoint verified by HTTP and XML parsing',
        'evidence_policy', CASE
            WHEN source_category = 'COMMUNITY' THEN 'Aggregate sentiment and attention only'
            ELSE 'Publisher evidence subject to classifier and entity-resolution thresholds'
        END,
        'review_scope', 'Technical source and public-access review'
    ))
FROM team_rss_seed
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

INSERT INTO social_subscriptions (
    id, source_id, provider, mode, configuration, polling_interval_seconds,
    enabled, next_eligible_poll_at
)
SELECT
    md5('stockball.market/subscription/rss:' || seed.feed_url)::uuid,
    source.id,
    'RSS',
    'RSS_FEED',
    jsonb_build_object('url', seed.feed_url),
    900,
    true,
    now()
FROM team_rss_seed seed
JOIN social_sources source
  ON source.provider = 'RSS'
 AND source.external_source_id = seed.feed_url
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

-- Team-specific BBC/Guardian feeds supersede the broad feeds. This avoids a shared article GUID
-- being inserted first without the club hint (social_documents is unique by provider/GUID).
UPDATE social_subscriptions subscription
SET enabled = false,
    updated_at = now()
FROM social_sources source
WHERE subscription.source_id = source.id
  AND source.provider = 'RSS'
  AND source.external_source_id IN ('bbc-football', 'guardian-football');

DROP TABLE team_rss_seed;
