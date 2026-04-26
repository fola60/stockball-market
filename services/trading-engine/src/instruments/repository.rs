use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use sqlx::{FromRow, PgConnection, PgExecutor};
use uuid::Uuid;

use super::{
    error::InstrumentError,
    model::{Instrument, InstrumentStatus, InstrumentType},
};

#[derive(Debug, FromRow)]
struct InstrumentRow {
    id: Uuid,
    instrument_type: String,
    player_id: Option<Uuid>,
    symbol: String,
    display_name: String,
    current_price: Decimal,
    shares_outstanding: Decimal,
    price_impact_unit: Decimal,
    trading_status: String,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
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
            shares_outstanding,
            price_impact_unit,
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

pub async fn get_price_impact_unit(
    executor: impl PgExecutor<'_>,
    instrument_id: Uuid,
) -> Result<Decimal, InstrumentError> {
    sqlx::query_scalar::<_, Decimal>(
        r#"
        SELECT price_impact_unit
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
            shares_outstanding,
            price_impact_unit,
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

pub(crate) async fn update_current_price(
    connection: &mut PgConnection,
    instrument_id: Uuid,
    new_price: Decimal,
) -> Result<Instrument, InstrumentError> {
    if new_price.is_sign_negative() {
        return Err(InstrumentError::NegativePrice);
    }

    let row = sqlx::query_as::<_, InstrumentRow>(
        r#"
        UPDATE instruments
        SET
            current_price = $2,
            updated_at = now()
        WHERE id = $1
        RETURNING
            id,
            instrument_type,
            player_id,
            symbol,
            display_name,
            current_price,
            shares_outstanding,
            price_impact_unit,
            trading_status,
            created_at,
            updated_at
        "#,
    )
    .bind(instrument_id)
    .bind(new_price)
    .fetch_optional(&mut *connection)
    .await?
    .ok_or(InstrumentError::NotFound(instrument_id))?;

    Instrument::try_from(row)
}

impl TryFrom<InstrumentRow> for Instrument {
    type Error = InstrumentError;

    fn try_from(row: InstrumentRow) -> Result<Self, Self::Error> {
        let instrument_type = InstrumentType::try_from(row.instrument_type)?;
        let status = InstrumentStatus::try_from(row.trading_status)?;
        let player_id = row
            .player_id
            .ok_or_else(|| InstrumentError::InvalidRecord {
                instrument_id: row.id,
                reason: "PLAYER_SHARE instruments must have a player_id".to_owned(),
            })?;

        Ok(Self {
            id: row.id,
            instrument_type,
            player_id,
            symbol: row.symbol,
            display_name: row.display_name,
            current_price: row.current_price,
            shares_outstanding: row.shares_outstanding,
            price_impact_unit: row.price_impact_unit,
            status,
            created_at: row.created_at,
            updated_at: row.updated_at,
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
            shares_outstanding: Decimal::new(1_000_000_000_000, 6),
            price_impact_unit: Decimal::new(1_0000, 6),
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
