use rust_decimal::Decimal;

use super::{error::PriceImpactError, model::PriceImpactDirection};

pub fn calculate_next_price(
    current_price: Decimal,
    quantity: Decimal,
    price_impact_unit: Decimal,
    direction: PriceImpactDirection,
) -> Result<Decimal, PriceImpactError> {
    if current_price.is_sign_negative() {
        return Err(PriceImpactError::NegativeCurrentPrice(current_price));
    }

    if quantity <= Decimal::ZERO {
        return Err(PriceImpactError::NonPositiveQuantity(quantity));
    }

    if price_impact_unit.is_sign_negative() {
        return Err(PriceImpactError::NegativePriceImpactUnit(price_impact_unit));
    }

    let price_delta = quantity * price_impact_unit;
    let next_price = match direction {
        PriceImpactDirection::Buy => current_price + price_delta,
        PriceImpactDirection::Sell => current_price - price_delta,
    }
    .round_dp(4);

    if next_price.is_sign_negative() {
        return Err(PriceImpactError::NegativeResultingPrice(next_price));
    }

    Ok(next_price)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn buy_increases_price_by_quantity_times_impact_unit() {
        let next_price = calculate_next_price(
            Decimal::new(100_0000, 4),
            Decimal::new(10_000000, 6),
            Decimal::new(10000, 6),
            PriceImpactDirection::Buy,
        )
        .unwrap();

        assert_eq!(next_price, Decimal::new(100_1000, 4));
    }

    #[test]
    fn sell_decreases_price_by_quantity_times_impact_unit() {
        let next_price = calculate_next_price(
            Decimal::new(100_0000, 4),
            Decimal::new(10_000000, 6),
            Decimal::new(10000, 6),
            PriceImpactDirection::Sell,
        )
        .unwrap();

        assert_eq!(next_price, Decimal::new(99_9000, 4));
    }

    #[test]
    fn sell_rejects_negative_resulting_price() {
        let error = calculate_next_price(
            Decimal::new(1_0000, 4),
            Decimal::new(2_000000, 6),
            Decimal::new(1_000000, 6),
            PriceImpactDirection::Sell,
        )
        .unwrap_err();

        assert!(matches!(error, PriceImpactError::NegativeResultingPrice(_)));
    }
}
