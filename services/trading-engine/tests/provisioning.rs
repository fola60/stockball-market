use rust_decimal::Decimal;
use sqlx::PgPool;
use stockball_trading_engine::{
    ledger::LedgerReason,
    provisioning::{
        apply_opening_balance, issue_initial_supply, set_pre_market_price,
        ApplyOpeningBalanceCommand, InitialSupplyAllocation, IssueInitialSupplyCommand,
        ProvisioningError, SetPreMarketPriceCommand,
    },
};
use uuid::Uuid;

#[test]
fn provisions_opening_balance_supply_and_pre_market_price() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap();

    runtime.block_on(async {
        provisions_opening_balance_supply_and_pre_market_price_inner().await;
    });
}

async fn provisions_opening_balance_supply_and_pre_market_price_inner() {
    let Some(database_url) = test_database_url() else {
        eprintln!(
            "skipping provisioning test; STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL is not set"
        );
        return;
    };

    let pool = PgPool::connect(&database_url).await.unwrap();
    let (first_account, first_portfolio) = insert_account(&pool).await;
    let (_, second_portfolio) = insert_account(&pool).await;
    let instrument_id = insert_pre_market_instrument(&pool, Decimal::new(10, 0)).await;

    // Opening balance: credited once, replayed on retry, refused under a new request id.
    let opening = ApplyOpeningBalanceCommand {
        request_id: format!("opening-balance:{first_account}"),
        account_id: first_account,
        portfolio_id: first_portfolio,
        amount: Decimal::new(100_000, 0),
    };
    let entry = apply_opening_balance(&pool, opening.clone()).await.unwrap();
    assert_eq!(entry.reason, LedgerReason::OpeningBalance);
    assert_eq!(entry.balance_after, Decimal::new(100_000, 0));
    let replayed = apply_opening_balance(&pool, opening.clone()).await.unwrap();
    assert_eq!(replayed.id, entry.id);
    let second_credit = apply_opening_balance(
        &pool,
        ApplyOpeningBalanceCommand {
            request_id: format!("opening-balance-retry:{first_account}"),
            ..opening
        },
    )
    .await
    .unwrap_err();
    assert!(matches!(second_credit, ProvisioningError::Ledger(_)));
    assert_eq!(
        cash_balance(&pool, first_portfolio).await,
        Decimal::new(100_000, 0)
    );

    // Pre-market price: re-anchors price and reference price and records a snapshot.
    let repriced = set_pre_market_price(
        &pool,
        SetPreMarketPriceCommand {
            request_id: format!("pre-market-price:{instrument_id}"),
            instrument_id,
            new_price: Decimal::new(1250, 2),
        },
    )
    .await
    .unwrap();
    assert_eq!(repriced.old_price, Decimal::new(100, 0));
    let (current_price, reference_price) = instrument_prices(&pool, instrument_id).await;
    assert_eq!(current_price, Decimal::new(1250, 2));
    assert_eq!(reference_price, Decimal::new(1250, 2));
    assert_eq!(admin_snapshot_count(&pool, instrument_id).await, 1);

    // Initial supply: must cover shares outstanding exactly.
    let short = issue_initial_supply(
        &pool,
        IssueInitialSupplyCommand {
            request_id: format!("initial-supply-short:{instrument_id}"),
            allocations: vec![allocation(instrument_id, first_portfolio, 4)],
        },
    )
    .await
    .unwrap_err();
    assert!(matches!(short, ProvisioningError::SupplyMismatch { .. }));

    let issued = issue_initial_supply(
        &pool,
        IssueInitialSupplyCommand {
            request_id: format!("initial-supply:{instrument_id}"),
            allocations: vec![
                allocation(instrument_id, first_portfolio, 4),
                allocation(instrument_id, second_portfolio, 6),
            ],
        },
    )
    .await
    .unwrap();
    assert_eq!(issued.instrument_count, 1);
    assert_eq!(issued.position_count, 2);
    assert_eq!(held_supply(&pool, instrument_id).await, Decimal::new(10, 0));

    // Once shares are held the instrument has left pre-market and cannot be repriced.
    let late_reprice = set_pre_market_price(
        &pool,
        SetPreMarketPriceCommand {
            request_id: format!("pre-market-price-late:{instrument_id}"),
            instrument_id,
            new_price: Decimal::new(20, 0),
        },
    )
    .await
    .unwrap_err();
    assert!(matches!(
        late_reprice,
        ProvisioningError::MarketActivityExists(id) if id == instrument_id
    ));
}

fn allocation(instrument_id: Uuid, portfolio_id: Uuid, quantity: i64) -> InitialSupplyAllocation {
    InitialSupplyAllocation {
        instrument_id,
        portfolio_id,
        quantity: Decimal::new(quantity, 0),
    }
}

async fn insert_account(pool: &PgPool) -> (Uuid, Uuid) {
    let account_id = Uuid::new_v4();
    let portfolio_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO accounts (id, handle, display_name, account_type, status) \
         VALUES ($1, $2, 'Provisioning Test', 'USER', 'ACTIVE')",
    )
    .bind(account_id)
    .bind(format!("provisioning-{account_id}"))
    .execute(pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO portfolios (id, account_id) VALUES ($1, $2)")
        .bind(portfolio_id)
        .bind(account_id)
        .execute(pool)
        .await
        .unwrap();
    (account_id, portfolio_id)
}

async fn insert_pre_market_instrument(pool: &PgPool, shares_outstanding: Decimal) -> Uuid {
    let player_id = Uuid::new_v4();
    let instrument_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO players (id, provider, provider_player_id, display_name) \
         VALUES ($1, 'provisioning-test', $2, 'Provisioning Test Player')",
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
        ) VALUES ($1, 'PLAYER_SHARE', $2, $3, 'Provisioning Test Share', 100, 100, $4, 0, 2.5, 'ACTIVE')
        "#,
    )
    .bind(instrument_id)
    .bind(player_id)
    .bind(format!("PROVISION-{instrument_id}"))
    .bind(shares_outstanding)
    .execute(pool)
    .await
    .unwrap();
    instrument_id
}

async fn cash_balance(pool: &PgPool, portfolio_id: Uuid) -> Decimal {
    sqlx::query_scalar("SELECT cash_balance FROM portfolios WHERE id = $1")
        .bind(portfolio_id)
        .fetch_one(pool)
        .await
        .unwrap()
}

async fn instrument_prices(pool: &PgPool, instrument_id: Uuid) -> (Decimal, Decimal) {
    sqlx::query_as("SELECT current_price, reference_price FROM instruments WHERE id = $1")
        .bind(instrument_id)
        .fetch_one(pool)
        .await
        .unwrap()
}

async fn admin_snapshot_count(pool: &PgPool, instrument_id: Uuid) -> i64 {
    sqlx::query_scalar(
        "SELECT COUNT(*) FROM price_snapshots WHERE instrument_id = $1 AND reason = 'ADMIN_ADJUSTMENT'",
    )
    .bind(instrument_id)
    .fetch_one(pool)
    .await
    .unwrap()
}

async fn held_supply(pool: &PgPool, instrument_id: Uuid) -> Decimal {
    sqlx::query_scalar("SELECT COALESCE(SUM(quantity), 0) FROM positions WHERE instrument_id = $1")
        .bind(instrument_id)
        .fetch_one(pool)
        .await
        .unwrap()
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
