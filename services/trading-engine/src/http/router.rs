use async_trait::async_trait;
use axum::{
    extract::{FromRequest, Request, State},
    routing::post,
    Json, Router,
};

use crate::http::{
    error::ApiError, executor::OrderExecutor, ApplyFreezeRequest, ApplyFreezeResponse,
    ApplyOpeningBalanceRequest, ApplyOpeningBalanceResponse, ApplyTopupRequest, ApplyTopupResponse,
    ExecuteOrderRequest, ExecuteOrderResponse, IssueInitialSupplyRequest,
    IssueInitialSupplyResponse, QuoteOrderRequest, QuoteOrderResponse,
    RecalibratePriceCurvesRequest, RecalibratePriceCurvesResponse, ReleaseFreezeRequest,
    ReleaseFreezeResponse, SeedPlayerSharesResponse, SetPreMarketPriceRequest,
    SetPreMarketPriceResponse,
};

#[derive(Debug, Clone)]
pub struct AppState<E> {
    executor: E,
}

impl<E> AppState<E> {
    pub fn new(executor: E) -> Self {
        Self { executor }
    }
}

pub fn build_router<E>(state: AppState<E>) -> Router
where
    E: OrderExecutor,
{
    Router::new()
        .route("/internal/v1/orders/execute", post(execute_order::<E>))
        .route("/internal/v1/orders/quote", post(quote_order::<E>))
        .route(
            "/internal/v1/instruments/player-shares/seed",
            post(seed_player_shares::<E>),
        )
        .route("/internal/v1/ledger/topups/apply", post(apply_topup::<E>))
        .route(
            "/internal/v1/ledger/opening-balance/apply",
            post(apply_opening_balance::<E>),
        )
        .route(
            "/internal/v1/positions/initial-supply/issue",
            post(issue_initial_supply::<E>),
        )
        .route(
            "/internal/v1/instruments/pre-market-price/set",
            post(set_pre_market_price::<E>),
        )
        .route(
            "/internal/v1/instruments/price-curves/recalibrate",
            post(recalibrate_price_curves::<E>),
        )
        .route("/internal/v1/freezes/apply", post(apply_freeze::<E>))
        .route("/internal/v1/freezes/release", post(release_freeze::<E>))
        .with_state(state)
}

async fn quote_order<E>(
    State(state): State<AppState<E>>,
    JsonBody(request): JsonBody<QuoteOrderRequest>,
) -> Result<Json<QuoteOrderResponse>, ApiError>
where
    E: OrderExecutor,
{
    let result = state.executor.quote_order(request).await?;
    Ok(Json(result))
}

async fn execute_order<E>(
    State(state): State<AppState<E>>,
    JsonBody(request): JsonBody<ExecuteOrderRequest>,
) -> Result<Json<ExecuteOrderResponse>, ApiError>
where
    E: OrderExecutor,
{
    let result = state.executor.execute_order(request).await?;
    Ok(Json(result))
}

async fn seed_player_shares<E>(
    State(state): State<AppState<E>>,
) -> Result<Json<SeedPlayerSharesResponse>, ApiError>
where
    E: OrderExecutor,
{
    let result = state.executor.seed_player_shares().await?;
    Ok(Json(result))
}

async fn apply_topup<E>(
    State(state): State<AppState<E>>,
    JsonBody(request): JsonBody<ApplyTopupRequest>,
) -> Result<Json<ApplyTopupResponse>, ApiError>
where
    E: OrderExecutor,
{
    let result = state.executor.apply_topup(request).await?;
    Ok(Json(result))
}

async fn apply_opening_balance<E>(
    State(state): State<AppState<E>>,
    JsonBody(request): JsonBody<ApplyOpeningBalanceRequest>,
) -> Result<Json<ApplyOpeningBalanceResponse>, ApiError>
where
    E: OrderExecutor,
{
    let result = state.executor.apply_opening_balance(request).await?;
    Ok(Json(result))
}

async fn issue_initial_supply<E>(
    State(state): State<AppState<E>>,
    JsonBody(request): JsonBody<IssueInitialSupplyRequest>,
) -> Result<Json<IssueInitialSupplyResponse>, ApiError>
where
    E: OrderExecutor,
{
    let result = state.executor.issue_initial_supply(request).await?;
    Ok(Json(result))
}

async fn set_pre_market_price<E>(
    State(state): State<AppState<E>>,
    JsonBody(request): JsonBody<SetPreMarketPriceRequest>,
) -> Result<Json<SetPreMarketPriceResponse>, ApiError>
where
    E: OrderExecutor,
{
    let result = state.executor.set_pre_market_price(request).await?;
    Ok(Json(result))
}

async fn recalibrate_price_curves<E>(
    State(state): State<AppState<E>>,
    JsonBody(request): JsonBody<RecalibratePriceCurvesRequest>,
) -> Result<Json<RecalibratePriceCurvesResponse>, ApiError>
where
    E: OrderExecutor,
{
    let result = state.executor.recalibrate_price_curves(request).await?;
    Ok(Json(result))
}

async fn apply_freeze<E>(
    State(state): State<AppState<E>>,
    JsonBody(request): JsonBody<ApplyFreezeRequest>,
) -> Result<Json<ApplyFreezeResponse>, ApiError>
where
    E: OrderExecutor,
{
    let result = state.executor.apply_freeze(request).await?;
    Ok(Json(result))
}

async fn release_freeze<E>(
    State(state): State<AppState<E>>,
    JsonBody(request): JsonBody<ReleaseFreezeRequest>,
) -> Result<Json<ReleaseFreezeResponse>, ApiError>
where
    E: OrderExecutor,
{
    let result = state.executor.release_freeze(request).await?;
    Ok(Json(result))
}

struct JsonBody<T>(T);

#[async_trait]
impl<S, T> FromRequest<S> for JsonBody<T>
where
    S: Send + Sync,
    T: Send,
    Json<T>: FromRequest<S, Rejection = axum::extract::rejection::JsonRejection>,
{
    type Rejection = ApiError;

    async fn from_request(req: Request, state: &S) -> Result<Self, Self::Rejection> {
        let Json(value) = Json::<T>::from_request(req, state)
            .await
            .map_err(ApiError::from_json_rejection)?;
        Ok(Self(value))
    }
}
