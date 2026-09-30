use std::{fmt, str::FromStr};

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::FreezeError;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum FreezeReason {
    /// From lineup lock until post-match settlement for players involved in a fixture.
    MatchDay,
    AdminHalt,
    DataIssue,
}

impl FreezeReason {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::MatchDay => "MATCH_DAY",
            Self::AdminHalt => "ADMIN_HALT",
            Self::DataIssue => "DATA_ISSUE",
        }
    }
}

impl fmt::Display for FreezeReason {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for FreezeReason {
    type Err = FreezeError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "MATCH_DAY" => Ok(Self::MatchDay),
            "ADMIN_HALT" => Ok(Self::AdminHalt),
            "DATA_ISSUE" => Ok(Self::DataIssue),
            other => Err(FreezeError::UnsupportedReason(other.to_owned())),
        }
    }
}

/// Opens a freeze on each instrument for `source_key`. Re-applying is a no-op for instruments
/// that already have an open freeze with the same key.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ApplyFreezeCommand {
    pub reason: FreezeReason,
    pub source_key: String,
    pub instrument_ids: Vec<Uuid>,
}

impl ApplyFreezeCommand {
    pub fn validate(&self) -> Result<(), FreezeError> {
        validate_source_key(&self.source_key)?;
        if self.instrument_ids.is_empty() {
            return Err(FreezeError::EmptyInstruments);
        }
        Ok(())
    }

    /// Instrument ids without duplicates, in a stable order so row locks are taken consistently.
    pub fn sorted_instrument_ids(&self) -> Vec<Uuid> {
        let mut ids = self.instrument_ids.clone();
        ids.sort();
        ids.dedup();
        ids
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ApplyFreezeResult {
    pub source_key: String,
    pub reason: FreezeReason,
    pub opened_count: usize,
    pub already_open_count: usize,
    pub skipped_delisted_count: usize,
}

/// Releases every open freeze with `source_key`. Releasing twice is a no-op.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReleaseFreezeCommand {
    pub source_key: String,
}

impl ReleaseFreezeCommand {
    pub fn validate(&self) -> Result<(), FreezeError> {
        validate_source_key(&self.source_key)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReleaseFreezeResult {
    pub source_key: String,
    pub released_count: usize,
    /// Instruments that became tradable again; others still have another open freeze.
    pub reactivated_instrument_ids: Vec<Uuid>,
}

fn validate_source_key(source_key: &str) -> Result<(), FreezeError> {
    if source_key.trim().is_empty() {
        return Err(FreezeError::EmptySourceKey);
    }
    Ok(())
}
