use std::{fmt, str::FromStr};

use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::error::SnapshotError;

#[derive(Debug, Clone, PartialEq)]
pub struct PriceSnapshot {
    pub id: Uuid,
    pub instrument_id: Uuid,
    pub old_price: Decimal,
    pub new_price: Decimal,
    pub reason: PriceSnapshotReason,
    pub trade_id: Option<Uuid>,
    pub captured_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PriceSnapshotReason {
    Seed,
    TradeBuy,
    TradeSell,
    AdminAdjustment,
}

impl PriceSnapshotReason {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Seed => "SEED",
            Self::TradeBuy => "TRADE_BUY",
            Self::TradeSell => "TRADE_SELL",
            Self::AdminAdjustment => "ADMIN_ADJUSTMENT",
        }
    }
}

impl fmt::Display for PriceSnapshotReason {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for PriceSnapshotReason {
    type Err = SnapshotError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "SEED" => Ok(Self::Seed),
            "TRADE_BUY" => Ok(Self::TradeBuy),
            "TRADE_SELL" => Ok(Self::TradeSell),
            "ADMIN_ADJUSTMENT" => Ok(Self::AdminAdjustment),
            other => Err(SnapshotError::UnsupportedSnapshotReason(other.to_owned())),
        }
    }
}

impl TryFrom<&str> for PriceSnapshotReason {
    type Error = SnapshotError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::from_str(value)
    }
}

impl TryFrom<String> for PriceSnapshotReason {
    type Error = SnapshotError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::from_str(&value)
    }
}
