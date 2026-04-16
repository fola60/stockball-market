use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum IdempotencyError {
    #[error("idempotency record {0} was not found")]
    NotFound(Uuid),

    #[error(
        "idempotency key {request_key} in scope {command_scope} was used with a different request"
    )]
    RequestMismatch {
        command_scope: String,
        request_key: String,
    },

    #[error("idempotency key {request_key} in scope {command_scope} is still in progress")]
    InProgress {
        command_scope: String,
        request_key: String,
    },

    #[error("idempotency key {request_key} in scope {command_scope} is marked failed")]
    Failed {
        command_scope: String,
        request_key: String,
    },

    #[error(
        "completed idempotency key {request_key} in scope {command_scope} is missing response body"
    )]
    MissingResponseBody {
        command_scope: String,
        request_key: String,
    },

    #[error("unsupported idempotency command scope: {0}")]
    UnsupportedCommandScope(String),

    #[error("unsupported idempotency status: {0}")]
    UnsupportedStatus(String),

    #[error(transparent)]
    Serialization(#[from] serde_json::Error),

    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
