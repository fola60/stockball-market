use rust_decimal::Decimal;
use sqlx::PgPool;

use crate::{
    freezes,
    index_funds::{self, BasketChange, CUSTODY_PORTFOLIO_ID},
    instruments::{self, InstrumentStatus, InstrumentType},
    ledger, portfolios, positions,
    snapshots::{self, PriceSnapshotReason},
};

use super::{
    error::DelistingError,
    model::{DelistInstrumentCommand, DelistInstrumentResult},
};

const CASH_DECIMAL_PLACES: u32 = 12;

/// Buys every holder of a halted share out at its last price and takes it off the market.
///
/// Holders are paid through the ledger and their positions closed. The index fund custody
/// account is paid like any holder, and each fund that held the share swaps it for the same
/// value in cash per unit, so no unit changes value; the fund's next rebalance spends the cash.
/// Delisting a share twice is a no-op.
pub async fn delist_instrument(
    pool: &PgPool,
    command: DelistInstrumentCommand,
) -> Result<DelistInstrumentResult, DelistingError> {
    command.validate()?;
    let instrument_id = command.instrument_id;
    let mut transaction = pool.begin().await?;
    if instruments::get_instrument_type(&mut *transaction, instrument_id).await?
        != InstrumentType::PlayerShare
    {
        return Err(DelistingError::NotAPlayerShare(instrument_id));
    }

    // Funds first, then the share, then holders with custody last: the order every flow takes.
    let fund_ids = index_funds::index_ids_containing(&mut *transaction, &[instrument_id]).await?;
    let funds = instruments::lock_index_fund_instruments(&mut transaction, &fund_ids).await?;
    let instrument = instruments::lock_instrument_by_id(&mut transaction, instrument_id).await?;
    let price = instrument.current_price;
    match instrument.status {
        InstrumentStatus::Delisted => {
            transaction.commit().await?;
            return Ok(DelistInstrumentResult {
                instrument_id,
                already_delisted: true,
                settlement_price: price,
                holders_paid: 0,
                shares_bought_out: Decimal::ZERO,
                amount_paid: Decimal::ZERO,
                index_funds_updated: Vec::new(),
            });
        }
        InstrumentStatus::Active => return Err(DelistingError::StillTrading(instrument_id)),
        InstrumentStatus::Frozen => {}
    }

    let holders =
        positions::lock_holders(&mut transaction, instrument_id, CUSTODY_PORTFOLIO_ID).await?;
    let mut shares_bought_out = Decimal::ZERO;
    let mut amount_paid = Decimal::ZERO;
    for holder in &holders {
        let amount = (holder.quantity * price).round_dp(CASH_DECIMAL_PLACES);
        let portfolio = portfolios::get_portfolio_by_id(&mut *transaction, holder.portfolio_id)
            .await?
            .ok_or(ledger::LedgerError::PortfolioNotFound(holder.portfolio_id))?;
        if amount > Decimal::ZERO {
            ledger::credit_delisting_buyout(
                &mut transaction,
                portfolio.account_id,
                holder.portfolio_id,
                amount,
                &format!("delisting:{instrument_id}:{}", holder.portfolio_id),
            )
            .await?;
        }
        positions::decrease_position(
            &mut transaction,
            holder.portfolio_id,
            instrument_id,
            holder.quantity,
        )
        .await?;
        shares_bought_out += holder.quantity;
        amount_paid += amount;
    }

    for fund_id in &fund_ids {
        let basket = index_funds::load_constituents(&mut *transaction, *fund_id).await?;
        let Some(removed) = basket.iter().find(|c| c.instrument_id == instrument_id) else {
            continue;
        };
        let cash_before = index_funds::cash_per_unit(&mut *transaction, *fund_id).await?;
        let cash_after = (cash_before + removed.shares_per_unit * price)
            .round_dp_with_strategy(CASH_DECIMAL_PLACES, rust_decimal::RoundingStrategy::ToZero);
        let remaining: Vec<_> = basket
            .iter()
            .filter(|c| c.instrument_id != instrument_id)
            .cloned()
            .collect();
        let unit_prices = index_funds::unit_prices(&mut *transaction, &[*fund_id]).await?;
        let unit_price = unit_prices.get(fund_id).copied().unwrap_or_default();
        let units = index_funds::units_outstanding(&mut *transaction, *fund_id).await?;
        index_funds::record_rebalance(
            &mut transaction,
            &format!("delisting:{instrument_id}:{fund_id}"),
            "DELISTING",
            command.reason.trim(),
            &BasketChange {
                index_instrument_id: *fund_id,
                units_outstanding: units,
                unit_price_before: unit_price,
                // The share leaves at the price the cash replaces it with.
                unit_price_after: unit_price,
                cash_per_unit_after: cash_after,
                old_basket: &basket,
                new_basket: &remaining,
            },
        )
        .await?;
        index_funds::replace_basket(&mut transaction, *fund_id, &remaining, cash_after).await?;
    }
    // Cash is rounded down to the cent's billionth, so a unit may lose that fraction.
    let unit_prices = index_funds::unit_prices(&mut *transaction, &fund_ids).await?;
    for fund in &funds {
        let Some(unit_price) = unit_prices.get(&fund.id).copied() else {
            continue;
        };
        if unit_price != fund.current_price && unit_price > Decimal::ZERO {
            instruments::update_index_fund_price(&mut transaction, fund.id, unit_price).await?;
            snapshots::record_price_snapshot(
                &mut transaction,
                fund.id,
                fund.current_price,
                unit_price,
                PriceSnapshotReason::IndexRevaluation,
                None,
            )
            .await?;
        }
    }

    freezes::release_all_for_instrument(&mut transaction, instrument_id).await?;
    instruments::mark_delisted(&mut transaction, instrument_id).await?;
    transaction.commit().await?;

    Ok(DelistInstrumentResult {
        instrument_id,
        already_delisted: false,
        settlement_price: price,
        holders_paid: holders.len(),
        shares_bought_out,
        amount_paid,
        index_funds_updated: fund_ids,
    })
}
