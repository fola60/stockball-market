use rust_decimal::Decimal;

#[derive(Debug, thiserror::Error)]
pub enum PriceImpactError {
    #[error("trade quantity must be greater than zero: {0}")]
    NonPositiveQuantity(Decimal),

    #[error("reference price must be positive: {0}")]
    NonPositiveReferencePrice(Decimal),

    #[error("shares outstanding must be positive: {0}")]
    NonPositiveSharesOutstanding(Decimal),

    #[error(
        "net shares purchased {net_shares_purchased} must be between negative and positive shares outstanding {shares_outstanding}"
    )]
    InvalidNetSharesPurchased {
        net_shares_purchased: Decimal,
        shares_outstanding: Decimal,
    },

    #[error("full-supply price multiplier must be greater than one: {0}")]
    InvalidFullSupplyPriceMultiplier(Decimal),

    #[error("buy exceeds curve limit: available {available}, requested {requested}")]
    BuyExceedsCurveLimit {
        available: Decimal,
        requested: Decimal,
    },

    #[error("sell exceeds curve limit: available {available}, requested {requested}")]
    SellExceedsCurveLimit {
        available: Decimal,
        requested: Decimal,
    },

    #[error("price curve calculation exceeded supported decimal precision")]
    CalculationOverflow,
}
