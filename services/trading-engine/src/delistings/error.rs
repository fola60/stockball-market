use uuid::Uuid;

use crate::{
    freezes::FreezeError, index_funds::IndexFundError, instruments::InstrumentError,
    ledger::LedgerError, portfolios::PortfolioError, positions::PositionError,
    snapshots::SnapshotError,
};

#[derive(Debug, thiserror::Error)]
pub enum DelistingError {
    #[error("a delisting must give a reason")]
    EmptyReason,

    #[error("instrument {0} is still trading; only a halted share can be delisted")]
    StillTrading(Uuid),

    #[error("instrument {0} is not a player share")]
    NotAPlayerShare(Uuid),

    #[error(transparent)]
    Freeze(#[from] FreezeError),

    #[error(transparent)]
    IndexFund(#[from] IndexFundError),

    #[error(transparent)]
    Instrument(#[from] InstrumentError),

    #[error(transparent)]
    Ledger(#[from] LedgerError),

    #[error(transparent)]
    Portfolio(#[from] PortfolioError),

    #[error(transparent)]
    Position(#[from] PositionError),

    #[error(transparent)]
    Snapshot(#[from] SnapshotError),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
