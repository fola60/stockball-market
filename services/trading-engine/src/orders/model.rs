use std::{fmt, str::FromStr};

use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::error::OrderError;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExecuteOrderCommand {
    pub request_id: String,
    pub account_id: Uuid,
    pub portfolio_id: Uuid,
    pub instrument_id: Uuid,
    pub side: OrderSide,
    #[serde(with = "rust_decimal::serde::str")]
    pub quantity: Decimal,
}

impl ExecuteOrderCommand {
    pub fn validate(&self) -> Result<(), OrderError> {
        if self.request_id.trim().is_empty() {
            return Err(OrderError::EmptyRequestId);
        }

        if self.quantity <= Decimal::ZERO {
            return Err(OrderError::NonPositiveQuantity(self.quantity));
        }

        if self.quantity.scale() > 6 {
            return Err(OrderError::QuantityScaleTooPrecise(self.quantity));
        }

        Ok(())
    }

    pub fn request_fingerprint(&self) -> String {
        format!(
            "account_id={};portfolio_id={};instrument_id={};side={};quantity={}",
            self.account_id,
            self.portfolio_id,
            self.instrument_id,
            self.side,
            self.quantity.round_dp(6).normalize()
        )
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Order {
    pub id: Uuid,
    pub request_id: String,
    pub account_id: Uuid,
    pub portfolio_id: Uuid,
    pub instrument_id: Uuid,
    pub side: OrderSide,
    pub quantity: Decimal,
    pub status: OrderStatus,
    pub rejection_reason: Option<String>,
    pub submitted_at: DateTime<Utc>,
    pub filled_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum OrderSide {
    Buy,
    Sell,
}

impl OrderSide {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Buy => "BUY",
            Self::Sell => "SELL",
        }
    }
}

impl fmt::Display for OrderSide {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for OrderSide {
    type Err = OrderError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "BUY" => Ok(Self::Buy),
            "SELL" => Ok(Self::Sell),
            other => Err(OrderError::UnsupportedOrderSide(other.to_owned())),
        }
    }
}

impl TryFrom<&str> for OrderSide {
    type Error = OrderError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::from_str(value)
    }
}

impl TryFrom<String> for OrderSide {
    type Error = OrderError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::from_str(&value)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum OrderStatus {
    Pending,
    Filled,
    Rejected,
    Failed,
}

impl OrderStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "PENDING",
            Self::Filled => "FILLED",
            Self::Rejected => "REJECTED",
            Self::Failed => "FAILED",
        }
    }
}

impl fmt::Display for OrderStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for OrderStatus {
    type Err = OrderError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "PENDING" => Ok(Self::Pending),
            "FILLED" => Ok(Self::Filled),
            "REJECTED" => Ok(Self::Rejected),
            "FAILED" => Ok(Self::Failed),
            other => Err(OrderError::UnsupportedOrderStatus(other.to_owned())),
        }
    }
}

impl TryFrom<&str> for OrderStatus {
    type Error = OrderError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::from_str(value)
    }
}

impl TryFrom<String> for OrderStatus {
    type Error = OrderError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::from_str(&value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_order_side() {
        assert_eq!(OrderSide::try_from("BUY").unwrap(), OrderSide::Buy);
        assert_eq!(OrderSide::try_from("SELL").unwrap(), OrderSide::Sell);
    }

    #[test]
    fn rejects_non_positive_quantity() {
        let command = ExecuteOrderCommand {
            request_id: "req_1".to_owned(),
            account_id: Uuid::new_v4(),
            portfolio_id: Uuid::new_v4(),
            instrument_id: Uuid::new_v4(),
            side: OrderSide::Buy,
            quantity: Decimal::ZERO,
        };

        assert!(matches!(
            command.validate().unwrap_err(),
            OrderError::NonPositiveQuantity(_)
        ));
    }

    #[test]
    fn request_fingerprint_normalizes_quantity_scale() {
        let account_id = Uuid::new_v4();
        let portfolio_id = Uuid::new_v4();
        let instrument_id = Uuid::new_v4();

        let left = ExecuteOrderCommand {
            request_id: "req_1".to_owned(),
            account_id,
            portfolio_id,
            instrument_id,
            side: OrderSide::Buy,
            quantity: Decimal::new(10, 0),
        };
        let right = ExecuteOrderCommand {
            request_id: "req_1".to_owned(),
            account_id,
            portfolio_id,
            instrument_id,
            side: OrderSide::Buy,
            quantity: Decimal::new(10_000000, 6),
        };

        assert_eq!(left.request_fingerprint(), right.request_fingerprint());
    }
}
