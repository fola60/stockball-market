//! The trading fee charged on every order a trader places.
//!
//! The fee is a share of the order's gross amount: a buyer pays it on top of the shares' cost
//! and a seller has it taken from the proceeds. It makes an instant buy-then-sell round trip
//! lose money, so a trader cannot profit from moving a price and reversing it. Custody legs of
//! index fund trades, rebalances and delisting buyouts are never charged.

use rust_decimal::{Decimal, RoundingStrategy};
use serde::{Deserialize, Serialize};

use crate::orders::OrderSide;

const CASH_DECIMAL_PLACES: u32 = 12;

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct TradingFee {
    #[serde(with = "rust_decimal::serde::str")]
    pub rate: Decimal,
}

impl TradingFee {
    pub const NONE: Self = Self {
        rate: Decimal::ZERO,
    };

    /// 0.5% of each order's gross amount.
    pub const DEFAULT: Self = Self {
        rate: Decimal::from_parts(5, 0, 0, false, 3),
    };

    /// Fees above this would make the market unusable, so they are treated as a typo.
    const MAX_RATE: Decimal = Decimal::from_parts(1, 0, 0, false, 1);

    pub fn validate(&self) -> Result<(), String> {
        if self.rate.is_sign_negative() || self.rate > Self::MAX_RATE {
            return Err(format!(
                "trading fee rate must be between 0 and {}: {}",
                Self::MAX_RATE,
                self.rate
            ));
        }
        Ok(())
    }

    /// The fee on a gross amount, rounded up so the fee never rounds to less than its rate.
    pub fn fee_for(&self, gross_amount: Decimal) -> Decimal {
        (gross_amount * self.rate)
            .round_dp_with_strategy(CASH_DECIMAL_PLACES, RoundingStrategy::AwayFromZero)
    }

    /// The cash an order moves: what a buyer pays in total, or what a seller receives.
    pub fn cash_amount(&self, side: OrderSide, gross_amount: Decimal) -> Decimal {
        let fee = self.fee_for(gross_amount);
        match side {
            OrderSide::Buy => gross_amount + fee,
            OrderSide::Sell => gross_amount - fee,
        }
    }
}

impl Default for TradingFee {
    fn default() -> Self {
        Self::DEFAULT
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn buyers_pay_the_fee_on_top_and_sellers_have_it_deducted() {
        let fee = TradingFee::DEFAULT;
        let gross = Decimal::from(1_000);

        assert_eq!(fee.fee_for(gross), Decimal::from(5));
        assert_eq!(fee.cash_amount(OrderSide::Buy, gross), Decimal::from(1_005));
        assert_eq!(fee.cash_amount(OrderSide::Sell, gross), Decimal::from(995));
    }

    #[test]
    fn rounds_the_fee_up() {
        let fee = TradingFee::DEFAULT;

        assert_eq!(
            fee.fee_for(Decimal::new(1, 12)),
            Decimal::new(1, 12),
            "a tiny order still pays the smallest unit of cash"
        );
    }

    #[test]
    fn rejects_negative_and_huge_rates() {
        assert!(TradingFee {
            rate: Decimal::NEGATIVE_ONE
        }
        .validate()
        .is_err());
        assert!(TradingFee { rate: Decimal::ONE }.validate().is_err());
        assert!(TradingFee::NONE.validate().is_ok());
        assert!(TradingFee::DEFAULT.validate().is_ok());
    }
}
