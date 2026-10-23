//! Sizes an order from a cash amount instead of a share count.
//!
//! An order's cost grows faster than its size because each share moves the price, so the share
//! count for an amount is found by bisection over whole millionths of a share, the finest
//! quantity an order can have. The cash function is the same one the order is priced with,
//! fee included, so the quote it produces is exactly affordable.

use rust_decimal::Decimal;

use crate::orders::{OrderError, OrderSide};

use super::error::ExecutionError;

const QUANTITY_DECIMAL_PLACES: u32 = 6;

/// The share count for `cash_amount`.
///
/// A buy gets the most shares whose cost, fee included, is at most the amount. A sale gets the
/// fewest shares whose proceeds after the fee reach the amount, but never more than
/// `max_quantity`: asking for more than a position can raise sells the whole position, and the
/// quote shows what that pays.
///
/// `cash_for` prices a quantity. It may fail for quantities the market cannot fill, such as a
/// buy past the end of a price curve; those count as too large.
pub(crate) fn quantity_for_cash(
    side: OrderSide,
    cash_amount: Decimal,
    max_quantity: Decimal,
    mut cash_for: impl FnMut(Decimal) -> Result<Decimal, ExecutionError>,
) -> Result<Decimal, ExecutionError> {
    let max_units = to_units(max_quantity);
    if max_units == 0 {
        return Err(OrderError::CashAmountTooSmall(cash_amount).into());
    }

    match side {
        OrderSide::Buy => {
            // The largest affordable quantity: `low` is always affordable, `high` never.
            let (mut low, mut high) = (0_u64, max_units + 1);
            while high - low > 1 {
                let middle = low + (high - low) / 2;
                match cash_for(from_units(middle)) {
                    Ok(cost) if cost <= cash_amount => low = middle,
                    _ => high = middle,
                }
            }
            if low == 0 {
                return Err(OrderError::CashAmountTooSmall(cash_amount).into());
            }
            Ok(from_units(low))
        }
        OrderSide::Sell => {
            if matches!(cash_for(from_units(max_units)), Ok(proceeds) if proceeds < cash_amount) {
                return Ok(from_units(max_units));
            }
            // The smallest sufficient quantity: `high` always raises enough, `low` never.
            let (mut low, mut high) = (0_u64, max_units);
            while high - low > 1 {
                let middle = low + (high - low) / 2;
                match cash_for(from_units(middle)) {
                    Ok(proceeds) if proceeds < cash_amount => low = middle,
                    _ => high = middle,
                }
            }
            Ok(from_units(high))
        }
    }
}

fn to_units(quantity: Decimal) -> u64 {
    if quantity <= Decimal::ZERO {
        return 0;
    }
    let units = quantity.round_dp_with_strategy(
        QUANTITY_DECIMAL_PLACES,
        rust_decimal::RoundingStrategy::ToZero,
    ) * Decimal::from(1_000_000_u64);
    u64::try_from(units).unwrap_or(u64::MAX / 2)
}

fn from_units(units: u64) -> Decimal {
    Decimal::from(units) / Decimal::from(1_000_000_u64)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A price that rises by a penny for every share already bought, plus a 1% fee.
    fn rising_cost(quantity: Decimal) -> Result<Decimal, ExecutionError> {
        let gross = Decimal::from(10) * quantity + quantity * quantity / Decimal::from(200);
        Ok(gross * Decimal::new(101, 2))
    }

    #[test]
    fn buys_the_most_shares_the_amount_affords() {
        let amount = Decimal::from(1_000);
        let quantity =
            quantity_for_cash(OrderSide::Buy, amount, Decimal::from(1_000), rising_cost).unwrap();

        assert!(rising_cost(quantity).unwrap() <= amount);
        assert!(rising_cost(quantity + Decimal::new(1, 6)).unwrap() > amount);
    }

    #[test]
    fn sells_the_fewest_shares_that_raise_the_amount() {
        let proceeds = |quantity: Decimal| Ok(Decimal::from(10) * quantity * Decimal::new(99, 2));
        let quantity = quantity_for_cash(
            OrderSide::Sell,
            Decimal::from(500),
            Decimal::from(80),
            proceeds,
        )
        .unwrap();

        assert!(proceeds(quantity).unwrap() >= Decimal::from(500));
        assert!(proceeds(quantity - Decimal::new(1, 6)).unwrap() < Decimal::from(500));
    }

    #[test]
    fn a_sale_larger_than_the_position_sells_all_of_it() {
        let proceeds = |quantity: Decimal| Ok(Decimal::from(10) * quantity);
        let quantity = quantity_for_cash(
            OrderSide::Sell,
            Decimal::from(500),
            Decimal::from(20),
            proceeds,
        )
        .unwrap();

        assert_eq!(quantity, Decimal::from(20));
    }

    #[test]
    fn unfillable_quantities_count_as_too_large() {
        let capped = |quantity: Decimal| {
            if quantity > Decimal::from(3) {
                Err(OrderError::QuoteChanged.into())
            } else {
                Ok(quantity)
            }
        };
        let quantity = quantity_for_cash(
            OrderSide::Buy,
            Decimal::from(100),
            Decimal::from(100),
            capped,
        )
        .unwrap();

        assert_eq!(quantity, Decimal::from(3));
    }

    #[test]
    fn an_amount_too_small_for_one_millionth_of_a_share_is_refused() {
        let error = quantity_for_cash(
            OrderSide::Buy,
            Decimal::new(1, 9),
            Decimal::from(10),
            rising_cost,
        )
        .unwrap_err();

        assert!(matches!(
            error,
            ExecutionError::Order(OrderError::CashAmountTooSmall(_))
        ));
    }
}
