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
    cost_basis: Decimal,
    realized_pnl: Decimal,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

const COST_DECIMAL_PLACES: u32 = 12;

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
            cost_basis,
            realized_pnl,
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
            cost_basis,
            realized_pnl,
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

/// Locks every non-empty position in an instrument, the given portfolio last: the index fund
/// custody portfolio is always the last portfolio a flow locks.
pub(crate) async fn lock_holders(
    connection: &mut PgConnection,
    instrument_id: Uuid,
    last_portfolio_id: Uuid,
) -> Result<Vec<Position>, PositionError> {
    let rows = sqlx::query_as::<_, PositionRow>(
        r#"
        SELECT
            id,
            portfolio_id,
            instrument_id,
            quantity,
            cost_basis,
            realized_pnl,
            created_at,
            updated_at
        FROM positions
        WHERE instrument_id = $1
          AND quantity > 0
        ORDER BY portfolio_id = $2, portfolio_id
        FOR UPDATE
        "#,
    )
    .bind(instrument_id)
    .bind(last_portfolio_id)
    .fetch_all(&mut *connection)
    .await?;

    rows.into_iter().map(Position::try_from).collect()
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

/// Adds shares to a position along with what they cost, fees included.
pub async fn increase_position(
    connection: &mut PgConnection,
    portfolio_id: Uuid,
    instrument_id: Uuid,
    quantity_delta: Decimal,
    cost: Decimal,
) -> Result<Position, PositionError> {
    ensure_positive_change(quantity_delta)?;
    if cost.is_sign_negative() {
        return Err(PositionError::NegativeCost(cost));
    }

    let row = sqlx::query_as::<_, PositionRow>(
        r#"
        INSERT INTO positions (
            portfolio_id,
            instrument_id,
            quantity,
            cost_basis
        ) VALUES (
            $1,
            $2,
            $3,
            $4
        )
        ON CONFLICT (portfolio_id, instrument_id)
        DO UPDATE SET
            quantity = positions.quantity + EXCLUDED.quantity,
            cost_basis = positions.cost_basis + EXCLUDED.cost_basis,
            updated_at = now()
        RETURNING
            id,
            portfolio_id,
            instrument_id,
            quantity,
            cost_basis,
            realized_pnl,
            created_at,
            updated_at
        "#,
    )
    .bind(portfolio_id)
    .bind(instrument_id)
    .bind(quantity_delta)
    .bind(cost.round_dp(COST_DECIMAL_PLACES))
    .fetch_one(&mut *connection)
    .await?;

    Position::try_from(row)
}

/// Removes shares from a position. They take a proportional share of its cost basis with
/// them, and the difference between `proceeds` and that cost is the sale's realized profit.
pub async fn decrease_position(
    connection: &mut PgConnection,
    portfolio_id: Uuid,
    instrument_id: Uuid,
    quantity_delta: Decimal,
    proceeds: Decimal,
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
    let removed_cost = removed_cost_basis(&position, quantity_delta);

    let row = sqlx::query_as::<_, PositionRow>(
        r#"
        UPDATE positions
        SET
            quantity = quantity - $3,
            cost_basis = cost_basis - $4,
            realized_pnl = realized_pnl + $5,
            updated_at = now()
        WHERE portfolio_id = $1
          AND instrument_id = $2
        RETURNING
            id,
            portfolio_id,
            instrument_id,
            quantity,
            cost_basis,
            realized_pnl,
            created_at,
            updated_at
        "#,
    )
    .bind(portfolio_id)
    .bind(instrument_id)
    .bind(quantity_delta)
    .bind(removed_cost)
    .bind((proceeds - removed_cost).round_dp(COST_DECIMAL_PLACES))
    .fetch_optional(&mut *connection)
    .await?
    .ok_or(PositionError::NotFound {
        portfolio_id,
        instrument_id,
    })?;

    Position::try_from(row)
}

/// The cost basis a sale of `quantity` takes with it: all of it when the position closes,
/// otherwise its proportional share.
fn removed_cost_basis(position: &Position, quantity: Decimal) -> Decimal {
    if quantity >= position.quantity || position.quantity.is_zero() {
        return position.cost_basis;
    }
    (position.cost_basis * quantity / position.quantity)
        .round_dp(COST_DECIMAL_PLACES)
        .min(position.cost_basis)
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
            cost_basis: row.cost_basis,
            realized_pnl: row.realized_pnl,
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

    fn position(quantity: i64, cost_basis: i64) -> Position {
        Position {
            id: Uuid::new_v4(),
            portfolio_id: Uuid::new_v4(),
            instrument_id: Uuid::new_v4(),
            quantity: Decimal::from(quantity),
            cost_basis: Decimal::from(cost_basis),
            realized_pnl: Decimal::ZERO,
            created_at: Utc::now(),
            updated_at: Utc::now(),
        }
    }

    #[test]
    fn a_partial_sale_removes_a_proportional_cost_basis() {
        assert_eq!(
            removed_cost_basis(&position(10, 1_000), Decimal::from(4)),
            Decimal::from(400)
        );
    }

    #[test]
    fn closing_a_position_removes_all_of_its_cost_basis() {
        assert_eq!(
            removed_cost_basis(&position(3, 1_000), Decimal::from(3)),
            Decimal::from(1_000)
        );
    }
}
