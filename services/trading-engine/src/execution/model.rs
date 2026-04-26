use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::orders::OrderSide;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExecuteOrderResult {
    pub request_id: String,
    pub order_id: Uuid,
    pub trade_id: Uuid,
    pub account_id: Uuid,
    pub portfolio_id: Uuid,
    pub instrument_id: Uuid,
    pub side: OrderSide,
    #[serde(with = "rust_decimal::serde::str")]
    pub quantity: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub execution_price: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub gross_amount: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub cash_balance_after: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub position_quantity_after: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub old_price: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub new_price: Decimal,
    pub executed_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Trade {
    pub id: Uuid,
    pub order_id: Uuid,
    pub account_id: Uuid,
    pub portfolio_id: Uuid,
    pub instrument_id: Uuid,
    pub side: OrderSide,
    pub quantity: Decimal,
    pub execution_price: Decimal,
    pub gross_amount: Decimal,
    pub executed_at: DateTime<Utc>,
    pub created_at: DateTime<Utc>,
}
