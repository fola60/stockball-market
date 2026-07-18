use rust_decimal::Decimal;

use crate::{idempotency::IdempotencyError, ledger::LedgerError};

#[derive(Debug, thiserror::Error)]
pub enum TopupError {
    #[error("request_id must not be empty")]
    EmptyRequestId,

    #[error("top-up amount must be greater than zero: {0}")]
    NonPositiveAmount(Decimal),

    #[error("top-ups only support WEEKLY_TOPUP or MONTHLY_TOPUP reasons")]
    UnsupportedReason,

    #[error(transparent)]
    Idempotency(#[from] IdempotencyError),

    #[error(transparent)]
    Ledger(#[from] LedgerError),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
