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
    let Some(database_url) = test_database_url() else {
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

    assert_eq!(buy.execution_price, decimal("100.000458146765"));
    assert_eq!(buy.gross_amount, decimal("1000.004581467652"));
    assert_eq!(buy.cash_balance_after, decimal("98999.995418532348"));
    assert_eq!(buy.position_quantity_after, Decimal::new(10, 0));
    assert_eq!(buy.old_price, decimal("100.000000000000"));
    assert_eq!(buy.new_price, decimal("100.000916294930"));

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

    assert_eq!(sell.execution_price, decimal("100.000733035328"));
    assert_eq!(sell.gross_amount, decimal("400.002932141312"));
    assert_eq!(sell.cash_balance_after, decimal("99399.998350673660"));
    assert_eq!(sell.position_quantity_after, Decimal::new(6, 0));
    assert_eq!(sell.old_price, decimal("100.000916294930"));
    assert_eq!(sell.new_price, decimal("100.000549775950"));

    let unsafe_price_update = sqlx::query(
        r#"
        UPDATE instruments
        SET current_price = 110
        WHERE id = $1
        "#,
    )
    .bind(fixture.instrument_id)
    .execute(&pool)
    .await;
    assert!(unsafe_price_update.is_err());

    sqlx::query(
        r#"
        UPDATE instruments
        SET
            current_price = 110,
            reference_price = 110,
            net_shares_purchased = 0,
            full_supply_price_multiplier = 3
        WHERE id = $1
        "#,
    )
    .bind(fixture.instrument_id)
    .execute(&pool)
    .await
    .unwrap();

    let rebase_count = sqlx::query_scalar::<_, i64>(
        r#"
        SELECT COUNT(*)
        FROM instrument_price_curve_rebases
        WHERE instrument_id = $1
        "#,
    )
    .bind(fixture.instrument_id)
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(rebase_count, 1);
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
            reference_price,
            shares_outstanding,
            net_shares_purchased,
            full_supply_price_multiplier,
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
            0,
            2.500000,
            'ACTIVE'
        )
        "#,
    )
    .bind(instrument_id)
    .bind(player_id)
    .bind(format!("SMOKE-{suffix}"))
    .bind(Decimal::new(100_0000, 4))
    .bind(Decimal::new(100_0000, 4))
    .bind(Decimal::new(1_000_000_000_000, 6))
    .execute(pool)
    .await
    .unwrap();

    Fixture {
        account_id,
        portfolio_id,
        instrument_id,
    }
}

fn decimal(value: &str) -> Decimal {
    value.parse().unwrap()
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
