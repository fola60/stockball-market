pub type ExecuteOrderRequest = crate::orders::ExecuteOrderCommand;
pub type ExecuteOrderResponse = crate::execution::ExecuteOrderResult;
pub type QuoteOrderRequest = crate::orders::QuoteOrderCommand;
pub type QuoteOrderResponse = crate::execution::OrderQuote;
pub type SeedPlayerSharesResponse = crate::instruments::SeedPlayerSharesResult;
pub type ApplyTopupRequest = crate::topups::ApplyTopupCommand;
pub type ApplyTopupResponse = crate::ledger::CashLedgerEntry;
pub type ApplyOpeningBalanceRequest = crate::provisioning::ApplyOpeningBalanceCommand;
pub type ApplyOpeningBalanceResponse = crate::ledger::CashLedgerEntry;
pub type IssueInitialSupplyRequest = crate::provisioning::IssueInitialSupplyCommand;
pub type IssueInitialSupplyResponse = crate::provisioning::IssueInitialSupplyResult;
pub type SetPreMarketPriceRequest = crate::provisioning::SetPreMarketPriceCommand;
pub type SetPreMarketPriceResponse = crate::provisioning::PreMarketPriceResult;
pub type RecalibratePriceCurvesRequest = crate::provisioning::RecalibratePriceCurvesCommand;
pub type RecalibratePriceCurvesResponse = crate::provisioning::RecalibratePriceCurvesResult;
pub type CreateIndexFundRequest = crate::index_funds::CreateIndexFundCommand;
pub type CreateIndexFundResponse = crate::index_funds::CreateIndexFundResult;
pub type RebalanceIndexFundRequest = crate::index_funds::RebalanceIndexFundCommand;
pub type RebalanceIndexFundResponse = crate::index_funds::RebalanceIndexFundResult;
pub type DelistInstrumentRequest = crate::delistings::DelistInstrumentCommand;
pub type DelistInstrumentResponse = crate::delistings::DelistInstrumentResult;
pub type ApplyFreezeRequest = crate::freezes::ApplyFreezeCommand;
pub type ApplyFreezeResponse = crate::freezes::ApplyFreezeResult;
pub type ReleaseFreezeRequest = crate::freezes::ReleaseFreezeCommand;
pub type ReleaseFreezeResponse = crate::freezes::ReleaseFreezeResult;

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ErrorResponse {
    pub code: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<serde_json::Value>,
}
