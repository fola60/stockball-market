use axum::{
    extract::rejection::JsonRejection,
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;

use crate::{
    execution::ExecutionError, freezes::FreezeError, http::dto::ErrorResponse,
    idempotency::IdempotencyError, instruments::InstrumentError, ledger::LedgerError,
    orders::OrderError, portfolios::PortfolioError, positions::PositionError,
    price_impact::PriceImpactError, provisioning::ProvisioningError, snapshots::SnapshotError,
    topups::TopupError,
};

#[derive(Debug)]
pub struct ApiError {
    status: StatusCode,
    body: ErrorResponse,
}

impl ApiError {
    pub fn bad_request(message: impl Into<String>, details: Option<serde_json::Value>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, "invalid_request", message, details)
    }

    fn new(
        status: StatusCode,
        code: impl Into<String>,
        message: impl Into<String>,
        details: Option<serde_json::Value>,
    ) -> Self {
        Self {
            status,
            body: ErrorResponse {
                code: code.into(),
                message: message.into(),
                details,
            },
        }
    }

    pub fn from_json_rejection(rejection: JsonRejection) -> Self {
        Self::bad_request(
            "Request body is malformed or does not match ExecuteOrderRequest.",
            Some(json!({ "error": rejection.body_text() })),
        )
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.status, Json(self.body)).into_response()
    }
}

impl From<ExecutionError> for ApiError {
    fn from(error: ExecutionError) -> Self {
        match error {
            ExecutionError::TradeNotFound(trade_id) => Self::new(
                StatusCode::NOT_FOUND,
                "trade_not_found",
                format!("trade {trade_id} was not found"),
                Some(json!({ "trade_id": trade_id })),
            ),
            ExecutionError::Freeze(error) => freeze_error(error),
            ExecutionError::Idempotency(error) => idempotency_error(error),
            ExecutionError::Instrument(error) => instrument_error(error),
            ExecutionError::Ledger(error) => ledger_error(error),
            ExecutionError::Order(error) => order_error(error),
            ExecutionError::Portfolio(error) => portfolio_error(error),
            ExecutionError::Position(error) => position_error(error),
            ExecutionError::PriceImpact(error) => price_impact_error(error),
            ExecutionError::Snapshot(error) => snapshot_error(error),
            ExecutionError::Database(error) => internal_error(
                "database_error",
                "Unexpected database error while executing order.",
                Some(json!({ "error": error.to_string() })),
            ),
        }
    }
}

impl From<InstrumentError> for ApiError {
    fn from(error: InstrumentError) -> Self {
        instrument_error(error)
    }
}

impl From<TopupError> for ApiError {
    fn from(error: TopupError) -> Self {
        match error {
            TopupError::EmptyRequestId => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "empty_request_id",
                "request_id must not be empty.",
                None,
            ),
            TopupError::NonPositiveAmount(amount) => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "non_positive_amount",
                "top-up amount must be greater than zero.",
                Some(json!({ "amount": amount })),
            ),
            TopupError::UnsupportedReason => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "unsupported_topup_reason",
                "top-ups only support WEEKLY_TOPUP or MONTHLY_TOPUP reasons.",
                None,
            ),
            TopupError::Idempotency(error) => idempotency_error(error),
            TopupError::Ledger(error) => ledger_error(error),
            TopupError::Database(error) => internal_error(
                "database_error",
                "Unexpected database error while applying top-up.",
                Some(json!({ "error": error.to_string() })),
            ),
        }
    }
}

impl From<FreezeError> for ApiError {
    fn from(error: FreezeError) -> Self {
        freeze_error(error)
    }
}

impl From<ProvisioningError> for ApiError {
    fn from(error: ProvisioningError) -> Self {
        match error {
            ProvisioningError::EmptyRequestId => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "empty_request_id",
                "request_id must not be empty.",
                None,
            ),
            ProvisioningError::NonPositiveAmount(amount) => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "non_positive_amount",
                "amount must be greater than zero.",
                Some(json!({ "amount": amount })),
            ),
            ProvisioningError::NonPositivePrice(price) => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "non_positive_price",
                "price must be greater than zero.",
                Some(json!({ "new_price": price })),
            ),
            ProvisioningError::EmptyAllocations => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "empty_allocations",
                "initial supply issuance must include at least one allocation.",
                None,
            ),
            ProvisioningError::NonPositiveQuantity(quantity) => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "non_positive_quantity",
                "allocation quantity must be greater than zero.",
                Some(json!({ "quantity": quantity })),
            ),
            ProvisioningError::DuplicateAllocation {
                instrument_id,
                portfolio_id,
            } => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "duplicate_allocation",
                "a portfolio may be allocated each instrument only once.",
                Some(json!({
                    "instrument_id": instrument_id,
                    "portfolio_id": portfolio_id
                })),
            ),
            ProvisioningError::SupplyMismatch {
                instrument_id,
                allocated,
                shares_outstanding,
            } => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "supply_mismatch",
                "allocations must add up to the instrument's shares outstanding.",
                Some(json!({
                    "instrument_id": instrument_id,
                    "allocated": allocated,
                    "shares_outstanding": shares_outstanding
                })),
            ),
            ProvisioningError::MarketActivityExists(instrument_id) => Self::new(
                StatusCode::CONFLICT,
                "instrument_has_market_activity",
                "instrument already has orders, trades, or positions.",
                Some(json!({ "instrument_id": instrument_id })),
            ),
            ProvisioningError::EmptyReason => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "empty_reason",
                "reason must not be empty.",
                None,
            ),
            ProvisioningError::InvalidCurveCalibration(reason) => Self::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "invalid_curve_calibration",
                "price curve calibration is invalid.",
                Some(json!({ "reason": reason })),
            ),
            ProvisioningError::Idempotency(error) => idempotency_error(error),
            ProvisioningError::Instrument(error) => instrument_error(error),
            ProvisioningError::Ledger(error) => ledger_error(error),
            ProvisioningError::Position(error) => position_error(error),
            ProvisioningError::Snapshot(error) => snapshot_error(error),
            ProvisioningError::Database(error) => internal_error(
                "database_error",
                "Unexpected database error while provisioning market state.",
                Some(json!({ "error": error.to_string() })),
            ),
        }
    }
}

fn order_error(error: OrderError) -> ApiError {
    match error {
        OrderError::QuoteChanged => ApiError::new(
            StatusCode::CONFLICT,
            "quote_changed",
            "Quote no longer satisfies execution limits.",
            None,
        ),
        OrderError::NotFound(order_id) => ApiError::new(
            StatusCode::NOT_FOUND,
            "order_not_found",
            format!("order {order_id} was not found"),
            Some(json!({ "order_id": order_id })),
        ),
        OrderError::EmptyRequestId => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "empty_request_id",
            "request_id must not be empty.",
            None,
        ),
        OrderError::NonPositiveQuantity(quantity) => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "non_positive_quantity",
            "quantity must be greater than zero.",
            Some(json!({ "quantity": quantity })),
        ),
        OrderError::QuantityScaleTooPrecise(quantity) => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "quantity_scale_too_precise",
            "quantity supports at most 6 decimal places.",
            Some(json!({ "quantity": quantity })),
        ),
        OrderError::UnsupportedOrderSide(side) => internal_error(
            "unsupported_order_side",
            "Unsupported order side encountered.",
            Some(json!({ "side": side })),
        ),
        OrderError::UnsupportedOrderStatus(status) => internal_error(
            "unsupported_order_status",
            "Unsupported order status encountered.",
            Some(json!({ "status": status })),
        ),
        OrderError::Database(error) => internal_error(
            "database_error",
            "Unexpected database error while working with orders.",
            Some(json!({ "error": error.to_string() })),
        ),
    }
}

fn portfolio_error(error: PortfolioError) -> ApiError {
    match error {
        PortfolioError::NotFound(portfolio_id) => ApiError::new(
            StatusCode::NOT_FOUND,
            "portfolio_not_found",
            format!("portfolio {portfolio_id} was not found"),
            Some(json!({ "portfolio_id": portfolio_id })),
        ),
        PortfolioError::NotFoundForAccount(account_id) => ApiError::new(
            StatusCode::NOT_FOUND,
            "portfolio_not_found",
            format!("portfolio for account {account_id} was not found"),
            Some(json!({ "account_id": account_id })),
        ),
        PortfolioError::AccountMismatch {
            portfolio_id,
            expected_account_id,
            actual_account_id,
        } => ApiError::new(
            StatusCode::NOT_FOUND,
            "account_portfolio_mismatch",
            "portfolio does not belong to the supplied account.",
            Some(json!({
                "portfolio_id": portfolio_id,
                "account_id": expected_account_id,
                "actual_account_id": actual_account_id
            })),
        ),
        PortfolioError::InsufficientCash {
            portfolio_id,
            available,
            required,
        } => ApiError::new(
            StatusCode::CONFLICT,
            "insufficient_cash",
            "portfolio has insufficient cash for this order.",
            Some(json!({
                "portfolio_id": portfolio_id,
                "available": available,
                "required": required
            })),
        ),
        PortfolioError::NegativeCashBalance {
            portfolio_id,
            cash_balance,
        } => internal_error(
            "negative_cash_balance",
            "portfolio cash balance is invalid.",
            Some(json!({
                "portfolio_id": portfolio_id,
                "cash_balance": cash_balance
            })),
        ),
        PortfolioError::NegativeRequiredCash {
            portfolio_id,
            required,
        } => internal_error(
            "negative_required_cash",
            "required cash is invalid.",
            Some(json!({
                "portfolio_id": portfolio_id,
                "required": required
            })),
        ),
        PortfolioError::Database(error) => internal_error(
            "database_error",
            "Unexpected database error while working with portfolios.",
            Some(json!({ "error": error.to_string() })),
        ),
    }
}

fn instrument_error(error: InstrumentError) -> ApiError {
    match error {
        InstrumentError::NotFound(instrument_id) => ApiError::new(
            StatusCode::NOT_FOUND,
            "instrument_not_found",
            format!("instrument {instrument_id} was not found"),
            Some(json!({ "instrument_id": instrument_id })),
        ),
        InstrumentError::NotActive {
            instrument_id,
            status,
        }
        | InstrumentError::NotTradable {
            instrument_id,
            status,
        } => ApiError::new(
            StatusCode::CONFLICT,
            "instrument_not_tradable",
            "instrument is not currently tradable.",
            Some(json!({
                "instrument_id": instrument_id,
                "status": status.as_str()
            })),
        ),
        InstrumentError::UnsupportedInstrumentType(instrument_type) => internal_error(
            "unsupported_instrument_type",
            "Unsupported instrument type encountered.",
            Some(json!({ "instrument_type": instrument_type })),
        ),
        InstrumentError::UnsupportedInstrumentStatus(status) => internal_error(
            "unsupported_instrument_status",
            "Unsupported instrument status encountered.",
            Some(json!({ "status": status })),
        ),
        InstrumentError::InvalidRecord {
            instrument_id,
            reason,
        } => internal_error(
            "invalid_instrument_record",
            "instrument record is invalid.",
            Some(json!({
                "instrument_id": instrument_id,
                "reason": reason
            })),
        ),
        InstrumentError::NegativePrice => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "non_positive_price",
            "order would result in an invalid instrument price.",
            None,
        ),
        InstrumentError::InvalidSeedValue { reason } => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_seed_value",
            "player-share seed value is invalid.",
            Some(json!({ "reason": reason })),
        ),
        InstrumentError::Snapshot(error) => snapshot_error(error),
        InstrumentError::Database(error) => internal_error(
            "database_error",
            "Unexpected database error while working with instruments.",
            Some(json!({ "error": error.to_string() })),
        ),
    }
}

fn freeze_error(error: FreezeError) -> ApiError {
    match error {
        FreezeError::Frozen { instrument_id } => ApiError::new(
            StatusCode::CONFLICT,
            "instrument_frozen",
            "instrument is currently frozen.",
            Some(json!({ "instrument_id": instrument_id })),
        ),
        FreezeError::CannotFreeze {
            instrument_id,
            status,
        } => ApiError::new(
            StatusCode::CONFLICT,
            "instrument_not_tradable",
            "instrument cannot be traded in its current state.",
            Some(json!({
                "instrument_id": instrument_id,
                "status": status.as_str()
            })),
        ),
        FreezeError::EmptySourceKey => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "empty_source_key",
            "freeze source_key must not be empty.",
            None,
        ),
        FreezeError::EmptyInstruments => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "empty_instruments",
            "a freeze must include at least one instrument.",
            None,
        ),
        FreezeError::UnsupportedReason(reason) => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "unsupported_freeze_reason",
            "freeze reason is not supported.",
            Some(json!({ "reason": reason })),
        ),
        FreezeError::Instrument(error) => instrument_error(error),
        FreezeError::Database(error) => internal_error(
            "database_error",
            "Unexpected database error while checking freeze state.",
            Some(json!({ "error": error.to_string() })),
        ),
    }
}

fn ledger_error(error: LedgerError) -> ApiError {
    match error {
        LedgerError::PortfolioNotFound(portfolio_id) => ApiError::new(
            StatusCode::NOT_FOUND,
            "portfolio_not_found",
            format!("portfolio {portfolio_id} was not found"),
            Some(json!({ "portfolio_id": portfolio_id })),
        ),
        LedgerError::PortfolioAccountMismatch {
            portfolio_id,
            expected_account_id,
            actual_account_id,
        } => ApiError::new(
            StatusCode::NOT_FOUND,
            "account_portfolio_mismatch",
            "portfolio does not belong to the supplied account.",
            Some(json!({
                "portfolio_id": portfolio_id,
                "account_id": expected_account_id,
                "actual_account_id": actual_account_id
            })),
        ),
        LedgerError::InsufficientCash {
            portfolio_id,
            available,
            required,
        } => ApiError::new(
            StatusCode::CONFLICT,
            "insufficient_cash",
            "portfolio has insufficient cash for this order.",
            Some(json!({
                "portfolio_id": portfolio_id,
                "available": available,
                "required": required
            })),
        ),
        LedgerError::NonPositiveAmount(amount_delta) => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "non_positive_amount",
            "cash movement amount must be greater than zero.",
            Some(json!({ "amount_delta": amount_delta })),
        ),
        LedgerError::NegativeCashBalance {
            portfolio_id,
            cash_balance,
        } => ApiError::new(
            StatusCode::CONFLICT,
            "negative_cash_balance",
            "portfolio cash balance would become negative.",
            Some(json!({
                "portfolio_id": portfolio_id,
                "cash_balance": cash_balance
            })),
        ),
        LedgerError::CashUpdateRejected {
            portfolio_id,
            amount_delta,
        } => ApiError::new(
            StatusCode::CONFLICT,
            "cash_update_rejected",
            "portfolio cash update was rejected.",
            Some(json!({
                "portfolio_id": portfolio_id,
                "amount_delta": amount_delta
            })),
        ),
        LedgerError::OpeningBalanceAlreadyApplied(portfolio_id) => ApiError::new(
            StatusCode::CONFLICT,
            "opening_balance_already_applied",
            "portfolio has already received its opening balance.",
            Some(json!({ "portfolio_id": portfolio_id })),
        ),
        LedgerError::UnsupportedLedgerReason(reason) => internal_error(
            "unsupported_ledger_reason",
            "Unsupported ledger reason encountered.",
            Some(json!({ "reason": reason })),
        ),
        LedgerError::Database(error) => internal_error(
            "database_error",
            "Unexpected database error while working with ledger entries.",
            Some(json!({ "error": error.to_string() })),
        ),
    }
}

fn position_error(error: PositionError) -> ApiError {
    match error {
        PositionError::NotFound {
            portfolio_id,
            instrument_id,
        } => ApiError::new(
            StatusCode::CONFLICT,
            "position_not_found",
            "portfolio does not have a position for this instrument.",
            Some(json!({
                "portfolio_id": portfolio_id,
                "instrument_id": instrument_id
            })),
        ),
        PositionError::NonPositiveQuantity(quantity) => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "non_positive_quantity",
            "quantity must be greater than zero.",
            Some(json!({ "quantity": quantity })),
        ),
        PositionError::InsufficientQuantity {
            portfolio_id,
            instrument_id,
            available,
            required,
        } => ApiError::new(
            StatusCode::CONFLICT,
            "insufficient_position",
            "portfolio has insufficient position quantity for this order.",
            Some(json!({
                "portfolio_id": portfolio_id,
                "instrument_id": instrument_id,
                "available": available,
                "required": required
            })),
        ),
        PositionError::NegativeQuantity {
            position_id,
            quantity,
        } => internal_error(
            "negative_position_quantity",
            "position quantity is invalid.",
            Some(json!({
                "position_id": position_id,
                "quantity": quantity
            })),
        ),
        PositionError::Database(error) => internal_error(
            "database_error",
            "Unexpected database error while working with positions.",
            Some(json!({ "error": error.to_string() })),
        ),
    }
}

fn idempotency_error(error: IdempotencyError) -> ApiError {
    match error {
        IdempotencyError::NotFound(record_id) => internal_error(
            "idempotency_record_not_found",
            "idempotency record was not found.",
            Some(json!({ "idempotency_record_id": record_id })),
        ),
        IdempotencyError::RequestMismatch {
            command_scope,
            request_key,
        } => ApiError::new(
            StatusCode::CONFLICT,
            "idempotency_request_mismatch",
            "request_id was already used for a different request.",
            Some(json!({
                "scope": command_scope,
                "request_id": request_key
            })),
        ),
        IdempotencyError::InProgress {
            command_scope,
            request_key,
        } => ApiError::new(
            StatusCode::CONFLICT,
            "idempotency_in_progress",
            "request_id is still in progress.",
            Some(json!({
                "scope": command_scope,
                "request_id": request_key
            })),
        ),
        IdempotencyError::Failed {
            command_scope,
            request_key,
        } => ApiError::new(
            StatusCode::CONFLICT,
            "idempotency_failed",
            "request_id is marked failed and cannot be replayed.",
            Some(json!({
                "scope": command_scope,
                "request_id": request_key
            })),
        ),
        IdempotencyError::MissingResponseBody {
            command_scope,
            request_key,
        } => internal_error(
            "idempotency_missing_response",
            "completed idempotency record is missing its stored response.",
            Some(json!({
                "scope": command_scope,
                "request_id": request_key
            })),
        ),
        IdempotencyError::UnsupportedCommandScope(scope) => internal_error(
            "unsupported_idempotency_scope",
            "Unsupported idempotency scope encountered.",
            Some(json!({ "scope": scope })),
        ),
        IdempotencyError::UnsupportedStatus(status) => internal_error(
            "unsupported_idempotency_status",
            "Unsupported idempotency status encountered.",
            Some(json!({ "status": status })),
        ),
        IdempotencyError::Serialization(error) => internal_error(
            "serialization_error",
            "Failed to serialize or deserialize idempotency payload.",
            Some(json!({ "error": error.to_string() })),
        ),
        IdempotencyError::Database(error) => internal_error(
            "database_error",
            "Unexpected database error while working with idempotency records.",
            Some(json!({ "error": error.to_string() })),
        ),
    }
}

fn price_impact_error(error: PriceImpactError) -> ApiError {
    match error {
        PriceImpactError::NonPositiveQuantity(quantity) => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "non_positive_quantity",
            "quantity must be greater than zero.",
            Some(json!({ "quantity": quantity })),
        ),
        PriceImpactError::BuyExceedsCurveLimit {
            available,
            requested,
        } => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "buy_exceeds_price_curve_limit",
            "order would exceed the positive limit of the price curve.",
            Some(json!({ "available": available, "requested": requested })),
        ),
        PriceImpactError::SellExceedsCurveLimit {
            available,
            requested,
        } => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "sell_exceeds_price_curve_limit",
            "order would exceed the negative limit of the price curve.",
            Some(json!({ "available": available, "requested": requested })),
        ),
        PriceImpactError::NonPositiveReferencePrice(reference_price) => internal_error(
            "non_positive_reference_price",
            "instrument reference price is invalid.",
            Some(json!({ "reference_price": reference_price })),
        ),
        PriceImpactError::NonPositiveCurveDepth(curve_depth_shares) => internal_error(
            "non_positive_curve_depth",
            "instrument price curve depth is invalid.",
            Some(json!({ "curve_depth_shares": curve_depth_shares })),
        ),
        PriceImpactError::InvalidNetSharesPurchased {
            net_shares_purchased,
            curve_depth_shares,
        } => internal_error(
            "invalid_net_shares_purchased",
            "instrument net shares purchased is invalid.",
            Some(json!({
                "net_shares_purchased": net_shares_purchased,
                "curve_depth_shares": curve_depth_shares
            })),
        ),
        PriceImpactError::InvalidFullSupplyPriceMultiplier(multiplier) => internal_error(
            "invalid_full_supply_price_multiplier",
            "instrument full-supply price multiplier is invalid.",
            Some(json!({ "full_supply_price_multiplier": multiplier })),
        ),
        PriceImpactError::CalculationOverflow => internal_error(
            "price_curve_calculation_overflow",
            "Price curve calculation exceeded supported precision.",
            None,
        ),
    }
}

fn snapshot_error(error: SnapshotError) -> ApiError {
    match error {
        SnapshotError::NotFound(snapshot_id) => internal_error(
            "snapshot_not_found",
            "price snapshot was not found.",
            Some(json!({ "snapshot_id": snapshot_id })),
        ),
        SnapshotError::NegativePrice(price) => internal_error(
            "non_positive_snapshot_price",
            "price snapshot contains an invalid price.",
            Some(json!({ "price": price })),
        ),
        SnapshotError::UnsupportedSnapshotReason(reason) => internal_error(
            "unsupported_snapshot_reason",
            "Unsupported snapshot reason encountered.",
            Some(json!({ "reason": reason })),
        ),
        SnapshotError::Database(error) => internal_error(
            "database_error",
            "Unexpected database error while recording price snapshots.",
            Some(json!({ "error": error.to_string() })),
        ),
    }
}

fn internal_error(
    code: impl Into<String>,
    message: impl Into<String>,
    details: Option<serde_json::Value>,
) -> ApiError {
    ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, code, message, details)
}
