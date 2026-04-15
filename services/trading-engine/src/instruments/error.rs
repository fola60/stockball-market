use uuid::Uuid;

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

    #[error("instrument price cannot be negative")]
    NegativePrice,

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
