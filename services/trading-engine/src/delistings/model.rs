use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::error::DelistingError;

/// Takes a halted player share off the market, buying every holder out at its last price.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DelistInstrumentCommand {
    pub instrument_id: Uuid,
    pub reason: String,
}

impl DelistInstrumentCommand {
    pub fn validate(&self) -> Result<(), DelistingError> {
        if self.reason.trim().is_empty() {
            return Err(DelistingError::EmptyReason);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DelistInstrumentResult {
    pub instrument_id: Uuid,
    /// True when the share had already been delisted; nothing was paid this time.
    pub already_delisted: bool,
    #[serde(with = "rust_decimal::serde::str")]
    pub settlement_price: Decimal,
    pub holders_paid: usize,
    #[serde(with = "rust_decimal::serde::str")]
    pub shares_bought_out: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub amount_paid: Decimal,
    /// Index funds that held the share; each now holds its value as cash per unit.
    pub index_funds_updated: Vec<Uuid>,
}
