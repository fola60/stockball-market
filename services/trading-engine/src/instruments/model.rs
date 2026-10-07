use std::{fmt, str::FromStr};

use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::error::InstrumentError;

#[derive(Debug, Clone, PartialEq)]
pub struct Instrument {
    pub id: Uuid,
    pub instrument_type: InstrumentType,
    pub player_id: Uuid,
    pub symbol: String,
    pub display_name: String,
    pub current_price: Decimal,
    pub reference_price: Decimal,
    pub shares_outstanding: Decimal,
    pub net_shares_purchased: Decimal,
    pub full_supply_price_multiplier: Decimal,
    /// Net shares that carry the price to `full_supply_price_multiplier` times the reference.
    pub curve_depth_shares: Decimal,
    pub status: InstrumentStatus,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum InstrumentType {
    PlayerShare,
}

impl InstrumentType {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::PlayerShare => "PLAYER_SHARE",
        }
    }
}

impl fmt::Display for InstrumentType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for InstrumentType {
    type Err = InstrumentError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "PLAYER_SHARE" => Ok(Self::PlayerShare),
            other => Err(InstrumentError::UnsupportedInstrumentType(other.to_owned())),
        }
    }
}

impl TryFrom<&str> for InstrumentType {
    type Error = InstrumentError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::from_str(value)
    }
}

impl TryFrom<String> for InstrumentType {
    type Error = InstrumentError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::from_str(&value)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum InstrumentStatus {
    Active,
    Frozen,
    Delisted,
}

impl InstrumentStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Active => "ACTIVE",
            Self::Frozen => "FROZEN",
            Self::Delisted => "DELISTED",
        }
    }

    pub const fn is_active(self) -> bool {
        matches!(self, Self::Active)
    }

    pub const fn is_tradable(self) -> bool {
        matches!(self, Self::Active)
    }
}

impl fmt::Display for InstrumentStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for InstrumentStatus {
    type Err = InstrumentError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "ACTIVE" => Ok(Self::Active),
            "FROZEN" => Ok(Self::Frozen),
            "DELISTED" => Ok(Self::Delisted),
            other => Err(InstrumentError::UnsupportedInstrumentStatus(
                other.to_owned(),
            )),
        }
    }
}

impl TryFrom<&str> for InstrumentStatus {
    type Error = InstrumentError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::from_str(value)
    }
}

impl TryFrom<String> for InstrumentStatus {
    type Error = InstrumentError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::from_str(&value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_v1_instrument_type() {
        assert_eq!(
            InstrumentType::try_from("PLAYER_SHARE").unwrap(),
            InstrumentType::PlayerShare
        );
    }

    #[test]
    fn rejects_unsupported_instrument_type() {
        let error = InstrumentType::try_from("PLAYER_OPTION").unwrap_err();

        assert!(matches!(
            error,
            InstrumentError::UnsupportedInstrumentType(value) if value == "PLAYER_OPTION"
        ));
    }

    #[test]
    fn parses_instrument_statuses() {
        assert_eq!(
            InstrumentStatus::try_from("ACTIVE").unwrap(),
            InstrumentStatus::Active
        );
        assert_eq!(
            InstrumentStatus::try_from("FROZEN").unwrap(),
            InstrumentStatus::Frozen
        );
        assert_eq!(
            InstrumentStatus::try_from("DELISTED").unwrap(),
            InstrumentStatus::Delisted
        );
    }

    #[test]
    fn status_tradability_is_active_only() {
        assert!(InstrumentStatus::Active.is_tradable());
        assert!(!InstrumentStatus::Frozen.is_tradable());
        assert!(!InstrumentStatus::Delisted.is_tradable());
    }
}
