use rust_decimal::{Decimal, MathematicalOps};

use super::{error::PriceImpactError, model::PriceImpactDirection};

pub const DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER: Decimal = Decimal::from_parts(25, 0, 0, false, 1);

const STORED_PRICE_DECIMAL_PLACES: u32 = 12;
const STORED_MONEY_DECIMAL_PLACES: u32 = 12;
const CALCULATION_TOLERANCE: Decimal = Decimal::from_parts(1, 0, 0, false, 18);

#[derive(Debug, Clone, PartialEq)]
pub struct PriceImpactQuote {
    pub old_price: Decimal,
    pub new_price: Decimal,
    pub execution_price: Decimal,
    pub gross_amount: Decimal,
    pub net_shares_purchased_after: Decimal,
}

/// Quotes a trade on an exponential price curve.
///
/// The price is `reference_price × multiplier ^ (net_shares_purchased ÷ curve_depth_shares)`:
/// net buying of `curve_depth_shares` reaches `multiplier` times the reference price, and the
/// same net selling reaches its reciprocal. The depth is usually a fraction of the supply, so
/// it sets how far each traded share moves the price.
pub fn quote_trade(
    reference_price: Decimal,
    curve_depth_shares: Decimal,
    net_shares_purchased: Decimal,
    full_supply_price_multiplier: Decimal,
    quantity: Decimal,
    direction: PriceImpactDirection,
) -> Result<PriceImpactQuote, PriceImpactError> {
    validate_curve_state(
        reference_price,
        curve_depth_shares,
        net_shares_purchased,
        full_supply_price_multiplier,
    )?;

    if quantity <= Decimal::ZERO {
        return Err(PriceImpactError::NonPositiveQuantity(quantity));
    }

    let net_shares_purchased_after = match direction {
        PriceImpactDirection::Buy => {
            let available = checked_sub(curve_depth_shares, net_shares_purchased)?;
            if quantity > available {
                return Err(PriceImpactError::BuyExceedsCurveLimit {
                    available,
                    requested: quantity,
                });
            }
            checked_add(net_shares_purchased, quantity)?
        }
        PriceImpactDirection::Sell => {
            let available = checked_add(curve_depth_shares, net_shares_purchased)?;
            if quantity > available {
                return Err(PriceImpactError::SellExceedsCurveLimit {
                    available,
                    requested: quantity,
                });
            }
            checked_sub(net_shares_purchased, quantity)?
        }
    };

    let old_price = price_at(
        reference_price,
        curve_depth_shares,
        net_shares_purchased,
        full_supply_price_multiplier,
    )?;
    let new_price = price_at(
        reference_price,
        curve_depth_shares,
        net_shares_purchased_after,
        full_supply_price_multiplier,
    )?;
    // Quantize the cumulative endpoints, not each order's independently calculated cost.
    // Adjacent trades then share the same endpoint and their stored costs telescope exactly.
    let old_cost = cumulative_cost(
        reference_price,
        curve_depth_shares,
        net_shares_purchased,
        full_supply_price_multiplier,
    )?
    .round_dp(STORED_MONEY_DECIMAL_PLACES);
    let new_cost = cumulative_cost(
        reference_price,
        curve_depth_shares,
        net_shares_purchased_after,
        full_supply_price_multiplier,
    )?
    .round_dp(STORED_MONEY_DECIMAL_PLACES);
    let exact_gross_amount = match direction {
        PriceImpactDirection::Buy => checked_sub(new_cost, old_cost)?,
        PriceImpactDirection::Sell => checked_sub(old_cost, new_cost)?,
    };
    let execution_price = checked_div(exact_gross_amount, quantity)?;

    Ok(PriceImpactQuote {
        old_price: old_price.round_dp(STORED_PRICE_DECIMAL_PLACES),
        new_price: new_price.round_dp(STORED_PRICE_DECIMAL_PLACES),
        execution_price: execution_price.round_dp(STORED_PRICE_DECIMAL_PLACES),
        gross_amount: exact_gross_amount,
        net_shares_purchased_after,
    })
}

fn validate_curve_state(
    reference_price: Decimal,
    curve_depth_shares: Decimal,
    net_shares_purchased: Decimal,
    full_supply_price_multiplier: Decimal,
) -> Result<(), PriceImpactError> {
    if reference_price <= Decimal::ZERO {
        return Err(PriceImpactError::NonPositiveReferencePrice(reference_price));
    }
    if curve_depth_shares <= Decimal::ZERO {
        return Err(PriceImpactError::NonPositiveCurveDepth(curve_depth_shares));
    }
    if net_shares_purchased < -curve_depth_shares || net_shares_purchased > curve_depth_shares {
        return Err(PriceImpactError::InvalidNetSharesPurchased {
            net_shares_purchased,
            curve_depth_shares,
        });
    }
    if full_supply_price_multiplier <= Decimal::ONE {
        return Err(PriceImpactError::InvalidFullSupplyPriceMultiplier(
            full_supply_price_multiplier,
        ));
    }
    Ok(())
}

fn price_at(
    reference_price: Decimal,
    curve_depth_shares: Decimal,
    net_shares_purchased: Decimal,
    full_supply_price_multiplier: Decimal,
) -> Result<Decimal, PriceImpactError> {
    let position = checked_div(net_shares_purchased, curve_depth_shares)?;
    let multiplier = curve_growth(full_supply_price_multiplier, position)?;

    checked_mul(reference_price, multiplier)
}

fn cumulative_cost(
    reference_price: Decimal,
    curve_depth_shares: Decimal,
    net_shares_purchased: Decimal,
    full_supply_price_multiplier: Decimal,
) -> Result<Decimal, PriceImpactError> {
    let position = checked_div(net_shares_purchased, curve_depth_shares)?;
    let growth = curve_growth(full_supply_price_multiplier, position)?;
    let logarithm = full_supply_price_multiplier
        .checked_ln()
        .ok_or(PriceImpactError::CalculationOverflow)?;
    let reference_curve_value = checked_mul(reference_price, curve_depth_shares)?;

    checked_div(checked_mul(reference_curve_value, growth)?, logarithm)
}

fn curve_growth(
    full_supply_price_multiplier: Decimal,
    position: Decimal,
) -> Result<Decimal, PriceImpactError> {
    let logarithm = full_supply_price_multiplier
        .checked_ln()
        .ok_or(PriceImpactError::CalculationOverflow)?;
    let exponent = checked_mul(position, logarithm)?;
    exponent
        .checked_exp_with_tolerance(CALCULATION_TOLERANCE)
        .ok_or(PriceImpactError::CalculationOverflow)
}

fn checked_add(left: Decimal, right: Decimal) -> Result<Decimal, PriceImpactError> {
    left.checked_add(right)
        .ok_or(PriceImpactError::CalculationOverflow)
}

fn checked_sub(left: Decimal, right: Decimal) -> Result<Decimal, PriceImpactError> {
    left.checked_sub(right)
        .ok_or(PriceImpactError::CalculationOverflow)
}

fn checked_mul(left: Decimal, right: Decimal) -> Result<Decimal, PriceImpactError> {
    left.checked_mul(right)
        .ok_or(PriceImpactError::CalculationOverflow)
}

fn checked_div(left: Decimal, right: Decimal) -> Result<Decimal, PriceImpactError> {
    left.checked_div(right)
        .ok_or(PriceImpactError::CalculationOverflow)
}

#[cfg(test)]
mod tests {
    use super::*;

    const REFERENCE_PRICE: Decimal = Decimal::from_parts(100, 0, 0, false, 0);
    const TOTAL_SHARES: Decimal = Decimal::from_parts(1_000_000, 0, 0, false, 0);

    #[test]
    fn a_shallower_curve_moves_further_for_the_same_trade() {
        let multiplier = Decimal::from(20);
        let quantity = Decimal::from(1_000);
        let full = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES,
            Decimal::ZERO,
            multiplier,
            quantity,
            PriceImpactDirection::Buy,
        )
        .unwrap();
        let shallow = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES / Decimal::from(15),
            Decimal::ZERO,
            multiplier,
            quantity,
            PriceImpactDirection::Buy,
        )
        .unwrap();

        // 20^(1000/1e6) − 1 ≈ 0.30% on the full supply, 20^(1000/66666.67) − 1 ≈ 4.6% on a
        // fifteenth of it: fifteen times the exponent.
        let full_move = (full.new_price / REFERENCE_PRICE).ln();
        let shallow_move = (shallow.new_price / REFERENCE_PRICE).ln();
        assert!((shallow_move / full_move - Decimal::from(15)).abs() < Decimal::new(1, 6));
        assert_eq!(shallow.net_shares_purchased_after, quantity);
    }

    #[test]
    fn a_shallow_curve_ends_at_its_depth() {
        let depth = TOTAL_SHARES / Decimal::from(15);
        let error = quote_trade(
            REFERENCE_PRICE,
            depth,
            depth - Decimal::from(10),
            Decimal::from(20),
            Decimal::from(11),
            PriceImpactDirection::Buy,
        )
        .unwrap_err();

        assert!(matches!(
            error,
            PriceImpactError::BuyExceedsCurveLimit { .. }
        ));
    }

    #[test]
    fn buying_the_full_supply_reaches_the_configured_multiplier() {
        let quote = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES,
            Decimal::ZERO,
            DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER,
            TOTAL_SHARES,
            PriceImpactDirection::Buy,
        )
        .unwrap();

        assert_eq!(quote.old_price, Decimal::from(100));
        assert_eq!(quote.new_price, Decimal::from(250));
        assert_eq!(quote.net_shares_purchased_after, TOTAL_SHARES);
    }

    #[test]
    fn multiplier_is_configurable_per_curve() {
        let quote = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES,
            Decimal::ZERO,
            Decimal::TWO,
            TOTAL_SHARES,
            PriceImpactDirection::Buy,
        )
        .unwrap();

        assert_eq!(quote.new_price, Decimal::from(200));
    }

    #[test]
    fn selling_the_full_scale_reaches_the_reciprocal_multiplier() {
        let quote = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES,
            Decimal::ZERO,
            DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER,
            TOTAL_SHARES,
            PriceImpactDirection::Sell,
        )
        .unwrap();

        assert_eq!(quote.new_price, Decimal::from(40));
        assert_eq!(quote.net_shares_purchased_after, -TOTAL_SHARES);
    }

    #[test]
    fn price_rises_more_in_the_second_half_of_the_curve() {
        let first_half = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES,
            Decimal::ZERO,
            DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER,
            Decimal::from(500_000),
            PriceImpactDirection::Buy,
        )
        .unwrap();
        let second_half = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES,
            Decimal::from(500_000),
            DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER,
            Decimal::from(500_000),
            PriceImpactDirection::Buy,
        )
        .unwrap();

        assert!(
            second_half.new_price - second_half.old_price
                > first_half.new_price - first_half.old_price
        );
    }

    #[test]
    fn combined_and_separate_orders_have_the_same_cost_and_end_price() {
        let combined_quantity = Decimal::new(133_001, 3);
        let combined = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES,
            Decimal::ZERO,
            DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER,
            combined_quantity,
            PriceImpactDirection::Buy,
        )
        .unwrap();

        let mut net_shares_purchased = Decimal::ZERO;
        let mut separate_cost = Decimal::ZERO;
        let mut separate_end_price = REFERENCE_PRICE;
        for quantity in [Decimal::from(100), Decimal::from(33), Decimal::new(1, 3)] {
            let quote = quote_trade(
                REFERENCE_PRICE,
                TOTAL_SHARES,
                net_shares_purchased,
                DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER,
                quantity,
                PriceImpactDirection::Buy,
            )
            .unwrap();
            net_shares_purchased = quote.net_shares_purchased_after;
            separate_cost += quote.gross_amount;
            separate_end_price = quote.new_price;
        }

        assert_eq!(separate_end_price, combined.new_price);
        assert_eq!(separate_cost, combined.gross_amount);
    }

    #[test]
    fn a_buy_followed_by_the_same_sell_reverses_at_the_same_cost() {
        let buy = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES,
            Decimal::ZERO,
            DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER,
            Decimal::new(133_001, 3),
            PriceImpactDirection::Buy,
        )
        .unwrap();
        let sell = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES,
            buy.net_shares_purchased_after,
            DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER,
            Decimal::new(133_001, 3),
            PriceImpactDirection::Sell,
        )
        .unwrap();

        assert_eq!(sell.new_price, REFERENCE_PRICE);
        assert_eq!(sell.net_shares_purchased_after, Decimal::ZERO);
        assert_eq!(sell.gross_amount, buy.gross_amount);
        assert_eq!(sell.execution_price, buy.execution_price);
    }

    #[test]
    fn fractional_orders_retain_sub_four_decimal_price_movement() {
        let quote = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES,
            Decimal::ZERO,
            DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER,
            Decimal::new(1, 6),
            PriceImpactDirection::Buy,
        )
        .unwrap();

        assert!(quote.new_price > quote.old_price);
        assert!(quote.gross_amount > Decimal::ZERO);
    }

    #[test]
    fn buy_cannot_exceed_the_remaining_supply() {
        let error = quote_trade(
            REFERENCE_PRICE,
            TOTAL_SHARES,
            Decimal::from(999_999),
            DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER,
            Decimal::from(2),
            PriceImpactDirection::Buy,
        )
        .unwrap_err();

        assert!(matches!(
            error,
            PriceImpactError::BuyExceedsCurveLimit { .. }
        ));
    }
}
