use rust_decimal::Decimal;
use sqlx::PgPool;
use stockball_trading_engine::{
    execution::{execute_order, quote_order, ExecutionError},
    fees::TradingFee,
    freezes::{
        apply_freeze, release_freeze, ApplyFreezeCommand, FreezeReason, ReleaseFreezeCommand,
    },
    index_funds::{
        create_index_fund, CreateIndexFundCommand, IndexConstituent, IndexFundError, IndexKind,
        CUSTODY_ACCOUNT_ID, CUSTODY_PORTFOLIO_ID,
    },
    orders::{ExecuteOrderCommand, ExecutionLimits, OrderSide, QuoteOrderCommand},
};
use uuid::Uuid;

struct Trader {
    account_id: Uuid,
    portfolio_id: Uuid,
}

#[test]
fn index_funds_trade_their_basket() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap();

    runtime.block_on(index_funds_trade_their_basket_inner());
}

async fn index_funds_trade_their_basket_inner() {
    let Some(database_url) = test_database_url() else {
        eprintln!(
            "skipping index fund test; STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL is not set"
        );
        return;
    };
    let pool = PgPool::connect(&database_url).await.unwrap();
    let suffix = Uuid::new_v4().simple().to_string();
    let trader = insert_trader(&pool, &suffix).await;
    let players = [
        insert_player_share(&pool, &format!("{suffix}-a"), decimal("40")).await,
        insert_player_share(&pool, &format!("{suffix}-b"), decimal("10")).await,
    ];
    let symbol = format!("IDX-{suffix}");
    let command = CreateIndexFundCommand {
        symbol: symbol.clone(),
        display_name: "Test Club Index".to_owned(),
        index_kind: IndexKind::Team,
        club: Some(format!("Test Club {suffix}")),
        constituents: players
            .iter()
            .map(|instrument_id| IndexConstituent {
                instrument_id: *instrument_id,
                shares_per_unit: Decimal::ONE,
            })
            .collect(),
    };

    // A unit is priced at its basket's value, and asking again for the same fund is a no-op.
    let created = create_index_fund(&pool, command.clone()).await.unwrap();
    assert!(created.created);
    assert_eq!(created.unit_price, decimal("50"));
    let fund_id = created.instrument_id;
    let repeated = create_index_fund(&pool, command.clone()).await.unwrap();
    assert!(!repeated.created);
    assert_eq!(repeated.instrument_id, fund_id);
    let mut other_basket = command.clone();
    other_basket.constituents.pop();
    assert!(matches!(
        create_index_fund(&pool, other_basket).await,
        Err(IndexFundError::SymbolTaken(_))
    ));

    let custody_before = custody_quantities(&pool, &players).await;
    let buy = ExecuteOrderCommand {
        execution_limits: None,
        cash_limit: None,
        request_id: format!("fund-buy-{suffix}"),
        account_id: trader.account_id,
        portfolio_id: trader.portfolio_id,
        instrument_id: fund_id,
        side: OrderSide::Buy,
        quantity: decimal("2"),
    };
    let quote = quote_order(&pool, buy.clone(), TradingFee::NONE)
        .await
        .unwrap();
    assert_eq!(quote.old_price, decimal("50"));
    assert!(quote.new_price > quote.old_price);

    // Sized by cash, a fund quote spends as much of the amount as whole millionths of a unit
    // allow, fee included, and no more.
    let by_cash = quote_order(
        &pool,
        QuoteOrderCommand {
            quantity: None,
            cash_amount: Some(quote.gross_amount),
            ..QuoteOrderCommand::from(buy.clone())
        },
        TradingFee::DEFAULT,
    )
    .await
    .unwrap();
    assert!(by_cash.cash_amount.unwrap() <= quote.gross_amount);
    assert!(by_cash.quantity < decimal("2"));
    assert!(by_cash.quantity > decimal("1.98"));

    // Execution limits bind the quoted unit price, like they bind a player's price.
    let limited = ExecuteOrderCommand {
        execution_limits: Some(ExecutionLimits {
            expected_price: quote.old_price,
            expected_cash_balance: decimal("10000"),
            max_gross_amount: quote.gross_amount,
        }),
        cash_limit: None,
        ..buy.clone()
    };
    let bought = execute_order(&pool, limited.clone(), TradingFee::NONE)
        .await
        .unwrap();
    assert_eq!(bought.gross_amount, quote.gross_amount);
    assert_eq!(bought.position_quantity_after, decimal("2"));
    assert_eq!(
        bought.cash_balance_after,
        decimal("10000") - quote.gross_amount
    );
    assert_eq!(
        execute_order(&pool, limited, TradingFee::NONE)
            .await
            .unwrap(),
        bought
    );

    // The custody account bought two shares of each player through their own curves.
    let custody_after = custody_quantities(&pool, &players).await;
    for (before, after) in custody_before.iter().zip(&custody_after) {
        assert_eq!(*after - *before, decimal("2"));
    }
    let leg_cost = sqlx::query_scalar::<_, Decimal>(
        "SELECT SUM(gross_amount) FROM trades WHERE index_trade_id = $1 AND account_id = $2",
    )
    .bind(bought.trade_id)
    .bind(CUSTODY_ACCOUNT_ID)
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(leg_cost, bought.gross_amount);
    assert_eq!(
        unit_price(&pool, fund_id).await,
        basket_value(&pool, &players).await
    );
    assert_eq!(bought.new_price, unit_price(&pool, fund_id).await);

    // Trading a constituent directly reprices the fund.
    let before_player_trade = unit_price(&pool, fund_id).await;
    execute_order(
        &pool,
        ExecuteOrderCommand {
            execution_limits: None,
            cash_limit: None,
            request_id: format!("player-buy-{suffix}"),
            account_id: trader.account_id,
            portfolio_id: trader.portfolio_id,
            instrument_id: players[0],
            side: OrderSide::Buy,
            quantity: decimal("5"),
        },
        TradingFee::NONE,
    )
    .await
    .unwrap();
    let after_player_trade = unit_price(&pool, fund_id).await;
    assert!(after_player_trade > before_player_trade);
    assert_eq!(after_player_trade, basket_value(&pool, &players).await);
    let revaluations = sqlx::query_scalar::<_, i64>(
        "SELECT COUNT(*) FROM price_snapshots WHERE instrument_id = $1 AND reason = 'INDEX_REVALUATION'",
    )
    .bind(fund_id)
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(revaluations, 1);

    // A frozen constituent pauses the fund.
    let source_key = format!("fixture:{suffix}");
    apply_freeze(
        &pool,
        ApplyFreezeCommand {
            source_key: source_key.clone(),
            reason: FreezeReason::MatchDay,
            instrument_ids: vec![players[1]],
        },
    )
    .await
    .unwrap();
    let sell = ExecuteOrderCommand {
        execution_limits: None,
        cash_limit: None,
        request_id: format!("fund-sell-{suffix}"),
        account_id: trader.account_id,
        portfolio_id: trader.portfolio_id,
        instrument_id: fund_id,
        side: OrderSide::Sell,
        quantity: decimal("1.5"),
    };
    assert!(matches!(
        execute_order(&pool, sell.clone(), TradingFee::NONE).await,
        Err(ExecutionError::Freeze(_))
    ));
    release_freeze(&pool, ReleaseFreezeCommand { source_key })
        .await
        .unwrap();

    // Selling units sells the custody shares back and credits the trader.
    let sold = execute_order(&pool, sell, TradingFee::NONE).await.unwrap();
    assert_eq!(sold.position_quantity_after, decimal("0.5"));
    assert_eq!(
        sold.cash_balance_after,
        bought.cash_balance_after - player_trade_cost(&pool, &suffix).await + sold.gross_amount
    );
    let custody_after_sale = custody_quantities(&pool, &players).await;
    for (before, after) in custody_before.iter().zip(&custody_after_sale) {
        assert_eq!(*after - *before, decimal("0.5"));
    }
    assert_eq!(
        unit_price(&pool, fund_id).await,
        basket_value(&pool, &players).await
    );

    // Units cannot be sold beyond the trader's holding.
    let oversell = execute_order(
        &pool,
        ExecuteOrderCommand {
            execution_limits: None,
            cash_limit: None,
            request_id: format!("fund-oversell-{suffix}"),
            account_id: trader.account_id,
            portfolio_id: trader.portfolio_id,
            instrument_id: fund_id,
            side: OrderSide::Sell,
            quantity: decimal("1"),
        },
        TradingFee::NONE,
    )
    .await;
    assert!(matches!(oversell, Err(ExecutionError::Position(_))));
}

async fn unit_price(pool: &PgPool, instrument_id: Uuid) -> Decimal {
    sqlx::query_scalar::<_, Decimal>("SELECT current_price FROM instruments WHERE id = $1")
        .bind(instrument_id)
        .fetch_one(pool)
        .await
        .unwrap()
}

async fn basket_value(pool: &PgPool, players: &[Uuid]) -> Decimal {
    sqlx::query_scalar::<_, Decimal>(
        "SELECT ROUND(SUM(current_price), 12) FROM instruments WHERE id = ANY($1)",
    )
    .bind(players)
    .fetch_one(pool)
    .await
    .unwrap()
}

async fn custody_quantities(pool: &PgPool, players: &[Uuid]) -> Vec<Decimal> {
    let mut quantities = Vec::new();
    for player in players {
        let quantity = sqlx::query_scalar::<_, Decimal>(
            "SELECT quantity FROM positions WHERE portfolio_id = $1 AND instrument_id = $2",
        )
        .bind(CUSTODY_PORTFOLIO_ID)
        .bind(player)
        .fetch_optional(pool)
        .await
        .unwrap()
        .unwrap_or(Decimal::ZERO);
        quantities.push(quantity);
    }
    quantities
}

async fn player_trade_cost(pool: &PgPool, suffix: &str) -> Decimal {
    sqlx::query_scalar::<_, Decimal>(
        "SELECT t.gross_amount FROM trades t JOIN orders o ON o.id = t.order_id WHERE o.request_id = $1",
    )
    .bind(format!("player-buy-{suffix}"))
    .fetch_one(pool)
    .await
    .unwrap()
}

async fn insert_trader(pool: &PgPool, suffix: &str) -> Trader {
    let account_id = Uuid::new_v4();
    let portfolio_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO accounts (id, handle, display_name, account_type, status)
         VALUES ($1, $2, 'Index Fund Tester', 'USER', 'ACTIVE')",
    )
    .bind(account_id)
    .bind(format!("index-fund-{suffix}"))
    .execute(pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO portfolios (id, account_id, cash_balance) VALUES ($1, $2, 10000)")
        .bind(portfolio_id)
        .bind(account_id)
        .execute(pool)
        .await
        .unwrap();
    Trader {
        account_id,
        portfolio_id,
    }
}

async fn insert_player_share(pool: &PgPool, suffix: &str, price: Decimal) -> Uuid {
    let player_id = Uuid::new_v4();
    let instrument_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO players (id, provider, provider_player_id, display_name)
         VALUES ($1, 'index-fund-test', $2, 'Index Fund Test Player')",
    )
    .bind(player_id)
    .bind(suffix)
    .execute(pool)
    .await
    .unwrap();
    // A shallow curve, so the test's small trades visibly move prices.
    sqlx::query(
        "INSERT INTO instruments (
            id, instrument_type, player_id, symbol, display_name, current_price, reference_price,
            shares_outstanding, net_shares_purchased, full_supply_price_multiplier,
            curve_depth_shares, trading_status
        ) VALUES ($1, 'PLAYER_SHARE', $2, $3, 'Index Fund Test Player Share', $4, $4,
            1000000, 0, 20, 1000, 'ACTIVE')",
    )
    .bind(instrument_id)
    .bind(player_id)
    .bind(format!("IFT-{suffix}"))
    .bind(price)
    .execute(pool)
    .await
    .unwrap();
    instrument_id
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
