use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use uuid::Uuid;

#[derive(Debug, Clone, PartialEq)]
pub struct Position {
    pub id: Uuid,
    pub portfolio_id: Uuid,
    pub instrument_id: Uuid,
    pub quantity: Decimal,
    /// What the shares still held cost, fees included, on a weighted-average basis.
    pub cost_basis: Decimal,
    /// Profit or loss locked in by sales: proceeds after fees less the cost basis they removed.
    pub realized_pnl: Decimal,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}
