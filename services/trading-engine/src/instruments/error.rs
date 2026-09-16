use uuid::Uuid;

use crate::snapshots::SnapshotError;

use super::model::InstrumentStatus;

#[derive(Debug, thiserror::Error)]
pub enum InstrumentError {
    #[error("instrument {0} was not found")]
    NotFound(Uuid),

    #[error("instrument {instrument_id} is not active: {status}")]
    NotActive {
        instrument_id: Uuid,
        status: InstrumentStatus,
    },

    #[error("instrument {instrument_id} is not tradable: {status}")]
    NotTradable {
        instrument_id: Uuid,
        status: InstrumentStatus,
    },

    #[error("unsupported instrument type: {0}")]
    UnsupportedInstrumentType(String),

    #[error("unsupported instrument status: {0}")]
    UnsupportedInstrumentStatus(String),

    #[error("invalid instrument record {instrument_id}: {reason}")]
    InvalidRecord { instrument_id: Uuid, reason: String },

    #[error("instrument price must be positive")]
    NegativePrice,

    #[error("player-share seed value is invalid: {reason}")]
    InvalidSeedValue { reason: String },

    #[error(transparent)]
    Snapshot(#[from] SnapshotError),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
