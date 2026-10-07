use std::collections::{BTreeMap, HashSet};

use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::ProvisioningError;
use crate::price_impact::CurveCalibration;

/// Credits the one-time opening balance of a newly registered account's portfolio.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ApplyOpeningBalanceCommand {
    pub request_id: String,
    pub account_id: Uuid,
    pub portfolio_id: Uuid,
    #[serde(with = "rust_decimal::serde::str")]
    pub amount: Decimal,
}

impl ApplyOpeningBalanceCommand {
    pub fn validate(&self) -> Result<(), ProvisioningError> {
        validate_request_id(&self.request_id)?;
        if self.amount <= Decimal::ZERO {
            return Err(ProvisioningError::NonPositiveAmount(self.amount));
        }
        Ok(())
    }

    pub fn request_fingerprint(&self) -> String {
        format!(
            "opening_balance;account_id={};portfolio_id={};amount={}",
            self.account_id,
            self.portfolio_id,
            self.amount.round_dp(4).normalize()
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InitialSupplyAllocation {
    pub instrument_id: Uuid,
    pub portfolio_id: Uuid,
    #[serde(with = "rust_decimal::serde::str")]
    pub quantity: Decimal,
}

/// Distributes the full share supply of pre-market instruments across portfolios.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct IssueInitialSupplyCommand {
    pub request_id: String,
    pub allocations: Vec<InitialSupplyAllocation>,
}

impl IssueInitialSupplyCommand {
    pub fn validate(&self) -> Result<(), ProvisioningError> {
        validate_request_id(&self.request_id)?;
        if self.allocations.is_empty() {
            return Err(ProvisioningError::EmptyAllocations);
        }
        let mut seen = HashSet::with_capacity(self.allocations.len());
        for allocation in &self.allocations {
            if allocation.quantity <= Decimal::ZERO {
                return Err(ProvisioningError::NonPositiveQuantity(allocation.quantity));
            }
            if !seen.insert((allocation.instrument_id, allocation.portfolio_id)) {
                return Err(ProvisioningError::DuplicateAllocation {
                    instrument_id: allocation.instrument_id,
                    portfolio_id: allocation.portfolio_id,
                });
            }
        }
        Ok(())
    }

    /// Allocations grouped by instrument, in a stable order so row locks are taken consistently.
    pub fn allocations_by_instrument(&self) -> BTreeMap<Uuid, Vec<&InitialSupplyAllocation>> {
        let mut grouped: BTreeMap<Uuid, Vec<&InitialSupplyAllocation>> = BTreeMap::new();
        for allocation in &self.allocations {
            grouped
                .entry(allocation.instrument_id)
                .or_default()
                .push(allocation);
        }
        grouped
    }

    pub fn request_fingerprint(&self) -> String {
        let mut parts: Vec<String> = self
            .allocations
            .iter()
            .map(|item| {
                format!(
                    "{}:{}:{}",
                    item.instrument_id,
                    item.portfolio_id,
                    item.quantity.normalize()
                )
            })
            .collect();
        parts.sort();
        format!("initial_supply;{}", parts.join(","))
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct IssueInitialSupplyResult {
    pub request_id: String,
    pub instrument_count: usize,
    pub position_count: usize,
}

/// Re-anchors the price of an instrument that has not traded yet.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SetPreMarketPriceCommand {
    pub request_id: String,
    pub instrument_id: Uuid,
    #[serde(with = "rust_decimal::serde::str")]
    pub new_price: Decimal,
}

impl SetPreMarketPriceCommand {
    pub fn validate(&self) -> Result<(), ProvisioningError> {
        validate_request_id(&self.request_id)?;
        if self.new_price <= Decimal::ZERO {
            return Err(ProvisioningError::NonPositivePrice(self.new_price));
        }
        Ok(())
    }

    pub fn request_fingerprint(&self) -> String {
        format!(
            "pre_market_price;instrument_id={};new_price={}",
            self.instrument_id,
            self.new_price.normalize()
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PreMarketPriceResult {
    pub instrument_id: Uuid,
    pub old_price: Decimal,
    pub new_price: Decimal,
}

/// Re-shapes every player-share price curve. Each curve is re-anchored at its current price, so
/// no price changes; the calibration only decides how far later trades move prices.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RecalibratePriceCurvesCommand {
    pub request_id: String,
    #[serde(flatten)]
    pub calibration: CurveCalibration,
    pub reason: String,
    /// Apply and report the recalibration, then roll it back. A dry run leaves the request id
    /// unused.
    #[serde(default)]
    pub dry_run: bool,
}

impl RecalibratePriceCurvesCommand {
    pub fn validate(&self) -> Result<(), ProvisioningError> {
        validate_request_id(&self.request_id)?;
        if self.reason.trim().is_empty() {
            return Err(ProvisioningError::EmptyReason);
        }
        self.calibration
            .validate()
            .map_err(ProvisioningError::InvalidCurveCalibration)
    }

    pub fn request_fingerprint(&self) -> String {
        format!(
            "recalibrate_price_curves;full_supply_price_multiplier={};curve_depth_divisor={};reason={}",
            self.calibration.full_supply_price_multiplier.normalize(),
            self.calibration.curve_depth_divisor.normalize(),
            self.reason.trim()
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RecalibratePriceCurvesResult {
    pub request_id: String,
    pub dry_run: bool,
    #[serde(flatten)]
    pub calibration: CurveCalibration,
    pub instrument_count: usize,
    /// Instruments whose accumulated net demand was folded into their new reference price.
    pub reset_net_demand_count: usize,
    /// The largest net demand reset, as a share of the old curve depth.
    #[serde(with = "rust_decimal::serde::str")]
    pub max_reset_demand_ratio: Decimal,
    /// Curve multipliers in use before the recalibration.
    #[serde(with = "rust_decimal::serde::str_option")]
    pub previous_min_multiplier: Option<Decimal>,
    #[serde(with = "rust_decimal::serde::str_option")]
    pub previous_max_multiplier: Option<Decimal>,
}

fn validate_request_id(request_id: &str) -> Result<(), ProvisioningError> {
    if request_id.trim().is_empty() {
        return Err(ProvisioningError::EmptyRequestId);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn allocation(
        instrument_id: Uuid,
        portfolio_id: Uuid,
        quantity: i64,
    ) -> InitialSupplyAllocation {
        InitialSupplyAllocation {
            instrument_id,
            portfolio_id,
            quantity: Decimal::new(quantity, 0),
        }
    }

    #[test]
    fn initial_supply_rejects_duplicate_portfolio_allocation() {
        let instrument_id = Uuid::new_v4();
        let portfolio_id = Uuid::new_v4();
        let command = IssueInitialSupplyCommand {
            request_id: "supply-1".to_owned(),
            allocations: vec![
                allocation(instrument_id, portfolio_id, 5),
                allocation(instrument_id, portfolio_id, 5),
            ],
        };

        assert!(matches!(
            command.validate(),
            Err(ProvisioningError::DuplicateAllocation { .. })
        ));
    }

    #[test]
    fn initial_supply_fingerprint_ignores_allocation_order() {
        let first = allocation(Uuid::new_v4(), Uuid::new_v4(), 3);
        let second = allocation(Uuid::new_v4(), Uuid::new_v4(), 7);
        let forward = IssueInitialSupplyCommand {
            request_id: "supply-1".to_owned(),
            allocations: vec![first.clone(), second.clone()],
        };
        let reversed = IssueInitialSupplyCommand {
            request_id: "supply-1".to_owned(),
            allocations: vec![second, first],
        };

        assert_eq!(
            forward.request_fingerprint(),
            reversed.request_fingerprint()
        );
    }

    #[test]
    fn pre_market_price_rejects_non_positive_price() {
        let command = SetPreMarketPriceCommand {
            request_id: "price-1".to_owned(),
            instrument_id: Uuid::new_v4(),
            new_price: Decimal::ZERO,
        };

        assert!(matches!(
            command.validate(),
            Err(ProvisioningError::NonPositivePrice(_))
        ));
    }
}
