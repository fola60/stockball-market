use chrono::{DateTime, Utc};
use serde::Serialize;
use sqlx::{FromRow, PgConnection};
use uuid::Uuid;

use super::{
    error::IdempotencyError,
    model::{IdempotencyClaim, IdempotencyRecord, IdempotencyScope, IdempotencyStatus},
};

#[derive(Debug, FromRow)]
struct IdempotencyKeyRow {
    id: Uuid,
    command_scope: String,
    request_key: String,
    request_hash: Option<String>,
    status: String,
    response_status_code: Option<i32>,
    response_body: Option<String>,
    created_at: DateTime<Utc>,
    completed_at: Option<DateTime<Utc>>,
}

pub async fn claim_order_execution(
    connection: &mut PgConnection,
    request_key: &str,
    request_hash: &str,
) -> Result<IdempotencyClaim, IdempotencyError> {
    claim_key(
        connection,
        IdempotencyScope::OrderExecution,
        request_key,
        request_hash,
    )
    .await
}

pub async fn complete_order_execution<T>(
    connection: &mut PgConnection,
    request_key: &str,
    response_status_code: i32,
    response: &T,
) -> Result<IdempotencyRecord, IdempotencyError>
where
    T: Serialize,
{
    complete_key(
        connection,
        IdempotencyScope::OrderExecution,
        request_key,
        response_status_code,
        response,
    )
    .await
}

async fn claim_key(
    connection: &mut PgConnection,
    scope: IdempotencyScope,
    request_key: &str,
    request_hash: &str,
) -> Result<IdempotencyClaim, IdempotencyError> {
    let inserted = sqlx::query_as::<_, IdempotencyKeyRow>(
        r#"
        INSERT INTO idempotency_keys (
            command_scope,
            request_key,
            request_hash,
            status
        ) VALUES (
            $1,
            $2,
            $3,
            'STARTED'
        )
        ON CONFLICT (command_scope, request_key) DO NOTHING
        RETURNING
            id,
            command_scope,
            request_key,
            request_hash,
            status,
            response_status_code,
            response_body::text AS response_body,
            created_at,
            completed_at
        "#,
    )
    .bind(scope.as_str())
    .bind(request_key)
    .bind(request_hash)
    .fetch_optional(&mut *connection)
    .await?;

    if let Some(row) = inserted {
        return Ok(IdempotencyClaim::Claimed(IdempotencyRecord::try_from(row)?));
    }

    let existing = lock_key(&mut *connection, scope, request_key).await?;

    if existing.request_hash.as_deref() != Some(request_hash) {
        return Err(IdempotencyError::RequestMismatch {
            command_scope: scope.to_string(),
            request_key: request_key.to_owned(),
        });
    }

    match existing.status {
        IdempotencyStatus::Completed => Ok(IdempotencyClaim::Completed(existing)),
        IdempotencyStatus::Started => Err(IdempotencyError::InProgress {
            command_scope: scope.to_string(),
            request_key: request_key.to_owned(),
        }),
        IdempotencyStatus::Failed => Err(IdempotencyError::Failed {
            command_scope: scope.to_string(),
            request_key: request_key.to_owned(),
        }),
    }
}

async fn complete_key<T>(
    connection: &mut PgConnection,
    scope: IdempotencyScope,
    request_key: &str,
    response_status_code: i32,
    response: &T,
) -> Result<IdempotencyRecord, IdempotencyError>
where
    T: Serialize,
{
    let response_body = serde_json::to_string(response)?;
    let row = sqlx::query_as::<_, IdempotencyKeyRow>(
        r#"
        UPDATE idempotency_keys
        SET
            status = 'COMPLETED',
            response_status_code = $3,
            response_body = $4::jsonb,
            completed_at = now()
        WHERE command_scope = $1
          AND request_key = $2
        RETURNING
            id,
            command_scope,
            request_key,
            request_hash,
            status,
            response_status_code,
            response_body::text AS response_body,
            created_at,
            completed_at
        "#,
    )
    .bind(scope.as_str())
    .bind(request_key)
    .bind(response_status_code)
    .bind(response_body)
    .fetch_optional(&mut *connection)
    .await?
    .ok_or_else(|| IdempotencyError::InProgress {
        command_scope: scope.to_string(),
        request_key: request_key.to_owned(),
    })?;

    IdempotencyRecord::try_from(row)
}

async fn lock_key(
    connection: &mut PgConnection,
    scope: IdempotencyScope,
    request_key: &str,
) -> Result<IdempotencyRecord, IdempotencyError> {
    let row = sqlx::query_as::<_, IdempotencyKeyRow>(
        r#"
        SELECT
            id,
            command_scope,
            request_key,
            request_hash,
            status,
            response_status_code,
            response_body::text AS response_body,
            created_at,
            completed_at
        FROM idempotency_keys
        WHERE command_scope = $1
          AND request_key = $2
        FOR UPDATE
        "#,
    )
    .bind(scope.as_str())
    .bind(request_key)
    .fetch_optional(&mut *connection)
    .await?
    .ok_or_else(|| IdempotencyError::InProgress {
        command_scope: scope.to_string(),
        request_key: request_key.to_owned(),
    })?;

    IdempotencyRecord::try_from(row)
}

impl TryFrom<IdempotencyKeyRow> for IdempotencyRecord {
    type Error = IdempotencyError;

    fn try_from(row: IdempotencyKeyRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: row.id,
            command_scope: IdempotencyScope::try_from(row.command_scope)?,
            request_key: row.request_key,
            request_hash: row.request_hash,
            status: IdempotencyStatus::try_from(row.status)?,
            response_status_code: row.response_status_code,
            response_body: row.response_body,
            created_at: row.created_at,
            completed_at: row.completed_at,
        })
    }
}
