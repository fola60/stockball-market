use rust_decimal::Decimal;
use uuid::Uuid;

use crate::{
    instruments::{InstrumentError, InstrumentStatus},
    snapshots::SnapshotError,
};

#[derive(Debug, thiserror::Error)]
pub enum IndexFundError {
    #[error("request_id must not be empty")]
    EmptyRequestId,

    #[error("a rebalance must give a reason")]
    EmptyReason,

    #[error("instrument {0} is not an index fund")]
    NotAnIndexFund(Uuid),

    #[error("request {0} was already used for a different fund")]
    RequestMismatch(String),

    #[error("index fund symbol must not be empty")]
    EmptySymbol,

    #[error("index fund display name must not be empty")]
    EmptyDisplayName,

    #[error("team index funds must name their club")]
    MissingClub,

    #[error("an index fund must hold at least one player share")]
    EmptyConstituents,

    #[error("instrument {0} appears more than once in the basket")]
    DuplicateConstituent(Uuid),

    #[error(
        "shares per unit for {instrument_id} must be positive with at most six decimal places: \
         {shares_per_unit}"
    )]
    InvalidSharesPerUnit {
        instrument_id: Uuid,
        shares_per_unit: Decimal,
    },

    #[error("unsupported index kind: {0}")]
    UnsupportedIndexKind(String),

    #[error("instrument {0} is not a player share")]
    ConstituentNotPlayerShare(Uuid),

    #[error("instrument {instrument_id} cannot join a fund while {status}")]
    ConstituentNotListed {
        instrument_id: Uuid,
        status: InstrumentStatus,
    },

    #[error("symbol {0} already belongs to a different instrument or basket")]
    SymbolTaken(String),

    #[error("index fund {0} has no constituents")]
    MissingBasket(Uuid),

    #[error(transparent)]
    Instrument(#[from] InstrumentError),

    #[error(transparent)]
    Snapshot(#[from] SnapshotError),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
