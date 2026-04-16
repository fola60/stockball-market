use rust_decimal::Decimal;

#[derive(Debug, thiserror::Error)]
pub enum PriceImpactError {
    #[error("current price cannot be negative: {0}")]
    NegativeCurrentPrice(Decimal),

    #[error("trade quantity must be greater than zero: {0}")]
    NonPositiveQuantity(Decimal),

    #[error("price impact unit cannot be negative: {0}")]
    NegativePriceImpactUnit(Decimal),

    #[error("resulting price cannot be negative: {0}")]
    NegativeResultingPrice(Decimal),
}
