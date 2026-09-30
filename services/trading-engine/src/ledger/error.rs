use rust_decimal::Decimal;
use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum LedgerError {
    #[error("portfolio {0} was not found")]
    PortfolioNotFound(Uuid),

    #[error("portfolio {portfolio_id} belongs to account {actual_account_id}, not {expected_account_id}")]
    PortfolioAccountMismatch {
        portfolio_id: Uuid,
        expected_account_id: Uuid,
        actual_account_id: Uuid,
    },

    #[error(
        "portfolio {portfolio_id} has insufficient cash: available {available}, required {required}"
    )]
    InsufficientCash {
        portfolio_id: Uuid,
        available: Decimal,
        required: Decimal,
    },

    #[error("cash movement amount must be greater than zero: {0}")]
    NonPositiveAmount(Decimal),

    #[error("portfolio {portfolio_id} cash balance cannot be negative: {cash_balance}")]
    NegativeCashBalance {
        portfolio_id: Uuid,
        cash_balance: Decimal,
    },

    #[error("portfolio {portfolio_id} cash update was rejected for delta {amount_delta}")]
    CashUpdateRejected {
        portfolio_id: Uuid,
        amount_delta: Decimal,
    },

    #[error("portfolio {0} has already received its opening balance")]
    OpeningBalanceAlreadyApplied(Uuid),

    #[error("unsupported ledger reason: {0}")]
    UnsupportedLedgerReason(String),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
