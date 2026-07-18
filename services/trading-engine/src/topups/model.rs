use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::ledger::LedgerReason;

use super::TopupError;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ApplyTopupCommand {
    pub request_id: String,
    pub account_id: Uuid,
    pub portfolio_id: Uuid,
    #[serde(with = "rust_decimal::serde::str")]
    pub amount: Decimal,
    pub reason: LedgerReason,
}

impl ApplyTopupCommand {
    pub fn validate(&self) -> Result<(), TopupError> {
        if self.request_id.trim().is_empty() {
            return Err(TopupError::EmptyRequestId);
        }
        if self.amount <= Decimal::ZERO {
            return Err(TopupError::NonPositiveAmount(self.amount));
        }
        if !matches!(
            self.reason,
            LedgerReason::WeeklyTopup | LedgerReason::MonthlyTopup
        ) {
            return Err(TopupError::UnsupportedReason);
        }
        Ok(())
    }

    pub fn request_fingerprint(&self) -> String {
        format!(
            "account_id={};portfolio_id={};amount={};reason={}",
            self.account_id,
            self.portfolio_id,
            self.amount.round_dp(4).normalize(),
            self.reason
        )
    }
}
