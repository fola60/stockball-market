use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PriceImpactDirection {
    Buy,
    Sell,
}

/// The shape every player's price curve is given: net buying of
/// `shares_outstanding ÷ curve_depth_divisor` shares carries the price to
/// `full_supply_price_multiplier` times its reference, and the same net selling to the
/// reciprocal. A larger divisor makes each traded share move the price further.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct CurveCalibration {
    #[serde(with = "rust_decimal::serde::str")]
    pub full_supply_price_multiplier: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub curve_depth_divisor: Decimal,
}

impl CurveCalibration {
    /// `instruments.full_supply_price_multiplier` is numeric(10, 6).
    const MAX_MULTIPLIER: Decimal = Decimal::from_parts(9_999, 0, 0, false, 0);

    /// The calibration chosen in October 2026: 20x the reference price after net buying of a
    /// fifteenth of the supply, about four times a typical player's circulating float.
    pub const DEFAULT: Self = Self {
        full_supply_price_multiplier: Decimal::from_parts(20, 0, 0, false, 0),
        curve_depth_divisor: Decimal::from_parts(15, 0, 0, false, 0),
    };

    pub fn validate(&self) -> Result<(), String> {
        if self.full_supply_price_multiplier <= Decimal::ONE
            || self.full_supply_price_multiplier > Self::MAX_MULTIPLIER
        {
            return Err(format!(
                "full_supply_price_multiplier must be greater than 1 and at most {}: {}",
                Self::MAX_MULTIPLIER,
                self.full_supply_price_multiplier
            ));
        }
        if self.curve_depth_divisor < Decimal::ONE {
            return Err(format!(
                "curve_depth_divisor must be at least 1: {}",
                self.curve_depth_divisor
            ));
        }
        Ok(())
    }

    /// The curve depth for an instrument with this supply, at the stored six decimal places.
    pub fn curve_depth_shares(&self, shares_outstanding: Decimal) -> Decimal {
        (shares_outstanding / self.curve_depth_divisor).round_dp(6)
    }
}

impl Default for CurveCalibration {
    fn default() -> Self {
        Self::DEFAULT
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_reaches_twenty_times_after_a_fifteenth_of_supply() {
        let calibration = CurveCalibration::default();

        assert!(calibration.validate().is_ok());
        assert_eq!(
            calibration.curve_depth_shares(Decimal::from(1_500_000)),
            Decimal::from(100_000)
        );
    }

    #[test]
    fn rejects_a_flat_curve_and_a_depth_beyond_the_supply() {
        let flat = CurveCalibration {
            full_supply_price_multiplier: Decimal::ONE,
            curve_depth_divisor: Decimal::from(15),
        };
        let too_deep = CurveCalibration {
            full_supply_price_multiplier: Decimal::from(20),
            curve_depth_divisor: Decimal::new(5, 1),
        };

        assert!(flat.validate().is_err());
        assert!(too_deep.validate().is_err());
    }
}
