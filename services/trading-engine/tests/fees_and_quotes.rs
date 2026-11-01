//! Trading fees, cost basis, cash-sized quotes, price protection, and lock-free quoting.

use std::time::Duration;

use rust_decimal::Decimal;
use sqlx::PgPool;
use stockball_trading_engine::{
    execution::{execute_order, quote_order, ExecutionError},
    fees::TradingFee,
    orders::{ExecuteOrderCommand, OrderError, OrderSide, QuoteOrderCommand},
    provisioning::{apply_opening_balance, ApplyOpeningBalanceCommand},
};
use uuid::Uuid;

struct Fixture {
    account_id: Uuid,
    portfolio_id: Uuid,
    instrument_id: Uuid,
}

impl Fixture {
    fn order(&self, side: OrderSide, quantity: Decimal) -> ExecuteOrderCommand {
        ExecuteOrderCommand {
            execution_limits: None,
            request_id: format!("fee-test-{}", Uuid::new_v4()),
            account_id: self.account_id,
            portfolio_id: self.portfolio_id,
            instrument_id: self.instrument_id,
            side,
            quantity,
            cash_limit: None,
        }
    }

    fn cash_quote(&self, side: OrderSide, cash_amount: Decimal) -> QuoteOrderCommand {
        QuoteOrderCommand {
            request_id: String::new(),
            account_id: self.account_id,
            portfolio_id: self.portfolio_id,
            instrument_id: self.instrument_id,
            side,
            quantity: None,
            cash_amount: Some(cash_amount),
        }
    }
}

#[test]
fn fees_cost_basis_and_quotes() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async {
        let Some(database_url) = test_database_url() else {
            eprintln!("skipping fee tests; STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL is not set");
            return;
        };
        let pool = PgPool::connect(&database_url).await.unwrap();

        charges_the_fee_and_tracks_cost_basis(&pool).await;
        a_round_trip_loses_the_fees(&pool).await;
        quotes_by_cash_spend_the_whole_balance(&pool).await;
        cash_quoted_sales_raise_the_amount(&pool).await;
        price_protection_refuses_a_moved_market(&pool).await;
        quotes_do_not_wait_for_locked_rows(&pool).await;
    });
}

async fn charges_the_fee_and_tracks_cost_basis(pool: &PgPool) {
    let fixture = insert_fixture(pool, Decimal::from(100_000)).await;
    assert_eq!(
        contributed_capital(pool, &fixture).await,
        Decimal::from(100_000)
    );

    let buy = execute_order(
        pool,
        fixture.order(OrderSide::Buy, Decimal::from(10)),
        TradingFee::DEFAULT,
    )
    .await
    .unwrap();
    let fee = TradingFee::DEFAULT.fee_for(buy.gross_amount);
    assert_eq!(buy.fee_amount, fee);
    assert_eq!(buy.cash_amount, Some(buy.gross_amount + fee));
    assert_eq!(
        buy.cash_balance_after,
        Decimal::from(100_000) - buy.gross_amount - fee
    );

    let (cost_basis, realized) = position_costs(pool, &fixture).await;
    assert_eq!(cost_basis, buy.gross_amount + fee);
    assert_eq!(realized, Decimal::ZERO);

    let stored_fee = sqlx::query_scalar::<_, Decimal>(
        "SELECT amount_delta FROM cash_ledger_entries WHERE trade_id = $1 AND reason = 'TRADE_FEE'",
    )
    .bind(buy.trade_id)
    .fetch_one(pool)
    .await
    .unwrap();
    assert_eq!(stored_fee, -fee);

    let sell = execute_order(
        pool,
        fixture.order(OrderSide::Sell, Decimal::from(4)),
        TradingFee::DEFAULT,
    )
    .await
    .unwrap();
    let proceeds = sell.gross_amount - TradingFee::DEFAULT.fee_for(sell.gross_amount);
    assert_eq!(sell.cash_amount, Some(proceeds));

    let removed = (cost_basis * Decimal::from(4) / Decimal::from(10)).round_dp(12);
    let (cost_after, realized_after) = position_costs(pool, &fixture).await;
    assert_eq!(cost_after, cost_basis - removed);
    assert_eq!(realized_after, proceeds - removed);
    assert_eq!(
        contributed_capital(pool, &fixture).await,
        Decimal::from(100_000),
        "trading never changes the capital a portfolio was given"
    );
}

async fn a_round_trip_loses_the_fees(pool: &PgPool) {
    let fixture = insert_fixture(pool, Decimal::from(100_000)).await;
    let quantity = Decimal::from(250);
    let buy = execute_order(
        pool,
        fixture.order(OrderSide::Buy, quantity),
        TradingFee::DEFAULT,
    )
    .await
    .unwrap();
    let sell = execute_order(
        pool,
        fixture.order(OrderSide::Sell, quantity),
        TradingFee::DEFAULT,
    )
    .await
    .unwrap();

    assert_eq!(sell.gross_amount, buy.gross_amount);
    assert_eq!(
        sell.cash_balance_after,
        Decimal::from(100_000) - buy.fee_amount - sell.fee_amount
    );
    let (cost_basis, realized) = position_costs(pool, &fixture).await;
    assert_eq!(cost_basis, Decimal::ZERO);
    assert_eq!(realized, -(buy.fee_amount + sell.fee_amount));
}

async fn quotes_by_cash_spend_the_whole_balance(pool: &PgPool) {
    let fixture = insert_fixture(pool, Decimal::from(100_000)).await;
    let quote = quote_order(
        pool,
        fixture.cash_quote(OrderSide::Buy, Decimal::from(100_000)),
        TradingFee::DEFAULT,
    )
    .await
    .unwrap();
    let cash_amount = quote.cash_amount.unwrap();

    assert!(cash_amount <= Decimal::from(100_000));
    assert!(
        Decimal::from(100_000) - cash_amount < Decimal::new(1, 2),
        "the quote should use all but a fraction of a penny: {cash_amount}"
    );

    let order = ExecuteOrderCommand {
        cash_limit: Some(Decimal::from(100_000)),
        ..fixture.order(OrderSide::Buy, quote.quantity)
    };
    let bought = execute_order(pool, order, TradingFee::DEFAULT)
        .await
        .unwrap();
    assert_eq!(bought.cash_amount, Some(cash_amount));
    assert_eq!(
        bought.cash_balance_after,
        Decimal::from(100_000) - cash_amount
    );
}

async fn cash_quoted_sales_raise_the_amount(pool: &PgPool) {
    let fixture = insert_fixture(pool, Decimal::from(100_000)).await;
    execute_order(
        pool,
        fixture.order(OrderSide::Buy, Decimal::from(100)),
        TradingFee::DEFAULT,
    )
    .await
    .unwrap();

    let quote = quote_order(
        pool,
        fixture.cash_quote(OrderSide::Sell, Decimal::from(2_500)),
        TradingFee::DEFAULT,
    )
    .await
    .unwrap();
    assert!(quote.cash_amount.unwrap() >= Decimal::from(2_500));
    assert!(quote.quantity < Decimal::from(100));

    let everything = quote_order(
        pool,
        fixture.cash_quote(OrderSide::Sell, Decimal::from(1_000_000)),
        TradingFee::DEFAULT,
    )
    .await
    .unwrap();
    assert_eq!(
        everything.quantity,
        Decimal::from(100),
        "asking for more than the position raises sells all of it"
    );
}

async fn price_protection_refuses_a_moved_market(pool: &PgPool) {
    let fixture = insert_fixture(pool, Decimal::from(100_000)).await;
    let other = insert_trader(pool, fixture.instrument_id, Decimal::from(100_000)).await;
    let quote = quote_order(
        pool,
        fixture.cash_quote(OrderSide::Buy, Decimal::from(5_000)),
        TradingFee::DEFAULT,
    )
    .await
    .unwrap();

    execute_order(
        pool,
        other.order(OrderSide::Buy, Decimal::from(500)),
        TradingFee::DEFAULT,
    )
    .await
    .unwrap();

    let protected = ExecuteOrderCommand {
        cash_limit: quote.cash_amount,
        ..fixture.order(OrderSide::Buy, quote.quantity)
    };
    let error = execute_order(pool, protected, TradingFee::DEFAULT)
        .await
        .unwrap_err();
    assert!(matches!(
        error,
        ExecutionError::Order(OrderError::CashLimitExceeded { .. })
    ));
    assert_eq!(
        cash_balance(pool, &fixture).await,
        Decimal::from(100_000),
        "a refused order moves no cash"
    );
}

async fn quotes_do_not_wait_for_locked_rows(pool: &PgPool) {
    let fixture = insert_fixture(pool, Decimal::from(100_000)).await;
    let mut locker = pool.begin().await.unwrap();
    sqlx::query("SELECT id FROM instruments WHERE id = $1 FOR UPDATE")
        .bind(fixture.instrument_id)
        .execute(&mut *locker)
        .await
        .unwrap();
    sqlx::query("SELECT id FROM portfolios WHERE id = $1 FOR UPDATE")
        .bind(fixture.portfolio_id)
        .execute(&mut *locker)
        .await
        .unwrap();

    let quote = tokio::time::timeout(
        Duration::from_secs(5),
        quote_order(
            pool,
            fixture.cash_quote(OrderSide::Buy, Decimal::from(1_000)),
            TradingFee::DEFAULT,
        ),
    )
    .await
    .expect("a quote must not wait for rows an order has locked");
    assert!(quote.is_ok());
    locker.rollback().await.unwrap();
}

async fn position_costs(pool: &PgPool, fixture: &Fixture) -> (Decimal, Decimal) {
    sqlx::query_as::<_, (Decimal, Decimal)>(
        "SELECT cost_basis, realized_pnl FROM positions WHERE portfolio_id = $1 AND instrument_id = $2",
    )
    .bind(fixture.portfolio_id)
    .bind(fixture.instrument_id)
    .fetch_one(pool)
    .await
    .unwrap()
}

async fn contributed_capital(pool: &PgPool, fixture: &Fixture) -> Decimal {
    sqlx::query_scalar::<_, Decimal>("SELECT contributed_capital FROM portfolios WHERE id = $1")
        .bind(fixture.portfolio_id)
        .fetch_one(pool)
        .await
        .unwrap()
}

async fn cash_balance(pool: &PgPool, fixture: &Fixture) -> Decimal {
    sqlx::query_scalar::<_, Decimal>("SELECT cash_balance FROM portfolios WHERE id = $1")
        .bind(fixture.portfolio_id)
        .fetch_one(pool)
        .await
        .unwrap()
}

/// A player share at £100 and a trader holding `cash` given as an opening balance.
async fn insert_fixture(pool: &PgPool, cash: Decimal) -> Fixture {
    let player_id = Uuid::new_v4();
    let instrument_id = Uuid::new_v4();
    let suffix = Uuid::new_v4();

    sqlx::query(
        "INSERT INTO players (id, provider, provider_player_id, display_name)
         VALUES ($1, 'fee-test', $2, 'Fee Test Player')",
    )
    .bind(player_id)
    .bind(suffix.to_string())
    .execute(pool)
    .await
    .unwrap();

    sqlx::query(
        r#"
        INSERT INTO instruments (
            id, instrument_type, player_id, symbol, display_name, current_price,
            reference_price, shares_outstanding, net_shares_purchased,
            full_supply_price_multiplier, trading_status
        ) VALUES ($1, 'PLAYER_SHARE', $2, $3, 'Fee Test Player Share', 100, 100, 1000000, 0, 20, 'ACTIVE')
        "#,
    )
    .bind(instrument_id)
    .bind(player_id)
    .bind(format!("FEE-{suffix}"))
    .execute(pool)
    .await
    .unwrap();

    insert_trader(pool, instrument_id, cash).await
}

async fn insert_trader(pool: &PgPool, instrument_id: Uuid, cash: Decimal) -> Fixture {
    let account_id = Uuid::new_v4();
    let portfolio_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO accounts (id, handle, display_name, account_type, status)
         VALUES ($1, $2, 'Fee Test User', 'USER', 'ACTIVE')",
    )
    .bind(account_id)
    .bind(format!("fee-{account_id}"))
    .execute(pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO portfolios (id, account_id, cash_balance) VALUES ($1, $2, 0)")
        .bind(portfolio_id)
        .bind(account_id)
        .execute(pool)
        .await
        .unwrap();
    apply_opening_balance(
        pool,
        ApplyOpeningBalanceCommand {
            request_id: format!("opening-{portfolio_id}"),
            account_id,
            portfolio_id,
            amount: cash,
        },
    )
    .await
    .unwrap();

    Fixture {
        account_id,
        portfolio_id,
        instrument_id,
    }
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
