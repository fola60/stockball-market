use std::{fmt, str::FromStr};

use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::error::LedgerError;

#[derive(Debug, Clone, PartialEq)]
pub struct CashLedgerEntry {
    pub id: Uuid,
    pub account_id: Uuid,
    pub portfolio_id: Uuid,
    pub trade_id: Option<Uuid>,
    pub reason: LedgerReason,
    pub amount_delta: Decimal,
    pub balance_after: Decimal,
    pub source_request_id: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum LedgerReason {
    TradeBuyDebit,
    TradeSellCredit,
    WeeklyTopup,
    MonthlyTopup,
    AdminAdjustment,
    Reversal,
}

impl LedgerReason {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::TradeBuyDebit => "TRADE_BUY_DEBIT",
            Self::TradeSellCredit => "TRADE_SELL_CREDIT",
            Self::WeeklyTopup => "WEEKLY_TOPUP",
            Self::MonthlyTopup => "MONTHLY_TOPUP",
            Self::AdminAdjustment => "ADMIN_ADJUSTMENT",
            Self::Reversal => "REVERSAL",
        }
    }
}

impl fmt::Display for LedgerReason {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for LedgerReason {
    type Err = LedgerError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "TRADE_BUY_DEBIT" => Ok(Self::TradeBuyDebit),
            "TRADE_SELL_CREDIT" => Ok(Self::TradeSellCredit),
            "WEEKLY_TOPUP" => Ok(Self::WeeklyTopup),
            "MONTHLY_TOPUP" => Ok(Self::MonthlyTopup),
            "ADMIN_ADJUSTMENT" => Ok(Self::AdminAdjustment),
            "REVERSAL" => Ok(Self::Reversal),
            other => Err(LedgerError::UnsupportedLedgerReason(other.to_owned())),
        }
    }
}

impl TryFrom<&str> for LedgerReason {
    type Error = LedgerError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::from_str(value)
    }
}

impl TryFrom<String> for LedgerReason {
    type Error = LedgerError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::from_str(&value)
    }
}
