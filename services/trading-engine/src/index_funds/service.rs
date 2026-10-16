use std::collections::HashMap;

use sqlx::PgPool;

use crate::{
    instruments::{self, InstrumentStatus, InstrumentType},
    snapshots::{self, PriceSnapshotReason},
};

use super::{
    error::IndexFundError,
    model::{CreateIndexFundCommand, CreateIndexFundResult},
    repository,
};

/// Lists a fund over a fixed basket of player shares, priced at the basket's current value.
///
/// Creation is idempotent by symbol: asking again for the same basket returns the existing
/// fund, while a different basket under a taken symbol is refused.
pub async fn create_index_fund(
    pool: &PgPool,
    command: CreateIndexFundCommand,
) -> Result<CreateIndexFundResult, IndexFundError> {
    command.validate()?;
    let constituents = command.sorted_constituents();
    let symbol = command.symbol.trim();
    let mut transaction = pool.begin().await?;

    if let Some((instrument_id, instrument_type)) =
        repository::find_instrument_by_symbol(&mut transaction, symbol).await?
    {
        let same_fund = InstrumentType::try_from(instrument_type)? == InstrumentType::IndexFund
            && repository::load_constituents(&mut *transaction, instrument_id).await?
                == constituents;
        if !same_fund {
            return Err(IndexFundError::SymbolTaken(symbol.to_owned()));
        }
        let unit_price = instruments::get_current_price(&mut *transaction, instrument_id).await?;
        transaction.commit().await?;
        return Ok(CreateIndexFundResult {
            instrument_id,
            symbol: symbol.to_owned(),
            created: false,
            constituent_count: constituents.len(),
            unit_price,
        });
    }

    let constituent_ids: Vec<_> = constituents.iter().map(|c| c.instrument_id).collect();
    let types = repository::instrument_types(&mut transaction, &constituent_ids).await?;
    for instrument_id in &constituent_ids {
        match types.get(instrument_id).map(String::as_str) {
            None => return Err(instruments::InstrumentError::NotFound(*instrument_id).into()),
            Some("PLAYER_SHARE") => {}
            Some(_) => return Err(IndexFundError::ConstituentNotPlayerShare(*instrument_id)),
        }
    }

    // Players only, in id order: no fund row is locked, so this cannot invert the
    // funds-before-players order that trade execution follows.
    let players = instruments::lock_instruments_by_ids(&mut transaction, &constituent_ids).await?;
    if let Some(delisted) = players
        .iter()
        .find(|player| player.status == InstrumentStatus::Delisted)
    {
        return Err(IndexFundError::ConstituentNotListed {
            instrument_id: delisted.id,
            status: delisted.status,
        });
    }
    let prices: HashMap<_, _> = players
        .iter()
        .map(|player| (player.id, player.current_price))
        .collect();
    let unit_price = repository::basket_value(&constituents, |id| prices[&id]);

    let instrument_id = instruments::insert_index_fund_instrument(
        &mut transaction,
        symbol,
        command.display_name.trim(),
        unit_price,
    )
    .await?;
    repository::insert_index_fund(
        &mut transaction,
        instrument_id,
        command.index_kind,
        command.club.as_deref().map(str::trim),
        &constituents,
    )
    .await?;
    snapshots::record_price_snapshot(
        &mut transaction,
        instrument_id,
        unit_price,
        unit_price,
        PriceSnapshotReason::Seed,
        None,
    )
    .await?;

    transaction.commit().await?;
    Ok(CreateIndexFundResult {
        instrument_id,
        symbol: symbol.to_owned(),
        created: true,
        constituent_count: constituents.len(),
        unit_price,
    })
}
