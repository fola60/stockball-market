use rust_decimal::Decimal;
use sqlx::PgPool;
use stockball_trading_engine::instruments::seed_player_shares;
use uuid::Uuid;

#[test]
fn seeds_player_shares_and_is_rerunnable() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap();

    runtime.block_on(async {
        seeds_player_shares_and_is_rerunnable_inner().await;
    });
}

async fn seeds_player_shares_and_is_rerunnable_inner() {
    let Ok(database_url) = std::env::var("STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL") else {
        eprintln!(
            "skipping database smoke test; STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL is not set"
        );
        return;
    };

    let pool = PgPool::connect(&database_url).await.unwrap();
    let priced_player_id = insert_player(&pool, "Bukayo Saka", "Right Winger").await;
    let fallback_player_id = insert_player(&pool, "Test Goalkeeper", "Goalkeeper").await;
    insert_market_value(&pool, priced_player_id, Decimal::new(100_000_000, 0)).await;

    let first = seed_player_shares(&pool).await.unwrap();

    assert_eq!(first.created_count, 2);
    assert_eq!(first.market_value_priced_count, 1);
    assert_eq!(first.fallback_priced_count, 1);
    assert_eq!(first.created_instrument_ids.len(), 2);

    let second = seed_player_shares(&pool).await.unwrap();

    assert_eq!(second.created_count, 0);
    assert_eq!(second.market_value_priced_count, 0);
    assert_eq!(second.fallback_priced_count, 0);
    assert!(second.skipped_existing_count >= first.created_count);

    let seeded_snapshot_count = sqlx::query_scalar::<_, i64>(
        r#"
        SELECT COUNT(*)
        FROM price_snapshots AS ps
        JOIN instruments AS i
            ON i.id = ps.instrument_id
        WHERE i.player_id = ANY($1)
          AND ps.reason = 'SEED'
        "#,
    )
    .bind(vec![priced_player_id, fallback_player_id])
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(seeded_snapshot_count, 2);

    let priced_price = current_price_for_player(&pool, priced_player_id).await;
    let fallback_price = current_price_for_player(&pool, fallback_player_id).await;
    assert_eq!(priced_price, Decimal::new(100_0000, 4));
    assert_eq!(fallback_price, Decimal::new(5_0000, 4));
}

async fn insert_player(pool: &PgPool, display_name: &str, position: &str) -> Uuid {
    let player_id = Uuid::new_v4();
    let suffix = Uuid::new_v4();
    sqlx::query(
        r#"
        INSERT INTO players (
            id,
            provider,
            provider_player_id,
            display_name,
            position
        ) VALUES (
            $1,
            'seeding-test',
            $2,
            $3,
            $4
        )
        "#,
    )
    .bind(player_id)
    .bind(suffix.to_string())
    .bind(display_name)
    .bind(position)
    .execute(pool)
    .await
    .unwrap();

    player_id
}

async fn insert_market_value(pool: &PgPool, player_id: Uuid, value: Decimal) {
    sqlx::query(
        r#"
        INSERT INTO player_market_value_observations (
            player_id,
            source,
            source_player_id,
            value,
            currency,
            observed_at
        ) VALUES (
            $1,
            'seeding-test',
            $2,
            $3,
            'EUR',
            now()
        )
        "#,
    )
    .bind(player_id)
    .bind(Uuid::new_v4().to_string())
    .bind(value)
    .execute(pool)
    .await
    .unwrap();
}

async fn current_price_for_player(pool: &PgPool, player_id: Uuid) -> Decimal {
    sqlx::query_scalar::<_, Decimal>(
        r#"
        SELECT current_price
        FROM instruments
        WHERE player_id = $1
          AND instrument_type = 'PLAYER_SHARE'
        "#,
    )
    .bind(player_id)
    .fetch_one(pool)
    .await
    .unwrap()
}
