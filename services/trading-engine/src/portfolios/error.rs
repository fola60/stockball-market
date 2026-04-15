use rust_decimal::Decimal;
use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum PortfolioError {
    #[error("portfolio {0} was not found")]
    NotFound(Uuid),

    #[error("portfolio for account {0} was not found")]
    NotFoundForAccount(Uuid),

    #[error(
        "portfolio {portfolio_id} belongs to account {actual_account_id}, not {expected_account_id}"
    )]
    AccountMismatch {
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

    #[error("portfolio {portfolio_id} cash balance cannot be negative: {cash_balance}")]
    NegativeCashBalance {
        portfolio_id: Uuid,
        cash_balance: Decimal,
    },

    #[error("portfolio {portfolio_id} required cash cannot be negative: {required}")]
    NegativeRequiredCash {
        portfolio_id: Uuid,
        required: Decimal,
    },

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
