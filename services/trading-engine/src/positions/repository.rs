use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use sqlx::{FromRow, PgConnection, PgExecutor};
use uuid::Uuid;

use super::{error::PositionError, model::Position};

#[derive(Debug, FromRow)]
struct PositionRow {
    id: Uuid,
    portfolio_id: Uuid,
    instrument_id: Uuid,
    quantity: Decimal,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

pub async fn get_position(
    executor: impl PgExecutor<'_>,
    portfolio_id: Uuid,
    instrument_id: Uuid,
) -> Result<Option<Position>, PositionError> {
    let row = sqlx::query_as::<_, PositionRow>(
        r#"
        SELECT
            id,
            portfolio_id,
            instrument_id,
            quantity,
            created_at,
            updated_at
        FROM positions
        WHERE portfolio_id = $1
          AND instrument_id = $2
        "#,
    )
    .bind(portfolio_id)
    .bind(instrument_id)
    .fetch_optional(executor)
    .await?;

    row.map(Position::try_from).transpose()
}

pub(crate) async fn lock_position(
    connection: &mut PgConnection,
    portfolio_id: Uuid,
    instrument_id: Uuid,
) -> Result<Option<Position>, PositionError> {
    let row = sqlx::query_as::<_, PositionRow>(
        r#"
        SELECT
            id,
            portfolio_id,
            instrument_id,
            quantity,
            created_at,
            updated_at
        FROM positions
        WHERE portfolio_id = $1
          AND instrument_id = $2
        FOR UPDATE
        "#,
    )
    .bind(portfolio_id)
    .bind(instrument_id)
    .fetch_optional(&mut *connection)
    .await?;

    row.map(Position::try_from).transpose()
}

pub fn assert_has_quantity(
    portfolio_id: Uuid,
    instrument_id: Uuid,
    available: Decimal,
    required: Decimal,
) -> Result<(), PositionError> {
    ensure_positive_change(required)?;

    if available < required {
        return Err(PositionError::InsufficientQuantity {
            portfolio_id,
            instrument_id,
            available,
            required,
        });
    }

    Ok(())
}

pub async fn increase_position(
    connection: &mut PgConnection,
    portfolio_id: Uuid,
    instrument_id: Uuid,
    quantity_delta: Decimal,
) -> Result<Position, PositionError> {
    ensure_positive_change(quantity_delta)?;

    let row = sqlx::query_as::<_, PositionRow>(
        r#"
        INSERT INTO positions (
            portfolio_id,
            instrument_id,
            quantity
        ) VALUES (
            $1,
            $2,
            $3
        )
        ON CONFLICT (portfolio_id, instrument_id)
        DO UPDATE SET
            quantity = positions.quantity + EXCLUDED.quantity,
            updated_at = now()
        RETURNING
            id,
            portfolio_id,
            instrument_id,
            quantity,
            created_at,
            updated_at
        "#,
    )
    .bind(portfolio_id)
    .bind(instrument_id)
    .bind(quantity_delta)
    .fetch_one(&mut *connection)
    .await?;

    Position::try_from(row)
}

pub async fn decrease_position(
    connection: &mut PgConnection,
    portfolio_id: Uuid,
    instrument_id: Uuid,
    quantity_delta: Decimal,
) -> Result<Position, PositionError> {
    ensure_positive_change(quantity_delta)?;

    let position = lock_position(&mut *connection, portfolio_id, instrument_id)
        .await?
        .ok_or(PositionError::InsufficientQuantity {
            portfolio_id,
            instrument_id,
            available: Decimal::ZERO,
            required: quantity_delta,
        })?;

    assert_has_quantity(
        portfolio_id,
        instrument_id,
        position.quantity,
        quantity_delta,
    )?;

    let row = sqlx::query_as::<_, PositionRow>(
        r#"
        UPDATE positions
        SET
            quantity = quantity - $3,
            updated_at = now()
        WHERE portfolio_id = $1
          AND instrument_id = $2
        RETURNING
            id,
            portfolio_id,
            instrument_id,
            quantity,
            created_at,
            updated_at
        "#,
    )
    .bind(portfolio_id)
    .bind(instrument_id)
    .bind(quantity_delta)
    .fetch_optional(&mut *connection)
    .await?
    .ok_or(PositionError::NotFound {
        portfolio_id,
        instrument_id,
    })?;

    Position::try_from(row)
}

fn ensure_positive_change(quantity: Decimal) -> Result<(), PositionError> {
    if quantity <= Decimal::ZERO {
        return Err(PositionError::NonPositiveQuantity(quantity));
    }

    Ok(())
}

impl TryFrom<PositionRow> for Position {
    type Error = PositionError;

    fn try_from(row: PositionRow) -> Result<Self, Self::Error> {
        if row.quantity.is_sign_negative() {
            return Err(PositionError::NegativeQuantity {
                position_id: row.id,
                quantity: row.quantity,
            });
        }

        Ok(Self {
            id: row.id,
            portfolio_id: row.portfolio_id,
            instrument_id: row.instrument_id,
            quantity: row.quantity,
            created_at: row.created_at,
            updated_at: row.updated_at,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn assert_has_quantity_accepts_exact_quantity() {
        assert!(assert_has_quantity(
            Uuid::new_v4(),
            Uuid::new_v4(),
            Decimal::new(10_000000, 6),
            Decimal::new(10_000000, 6),
        )
        .is_ok());
    }

    #[test]
    fn assert_has_quantity_rejects_insufficient_quantity() {
        let error = assert_has_quantity(
            Uuid::new_v4(),
            Uuid::new_v4(),
            Decimal::new(9_000000, 6),
            Decimal::new(10_000000, 6),
        )
        .unwrap_err();

        assert!(matches!(error, PositionError::InsufficientQuantity { .. }));
    }
}
