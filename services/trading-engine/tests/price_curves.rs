use rust_decimal::{Decimal, MathematicalOps};
use sqlx::PgPool;
use stockball_trading_engine::{
    execution::execute_order,
    orders::{ExecuteOrderCommand, OrderSide},
    price_impact::CurveCalibration,
    provisioning::{recalibrate_price_curves, ProvisioningError, RecalibratePriceCurvesCommand},
};
use uuid::Uuid;

const SUPPLY: i64 = 1_500_000;

#[test]
fn recalibration_rebases_curves_without_moving_prices() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap();

    runtime.block_on(async {
        recalibration_rebases_curves_without_moving_prices_inner().await;
    });
}

async fn recalibration_rebases_curves_without_moving_prices_inner() {
    let Some(database_url) = test_database_url() else {
        eprintln!(
            "skipping price curve test; STOCKBALL_TRADING_ENGINE_TEST_DATABASE_URL is not set"
        );
        return;
    };

    let pool = PgPool::connect(&database_url).await.unwrap();
    let (account_id, portfolio_id, instrument_id) = insert_fixture(&pool).await;

    // Inserted without a depth: the curve spans the full supply, as before.
    let before = curve(&pool, instrument_id).await;
    assert_eq!(before.depth, Decimal::from(SUPPLY));

    // Accumulate net demand on the old curve.
    buy(&pool, account_id, portfolio_id, instrument_id, 10_000).await;
    let traded = curve(&pool, instrument_id).await;
    assert_eq!(traded.net, Decimal::from(10_000));
    assert!(traded.current > traded.reference);

    let calibration = CurveCalibration {
        full_supply_price_multiplier: Decimal::from(20),
        curve_depth_divisor: Decimal::from(15),
    };
    let request_id = format!("curve-recalibration-{}", Uuid::new_v4());
    let command = RecalibratePriceCurvesCommand {
        request_id: request_id.clone(),
        calibration,
        reason: "integration test".to_owned(),
        dry_run: true,
    };

    // A dry run reports what would happen and changes nothing.
    let dry_run = recalibrate_price_curves(&pool, command.clone())
        .await
        .unwrap();
    assert!(dry_run.dry_run);
    assert!(dry_run.instrument_count >= 1);
    assert!(dry_run.reset_net_demand_count >= 1);
    assert_eq!(curve(&pool, instrument_id).await, traded);

    let applied = recalibrate_price_curves(
        &pool,
        RecalibratePriceCurvesCommand {
            dry_run: false,
            ..command.clone()
        },
    )
    .await
    .unwrap();
    assert!(!applied.dry_run);

    // The price stays put; the curve is re-anchored there with the new shape.
    let rebased = curve(&pool, instrument_id).await;
    assert_eq!(rebased.current, traded.current);
    assert_eq!(rebased.reference, traded.current);
    assert_eq!(rebased.net, Decimal::ZERO);
    assert_eq!(rebased.multiplier, Decimal::from(20));
    assert_eq!(rebased.depth, Decimal::from(SUPPLY / 15));

    let audit: (Decimal, Decimal, Decimal, Decimal) = sqlx::query_as(
        "SELECT old_curve_depth_shares, new_curve_depth_shares, old_net_shares_purchased, \
         new_full_supply_price_multiplier FROM instrument_price_curve_rebases \
         WHERE instrument_id = $1 ORDER BY changed_at DESC LIMIT 1",
    )
    .bind(instrument_id)
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(
        audit,
        (
            Decimal::from(SUPPLY),
            Decimal::from(SUPPLY / 15),
            Decimal::from(10_000),
            Decimal::from(20)
        )
    );

    // Retrying replays the result without rebasing again; reusing the id for another
    // calibration is refused.
    let replayed = recalibrate_price_curves(
        &pool,
        RecalibratePriceCurvesCommand {
            dry_run: false,
            ..command.clone()
        },
    )
    .await
    .unwrap();
    assert_eq!(replayed, applied);
    assert_eq!(rebase_count(&pool, instrument_id).await, 1);
    let conflict = recalibrate_price_curves(
        &pool,
        RecalibratePriceCurvesCommand {
            dry_run: false,
            calibration: CurveCalibration {
                curve_depth_divisor: Decimal::from(10),
                ..calibration
            },
            ..command
        },
    )
    .await
    .unwrap_err();
    assert!(matches!(conflict, ProvisioningError::Idempotency(_)));

    // The same 1,000-share buy now moves the price 20^(1000/100000) ≈ 3.04%; on the old curve
    // it would have moved 2.5^(1000/1500000) ≈ 0.06%.
    buy(&pool, account_id, portfolio_id, instrument_id, 1_000).await;
    let after = curve(&pool, instrument_id).await;
    let expected =
        rebased.current * Decimal::from(20).powd(Decimal::from(1_000) / Decimal::from(SUPPLY / 15));
    assert!((after.current - expected).abs() < Decimal::new(1, 6));
    assert!(after.current / rebased.current > Decimal::new(103, 2));
}

#[derive(Debug, PartialEq)]
struct Curve {
    current: Decimal,
    reference: Decimal,
    net: Decimal,
    multiplier: Decimal,
    depth: Decimal,
}

async fn curve(pool: &PgPool, instrument_id: Uuid) -> Curve {
    let (current, reference, net, multiplier, depth) = sqlx::query_as(
        "SELECT current_price, reference_price, net_shares_purchased, \
         full_supply_price_multiplier, curve_depth_shares FROM instruments WHERE id = $1",
    )
    .bind(instrument_id)
    .fetch_one(pool)
    .await
    .unwrap();
    Curve {
        current,
        reference,
        net,
        multiplier,
        depth,
    }
}

async fn rebase_count(pool: &PgPool, instrument_id: Uuid) -> i64 {
    sqlx::query_scalar(
        "SELECT COUNT(*) FROM instrument_price_curve_rebases WHERE instrument_id = $1",
    )
    .bind(instrument_id)
    .fetch_one(pool)
    .await
    .unwrap()
}

async fn buy(
    pool: &PgPool,
    account_id: Uuid,
    portfolio_id: Uuid,
    instrument_id: Uuid,
    quantity: i64,
) {
    execute_order(
        pool,
        ExecuteOrderCommand {
            execution_limits: None,
            request_id: format!("curve-buy-{}", Uuid::new_v4()),
            account_id,
            portfolio_id,
            instrument_id,
            side: OrderSide::Buy,
            quantity: Decimal::from(quantity),
        },
    )
    .await
    .unwrap();
}

async fn insert_fixture(pool: &PgPool) -> (Uuid, Uuid, Uuid) {
    let account_id = Uuid::new_v4();
    let portfolio_id = Uuid::new_v4();
    let player_id = Uuid::new_v4();
    let instrument_id = Uuid::new_v4();

    sqlx::query(
        "INSERT INTO accounts (id, handle, display_name, account_type, status) \
         VALUES ($1, $2, 'Curve Test User', 'USER', 'ACTIVE')",
    )
    .bind(account_id)
    .bind(format!("curve-{account_id}"))
    .execute(pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO portfolios (id, account_id, cash_balance) VALUES ($1, $2, 100000000)")
        .bind(portfolio_id)
        .bind(account_id)
        .execute(pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO players (id, provider, provider_player_id, display_name) \
         VALUES ($1, 'curve-test', $2, 'Curve Test Player')",
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
        ) VALUES ($1, 'PLAYER_SHARE', $2, $3, 'Curve Test Share', 100, 100, $4, 0, 2.5, 'ACTIVE')
        "#,
    )
    .bind(instrument_id)
    .bind(player_id)
    .bind(format!("CURVE-{instrument_id}"))
    .bind(Decimal::from(SUPPLY))
    .execute(pool)
    .await
    .unwrap();
    (account_id, portfolio_id, instrument_id)
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
