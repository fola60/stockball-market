use async_trait::async_trait;
use axum::{
    extract::{FromRequest, Request, State},
    routing::post,
    Json, Router,
};

use crate::http::{
    error::ApiError, executor::OrderExecutor, ExecuteOrderRequest, ExecuteOrderResponse,
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
        .with_state(state)
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
