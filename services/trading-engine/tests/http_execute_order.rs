use async_trait::async_trait;
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use rust_decimal::Decimal;
use serde_json::{json, Value};
use stockball_trading_engine::{
    execution::{ExecuteOrderResult, ExecutionError, OrderQuote},
    freezes::FreezeError,
    http::{build_router, AppState, OrderExecutor},
    instruments::{InstrumentError, InstrumentStatus, SeedPlayerSharesResult},
    ledger::{CashLedgerEntry, LedgerReason},
    orders::{ExecuteOrderCommand, OrderError, OrderSide},
    topups::{ApplyTopupCommand, TopupError},
};
use tower::ServiceExt;
use uuid::Uuid;

#[tokio::test]
async fn execute_order_returns_success_response() {
    let response = build_router(AppState::new(StubExecutor::success(sample_response())))
        .oneshot(
            Request::post("/internal/v1/orders/execute")
                .header("content-type", "application/json")
                .body(Body::from(sample_request().to_string()))
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = read_body(response).await;
    assert_eq!(body["request_id"], "req_123");
    assert_eq!(body["side"], "BUY");
    assert_eq!(body["quantity"], "10");
    assert_eq!(body["gross_amount"], "1000.004581467652");
}

#[tokio::test]
async fn execute_order_rejects_malformed_request_body_with_400() {
    let response = build_router(AppState::new(StubExecutor::success(sample_response())))
        .oneshot(
            Request::post("/internal/v1/orders/execute")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({
                        "request_id": "req_123",
                        "account_id": Uuid::new_v4(),
                        "portfolio_id": Uuid::new_v4(),
                        "instrument_id": Uuid::new_v4(),
                        "side": "BUY",
                        "quantity": 10
                    })
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);

    let body = read_body(response).await;
    assert_eq!(body["code"], "invalid_request");
}

#[tokio::test]
async fn execute_order_maps_missing_instrument_to_404() {
    let instrument_id = Uuid::new_v4();
    let response = build_router(AppState::new(StubExecutor::error(
        ExecutionError::Instrument(InstrumentError::NotFound(instrument_id)),
    )))
    .oneshot(
        Request::post("/internal/v1/orders/execute")
            .header("content-type", "application/json")
            .body(Body::from(sample_request().to_string()))
            .unwrap(),
    )
    .await
    .unwrap();

    assert_eq!(response.status(), StatusCode::NOT_FOUND);

    let body = read_body(response).await;
    assert_eq!(body["code"], "instrument_not_found");
    assert_eq!(body["details"]["instrument_id"], instrument_id.to_string());
}

#[tokio::test]
async fn execute_order_maps_frozen_market_to_409() {
    let instrument_id = Uuid::new_v4();
    let response = build_router(AppState::new(StubExecutor::error(ExecutionError::Freeze(
        FreezeError::Frozen { instrument_id },
    ))))
    .oneshot(
        Request::post("/internal/v1/orders/execute")
            .header("content-type", "application/json")
            .body(Body::from(sample_request().to_string()))
            .unwrap(),
    )
    .await
    .unwrap();

    assert_eq!(response.status(), StatusCode::CONFLICT);

    let body = read_body(response).await;
    assert_eq!(body["code"], "instrument_frozen");
}

#[tokio::test]
async fn execute_order_maps_trading_rule_rejection_to_422() {
    let response = build_router(AppState::new(StubExecutor::error(ExecutionError::Order(
        OrderError::NonPositiveQuantity(Decimal::ZERO),
    ))))
    .oneshot(
        Request::post("/internal/v1/orders/execute")
            .header("content-type", "application/json")
            .body(Body::from(sample_request().to_string()))
            .unwrap(),
    )
    .await
    .unwrap();

    assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);

    let body = read_body(response).await;
    assert_eq!(body["code"], "non_positive_quantity");
}

#[tokio::test]
async fn seed_player_shares_returns_success_response() {
    let instrument_id = Uuid::new_v4();
    let response = build_router(AppState::new(StubExecutor::seed_success(
        SeedPlayerSharesResult {
            created_count: 1,
            skipped_existing_count: 2,
            market_value_priced_count: 1,
            fallback_priced_count: 0,
            created_instrument_ids: vec![instrument_id],
        },
    )))
    .oneshot(
        Request::post("/internal/v1/instruments/player-shares/seed")
            .body(Body::empty())
            .unwrap(),
    )
    .await
    .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = read_body(response).await;
    assert_eq!(body["created_count"], 1);
    assert_eq!(body["skipped_existing_count"], 2);
    assert_eq!(body["market_value_priced_count"], 1);
    assert_eq!(body["fallback_priced_count"], 0);
    assert_eq!(body["created_instrument_ids"][0], instrument_id.to_string());
}

#[tokio::test]
async fn apply_topup_returns_ledger_entry_response() {
    let entry = sample_topup_response();
    let response = build_router(AppState::new(StubExecutor::topup_success(entry.clone())))
        .oneshot(
            Request::post("/internal/v1/ledger/topups/apply")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({
                        "request_id": "topup_123",
                        "account_id": entry.account_id,
                        "portfolio_id": entry.portfolio_id,
                        "amount": "100.0000",
                        "reason": "WEEKLY_TOPUP"
                    })
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);
    let body = read_body(response).await;
    assert_eq!(body["id"], entry.id.to_string());
    assert_eq!(body["reason"], "WEEKLY_TOPUP");
    assert_eq!(body["amount_delta"], "100.0000");
    assert_eq!(body["balance_after"], "10100.0000");
}

#[derive(Debug, Clone)]
struct StubExecutor {
    outcome: StubOutcome,
}

impl StubExecutor {
    fn success(result: ExecuteOrderResult) -> Self {
        Self {
            outcome: StubOutcome::Success(result),
        }
    }

    fn error(error: ExecutionError) -> Self {
        let outcome = match error {
            ExecutionError::Instrument(InstrumentError::NotFound(instrument_id)) => {
                StubOutcome::InstrumentNotFound(instrument_id)
            }
            ExecutionError::Freeze(FreezeError::Frozen { instrument_id }) => {
                StubOutcome::Frozen(instrument_id)
            }
            ExecutionError::Order(OrderError::NonPositiveQuantity(quantity)) => {
                StubOutcome::NonPositiveQuantity(quantity)
            }
            other => panic!("unsupported stub error: {other}"),
        };

        Self { outcome }
    }

    fn seed_success(result: SeedPlayerSharesResult) -> Self {
        Self {
            outcome: StubOutcome::SeedSuccess(result),
        }
    }

    fn topup_success(result: CashLedgerEntry) -> Self {
        Self {
            outcome: StubOutcome::TopupSuccess(result),
        }
    }
}

#[async_trait]
impl OrderExecutor for StubExecutor {
    async fn quote_order(
        &self,
        _command: ExecuteOrderCommand,
    ) -> Result<OrderQuote, ExecutionError> {
        panic!("quote endpoint is not used by this stub")
    }

    async fn execute_order(
        &self,
        _command: ExecuteOrderCommand,
    ) -> Result<ExecuteOrderResult, ExecutionError> {
        match &self.outcome {
            StubOutcome::Success(result) => Ok(result.clone()),
            StubOutcome::InstrumentNotFound(instrument_id) => Err(ExecutionError::Instrument(
                InstrumentError::NotFound(*instrument_id),
            )),
            StubOutcome::Frozen(instrument_id) => {
                Err(ExecutionError::Freeze(FreezeError::Frozen {
                    instrument_id: *instrument_id,
                }))
            }
            StubOutcome::NonPositiveQuantity(quantity) => Err(ExecutionError::Order(
                OrderError::NonPositiveQuantity(*quantity),
            )),
            StubOutcome::SeedSuccess(_) => panic!("seed stub cannot execute orders"),
            StubOutcome::TopupSuccess(_) => panic!("top-up stub cannot execute orders"),
        }
    }

    async fn seed_player_shares(&self) -> Result<SeedPlayerSharesResult, InstrumentError> {
        match &self.outcome {
            StubOutcome::SeedSuccess(result) => Ok(result.clone()),
            _ => panic!("order stub cannot seed player shares"),
        }
    }

    async fn apply_topup(
        &self,
        _command: ApplyTopupCommand,
    ) -> Result<CashLedgerEntry, TopupError> {
        match &self.outcome {
            StubOutcome::TopupSuccess(result) => Ok(result.clone()),
            _ => panic!("stub cannot apply top-ups"),
        }
    }
}

#[derive(Debug, Clone)]
enum StubOutcome {
    Success(ExecuteOrderResult),
    InstrumentNotFound(Uuid),
    Frozen(Uuid),
    NonPositiveQuantity(Decimal),
    SeedSuccess(SeedPlayerSharesResult),
    TopupSuccess(CashLedgerEntry),
}

fn sample_request() -> Value {
    json!({
        "request_id": "req_123",
        "account_id": Uuid::new_v4(),
        "portfolio_id": Uuid::new_v4(),
        "instrument_id": Uuid::new_v4(),
        "side": "BUY",
        "quantity": "10"
    })
}

fn sample_response() -> ExecuteOrderResult {
    ExecuteOrderResult {
        request_id: "req_123".to_owned(),
        order_id: Uuid::new_v4(),
        trade_id: Uuid::new_v4(),
        account_id: Uuid::new_v4(),
        portfolio_id: Uuid::new_v4(),
        instrument_id: Uuid::new_v4(),
        side: OrderSide::Buy,
        quantity: Decimal::new(10, 0),
        execution_price: "100.000458146765".parse().unwrap(),
        gross_amount: "1000.004581467652".parse().unwrap(),
        cash_balance_after: "98999.995418532348".parse().unwrap(),
        position_quantity_after: Decimal::new(10, 0),
        old_price: "100.000000000000".parse().unwrap(),
        new_price: "100.000916294930".parse().unwrap(),
        executed_at: chrono::Utc::now(),
    }
}

fn sample_topup_response() -> CashLedgerEntry {
    CashLedgerEntry {
        id: Uuid::new_v4(),
        account_id: Uuid::new_v4(),
        portfolio_id: Uuid::new_v4(),
        trade_id: None,
        reason: LedgerReason::WeeklyTopup,
        amount_delta: Decimal::new(100_0000, 4),
        balance_after: Decimal::new(101_000_000, 4),
        source_request_id: Some("topup_123".to_owned()),
        created_at: chrono::Utc::now(),
    }
}

async fn read_body(response: axum::response::Response) -> Value {
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

#[test]
fn uses_active_status_string_in_error_details() {
    assert_eq!(InstrumentStatus::Active.as_str(), "ACTIVE");
}
