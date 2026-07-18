pub type ExecuteOrderRequest = crate::orders::ExecuteOrderCommand;
pub type ExecuteOrderResponse = crate::execution::ExecuteOrderResult;
pub type SeedPlayerSharesResponse = crate::instruments::SeedPlayerSharesResult;
pub type ApplyTopupRequest = crate::topups::ApplyTopupCommand;
pub type ApplyTopupResponse = crate::ledger::CashLedgerEntry;

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ErrorResponse {
    pub code: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<serde_json::Value>,
}
