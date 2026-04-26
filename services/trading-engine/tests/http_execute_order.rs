use async_trait::async_trait;
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use rust_decimal::Decimal;
use serde_json::{json, Value};
use stockball_trading_engine::{
    execution::{ExecuteOrderResult, ExecutionError},
    freezes::FreezeError,
    http::{build_router, AppState, OrderExecutor},
    instruments::{InstrumentError, InstrumentStatus},
    orders::{ExecuteOrderCommand, OrderError, OrderSide},
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
    assert_eq!(body["gross_amount"], "1000.0000");
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
}

#[async_trait]
impl OrderExecutor for StubExecutor {
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
        }
    }
}

#[derive(Debug, Clone)]
enum StubOutcome {
    Success(ExecuteOrderResult),
    InstrumentNotFound(Uuid),
    Frozen(Uuid),
    NonPositiveQuantity(Decimal),
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
        execution_price: Decimal::new(100_0000, 4),
        gross_amount: Decimal::new(1000_0000, 4),
        cash_balance_after: Decimal::new(99000_0000, 4),
        position_quantity_after: Decimal::new(10, 0),
        old_price: Decimal::new(100_0000, 4),
        new_price: Decimal::new(100_1000, 4),
        executed_at: chrono::Utc::now(),
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
