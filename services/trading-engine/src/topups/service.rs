use sqlx::PgPool;

use crate::{
    idempotency::{self, IdempotencyClaim},
    ledger::{self, CashLedgerEntry, LedgerReason},
};

use super::{ApplyTopupCommand, TopupError};

pub async fn apply_topup(
    pool: &PgPool,
    command: ApplyTopupCommand,
) -> Result<CashLedgerEntry, TopupError> {
    command.validate()?;

    let request_hash = command.request_fingerprint();
    let mut transaction = pool.begin().await?;

    match idempotency::claim_topup(&mut transaction, &command.request_id, &request_hash).await? {
        IdempotencyClaim::Completed(record) => {
            let entry = record.deserialize_response::<CashLedgerEntry>()?;
            transaction.commit().await?;
            return Ok(entry);
        }
        IdempotencyClaim::Claimed(_) => {}
    }

    let entry = match command.reason {
        LedgerReason::WeeklyTopup => {
            ledger::credit_weekly_topup(
                &mut transaction,
                command.account_id,
                command.portfolio_id,
                command.amount,
                &command.request_id,
            )
            .await?
        }
        LedgerReason::MonthlyTopup => {
            ledger::credit_monthly_topup(
                &mut transaction,
                command.account_id,
                command.portfolio_id,
                command.amount,
                &command.request_id,
            )
            .await?
        }
        _ => return Err(TopupError::UnsupportedReason),
    };

    idempotency::complete_topup(&mut transaction, &command.request_id, 200, &entry).await?;
    transaction.commit().await?;
    Ok(entry)
}
