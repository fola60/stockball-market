use rust_decimal::{Decimal, RoundingStrategy};
use sqlx::PgPool;
use stockball_trading_engine::{
    delistings::{delist_instrument, DelistInstrumentCommand, DelistingError},
    execution::{execute_order, rebalance_index_fund, ExecutionError},
    freezes::{
        apply_freeze, release_freeze, ApplyFreezeCommand, FreezeReason, ReleaseFreezeCommand,
    },
    index_funds::{
        create_index_fund, CreateIndexFundCommand, IndexConstituent, IndexFundError, IndexKind,
        RebalanceIndexFundCommand, CUSTODY_PORTFOLIO_ID,
    },
    orders::{ExecuteOrderCommand, OrderSide},
};
use uuid::Uuid;

struct Trader {
    account_id: Uuid,
    portfolio_id: Uuid,
}

#[test]
fn funds_rebalance_to_new_members_and_absorb_delistings() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(inner());
}

async fn inner() {
    let Some(database_url) = test_database_url() else {
        eprintln!(
            "skipping rebalancing test; STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL is not set"
        );
        return;
    };
    let pool = PgPool::connect(&database_url).await.unwrap();
    let suffix = Uuid::new_v4().simple().to_string();
    let trader = insert_trader(&pool, &suffix).await;
    let [a, b, c, d, e] = [
        ("a", "40"),
        ("b", "20"),
        ("c", "10"),
        ("d", "30"),
        ("e", "15"),
    ]
    .map(|(name, price)| (format!("{suffix}-{name}"), decimal(price)));
    let a = insert_player_share(&pool, &a.0, a.1).await;
    let b = insert_player_share(&pool, &b.0, b.1).await;
    let c = insert_player_share(&pool, &c.0, c.1).await;
    let d = insert_player_share(&pool, &d.0, d.1).await;
    let e = insert_player_share(&pool, &e.0, e.1).await;

    let fund = create_index_fund(
        &pool,
        CreateIndexFundCommand {
            symbol: format!("IDX-R{suffix}"),
            display_name: "Rebalancing Index".to_owned(),
            index_kind: IndexKind::Team,
            club: Some(format!("Rebalancing Club {suffix}")),
            constituents: [a, b, c]
                .map(|instrument_id| IndexConstituent {
                    instrument_id,
                    shares_per_unit: Decimal::ONE,
                })
                .to_vec(),
        },
    )
    .await
    .unwrap()
    .instrument_id;
    order(
        &pool,
        &trader,
        fund,
        OrderSide::Buy,
        "4",
        &format!("{suffix}-buy"),
    )
    .await;
    // A direct holding in B, to be paid out when B is delisted.
    order(
        &pool,
        &trader,
        b,
        OrderSide::Buy,
        "3",
        &format!("{suffix}-buy-b"),
    )
    .await;

    // Swap C for D: custody sells C and the proceeds buy D, re-weighting A and B evenly.
    let swap = RebalanceIndexFundCommand {
        request_id: format!("{suffix}-swap"),
        instrument_id: fund,
        reason: "C left, D joined".to_owned(),
        members: vec![a, b, d],
    };
    let rebalanced = rebalance_index_fund(&pool, swap.clone()).await.unwrap();
    assert!(!rebalanced.replayed);
    assert_eq!(rebalanced.added_instrument_ids, vec![d]);
    assert_eq!(rebalanced.removed_instrument_ids, vec![c]);
    assert_eq!(rebalanced.units_outstanding, decimal("4"));
    let shares: Vec<Decimal> = rebalanced
        .constituents
        .iter()
        .map(|c| c.shares_per_unit)
        .collect();
    assert_eq!(shares.len(), 3);
    // Price impact costs a little, never more than a percent here.
    assert!(rebalanced.unit_price_after <= rebalanced.unit_price_before);
    assert!(rebalanced.unit_price_after > rebalanced.unit_price_before * decimal("0.99"));
    assert_eq!(
        unit_price(&pool, fund).await,
        basket_value(&pool, fund).await
    );
    assert_custody_covers_units(&pool, fund).await;
    assert_eq!(custody_quantity(&pool, c).await, Decimal::ZERO);
    let rebalance_trades =
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM trades WHERE index_rebalance_id = $1")
            .bind(rebalanced.rebalance_id)
            .fetch_one(&pool)
            .await
            .unwrap();
    assert!(rebalance_trades >= 2);

    // A retried request replays its record; the same request id for another fund is refused.
    let replayed = rebalance_index_fund(&pool, swap.clone()).await.unwrap();
    assert!(replayed.replayed);
    assert_eq!(replayed.rebalance_id, rebalanced.rebalance_id);
    assert!(matches!(
        rebalance_index_fund(
            &pool,
            RebalanceIndexFundCommand {
                instrument_id: Uuid::new_v4(),
                ..swap
            }
        )
        .await,
        Err(ExecutionError::IndexFund(IndexFundError::RequestMismatch(
            _
        )))
    ));

    // A trading share cannot be delisted.
    assert!(matches!(
        delist_instrument(
            &pool,
            DelistInstrumentCommand {
                instrument_id: b,
                reason: "left the league".to_owned()
            }
        )
        .await,
        Err(DelistingError::StillTrading(_))
    ));

    // B leaves the league: halted, then bought out at its last price.
    let b_price = price(&pool, b).await;
    let b_shares_per_unit = shares_per_unit(&pool, fund, b).await;
    let cash_before = trader_cash(&pool, &trader).await;
    let unit_price_before_delisting = unit_price(&pool, fund).await;
    let fund_cash_before_delisting = cash_per_unit(&pool, fund).await;
    halt(&pool, b, &format!("not-in-league:{suffix}")).await;
    let delisted = delist_instrument(
        &pool,
        DelistInstrumentCommand {
            instrument_id: b,
            reason: "left the league".to_owned(),
        },
    )
    .await
    .unwrap();
    assert!(!delisted.already_delisted);
    assert_eq!(delisted.settlement_price, b_price);
    assert_eq!(delisted.index_funds_updated, vec![fund]);
    assert_eq!(
        trader_cash(&pool, &trader).await - cash_before,
        (decimal("3") * b_price).round_dp(12)
    );
    assert_eq!(custody_quantity(&pool, b).await, Decimal::ZERO);
    assert_eq!(
        cash_per_unit(&pool, fund).await,
        (fund_cash_before_delisting + b_shares_per_unit * b_price)
            .round_dp_with_strategy(12, RoundingStrategy::ToZero)
    );
    // The share becomes cash at its own price; rounding the cash down costs at most 1e-12.
    let after = unit_price(&pool, fund).await;
    assert!(unit_price_before_delisting - after <= decimal("0.000000000001"));
    assert!(after <= unit_price_before_delisting);
    assert_eq!(basket_value(&pool, fund).await, after);
    let (status, symbol): (String, String) =
        sqlx::query_as("SELECT trading_status, symbol FROM instruments WHERE id = $1")
            .bind(b)
            .fetch_one(&pool)
            .await
            .unwrap();
    assert_eq!(status, "DELISTED");
    assert!(symbol.contains("-DL"));
    let again = delist_instrument(
        &pool,
        DelistInstrumentCommand {
            instrument_id: b,
            reason: "left the league".to_owned(),
        },
    )
    .await
    .unwrap();
    assert!(again.already_delisted);

    // Units now carry cash: buying one pays it into custody, and custody still covers it all.
    order(
        &pool,
        &trader,
        fund,
        OrderSide::Buy,
        "1",
        &format!("{suffix}-buy-cash"),
    )
    .await;
    assert_custody_covers_units(&pool, fund).await;

    // A is paused for a match while the fund adds E and spends its cash: A keeps its shares.
    let a_shares = shares_per_unit(&pool, fund, a).await;
    let source_key = format!("fixture:{suffix}");
    apply_freeze(
        &pool,
        ApplyFreezeCommand {
            source_key: source_key.clone(),
            reason: FreezeReason::MatchDay,
            instrument_ids: vec![a],
        },
    )
    .await
    .unwrap();
    let spent = rebalance_index_fund(
        &pool,
        RebalanceIndexFundCommand {
            request_id: format!("{suffix}-add-e"),
            instrument_id: fund,
            reason: "E joined".to_owned(),
            members: vec![a, d, e],
        },
    )
    .await
    .unwrap();
    assert_eq!(spent.added_instrument_ids, vec![e]);
    assert_eq!(shares_per_unit(&pool, fund, a).await, a_shares);
    assert!(spent.cash_per_unit_after < cash_per_unit_after_delisting(&pool, fund, &suffix).await);
    assert_custody_covers_units(&pool, fund).await;
    release_freeze(&pool, ReleaseFreezeCommand { source_key })
        .await
        .unwrap();

    // Selling every unit pays the basket and cash out and leaves custody covered.
    order(
        &pool,
        &trader,
        fund,
        OrderSide::Sell,
        "5",
        &format!("{suffix}-sell"),
    )
    .await;
    assert_custody_covers_units(&pool, fund).await;
    let custody_cash =
        sqlx::query_scalar::<_, Decimal>("SELECT cash_balance FROM portfolios WHERE id = $1")
            .bind(CUSTODY_PORTFOLIO_ID)
            .fetch_one(&pool)
            .await
            .unwrap();
    assert!(custody_cash >= Decimal::ZERO);

    // With no units in issue nothing trades: the basket is rewritten at current prices.
    let rewritten = rebalance_index_fund(
        &pool,
        RebalanceIndexFundCommand {
            request_id: format!("{suffix}-empty"),
            instrument_id: fund,
            reason: "squad review".to_owned(),
            members: vec![d, e],
        },
    )
    .await
    .unwrap();
    assert_eq!(rewritten.units_outstanding, Decimal::ZERO);
    assert_eq!(rewritten.cash_per_unit_after, Decimal::ZERO);
    assert_eq!(rewritten.constituents.len(), 2);
}

/// The cash a unit held straight after B's buyout, read from its delisting record.
async fn cash_per_unit_after_delisting(pool: &PgPool, fund: Uuid, _suffix: &str) -> Decimal {
    sqlx::query_scalar::<_, Decimal>(
        "SELECT cash_per_unit_after FROM index_fund_rebalances
         WHERE index_instrument_id = $1 AND kind = 'DELISTING'",
    )
    .bind(fund)
    .fetch_one(pool)
    .await
    .unwrap()
}

async fn assert_custody_covers_units(pool: &PgPool, fund: Uuid) {
    let shortfall = sqlx::query_scalar::<_, i64>(
        "SELECT COUNT(*)
         FROM index_constituents AS c
         LEFT JOIN positions AS p
             ON p.portfolio_id = $2 AND p.instrument_id = c.constituent_instrument_id
         WHERE c.index_instrument_id = $1
           AND COALESCE(p.quantity, 0) < c.shares_per_unit
               * (SELECT COALESCE(SUM(quantity), 0) FROM positions WHERE instrument_id = $1)",
    )
    .bind(fund)
    .bind(CUSTODY_PORTFOLIO_ID)
    .fetch_one(pool)
    .await
    .unwrap();
    assert_eq!(
        shortfall, 0,
        "custody holds fewer shares than the units in issue need"
    );
}

async fn order(
    pool: &PgPool,
    trader: &Trader,
    instrument_id: Uuid,
    side: OrderSide,
    quantity: &str,
    request_id: &str,
) {
    execute_order(
        pool,
        ExecuteOrderCommand {
            execution_limits: None,
            request_id: request_id.to_owned(),
            account_id: trader.account_id,
            portfolio_id: trader.portfolio_id,
            instrument_id,
            side,
            quantity: decimal(quantity),
        },
    )
    .await
    .unwrap();
}

async fn halt(pool: &PgPool, instrument_id: Uuid, source_key: &str) {
    apply_freeze(
        pool,
        ApplyFreezeCommand {
            source_key: source_key.to_owned(),
            reason: FreezeReason::AdminHalt,
            instrument_ids: vec![instrument_id],
        },
    )
    .await
    .unwrap();
}

async fn price(pool: &PgPool, instrument_id: Uuid) -> Decimal {
    unit_price(pool, instrument_id).await
}

async fn unit_price(pool: &PgPool, instrument_id: Uuid) -> Decimal {
    sqlx::query_scalar::<_, Decimal>("SELECT current_price FROM instruments WHERE id = $1")
        .bind(instrument_id)
        .fetch_one(pool)
        .await
        .unwrap()
}

async fn basket_value(pool: &PgPool, fund: Uuid) -> Decimal {
    sqlx::query_scalar::<_, Decimal>(
        "SELECT ROUND(COALESCE(SUM(c.shares_per_unit * i.current_price), 0), 12) + f.cash_per_unit
         FROM index_funds f
         LEFT JOIN index_constituents c ON c.index_instrument_id = f.instrument_id
         LEFT JOIN instruments i ON i.id = c.constituent_instrument_id
         WHERE f.instrument_id = $1
         GROUP BY f.cash_per_unit",
    )
    .bind(fund)
    .fetch_one(pool)
    .await
    .unwrap()
}

async fn cash_per_unit(pool: &PgPool, fund: Uuid) -> Decimal {
    sqlx::query_scalar::<_, Decimal>(
        "SELECT cash_per_unit FROM index_funds WHERE instrument_id = $1",
    )
    .bind(fund)
    .fetch_one(pool)
    .await
    .unwrap()
}

async fn shares_per_unit(pool: &PgPool, fund: Uuid, instrument_id: Uuid) -> Decimal {
    sqlx::query_scalar::<_, Decimal>(
        "SELECT shares_per_unit FROM index_constituents
         WHERE index_instrument_id = $1 AND constituent_instrument_id = $2",
    )
    .bind(fund)
    .bind(instrument_id)
    .fetch_one(pool)
    .await
    .unwrap()
}

async fn custody_quantity(pool: &PgPool, instrument_id: Uuid) -> Decimal {
    sqlx::query_scalar::<_, Decimal>(
        "SELECT quantity FROM positions WHERE portfolio_id = $1 AND instrument_id = $2",
    )
    .bind(CUSTODY_PORTFOLIO_ID)
    .bind(instrument_id)
    .fetch_optional(pool)
    .await
    .unwrap()
    .unwrap_or(Decimal::ZERO)
}

async fn trader_cash(pool: &PgPool, trader: &Trader) -> Decimal {
    sqlx::query_scalar::<_, Decimal>("SELECT cash_balance FROM portfolios WHERE id = $1")
        .bind(trader.portfolio_id)
        .fetch_one(pool)
        .await
        .unwrap()
}

async fn insert_trader(pool: &PgPool, suffix: &str) -> Trader {
    let account_id = Uuid::new_v4();
    let portfolio_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO accounts (id, handle, display_name, account_type, status)
         VALUES ($1, $2, 'Rebalance Tester', 'USER', 'ACTIVE')",
    )
    .bind(account_id)
    .bind(format!("rebalance-{suffix}"))
    .execute(pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO portfolios (id, account_id, cash_balance) VALUES ($1, $2, 100000)")
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
         VALUES ($1, 'rebalance-test', $2, 'Rebalance Test Player')",
    )
    .bind(player_id)
    .bind(suffix)
    .execute(pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO instruments (
            id, instrument_type, player_id, symbol, display_name, current_price, reference_price,
            shares_outstanding, net_shares_purchased, full_supply_price_multiplier,
            curve_depth_shares, trading_status
        ) VALUES ($1, 'PLAYER_SHARE', $2, $3, 'Rebalance Test Share', $4, $4,
            1000000, 0, 20, 5000, 'ACTIVE')",
    )
    .bind(instrument_id)
    .bind(player_id)
    .bind(format!("RBT-{suffix}"))
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
