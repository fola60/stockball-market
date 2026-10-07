use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use sqlx::{FromRow, PgConnection, PgPool};
use uuid::Uuid;

use crate::{
    instruments::InstrumentError,
    price_impact::CurveCalibration,
    snapshots::{self, PriceSnapshotReason},
};

const MARKET_VALUE_SCALE_FACTOR: i64 = 1_000_000;
const MIN_INITIAL_PRICE: Decimal = Decimal::ONE;
const MAX_INITIAL_PRICE: Decimal = Decimal::from_parts(250, 0, 0, false, 0);
const SHARES_OUTSTANDING: Decimal = Decimal::from_parts(1_000_000, 0, 0, false, 0);

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SeedPlayerSharesResult {
    pub created_count: usize,
    pub skipped_existing_count: usize,
    pub market_value_priced_count: usize,
    pub fallback_priced_count: usize,
    pub created_instrument_ids: Vec<Uuid>,
}

#[derive(Debug, FromRow)]
struct SeedCandidateRow {
    player_id: Uuid,
    display_name: String,
    position: Option<String>,
    market_value: Option<Decimal>,
    existing_instrument_id: Option<Uuid>,
}

/// Lists every unlisted player, starting each curve with `calibration` so new players trade on
/// the same scale as the rest of the market.
pub async fn seed_player_shares(
    pool: &PgPool,
    calibration: CurveCalibration,
) -> Result<SeedPlayerSharesResult, InstrumentError> {
    let mut transaction = pool.begin().await?;
    let candidates = list_seed_candidates(&mut transaction).await?;

    let mut result = SeedPlayerSharesResult {
        created_count: 0,
        skipped_existing_count: 0,
        market_value_priced_count: 0,
        fallback_priced_count: 0,
        created_instrument_ids: Vec::new(),
    };

    for candidate in candidates {
        if candidate.existing_instrument_id.is_some() {
            result.skipped_existing_count += 1;
            continue;
        }

        let (initial_price, used_market_value) = initial_price_for_candidate(&candidate)?;
        let instrument_id = insert_player_share_instrument(
            &mut transaction,
            candidate.player_id,
            &symbol_for_player(&candidate.display_name, candidate.player_id),
            &format!("{} Share", candidate.display_name),
            initial_price,
            calibration,
        )
        .await?;

        snapshots::record_price_snapshot(
            &mut transaction,
            instrument_id,
            initial_price,
            initial_price,
            PriceSnapshotReason::Seed,
            None,
        )
        .await?;

        result.created_count += 1;
        if used_market_value {
            result.market_value_priced_count += 1;
        } else {
            result.fallback_priced_count += 1;
        }
        result.created_instrument_ids.push(instrument_id);
    }

    transaction.commit().await?;
    Ok(result)
}

async fn list_seed_candidates(
    connection: &mut PgConnection,
) -> Result<Vec<SeedCandidateRow>, InstrumentError> {
    let rows = sqlx::query_as::<_, SeedCandidateRow>(
        r#"
        SELECT
            p.id AS player_id,
            p.display_name,
            p.position,
            mv.value AS market_value,
            i.id AS existing_instrument_id
        FROM players AS p
        LEFT JOIN instruments AS i
            ON i.player_id = p.id
           AND i.instrument_type = 'PLAYER_SHARE'
        LEFT JOIN LATERAL (
            SELECT value
            FROM player_market_value_observations
            WHERE player_id = p.id
              AND currency = 'EUR'
            ORDER BY observed_at DESC, imported_at DESC, id DESC
            LIMIT 1
        ) AS mv ON true
        ORDER BY p.display_name, p.id
        "#,
    )
    .fetch_all(&mut *connection)
    .await?;

    Ok(rows)
}

fn initial_price_for_candidate(
    candidate: &SeedCandidateRow,
) -> Result<(Decimal, bool), InstrumentError> {
    if let Some(market_value) = candidate.market_value {
        return Ok((calculate_initial_price(market_value)?, true));
    }

    Ok((
        fallback_price_for_position(candidate.position.as_deref()),
        false,
    ))
}

pub fn calculate_initial_price(market_value: Decimal) -> Result<Decimal, InstrumentError> {
    if market_value <= Decimal::ZERO {
        return Err(InstrumentError::InvalidSeedValue {
            reason: format!("market value must be positive: {market_value}"),
        });
    }

    let scaled = (market_value / Decimal::from(MARKET_VALUE_SCALE_FACTOR)).round_dp(4);
    Ok(clamp_initial_price(scaled))
}

pub fn fallback_price_for_position(position: Option<&str>) -> Decimal {
    let normalized = position.unwrap_or_default().to_ascii_lowercase();
    if normalized.contains("goalkeeper") || normalized == "gk" {
        return Decimal::new(5_0000, 4);
    }
    if normalized.contains("defender")
        || normalized.contains("back")
        || normalized == "cb"
        || normalized == "lb"
        || normalized == "rb"
    {
        return Decimal::new(7_5000, 4);
    }
    if normalized.contains("midfield") || normalized == "mid" {
        return Decimal::new(10_0000, 4);
    }
    if normalized.contains("forward")
        || normalized.contains("attacker")
        || normalized.contains("winger")
        || normalized.contains("striker")
        || normalized == "fw"
    {
        return Decimal::new(12_5000, 4);
    }
    Decimal::new(5_0000, 4)
}

fn clamp_initial_price(price: Decimal) -> Decimal {
    if price < MIN_INITIAL_PRICE {
        MIN_INITIAL_PRICE
    } else if price > MAX_INITIAL_PRICE {
        MAX_INITIAL_PRICE
    } else {
        price
    }
}

async fn insert_player_share_instrument(
    connection: &mut PgConnection,
    player_id: Uuid,
    symbol: &str,
    display_name: &str,
    current_price: Decimal,
    calibration: CurveCalibration,
) -> Result<Uuid, InstrumentError> {
    let shares_outstanding = SHARES_OUTSTANDING.round_dp(6);
    let instrument_id = sqlx::query_scalar::<_, Uuid>(
        r#"
        INSERT INTO instruments (
            instrument_type,
            player_id,
            symbol,
            display_name,
            current_price,
            reference_price,
            shares_outstanding,
            net_shares_purchased,
            full_supply_price_multiplier,
            curve_depth_shares,
            trading_status
        ) VALUES (
            'PLAYER_SHARE',
            $1,
            $2,
            $3,
            $4,
            $5,
            $6,
            0,
            $7,
            $8,
            'ACTIVE'
        )
        RETURNING id
        "#,
    )
    .bind(player_id)
    .bind(symbol)
    .bind(display_name)
    .bind(current_price)
    .bind(current_price)
    .bind(shares_outstanding)
    .bind(calibration.full_supply_price_multiplier)
    .bind(calibration.curve_depth_shares(shares_outstanding))
    .fetch_one(&mut *connection)
    .await?;

    Ok(instrument_id)
}

fn symbol_for_player(display_name: &str, player_id: Uuid) -> String {
    let mut symbol = String::new();
    let mut previous_was_separator = false;
    for character in display_name.chars() {
        if character.is_ascii_alphanumeric() {
            symbol.push(character.to_ascii_uppercase());
            previous_was_separator = false;
        } else if !previous_was_separator && !symbol.is_empty() {
            symbol.push('-');
            previous_was_separator = true;
        }
    }
    while symbol.ends_with('-') {
        symbol.pop();
    }
    if symbol.is_empty() {
        symbol.push_str("PLAYER");
    }

    let suffix: String = player_id
        .simple()
        .to_string()
        .chars()
        .take(8)
        .map(|character| character.to_ascii_uppercase())
        .collect();
    format!("{symbol}-{suffix}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn market_value_converts_to_initial_price() {
        let price = calculate_initial_price(Decimal::new(100_000_000, 0)).unwrap();
        assert_eq!(price, Decimal::new(100_0000, 4));
    }

    #[test]
    fn tiny_market_value_clamps_to_minimum_price() {
        let price = calculate_initial_price(Decimal::new(100_000, 0)).unwrap();
        assert_eq!(price, Decimal::new(1_0000, 4));
    }

    #[test]
    fn large_market_value_clamps_to_maximum_price() {
        let price = calculate_initial_price(Decimal::new(500_000_000, 0)).unwrap();
        assert_eq!(price, Decimal::new(250_0000, 4));
    }

    #[test]
    fn missing_market_value_uses_position_fallback() {
        assert_eq!(
            fallback_price_for_position(Some("Goalkeeper")),
            Decimal::new(5_0000, 4)
        );
        assert_eq!(
            fallback_price_for_position(Some("Centre-Back")),
            Decimal::new(7_5000, 4)
        );
        assert_eq!(
            fallback_price_for_position(Some("Central Midfield")),
            Decimal::new(10_0000, 4)
        );
        assert_eq!(
            fallback_price_for_position(Some("Right Winger")),
            Decimal::new(12_5000, 4)
        );
        assert_eq!(fallback_price_for_position(None), Decimal::new(5_0000, 4));
    }

    #[test]
    fn symbol_is_deterministic_and_uses_player_suffix() {
        let player_id = Uuid::parse_str("12345678-1234-5678-1234-567812345678").unwrap();
        assert_eq!(
            symbol_for_player("Bukayo Saka", player_id),
            "BUKAYO-SAKA-12345678"
        );
    }
}
