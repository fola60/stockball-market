use std::collections::HashMap;

use rust_decimal::Decimal;
use sqlx::{FromRow, PgConnection, PgExecutor};
use uuid::Uuid;

use super::{
    error::IndexFundError,
    model::{BasketChange, IndexConstituent, IndexKind, RebalanceIndexFundResult},
};

/// Prices are stored to twelve decimal places, like player-share prices.
const UNIT_PRICE_DECIMAL_PLACES: u32 = 12;

#[derive(Debug, FromRow)]
struct ConstituentRow {
    constituent_instrument_id: Uuid,
    shares_per_unit: Decimal,
}

#[derive(Debug, FromRow)]
struct RebalanceRow {
    id: Uuid,
    index_instrument_id: Uuid,
    units_outstanding: Decimal,
    unit_price_before: Decimal,
    unit_price_after: Decimal,
    cash_per_unit_after: Decimal,
    new_basket: serde_json::Value,
    added_instrument_ids: Vec<Uuid>,
    removed_instrument_ids: Vec<Uuid>,
}

impl RebalanceRow {
    fn into_result(self, replayed: bool) -> Result<RebalanceIndexFundResult, IndexFundError> {
        let constituents: Vec<IndexConstituent> = serde_json::from_value(self.new_basket)
            .map_err(|_| IndexFundError::MissingBasket(self.index_instrument_id))?;
        Ok(RebalanceIndexFundResult {
            rebalance_id: self.id,
            instrument_id: self.index_instrument_id,
            replayed,
            units_outstanding: self.units_outstanding,
            unit_price_before: self.unit_price_before,
            unit_price_after: self.unit_price_after,
            cash_per_unit_after: self.cash_per_unit_after,
            added_instrument_ids: self.added_instrument_ids,
            removed_instrument_ids: self.removed_instrument_ids,
            constituents,
        })
    }
}

#[derive(Debug, FromRow)]
struct UnitPriceRow {
    index_instrument_id: Uuid,
    unit_price: Decimal,
}

/// A fund's basket, in constituent id order.
pub async fn load_constituents(
    executor: impl PgExecutor<'_>,
    index_instrument_id: Uuid,
) -> Result<Vec<IndexConstituent>, IndexFundError> {
    let rows = sqlx::query_as::<_, ConstituentRow>(
        r#"
        SELECT constituent_instrument_id, shares_per_unit
        FROM index_constituents
        WHERE index_instrument_id = $1
        ORDER BY constituent_instrument_id
        "#,
    )
    .bind(index_instrument_id)
    .fetch_all(executor)
    .await?;

    Ok(rows
        .into_iter()
        .map(|row| IndexConstituent {
            instrument_id: row.constituent_instrument_id,
            shares_per_unit: row.shares_per_unit,
        })
        .collect())
}

/// Every fund holding any of these player shares, in id order.
pub async fn index_ids_containing(
    executor: impl PgExecutor<'_>,
    instrument_ids: &[Uuid],
) -> Result<Vec<Uuid>, IndexFundError> {
    let ids = sqlx::query_scalar::<_, Uuid>(
        r#"
        SELECT DISTINCT index_instrument_id
        FROM index_constituents
        WHERE constituent_instrument_id = ANY($1)
        ORDER BY index_instrument_id
        "#,
    )
    .bind(instrument_ids)
    .fetch_all(executor)
    .await?;

    Ok(ids)
}

/// What one unit of each fund is worth: its basket at current prices plus its cash.
pub async fn unit_prices(
    executor: impl PgExecutor<'_>,
    index_instrument_ids: &[Uuid],
) -> Result<HashMap<Uuid, Decimal>, IndexFundError> {
    let rows = sqlx::query_as::<_, UnitPriceRow>(
        r#"
        SELECT
            fund.instrument_id AS index_instrument_id,
            COALESCE(SUM(constituent.shares_per_unit * instrument.current_price), 0)
                + fund.cash_per_unit AS unit_price
        FROM index_funds AS fund
        LEFT JOIN index_constituents AS constituent
            ON constituent.index_instrument_id = fund.instrument_id
        LEFT JOIN instruments AS instrument
            ON instrument.id = constituent.constituent_instrument_id
        WHERE fund.instrument_id = ANY($1)
        GROUP BY fund.instrument_id, fund.cash_per_unit
        "#,
    )
    .bind(index_instrument_ids)
    .fetch_all(executor)
    .await?;

    Ok(rows
        .into_iter()
        .map(|row| {
            (
                row.index_instrument_id,
                row.unit_price.round_dp(UNIT_PRICE_DECIMAL_PLACES),
            )
        })
        .collect())
}

/// The value of a basket at the given prices, rounded like a stored unit price.
pub fn basket_value(
    constituents: &[IndexConstituent],
    price_of: impl Fn(Uuid) -> Decimal,
) -> Decimal {
    constituents
        .iter()
        .map(|constituent| constituent.shares_per_unit * price_of(constituent.instrument_id))
        .sum::<Decimal>()
        .round_dp(UNIT_PRICE_DECIMAL_PLACES)
}

/// Cash held behind each unit of a fund.
pub async fn cash_per_unit(
    executor: impl PgExecutor<'_>,
    index_instrument_id: Uuid,
) -> Result<Decimal, IndexFundError> {
    sqlx::query_scalar::<_, Decimal>(
        "SELECT cash_per_unit FROM index_funds WHERE instrument_id = $1",
    )
    .bind(index_instrument_id)
    .fetch_optional(executor)
    .await?
    .ok_or(IndexFundError::NotAnIndexFund(index_instrument_id))
}

/// Units of a fund held across all portfolios. Callers hold the fund's row lock, which every
/// unit trade takes first, so the count cannot change underneath them.
pub async fn units_outstanding(
    executor: impl PgExecutor<'_>,
    index_instrument_id: Uuid,
) -> Result<Decimal, IndexFundError> {
    let units = sqlx::query_scalar::<_, Decimal>(
        "SELECT COALESCE(SUM(quantity), 0) FROM positions WHERE instrument_id = $1",
    )
    .bind(index_instrument_id)
    .fetch_one(executor)
    .await?;
    Ok(units)
}

/// Replaces a fund's basket and cash per unit.
pub(crate) async fn replace_basket(
    connection: &mut PgConnection,
    index_instrument_id: Uuid,
    constituents: &[IndexConstituent],
    cash_per_unit: Decimal,
) -> Result<(), IndexFundError> {
    sqlx::query("DELETE FROM index_constituents WHERE index_instrument_id = $1")
        .bind(index_instrument_id)
        .execute(&mut *connection)
        .await?;
    insert_constituents(connection, index_instrument_id, constituents).await?;
    sqlx::query("UPDATE index_funds SET cash_per_unit = $2 WHERE instrument_id = $1")
        .bind(index_instrument_id)
        .bind(cash_per_unit)
        .execute(&mut *connection)
        .await?;
    Ok(())
}

pub(crate) async fn find_rebalance(
    connection: &mut PgConnection,
    request_id: &str,
) -> Result<Option<RebalanceIndexFundResult>, IndexFundError> {
    let row = sqlx::query_as::<_, RebalanceRow>(
        r#"
        SELECT id, index_instrument_id, units_outstanding, unit_price_before, unit_price_after,
               cash_per_unit_after, new_basket, added_instrument_ids, removed_instrument_ids
        FROM index_fund_rebalances
        WHERE request_id = $1
        "#,
    )
    .bind(request_id)
    .fetch_optional(&mut *connection)
    .await?;
    row.map(|row| row.into_result(true)).transpose()
}

/// Records a basket change. `request_id` makes a retried rebalance replay this record.
pub(crate) async fn record_rebalance(
    connection: &mut PgConnection,
    request_id: &str,
    kind: &str,
    reason: &str,
    change: &BasketChange<'_>,
) -> Result<Uuid, IndexFundError> {
    let id = sqlx::query_scalar::<_, Uuid>(
        r#"
        INSERT INTO index_fund_rebalances (
            request_id, index_instrument_id, kind, reason, units_outstanding,
            unit_price_before, unit_price_after, cash_per_unit_after, old_basket, new_basket,
            added_instrument_ids, removed_instrument_ids
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        RETURNING id
        "#,
    )
    .bind(request_id)
    .bind(change.index_instrument_id)
    .bind(kind)
    .bind(reason)
    .bind(change.units_outstanding)
    .bind(change.unit_price_before)
    .bind(change.unit_price_after)
    .bind(change.cash_per_unit_after)
    .bind(serde_json::to_value(change.old_basket).unwrap_or_default())
    .bind(serde_json::to_value(change.new_basket).unwrap_or_default())
    .bind(change.added())
    .bind(change.removed())
    .fetch_one(&mut *connection)
    .await?;
    Ok(id)
}

pub(crate) async fn find_instrument_by_symbol(
    connection: &mut PgConnection,
    symbol: &str,
) -> Result<Option<(Uuid, String)>, IndexFundError> {
    let row = sqlx::query_as::<_, (Uuid, String)>(
        r#"
        SELECT id, instrument_type
        FROM instruments
        WHERE symbol = $1
        "#,
    )
    .bind(symbol)
    .fetch_optional(&mut *connection)
    .await?;

    Ok(row)
}

/// The type of each requested instrument; ids with no instrument are left out.
pub(crate) async fn instrument_types(
    connection: &mut PgConnection,
    instrument_ids: &[Uuid],
) -> Result<HashMap<Uuid, String>, IndexFundError> {
    let rows = sqlx::query_as::<_, (Uuid, String)>(
        r#"
        SELECT id, instrument_type
        FROM instruments
        WHERE id = ANY($1)
        "#,
    )
    .bind(instrument_ids)
    .fetch_all(&mut *connection)
    .await?;

    Ok(rows.into_iter().collect())
}

pub(crate) async fn insert_index_fund(
    connection: &mut PgConnection,
    instrument_id: Uuid,
    index_kind: IndexKind,
    club: Option<&str>,
    constituents: &[IndexConstituent],
) -> Result<(), IndexFundError> {
    sqlx::query(
        r#"
        INSERT INTO index_funds (instrument_id, index_kind, club)
        VALUES ($1, $2, $3)
        "#,
    )
    .bind(instrument_id)
    .bind(index_kind.as_str())
    .bind(club)
    .execute(&mut *connection)
    .await?;

    insert_constituents(connection, instrument_id, constituents).await
}

async fn insert_constituents(
    connection: &mut PgConnection,
    instrument_id: Uuid,
    constituents: &[IndexConstituent],
) -> Result<(), IndexFundError> {
    let constituent_ids: Vec<Uuid> = constituents.iter().map(|c| c.instrument_id).collect();
    let shares_per_unit: Vec<Decimal> = constituents.iter().map(|c| c.shares_per_unit).collect();
    sqlx::query(
        r#"
        INSERT INTO index_constituents (
            index_instrument_id,
            constituent_instrument_id,
            shares_per_unit
        )
        SELECT $1, constituent.instrument_id, constituent.shares_per_unit
        FROM unnest($2::uuid[], $3::numeric[]) AS constituent(instrument_id, shares_per_unit)
        "#,
    )
    .bind(instrument_id)
    .bind(&constituent_ids)
    .bind(&shares_per_unit)
    .execute(&mut *connection)
    .await?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn basket_value_weights_each_price_by_its_shares_per_unit() {
        let first = Uuid::new_v4();
        let second = Uuid::new_v4();
        let basket = [
            IndexConstituent {
                instrument_id: first,
                shares_per_unit: Decimal::ONE,
            },
            IndexConstituent {
                instrument_id: second,
                shares_per_unit: Decimal::new(25, 1),
            },
        ];

        let value = basket_value(&basket, |id| {
            if id == first {
                Decimal::new(10, 0)
            } else {
                Decimal::new(4, 0)
            }
        });

        assert_eq!(value, Decimal::new(20, 0));
    }
}
