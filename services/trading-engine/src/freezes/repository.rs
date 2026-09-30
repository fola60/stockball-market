use sqlx::{PgConnection, PgPool};
use uuid::Uuid;

use crate::instruments::{self, Instrument, InstrumentStatus};

use super::{
    error::FreezeError,
    model::{ApplyFreezeCommand, ApplyFreezeResult, ReleaseFreezeCommand, ReleaseFreezeResult},
};

pub fn assert_not_frozen(instrument: &Instrument) -> Result<(), FreezeError> {
    if instrument.status == InstrumentStatus::Frozen {
        return Err(FreezeError::Frozen {
            instrument_id: instrument.id,
        });
    }

    Ok(())
}

pub async fn apply_freeze(
    pool: &PgPool,
    command: ApplyFreezeCommand,
) -> Result<ApplyFreezeResult, FreezeError> {
    command.validate()?;

    let mut transaction = pool.begin().await?;
    let mut result = ApplyFreezeResult {
        source_key: command.source_key.clone(),
        reason: command.reason,
        opened_count: 0,
        already_open_count: 0,
        skipped_delisted_count: 0,
    };

    for instrument_id in command.sorted_instrument_ids() {
        let instrument =
            instruments::lock_instrument_by_id(&mut transaction, instrument_id).await?;
        if instrument.status == InstrumentStatus::Delisted {
            result.skipped_delisted_count += 1;
            continue;
        }

        let opened = sqlx::query_scalar::<_, Uuid>(
            r#"
            INSERT INTO instrument_freezes (instrument_id, reason, source_key)
            VALUES ($1, $2, $3)
            ON CONFLICT (instrument_id, source_key) WHERE released_at IS NULL DO NOTHING
            RETURNING id
            "#,
        )
        .bind(instrument_id)
        .bind(command.reason.as_str())
        .bind(&command.source_key)
        .fetch_optional(&mut *transaction)
        .await?;

        if opened.is_some() {
            result.opened_count += 1;
        } else {
            result.already_open_count += 1;
        }
        if instrument.status == InstrumentStatus::Active {
            set_trading_status(&mut transaction, instrument_id, InstrumentStatus::Frozen).await?;
        }
    }

    transaction.commit().await?;
    Ok(result)
}

pub async fn release_freeze(
    pool: &PgPool,
    command: ReleaseFreezeCommand,
) -> Result<ReleaseFreezeResult, FreezeError> {
    command.validate()?;

    let mut transaction = pool.begin().await?;
    let instrument_ids = sqlx::query_scalar::<_, Uuid>(
        r#"
        SELECT instrument_id
        FROM instrument_freezes
        WHERE source_key = $1
          AND released_at IS NULL
        ORDER BY instrument_id
        "#,
    )
    .bind(&command.source_key)
    .fetch_all(&mut *transaction)
    .await?;

    let mut reactivated_instrument_ids = Vec::new();
    // Instruments are locked before their freeze rows, in id order, matching apply_freeze.
    for instrument_id in &instrument_ids {
        let instrument =
            instruments::lock_instrument_by_id(&mut transaction, *instrument_id).await?;
        sqlx::query(
            r#"
            UPDATE instrument_freezes
            SET released_at = now()
            WHERE instrument_id = $1
              AND source_key = $2
              AND released_at IS NULL
            "#,
        )
        .bind(instrument_id)
        .bind(&command.source_key)
        .execute(&mut *transaction)
        .await?;

        let still_frozen = sqlx::query_scalar::<_, bool>(
            r#"
            SELECT EXISTS (
                SELECT 1
                FROM instrument_freezes
                WHERE instrument_id = $1
                  AND released_at IS NULL
            )
            "#,
        )
        .bind(instrument_id)
        .fetch_one(&mut *transaction)
        .await?;

        if !still_frozen && instrument.status == InstrumentStatus::Frozen {
            set_trading_status(&mut transaction, *instrument_id, InstrumentStatus::Active).await?;
            reactivated_instrument_ids.push(*instrument_id);
        }
    }

    transaction.commit().await?;
    Ok(ReleaseFreezeResult {
        source_key: command.source_key,
        released_count: instrument_ids.len(),
        reactivated_instrument_ids,
    })
}

async fn set_trading_status(
    connection: &mut PgConnection,
    instrument_id: Uuid,
    status: InstrumentStatus,
) -> Result<(), FreezeError> {
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
    Ok(())
}
