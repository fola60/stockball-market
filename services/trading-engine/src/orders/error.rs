use rust_decimal::Decimal;
use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum OrderError {
    #[error("quoted price, cash balance or order budget changed")]
    QuoteChanged,

    #[error("order {0} was not found")]
    NotFound(Uuid),

    #[error("request_id cannot be empty")]
    EmptyRequestId,

    #[error("order quantity must be greater than zero: {0}")]
    NonPositiveQuantity(Decimal),

    #[error("order quantity supports at most 6 decimal places: {0}")]
    QuantityScaleTooPrecise(Decimal),

    #[error("unsupported order side: {0}")]
    UnsupportedOrderSide(String),

    #[error("unsupported order status: {0}")]
    UnsupportedOrderStatus(String),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
