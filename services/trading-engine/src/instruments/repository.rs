use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use sqlx::{FromRow, PgConnection, PgExecutor};
use uuid::Uuid;

use super::{
    error::InstrumentError,
    model::{IndexFundInstrument, Instrument, InstrumentStatus, InstrumentType},
};
use crate::price_impact::CurveCalibration;

#[derive(Debug, FromRow)]
struct InstrumentRow {
    id: Uuid,
    instrument_type: String,
    player_id: Option<Uuid>,
    symbol: String,
    display_name: String,
    current_price: Decimal,
    // Null for index funds, which have no supply or price curve of their own.
    reference_price: Option<Decimal>,
    shares_outstanding: Option<Decimal>,
    net_shares_purchased: Decimal,
    full_supply_price_multiplier: Option<Decimal>,
    curve_depth_shares: Option<Decimal>,
    trading_status: String,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

#[derive(Debug, FromRow)]
struct IndexFundInstrumentRow {
    id: Uuid,
    instrument_type: String,
    symbol: String,
    display_name: String,
    current_price: Decimal,
    trading_status: String,
}

pub async fn get_instrument_by_id(
    executor: impl PgExecutor<'_>,
    instrument_id: Uuid,
) -> Result<Option<Instrument>, InstrumentError> {
    let row = sqlx::query_as::<_, InstrumentRow>(
        r#"
        SELECT
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
            curve_depth_shares,
            trading_status,
            created_at,
            updated_at
        FROM instruments
        WHERE id = $1
        "#,
    )
    .bind(instrument_id)
    .fetch_optional(executor)
    .await?;

    row.map(Instrument::try_from).transpose()
}

pub async fn get_active_instrument_by_id(
    executor: impl PgExecutor<'_>,
    instrument_id: Uuid,
) -> Result<Instrument, InstrumentError> {
    let instrument = get_instrument_by_id(executor, instrument_id)
        .await?
        .ok_or(InstrumentError::NotFound(instrument_id))?;

    if !instrument.status.is_active() {
        return Err(InstrumentError::NotActive {
            instrument_id,
            status: instrument.status,
        });
    }

    Ok(instrument)
}

pub fn assert_tradable(instrument: &Instrument) -> Result<(), InstrumentError> {
    if instrument.status.is_tradable() {
        return Ok(());
    }

    Err(InstrumentError::NotTradable {
        instrument_id: instrument.id,
        status: instrument.status,
    })
}

pub async fn get_current_price(
    executor: impl PgExecutor<'_>,
    instrument_id: Uuid,
) -> Result<Decimal, InstrumentError> {
    sqlx::query_scalar::<_, Decimal>(
        r#"
        SELECT current_price
        FROM instruments
        WHERE id = $1
        "#,
    )
    .bind(instrument_id)
    .fetch_optional(executor)
    .await?
    .ok_or(InstrumentError::NotFound(instrument_id))
}

pub(crate) async fn lock_instrument_by_id(
    connection: &mut PgConnection,
    instrument_id: Uuid,
) -> Result<Instrument, InstrumentError> {
    let row = sqlx::query_as::<_, InstrumentRow>(
        r#"
        SELECT
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
            curve_depth_shares,
            trading_status,
            created_at,
            updated_at
        FROM instruments
        WHERE id = $1
        FOR UPDATE
        "#,
    )
    .bind(instrument_id)
    .fetch_optional(&mut *connection)
    .await?
    .ok_or(InstrumentError::NotFound(instrument_id))?;

    Instrument::try_from(row)
}

pub(crate) async fn update_market_state(
    connection: &mut PgConnection,
    instrument_id: Uuid,
    new_price: Decimal,
    net_shares_purchased: Decimal,
) -> Result<Instrument, InstrumentError> {
    if new_price <= Decimal::ZERO {
        return Err(InstrumentError::NegativePrice);
    }

    let row = sqlx::query_as::<_, InstrumentRow>(
        r#"
        UPDATE instruments
        SET
            current_price = $2,
            net_shares_purchased = $3,
            updated_at = now()
        WHERE id = $1
        RETURNING
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
            curve_depth_shares,
            trading_status,
            created_at,
            updated_at
        "#,
    )
    .bind(instrument_id)
    .bind(new_price)
    .bind(net_shares_purchased)
    .fetch_optional(&mut *connection)
    .await?
    .ok_or(InstrumentError::NotFound(instrument_id))?;

    Instrument::try_from(row)
}

pub async fn get_instrument_type(
    executor: impl PgExecutor<'_>,
    instrument_id: Uuid,
) -> Result<InstrumentType, InstrumentError> {
    let instrument_type = sqlx::query_scalar::<_, String>(
        r#"
        SELECT instrument_type
        FROM instruments
        WHERE id = $1
        "#,
    )
    .bind(instrument_id)
    .fetch_optional(executor)
    .await?
    .ok_or(InstrumentError::NotFound(instrument_id))?;

    InstrumentType::try_from(instrument_type)
}

/// Locks player-share instruments in id order, the order every multi-instrument flow uses.
pub(crate) async fn lock_instruments_by_ids(
    connection: &mut PgConnection,
    instrument_ids: &[Uuid],
) -> Result<Vec<Instrument>, InstrumentError> {
    select_instruments_by_ids(connection, instrument_ids, RowLock::ForUpdate).await
}

/// Reads player-share instruments without locking them, for quotes.
pub(crate) async fn get_instruments_by_ids(
    connection: &mut PgConnection,
    instrument_ids: &[Uuid],
) -> Result<Vec<Instrument>, InstrumentError> {
    select_instruments_by_ids(connection, instrument_ids, RowLock::None).await
}

/// Whether a read takes row locks. Orders lock what they change; quotes only read.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RowLock {
    None,
    ForUpdate,
}

impl RowLock {
    const fn clause(self) -> &'static str {
        match self {
            Self::None => "",
            Self::ForUpdate => "FOR UPDATE",
        }
    }
}

async fn select_instruments_by_ids(
    connection: &mut PgConnection,
    instrument_ids: &[Uuid],
    lock: RowLock,
) -> Result<Vec<Instrument>, InstrumentError> {
    let mut sorted = instrument_ids.to_vec();
    sorted.sort_unstable();
    sorted.dedup();
    let query = format!(
        r#"
        SELECT
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
            curve_depth_shares,
            trading_status,
            created_at,
            updated_at
        FROM instruments
        WHERE id = ANY($1)
        ORDER BY id
        {}
        "#,
        lock.clause()
    );
    let rows = sqlx::query_as::<_, InstrumentRow>(&query)
        .bind(&sorted)
        .fetch_all(&mut *connection)
        .await?;
    if let Some(missing) = sorted
        .iter()
        .find(|id| !rows.iter().any(|row| row.id == **id))
    {
        return Err(InstrumentError::NotFound(*missing));
    }

    rows.into_iter().map(Instrument::try_from).collect()
}

/// Locks index fund instruments in id order. Every flow that changes a constituent's price
/// locks the funds holding it first, so funds are always locked before player shares.
pub(crate) async fn lock_index_fund_instruments(
    connection: &mut PgConnection,
    instrument_ids: &[Uuid],
) -> Result<Vec<IndexFundInstrument>, InstrumentError> {
    select_index_fund_instruments(connection, instrument_ids, RowLock::ForUpdate).await
}

pub(crate) async fn select_index_fund_instruments(
    connection: &mut PgConnection,
    instrument_ids: &[Uuid],
    lock: RowLock,
) -> Result<Vec<IndexFundInstrument>, InstrumentError> {
    let mut sorted = instrument_ids.to_vec();
    sorted.sort_unstable();
    sorted.dedup();
    let query = format!(
        r#"
        SELECT id, instrument_type, symbol, display_name, current_price, trading_status
        FROM instruments
        WHERE id = ANY($1)
        ORDER BY id
        {}
        "#,
        lock.clause()
    );
    let rows = sqlx::query_as::<_, IndexFundInstrumentRow>(&query)
        .bind(&sorted)
        .fetch_all(&mut *connection)
        .await?;
    if let Some(missing) = sorted
        .iter()
        .find(|id| !rows.iter().any(|row| row.id == **id))
    {
        return Err(InstrumentError::NotFound(*missing));
    }

    rows.into_iter()
        .map(IndexFundInstrument::try_from)
        .collect()
}

/// Takes a player share off the market. Its symbol gains a `-DL<timestamp>` suffix so a share
/// listed for the same player later can reuse the plain symbol.
pub(crate) async fn mark_delisted(
    connection: &mut PgConnection,
    instrument_id: Uuid,
) -> Result<(), InstrumentError> {
    let updated = sqlx::query(
        r#"
        UPDATE instruments
        SET
            trading_status = 'DELISTED',
            symbol = symbol || '-DL' || to_char(now() AT TIME ZONE 'UTC', 'YYYYMMDDHH24MISS'),
            updated_at = now()
        WHERE id = $1
          AND trading_status <> 'DELISTED'
        "#,
    )
    .bind(instrument_id)
    .execute(&mut *connection)
    .await?;
    if updated.rows_affected() == 0 {
        return Err(InstrumentError::NotFound(instrument_id));
    }
    Ok(())
}

/// Sets an index fund's price to the current value of its basket.
pub(crate) async fn update_index_fund_price(
    connection: &mut PgConnection,
    instrument_id: Uuid,
    new_price: Decimal,
) -> Result<(), InstrumentError> {
    if new_price <= Decimal::ZERO {
        return Err(InstrumentError::NegativePrice);
    }

    let updated = sqlx::query(
        r#"
        UPDATE instruments
        SET
            current_price = $2,
            updated_at = now()
        WHERE id = $1
          AND instrument_type = 'INDEX_FUND'
        "#,
    )
    .bind(instrument_id)
    .bind(new_price)
    .execute(&mut *connection)
    .await?;
    if updated.rows_affected() == 0 {
        return Err(InstrumentError::NotFound(instrument_id));
    }
    Ok(())
}

pub(crate) async fn insert_index_fund_instrument(
    connection: &mut PgConnection,
    symbol: &str,
    display_name: &str,
    current_price: Decimal,
) -> Result<Uuid, InstrumentError> {
    if current_price <= Decimal::ZERO {
        return Err(InstrumentError::NegativePrice);
    }

    let instrument_id = sqlx::query_scalar::<_, Uuid>(
        r#"
        INSERT INTO instruments (
            instrument_type,
            symbol,
            display_name,
            current_price,
            full_supply_price_multiplier,
            trading_status
        ) VALUES (
            'INDEX_FUND',
            $1,
            $2,
            $3,
            NULL,
            'ACTIVE'
        )
        RETURNING id
        "#,
    )
    .bind(symbol)
    .bind(display_name)
    .bind(current_price)
    .fetch_one(&mut *connection)
    .await?;

    Ok(instrument_id)
}

/// True once an instrument has any order, trade, or held position, i.e. it has left pre-market.
pub(crate) async fn has_market_activity(
    connection: &mut PgConnection,
    instrument_id: Uuid,
) -> Result<bool, InstrumentError> {
    let active = sqlx::query_scalar::<_, bool>(
        r#"
        SELECT
            EXISTS (SELECT 1 FROM orders WHERE instrument_id = $1)
            OR EXISTS (SELECT 1 FROM trades WHERE instrument_id = $1)
            OR EXISTS (SELECT 1 FROM positions WHERE instrument_id = $1)
        "#,
    )
    .bind(instrument_id)
    .fetch_one(&mut *connection)
    .await?;
    Ok(active)
}

/// Re-anchors a pre-market instrument: both the quoted and curve reference price move to
/// `new_price` and net demand resets, so the curve starts from the new valuation.
pub(crate) async fn reset_pre_market_price(
    connection: &mut PgConnection,
    instrument_id: Uuid,
    new_price: Decimal,
) -> Result<(), InstrumentError> {
    if new_price <= Decimal::ZERO {
        return Err(InstrumentError::NegativePrice);
    }

    let updated = sqlx::query(
        r#"
        UPDATE instruments
        SET
            current_price = $2,
            reference_price = $2,
            net_shares_purchased = 0,
            updated_at = now()
        WHERE id = $1
        "#,
    )
    .bind(instrument_id)
    .bind(new_price)
    .execute(&mut *connection)
    .await?;
    if updated.rows_affected() == 0 {
        return Err(InstrumentError::NotFound(instrument_id));
    }
    Ok(())
}

/// What a curve recalibration did to one instrument.
#[derive(Debug, Clone, PartialEq, FromRow)]
pub struct RecalibratedCurve {
    pub instrument_id: Uuid,
    pub current_price: Decimal,
    pub old_reference_price: Decimal,
    pub old_net_shares_purchased: Decimal,
    pub old_full_supply_price_multiplier: Decimal,
    pub old_curve_depth_shares: Decimal,
    pub new_curve_depth_shares: Decimal,
}

/// Re-anchors every player-share curve at its current price with a new calibration. Net
/// demand resets and the reference becomes the current price, so no price changes; only how
/// far later trades move it. The database trigger audits each rebase.
pub(crate) async fn recalibrate_price_curves(
    connection: &mut PgConnection,
    calibration: CurveCalibration,
) -> Result<Vec<RecalibratedCurve>, InstrumentError> {
    let rows = sqlx::query_as::<_, RecalibratedCurve>(
        r#"
        WITH locked AS (
            SELECT
                id,
                reference_price,
                net_shares_purchased,
                full_supply_price_multiplier,
                curve_depth_shares
            FROM instruments
            WHERE instrument_type = 'PLAYER_SHARE'
            ORDER BY id
            FOR UPDATE
        )
        UPDATE instruments AS instrument
        SET
            reference_price = instrument.current_price,
            net_shares_purchased = 0,
            full_supply_price_multiplier = $1,
            curve_depth_shares = round(instrument.shares_outstanding / $2, 6),
            updated_at = now()
        FROM locked
        WHERE instrument.id = locked.id
        RETURNING
            instrument.id AS instrument_id,
            instrument.current_price,
            locked.reference_price AS old_reference_price,
            locked.net_shares_purchased AS old_net_shares_purchased,
            locked.full_supply_price_multiplier AS old_full_supply_price_multiplier,
            locked.curve_depth_shares AS old_curve_depth_shares,
            instrument.curve_depth_shares AS new_curve_depth_shares
        "#,
    )
    .bind(calibration.full_supply_price_multiplier)
    .bind(calibration.curve_depth_divisor)
    .fetch_all(&mut *connection)
    .await?;
    Ok(rows)
}

impl TryFrom<InstrumentRow> for Instrument {
    type Error = InstrumentError;

    fn try_from(row: InstrumentRow) -> Result<Self, Self::Error> {
        let instrument_type = InstrumentType::try_from(row.instrument_type)?;
        let status = InstrumentStatus::try_from(row.trading_status)?;
        let invalid = |reason: &str| InstrumentError::InvalidRecord {
            instrument_id: row.id,
            reason: reason.to_owned(),
        };
        if instrument_type != InstrumentType::PlayerShare {
            return Err(invalid("only PLAYER_SHARE instruments have a price curve"));
        }
        let player_id = row
            .player_id
            .ok_or_else(|| invalid("PLAYER_SHARE instruments must have a player_id"))?;
        let curve_term = |value: Option<Decimal>| {
            value.ok_or_else(|| invalid("PLAYER_SHARE instruments must have price curve terms"))
        };

        Ok(Self {
            id: row.id,
            instrument_type,
            player_id,
            symbol: row.symbol,
            display_name: row.display_name,
            current_price: row.current_price,
            reference_price: curve_term(row.reference_price)?,
            shares_outstanding: curve_term(row.shares_outstanding)?,
            net_shares_purchased: row.net_shares_purchased,
            full_supply_price_multiplier: curve_term(row.full_supply_price_multiplier)?,
            curve_depth_shares: curve_term(row.curve_depth_shares)?,
            status,
            created_at: row.created_at,
            updated_at: row.updated_at,
        })
    }
}

impl TryFrom<IndexFundInstrumentRow> for IndexFundInstrument {
    type Error = InstrumentError;

    fn try_from(row: IndexFundInstrumentRow) -> Result<Self, Self::Error> {
        if InstrumentType::try_from(row.instrument_type)? != InstrumentType::IndexFund {
            return Err(InstrumentError::InvalidRecord {
                instrument_id: row.id,
                reason: "instrument is not an index fund".to_owned(),
            });
        }
        Ok(Self {
            id: row.id,
            symbol: row.symbol,
            display_name: row.display_name,
            current_price: row.current_price,
            status: InstrumentStatus::try_from(row.trading_status)?,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn instrument_with_status(status: InstrumentStatus) -> Instrument {
        Instrument {
            id: Uuid::new_v4(),
            instrument_type: InstrumentType::PlayerShare,
            player_id: Uuid::new_v4(),
            symbol: "TEST".to_owned(),
            display_name: "Test Player Share".to_owned(),
            current_price: Decimal::new(100_0000, 4),
            reference_price: Decimal::new(100_0000, 4),
            shares_outstanding: Decimal::new(1_000_000_000_000, 6),
            net_shares_purchased: Decimal::ZERO,
            full_supply_price_multiplier: Decimal::new(25, 1),
            curve_depth_shares: Decimal::new(1_000_000_000_000, 6),
            status,
            created_at: Utc::now(),
            updated_at: Utc::now(),
        }
    }

    #[test]
    fn assert_tradable_accepts_active_instrument() {
        let instrument = instrument_with_status(InstrumentStatus::Active);

        assert!(assert_tradable(&instrument).is_ok());
    }

    #[test]
    fn assert_tradable_rejects_frozen_instrument() {
        let instrument = instrument_with_status(InstrumentStatus::Frozen);
        let error = assert_tradable(&instrument).unwrap_err();

        assert!(matches!(
            error,
            InstrumentError::NotTradable {
                status: InstrumentStatus::Frozen,
                ..
            }
        ));
    }

    #[test]
    fn assert_tradable_rejects_delisted_instrument() {
        let instrument = instrument_with_status(InstrumentStatus::Delisted);
        let error = assert_tradable(&instrument).unwrap_err();

        assert!(matches!(
            error,
            InstrumentError::NotTradable {
                status: InstrumentStatus::Delisted,
                ..
            }
        ));
    }
}
