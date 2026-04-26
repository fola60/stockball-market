use uuid::Uuid;

use crate::{
    freezes::FreezeError, idempotency::IdempotencyError, instruments::InstrumentError,
    ledger::LedgerError, orders::OrderError, portfolios::PortfolioError, positions::PositionError,
    price_impact::PriceImpactError, snapshots::SnapshotError,
};

#[derive(Debug, thiserror::Error)]
pub enum ExecutionError {
    #[error("trade {0} was not found")]
    TradeNotFound(Uuid),

    #[error(transparent)]
    Freeze(#[from] FreezeError),

    #[error(transparent)]
    Idempotency(#[from] IdempotencyError),

    #[error(transparent)]
    Instrument(#[from] InstrumentError),

    #[error(transparent)]
    Ledger(#[from] LedgerError),

    #[error(transparent)]
    Order(#[from] OrderError),

    #[error(transparent)]
    Portfolio(#[from] PortfolioError),

    #[error(transparent)]
    Position(#[from] PositionError),

    #[error(transparent)]
    PriceImpact(#[from] PriceImpactError),

    #[error(transparent)]
    Snapshot(#[from] SnapshotError),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
