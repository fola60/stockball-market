use sqlx::PgConnection;
use uuid::Uuid;

use crate::instruments::{self, Instrument, InstrumentStatus};

use super::error::FreezeError;

pub fn assert_not_frozen(instrument: &Instrument) -> Result<(), FreezeError> {
    if instrument.status == InstrumentStatus::Frozen {
        return Err(FreezeError::Frozen {
            instrument_id: instrument.id,
        });
    }

    Ok(())
}

pub async fn freeze_instrument(
    connection: &mut PgConnection,
    instrument_id: Uuid,
) -> Result<Instrument, FreezeError> {
    let instrument = instruments::lock_instrument_by_id(&mut *connection, instrument_id).await?;

    if instrument.status == InstrumentStatus::Delisted {
        return Err(FreezeError::CannotFreeze {
            instrument_id,
            status: instrument.status,
        });
    }

    set_trading_status(connection, instrument_id, InstrumentStatus::Frozen).await
}

pub async fn unfreeze_instrument(
    connection: &mut PgConnection,
    instrument_id: Uuid,
) -> Result<Instrument, FreezeError> {
    set_trading_status(connection, instrument_id, InstrumentStatus::Active).await
}

async fn set_trading_status(
    connection: &mut PgConnection,
    instrument_id: Uuid,
    status: InstrumentStatus,
) -> Result<Instrument, FreezeError> {
    sqlx::query(
        r#"
        UPDATE instruments
        SET
            trading_status = $2,
            updated_at = now()
        WHERE id = $1
        "#,
    )
    .bind(instrument_id)
    .bind(status.as_str())
    .execute(&mut *connection)
    .await?;

    Ok(instruments::lock_instrument_by_id(connection, instrument_id).await?)
}
