use rust_decimal::Decimal;
use uuid::Uuid;

use crate::{
    idempotency::IdempotencyError, instruments::InstrumentError, ledger::LedgerError,
    positions::PositionError, snapshots::SnapshotError,
};

#[derive(Debug, thiserror::Error)]
pub enum ProvisioningError {
    #[error("request_id must not be empty")]
    EmptyRequestId,

    #[error("amount must be greater than zero: {0}")]
    NonPositiveAmount(Decimal),

    #[error("price must be greater than zero: {0}")]
    NonPositivePrice(Decimal),

    #[error("initial supply issuance must include at least one allocation")]
    EmptyAllocations,

    #[error("allocation quantity must be greater than zero: {0}")]
    NonPositiveQuantity(Decimal),

    #[error("portfolio {portfolio_id} is allocated instrument {instrument_id} more than once")]
    DuplicateAllocation {
        instrument_id: Uuid,
        portfolio_id: Uuid,
    },

    #[error(
        "allocations for instrument {instrument_id} total {allocated}, but shares outstanding are {shares_outstanding}"
    )]
    SupplyMismatch {
        instrument_id: Uuid,
        allocated: Decimal,
        shares_outstanding: Decimal,
    },

    #[error("instrument {0} already has orders, trades, or positions")]
    MarketActivityExists(Uuid),

    #[error(transparent)]
    Idempotency(#[from] IdempotencyError),

    #[error(transparent)]
    Instrument(#[from] InstrumentError),

    #[error(transparent)]
    Ledger(#[from] LedgerError),

    #[error(transparent)]
    Position(#[from] PositionError),

    #[error(transparent)]
    Snapshot(#[from] SnapshotError),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
