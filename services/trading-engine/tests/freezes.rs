use rust_decimal::Decimal;
use sqlx::PgPool;
use stockball_trading_engine::{
    execution::execute_order,
    freezes::{
        apply_freeze, release_freeze, ApplyFreezeCommand, FreezeReason, ReleaseFreezeCommand,
    },
    orders::{ExecuteOrderCommand, OrderSide},
};
use uuid::Uuid;

#[test]
fn match_day_freeze_blocks_trading_and_respects_other_freezes() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap();

    runtime.block_on(async {
        match_day_freeze_inner().await;
    });
}

async fn match_day_freeze_inner() {
    let Some(database_url) = test_database_url() else {
        eprintln!("skipping freeze test; STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL is not set");
        return;
    };

    let pool = PgPool::connect(&database_url).await.unwrap();
    let (account_id, portfolio_id) = insert_funded_account(&pool).await;
    let instrument_id = insert_instrument(&pool).await;
    let fixture_key = format!("fixture:{}", Uuid::new_v4());
    let halt_key = format!("admin-halt:{}", Uuid::new_v4());

    let applied = apply_freeze(&pool, match_day(&fixture_key, instrument_id))
        .await
        .unwrap();
    assert_eq!(applied.opened_count, 1);
    assert_eq!(status(&pool, instrument_id).await, "FROZEN");

    // Re-applying is a no-op.
    let reapplied = apply_freeze(&pool, match_day(&fixture_key, instrument_id))
        .await
        .unwrap();
    assert_eq!(
        (reapplied.opened_count, reapplied.already_open_count),
        (0, 1)
    );

    // Orders are rejected while frozen.
    let order = ExecuteOrderCommand {
        execution_limits: None,
        request_id: format!("frozen-buy-{}", Uuid::new_v4()),
        account_id,
        portfolio_id,
        instrument_id,
        side: OrderSide::Buy,
        quantity: Decimal::new(1, 0),
    };
    assert!(execute_order(&pool, order.clone()).await.is_err());

    // An admin halt overlapping the match keeps the instrument frozen after the match ends.
    apply_freeze(
        &pool,
        ApplyFreezeCommand {
            reason: FreezeReason::AdminHalt,
            source_key: halt_key.clone(),
            instrument_ids: vec![instrument_id],
        },
    )
    .await
    .unwrap();
    let released = release_freeze(
        &pool,
        ReleaseFreezeCommand {
            source_key: fixture_key.clone(),
        },
    )
    .await
    .unwrap();
    assert_eq!(released.released_count, 1);
    assert!(released.reactivated_instrument_ids.is_empty());
    assert_eq!(status(&pool, instrument_id).await, "FROZEN");

    // Releasing the last open freeze makes it tradable again; releasing twice is a no-op.
    let released = release_freeze(
        &pool,
        ReleaseFreezeCommand {
            source_key: halt_key.clone(),
        },
    )
    .await
    .unwrap();
    assert_eq!(released.reactivated_instrument_ids, vec![instrument_id]);
    assert_eq!(status(&pool, instrument_id).await, "ACTIVE");
    let again = release_freeze(
        &pool,
        ReleaseFreezeCommand {
            source_key: halt_key,
        },
    )
    .await
    .unwrap();
    assert_eq!(again.released_count, 0);

    let order = ExecuteOrderCommand {
        execution_limits: None,
        request_id: format!("thawed-buy-{}", Uuid::new_v4()),
        ..order
    };
    execute_order(&pool, order).await.unwrap();
}

fn match_day(source_key: &str, instrument_id: Uuid) -> ApplyFreezeCommand {
    ApplyFreezeCommand {
        reason: FreezeReason::MatchDay,
        source_key: source_key.to_owned(),
        instrument_ids: vec![instrument_id, instrument_id],
    }
}

async fn status(pool: &PgPool, instrument_id: Uuid) -> String {
    sqlx::query_scalar("SELECT trading_status FROM instruments WHERE id = $1")
        .bind(instrument_id)
        .fetch_one(pool)
        .await
        .unwrap()
}

async fn insert_funded_account(pool: &PgPool) -> (Uuid, Uuid) {
    let account_id = Uuid::new_v4();
    let portfolio_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO accounts (id, handle, display_name, account_type, status) \
         VALUES ($1, $2, 'Freeze Test', 'USER', 'ACTIVE')",
    )
    .bind(account_id)
    .bind(format!("freeze-{account_id}"))
    .execute(pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO portfolios (id, account_id, cash_balance) VALUES ($1, $2, 100000)")
        .bind(portfolio_id)
        .bind(account_id)
        .execute(pool)
        .await
        .unwrap();
    (account_id, portfolio_id)
}

async fn insert_instrument(pool: &PgPool) -> Uuid {
    let player_id = Uuid::new_v4();
    let instrument_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO players (id, provider, provider_player_id, display_name) \
         VALUES ($1, 'freeze-test', $2, 'Freeze Test Player')",
    )
    .bind(player_id)
    .bind(player_id.to_string())
    .execute(pool)
    .await
    .unwrap();
    sqlx::query(
        r#"
        INSERT INTO instruments (
            id, instrument_type, player_id, symbol, display_name, current_price,
            reference_price, shares_outstanding, net_shares_purchased,
            full_supply_price_multiplier, trading_status
        ) VALUES ($1, 'PLAYER_SHARE', $2, $3, 'Freeze Test Share', 100, 100, 1000000, 0, 2.5, 'ACTIVE')
        "#,
    )
    .bind(instrument_id)
    .bind(player_id)
    .bind(format!("FREEZE-{instrument_id}"))
    .execute(pool)
    .await
    .unwrap();
    instrument_id
}

fn test_database_url() -> Option<String> {
    match std::env::var("STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL") {
        Ok(database_url) => Some(database_url),
        Err(_) if std::env::var_os("CI").is_some() => {
            panic!("STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL must be set in CI")
        }
        Err(_) => None,
    }
}
