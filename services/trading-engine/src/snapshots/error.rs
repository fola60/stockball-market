use rust_decimal::Decimal;
use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum SnapshotError {
    #[error("price snapshot {0} was not found")]
    NotFound(Uuid),

    #[error("price snapshot price cannot be negative: {0}")]
    NegativePrice(Decimal),

    #[error("unsupported price snapshot reason: {0}")]
    UnsupportedSnapshotReason(String),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
