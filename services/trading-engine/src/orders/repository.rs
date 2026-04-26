use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use sqlx::{FromRow, PgConnection};
use uuid::Uuid;

use super::{
    error::OrderError,
    model::{ExecuteOrderCommand, Order, OrderSide, OrderStatus},
};

#[derive(Debug, FromRow)]
struct OrderRow {
    id: Uuid,
    request_id: String,
    account_id: Uuid,
    portfolio_id: Uuid,
    instrument_id: Uuid,
    side: String,
    shares: Decimal,
    status: String,
    rejection_reason: Option<String>,
    submitted_at: DateTime<Utc>,
    filled_at: Option<DateTime<Utc>>,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

pub async fn create_pending_order(
    connection: &mut PgConnection,
    command: &ExecuteOrderCommand,
) -> Result<Order, OrderError> {
    command.validate()?;

    let row = sqlx::query_as::<_, OrderRow>(
        r#"
        INSERT INTO orders (
            request_id,
            account_id,
            portfolio_id,
            instrument_id,
            side,
            shares,
            status
        ) VALUES (
            $1,
            $2,
            $3,
            $4,
            $5,
            $6,
            'PENDING'
        )
        RETURNING
            id,
            request_id,
            account_id,
            portfolio_id,
            instrument_id,
            side,
            shares,
            status,
            rejection_reason,
            submitted_at,
            filled_at,
            created_at,
            updated_at
        "#,
    )
    .bind(&command.request_id)
    .bind(command.account_id)
    .bind(command.portfolio_id)
    .bind(command.instrument_id)
    .bind(command.side.as_str())
    .bind(command.quantity)
    .fetch_one(&mut *connection)
    .await?;

    Order::try_from(row)
}

pub async fn mark_order_filled(
    connection: &mut PgConnection,
    order_id: Uuid,
) -> Result<Order, OrderError> {
    update_order_status(connection, order_id, OrderStatus::Filled, None).await
}

pub async fn mark_order_rejected(
    connection: &mut PgConnection,
    order_id: Uuid,
    rejection_reason: &str,
) -> Result<Order, OrderError> {
    update_order_status(
        connection,
        order_id,
        OrderStatus::Rejected,
        Some(rejection_reason),
    )
    .await
}

pub async fn mark_order_failed(
    connection: &mut PgConnection,
    order_id: Uuid,
    failure_reason: &str,
) -> Result<Order, OrderError> {
    update_order_status(
        connection,
        order_id,
        OrderStatus::Failed,
        Some(failure_reason),
    )
    .await
}

async fn update_order_status(
    connection: &mut PgConnection,
    order_id: Uuid,
    status: OrderStatus,
    rejection_reason: Option<&str>,
) -> Result<Order, OrderError> {
    let row = sqlx::query_as::<_, OrderRow>(
        r#"
        UPDATE orders
        SET
            status = $2,
            rejection_reason = $3,
            filled_at = CASE WHEN $2 = 'FILLED' THEN now() ELSE filled_at END,
            updated_at = now()
        WHERE id = $1
        RETURNING
            id,
            request_id,
            account_id,
            portfolio_id,
            instrument_id,
            side,
            shares,
            status,
            rejection_reason,
            submitted_at,
            filled_at,
            created_at,
            updated_at
        "#,
    )
    .bind(order_id)
    .bind(status.as_str())
    .bind(rejection_reason)
    .fetch_optional(&mut *connection)
    .await?
    .ok_or(OrderError::NotFound(order_id))?;

    Order::try_from(row)
}

impl TryFrom<OrderRow> for Order {
    type Error = OrderError;

    fn try_from(row: OrderRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: row.id,
            request_id: row.request_id,
            account_id: row.account_id,
            portfolio_id: row.portfolio_id,
            instrument_id: row.instrument_id,
            side: OrderSide::try_from(row.side)?,
            quantity: row.shares,
            status: OrderStatus::try_from(row.status)?,
            rejection_reason: row.rejection_reason,
            submitted_at: row.submitted_at,
            filled_at: row.filled_at,
            created_at: row.created_at,
            updated_at: row.updated_at,
        })
    }
}
