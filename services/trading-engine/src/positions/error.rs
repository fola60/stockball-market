use rust_decimal::Decimal;
use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum PositionError {
    #[error("position for portfolio {portfolio_id} and instrument {instrument_id} was not found")]
    NotFound {
        portfolio_id: Uuid,
        instrument_id: Uuid,
    },

    #[error("position quantity change must be greater than zero: {0}")]
    NonPositiveQuantity(Decimal),

    #[error(
        "portfolio {portfolio_id} has insufficient position quantity for instrument {instrument_id}: available {available}, required {required}"
    )]
    InsufficientQuantity {
        portfolio_id: Uuid,
        instrument_id: Uuid,
        available: Decimal,
        required: Decimal,
    },

    #[error("position {position_id} quantity cannot be negative: {quantity}")]
    NegativeQuantity {
        position_id: Uuid,
        quantity: Decimal,
    },

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
