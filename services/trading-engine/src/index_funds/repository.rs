use std::collections::HashMap;

use rust_decimal::Decimal;
use sqlx::{FromRow, PgConnection, PgExecutor};
use uuid::Uuid;

use super::{
    error::IndexFundError,
    model::{IndexConstituent, IndexKind},
};

/// Prices are stored to twelve decimal places, like player-share prices.
const UNIT_PRICE_DECIMAL_PLACES: u32 = 12;

#[derive(Debug, FromRow)]
struct ConstituentRow {
    constituent_instrument_id: Uuid,
    shares_per_unit: Decimal,
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

/// What one unit of each fund is worth at its constituents' current prices.
pub async fn unit_prices(
    executor: impl PgExecutor<'_>,
    index_instrument_ids: &[Uuid],
) -> Result<HashMap<Uuid, Decimal>, IndexFundError> {
    let rows = sqlx::query_as::<_, UnitPriceRow>(
        r#"
        SELECT
            constituent.index_instrument_id,
            SUM(constituent.shares_per_unit * instrument.current_price) AS unit_price
        FROM index_constituents AS constituent
        JOIN instruments AS instrument ON instrument.id = constituent.constituent_instrument_id
        WHERE constituent.index_instrument_id = ANY($1)
        GROUP BY constituent.index_instrument_id
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
