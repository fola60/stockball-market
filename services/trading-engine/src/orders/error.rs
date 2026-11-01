use rust_decimal::Decimal;
use uuid::Uuid;

use super::OrderSide;

#[derive(Debug, thiserror::Error)]
pub enum OrderError {
    #[error("quoted price, cash balance or order budget changed")]
    QuoteChanged,

    #[error(
        "the price moved: the {side} would move {cash_amount} cash against a limit of {limit}"
    )]
    CashLimitExceeded {
        side: OrderSide,
        limit: Decimal,
        cash_amount: Decimal,
    },

    #[error("cash amount must be greater than zero: {0}")]
    NonPositiveCashAmount(Decimal),

    #[error("cash amount {0} is too small to buy any shares")]
    CashAmountTooSmall(Decimal),

    #[error("a quote needs exactly one of quantity and cash_amount")]
    AmbiguousQuoteSize,

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
