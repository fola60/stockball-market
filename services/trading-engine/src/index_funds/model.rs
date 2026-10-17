use std::{collections::HashSet, fmt, str::FromStr};

use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::error::IndexFundError;

/// The ADMIN account holding the player shares behind every index fund unit in issue.
pub const CUSTODY_ACCOUNT_ID: Uuid = Uuid::from_u128(0x7f63e2d0_1adc_4af1_8ad0_000000000003);
pub const CUSTODY_PORTFOLIO_ID: Uuid = Uuid::from_u128(0x7f63e2d0_1adc_4af1_8ad0_000000000004);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum IndexKind {
    /// Every league player at one club.
    Team,
}

impl IndexKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Team => "TEAM",
        }
    }
}

impl fmt::Display for IndexKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for IndexKind {
    type Err = IndexFundError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "TEAM" => Ok(Self::Team),
            other => Err(IndexFundError::UnsupportedIndexKind(other.to_owned())),
        }
    }
}

/// One player share in a fund's basket: how many shares back each unit of the fund.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct IndexConstituent {
    pub instrument_id: Uuid,
    #[serde(with = "rust_decimal::serde::str")]
    pub shares_per_unit: Decimal,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CreateIndexFundCommand {
    pub symbol: String,
    pub display_name: String,
    pub index_kind: IndexKind,
    #[serde(default)]
    pub club: Option<String>,
    pub constituents: Vec<IndexConstituent>,
}

impl CreateIndexFundCommand {
    pub fn validate(&self) -> Result<(), IndexFundError> {
        if self.symbol.trim().is_empty() {
            return Err(IndexFundError::EmptySymbol);
        }
        if self.display_name.trim().is_empty() {
            return Err(IndexFundError::EmptyDisplayName);
        }
        if self.index_kind == IndexKind::Team
            && self
                .club
                .as_deref()
                .is_none_or(|club| club.trim().is_empty())
        {
            return Err(IndexFundError::MissingClub);
        }
        if self.constituents.is_empty() {
            return Err(IndexFundError::EmptyConstituents);
        }
        let mut seen = HashSet::with_capacity(self.constituents.len());
        for constituent in &self.constituents {
            if !seen.insert(constituent.instrument_id) {
                return Err(IndexFundError::DuplicateConstituent(
                    constituent.instrument_id,
                ));
            }
            if constituent.shares_per_unit <= Decimal::ZERO
                || constituent.shares_per_unit.scale() > 6
            {
                return Err(IndexFundError::InvalidSharesPerUnit {
                    instrument_id: constituent.instrument_id,
                    shares_per_unit: constituent.shares_per_unit,
                });
            }
        }
        Ok(())
    }

    /// The basket in instrument id order, the order its shares are locked and stored in.
    pub fn sorted_constituents(&self) -> Vec<IndexConstituent> {
        let mut constituents = self.constituents.clone();
        constituents.sort_by_key(|constituent| constituent.instrument_id);
        constituents
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CreateIndexFundResult {
    pub instrument_id: Uuid,
    pub symbol: String,
    /// False when a fund with this symbol and basket already existed.
    pub created: bool,
    pub constituent_count: usize,
    #[serde(with = "rust_decimal::serde::str")]
    pub unit_price: Decimal,
}

/// Rebalances a fund to a new membership, giving every member the same number of shares per
/// unit. Value-neutral: custody sells what leaves or shrinks and spends the proceeds, with any
/// cash already behind the units, on what joins or grows, so a unit keeps its value apart from
/// the trades' price impact.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RebalanceIndexFundCommand {
    pub request_id: String,
    pub instrument_id: Uuid,
    pub reason: String,
    pub members: Vec<Uuid>,
}

impl RebalanceIndexFundCommand {
    pub fn validate(&self) -> Result<(), IndexFundError> {
        if self.request_id.trim().is_empty() {
            return Err(IndexFundError::EmptyRequestId);
        }
        if self.reason.trim().is_empty() {
            return Err(IndexFundError::EmptyReason);
        }
        if self.members.is_empty() {
            return Err(IndexFundError::EmptyConstituents);
        }
        let mut seen = HashSet::with_capacity(self.members.len());
        for member in &self.members {
            if !seen.insert(*member) {
                return Err(IndexFundError::DuplicateConstituent(*member));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RebalanceIndexFundResult {
    pub rebalance_id: Uuid,
    pub instrument_id: Uuid,
    /// True when this request had already been applied and its record is returned.
    pub replayed: bool,
    #[serde(with = "rust_decimal::serde::str")]
    pub units_outstanding: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub unit_price_before: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub unit_price_after: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub cash_per_unit_after: Decimal,
    pub added_instrument_ids: Vec<Uuid>,
    pub removed_instrument_ids: Vec<Uuid>,
    pub constituents: Vec<IndexConstituent>,
}

/// A basket change about to be recorded.
pub(crate) struct BasketChange<'a> {
    pub index_instrument_id: Uuid,
    pub units_outstanding: Decimal,
    pub unit_price_before: Decimal,
    pub unit_price_after: Decimal,
    pub cash_per_unit_after: Decimal,
    pub old_basket: &'a [IndexConstituent],
    pub new_basket: &'a [IndexConstituent],
}

impl BasketChange<'_> {
    pub fn added(&self) -> Vec<Uuid> {
        let old: HashSet<Uuid> = self.old_basket.iter().map(|c| c.instrument_id).collect();
        self.new_basket
            .iter()
            .map(|c| c.instrument_id)
            .filter(|id| !old.contains(id))
            .collect()
    }

    pub fn removed(&self) -> Vec<Uuid> {
        let new: HashSet<Uuid> = self.new_basket.iter().map(|c| c.instrument_id).collect();
        self.old_basket
            .iter()
            .map(|c| c.instrument_id)
            .filter(|id| !new.contains(id))
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn command(constituents: Vec<IndexConstituent>) -> CreateIndexFundCommand {
        CreateIndexFundCommand {
            symbol: "IDX-ARS".to_owned(),
            display_name: "Arsenal Index".to_owned(),
            index_kind: IndexKind::Team,
            club: Some("Arsenal".to_owned()),
            constituents,
        }
    }

    fn constituent(shares_per_unit: Decimal) -> IndexConstituent {
        IndexConstituent {
            instrument_id: Uuid::new_v4(),
            shares_per_unit,
        }
    }

    #[test]
    fn accepts_a_team_basket() {
        assert!(command(vec![constituent(Decimal::ONE)]).validate().is_ok());
    }

    #[test]
    fn team_funds_need_a_club() {
        let mut command = command(vec![constituent(Decimal::ONE)]);
        command.club = Some("  ".to_owned());

        assert!(matches!(
            command.validate(),
            Err(IndexFundError::MissingClub)
        ));
    }

    #[test]
    fn rejects_duplicate_and_unpriceable_constituents() {
        let repeated = constituent(Decimal::ONE);
        assert!(matches!(
            command(vec![repeated.clone(), repeated]).validate(),
            Err(IndexFundError::DuplicateConstituent(_))
        ));
        assert!(matches!(
            command(vec![constituent(Decimal::ZERO)]).validate(),
            Err(IndexFundError::InvalidSharesPerUnit { .. })
        ));
        assert!(matches!(
            command(vec![constituent(Decimal::new(1, 7))]).validate(),
            Err(IndexFundError::InvalidSharesPerUnit { .. })
        ));
    }

    #[test]
    fn custody_ids_match_the_migration() {
        assert_eq!(
            CUSTODY_ACCOUNT_ID.to_string(),
            "7f63e2d0-1adc-4af1-8ad0-000000000003"
        );
        assert_eq!(
            CUSTODY_PORTFOLIO_ID.to_string(),
            "7f63e2d0-1adc-4af1-8ad0-000000000004"
        );
    }
}
