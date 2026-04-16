use std::{fmt, str::FromStr};

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::error::IdempotencyError;

#[derive(Debug, Clone, PartialEq)]
pub struct IdempotencyRecord {
    pub id: Uuid,
    pub command_scope: IdempotencyScope,
    pub request_key: String,
    pub request_hash: Option<String>,
    pub status: IdempotencyStatus,
    pub response_status_code: Option<i32>,
    pub response_body: Option<String>,
    pub created_at: DateTime<Utc>,
    pub completed_at: Option<DateTime<Utc>>,
}

impl IdempotencyRecord {
    pub fn deserialize_response<T>(&self) -> Result<T, IdempotencyError>
    where
        T: for<'de> Deserialize<'de>,
    {
        let response_body =
            self.response_body
                .as_deref()
                .ok_or_else(|| IdempotencyError::MissingResponseBody {
                    command_scope: self.command_scope.to_string(),
                    request_key: self.request_key.clone(),
                })?;

        Ok(serde_json::from_str(response_body)?)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum IdempotencyClaim {
    Claimed(IdempotencyRecord),
    Completed(IdempotencyRecord),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum IdempotencyScope {
    OrderExecution,
    Topup,
    AdminAdjustment,
    Freeze,
    Unfreeze,
}

impl IdempotencyScope {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::OrderExecution => "ORDER_EXECUTION",
            Self::Topup => "TOPUP",
            Self::AdminAdjustment => "ADMIN_ADJUSTMENT",
            Self::Freeze => "FREEZE",
            Self::Unfreeze => "UNFREEZE",
        }
    }
}

impl fmt::Display for IdempotencyScope {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for IdempotencyScope {
    type Err = IdempotencyError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "ORDER_EXECUTION" => Ok(Self::OrderExecution),
            "TOPUP" => Ok(Self::Topup),
            "ADMIN_ADJUSTMENT" => Ok(Self::AdminAdjustment),
            "FREEZE" => Ok(Self::Freeze),
            "UNFREEZE" => Ok(Self::Unfreeze),
            other => Err(IdempotencyError::UnsupportedCommandScope(other.to_owned())),
        }
    }
}

impl TryFrom<&str> for IdempotencyScope {
    type Error = IdempotencyError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::from_str(value)
    }
}

impl TryFrom<String> for IdempotencyScope {
    type Error = IdempotencyError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::from_str(&value)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum IdempotencyStatus {
    Started,
    Completed,
    Failed,
}

impl IdempotencyStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Started => "STARTED",
            Self::Completed => "COMPLETED",
            Self::Failed => "FAILED",
        }
    }
}

impl fmt::Display for IdempotencyStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for IdempotencyStatus {
    type Err = IdempotencyError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "STARTED" => Ok(Self::Started),
            "COMPLETED" => Ok(Self::Completed),
            "FAILED" => Ok(Self::Failed),
            other => Err(IdempotencyError::UnsupportedStatus(other.to_owned())),
        }
    }
}

impl TryFrom<&str> for IdempotencyStatus {
    type Error = IdempotencyError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::from_str(value)
    }
}

impl TryFrom<String> for IdempotencyStatus {
    type Error = IdempotencyError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::from_str(&value)
    }
}
