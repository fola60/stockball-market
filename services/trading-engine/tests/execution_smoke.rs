use rust_decimal::Decimal;
use sqlx::PgPool;
use stockball_trading_engine::{
    execution::execute_order,
    orders::{ExecuteOrderCommand, OrderSide},
};
use uuid::Uuid;

struct Fixture {
    account_id: Uuid,
    portfolio_id: Uuid,
    instrument_id: Uuid,
}

#[test]
fn executes_buy_sell_and_idempotent_duplicate() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap();

    runtime.block_on(async {
        executes_buy_sell_and_idempotent_duplicate_inner().await;
    });
}

async fn executes_buy_sell_and_idempotent_duplicate_inner() {
    let Ok(database_url) = std::env::var("STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL") else {
        eprintln!(
            "skipping database smoke test; STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL is not set"
        );
        return;
    };

    let pool = PgPool::connect(&database_url).await.unwrap();
    let fixture = insert_fixture(&pool).await;

    let buy_request_id = format!("buy-{}", Uuid::new_v4());
    let buy_command = ExecuteOrderCommand {
        request_id: buy_request_id.clone(),
        account_id: fixture.account_id,
        portfolio_id: fixture.portfolio_id,
        instrument_id: fixture.instrument_id,
        side: OrderSide::Buy,
        quantity: Decimal::new(10, 0),
    };

    let buy = execute_order(&pool, buy_command.clone()).await.unwrap();

    assert_eq!(buy.execution_price, Decimal::new(100_0000, 4));
    assert_eq!(buy.gross_amount, Decimal::new(1000_0000, 4));
    assert_eq!(buy.cash_balance_after, Decimal::new(990_000_000, 4));
    assert_eq!(buy.position_quantity_after, Decimal::new(10, 0));
    assert_eq!(buy.old_price, Decimal::new(100_0000, 4));
    assert_eq!(buy.new_price, Decimal::new(100_1000, 4));

    let duplicate_buy = execute_order(&pool, buy_command).await.unwrap();
    assert_eq!(duplicate_buy, buy);

    let order_count = sqlx::query_scalar::<_, i64>(
        r#"
        SELECT COUNT(*)
        FROM orders
        WHERE request_id = $1
        "#,
    )
    .bind(&buy_request_id)
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(order_count, 1);

    let sell = execute_order(
        &pool,
        ExecuteOrderCommand {
            request_id: format!("sell-{}", Uuid::new_v4()),
            account_id: fixture.account_id,
            portfolio_id: fixture.portfolio_id,
            instrument_id: fixture.instrument_id,
            side: OrderSide::Sell,
            quantity: Decimal::new(4, 0),
        },
    )
    .await
    .unwrap();

    assert_eq!(sell.execution_price, Decimal::new(100_1000, 4));
    assert_eq!(sell.gross_amount, Decimal::new(400_4000, 4));
    assert_eq!(sell.cash_balance_after, Decimal::new(994_004_000, 4));
    assert_eq!(sell.position_quantity_after, Decimal::new(6, 0));
    assert_eq!(sell.old_price, Decimal::new(100_1000, 4));
    assert_eq!(sell.new_price, Decimal::new(100_0600, 4));
}

async fn insert_fixture(pool: &PgPool) -> Fixture {
    let account_id = Uuid::new_v4();
    let portfolio_id = Uuid::new_v4();
    let player_id = Uuid::new_v4();
    let instrument_id = Uuid::new_v4();
    let suffix = Uuid::new_v4();

    sqlx::query(
        r#"
        INSERT INTO accounts (
            id,
            handle,
            display_name,
            account_type,
            status
        ) VALUES (
            $1,
            $2,
            'Smoke Test User',
            'USER',
            'ACTIVE'
        )
        "#,
    )
    .bind(account_id)
    .bind(format!("smoke-{suffix}"))
    .execute(pool)
    .await
    .unwrap();

    sqlx::query(
        r#"
        INSERT INTO portfolios (
            id,
            account_id,
            cash_balance
        ) VALUES (
            $1,
            $2,
            $3
        )
        "#,
    )
    .bind(portfolio_id)
    .bind(account_id)
    .bind(Decimal::new(1_000_000_000, 4))
    .execute(pool)
    .await
    .unwrap();

    sqlx::query(
        r#"
        INSERT INTO players (
            id,
            provider,
            provider_player_id,
            display_name
        ) VALUES (
            $1,
            'smoke-test',
            $2,
            'Smoke Test Player'
        )
        "#,
    )
    .bind(player_id)
    .bind(suffix.to_string())
    .execute(pool)
    .await
    .unwrap();

    sqlx::query(
        r#"
        INSERT INTO instruments (
            id,
            instrument_type,
            player_id,
            symbol,
            display_name,
            current_price,
            shares_outstanding,
            price_impact_unit,
            trading_status
        ) VALUES (
            $1,
            'PLAYER_SHARE',
            $2,
            $3,
            'Smoke Test Player Share',
            $4,
            $5,
            $6,
            'ACTIVE'
        )
        "#,
    )
    .bind(instrument_id)
    .bind(player_id)
    .bind(format!("SMOKE-{suffix}"))
    .bind(Decimal::new(100_0000, 4))
    .bind(Decimal::new(1_000_000_000_000, 6))
    .bind(Decimal::new(10000, 6))
    .execute(pool)
    .await
    .unwrap();

    Fixture {
        account_id,
        portfolio_id,
        instrument_id,
    }
}
