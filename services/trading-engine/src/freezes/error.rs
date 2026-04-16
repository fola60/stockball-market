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

    #[error(transparent)]
    Instrument(#[from] InstrumentError),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
