use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use sqlx::{FromRow, PgConnection};
use uuid::Uuid;

use super::{
    error::SnapshotError,
    model::{PriceSnapshot, PriceSnapshotReason},
};

#[derive(Debug, FromRow)]
struct PriceSnapshotRow {
    id: Uuid,
    instrument_id: Uuid,
    old_price: Decimal,
    new_price: Decimal,
    reason: String,
    trade_id: Option<Uuid>,
    captured_at: DateTime<Utc>,
}

pub async fn record_price_snapshot(
    connection: &mut PgConnection,
    instrument_id: Uuid,
    old_price: Decimal,
    new_price: Decimal,
    reason: PriceSnapshotReason,
    trade_id: Option<Uuid>,
) -> Result<PriceSnapshot, SnapshotError> {
    ensure_non_negative_price(old_price)?;
    ensure_non_negative_price(new_price)?;

    let row = sqlx::query_as::<_, PriceSnapshotRow>(
        r#"
        INSERT INTO price_snapshots (
            instrument_id,
            old_price,
            new_price,
            reason,
            trade_id
        ) VALUES (
            $1,
            $2,
            $3,
            $4,
            $5
        )
        RETURNING
            id,
            instrument_id,
            old_price,
            new_price,
            reason,
            trade_id,
            captured_at
        "#,
    )
    .bind(instrument_id)
    .bind(old_price)
    .bind(new_price)
    .bind(reason.as_str())
    .bind(trade_id)
    .fetch_one(&mut *connection)
    .await?;

    PriceSnapshot::try_from(row)
}

fn ensure_non_negative_price(price: Decimal) -> Result<(), SnapshotError> {
    if price.is_sign_negative() {
        return Err(SnapshotError::NegativePrice(price));
    }

    Ok(())
}

impl TryFrom<PriceSnapshotRow> for PriceSnapshot {
    type Error = SnapshotError;

    fn try_from(row: PriceSnapshotRow) -> Result<Self, Self::Error> {
        ensure_non_negative_price(row.old_price)?;
        ensure_non_negative_price(row.new_price)?;

        Ok(Self {
            id: row.id,
            instrument_id: row.instrument_id,
            old_price: row.old_price,
            new_price: row.new_price,
            reason: PriceSnapshotReason::try_from(row.reason)?,
            trade_id: row.trade_id,
            captured_at: row.captured_at,
        })
    }
}
