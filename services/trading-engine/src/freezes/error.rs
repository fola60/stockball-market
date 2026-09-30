use uuid::Uuid;

use crate::instruments::{InstrumentError, InstrumentStatus};

#[derive(Debug, thiserror::Error)]
pub enum FreezeError {
    #[error("instrument {instrument_id} is frozen")]
    Frozen { instrument_id: Uuid },

    #[error("instrument {instrument_id} cannot be frozen because its status is {status}")]
    CannotFreeze {
        instrument_id: Uuid,
        status: InstrumentStatus,
    },

    #[error("freeze source_key must not be empty")]
    EmptySourceKey,

    #[error("a freeze must include at least one instrument")]
    EmptyInstruments,

    #[error("unsupported freeze reason: {0}")]
    UnsupportedReason(String),

    #[error(transparent)]
    Instrument(#[from] InstrumentError),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
