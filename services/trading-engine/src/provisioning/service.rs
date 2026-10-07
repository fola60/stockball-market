//! Market provisioning commands: the one-off cash, supply, and price writes that set up
//! accounts and pre-market instruments. They live in the engine so that every change to
//! cash, positions, and prices has a single owner, just like trades and top-ups.

use rust_decimal::Decimal;
use sqlx::PgPool;

use crate::{
    idempotency::{self, IdempotencyClaim},
    instruments,
    ledger::{self, CashLedgerEntry},
    positions,
    snapshots::{self, PriceSnapshotReason},
};

use super::{
    ApplyOpeningBalanceCommand, IssueInitialSupplyCommand, IssueInitialSupplyResult,
    PreMarketPriceResult, ProvisioningError, RecalibratePriceCurvesCommand,
    RecalibratePriceCurvesResult, SetPreMarketPriceCommand,
};

pub async fn apply_opening_balance(
    pool: &PgPool,
    command: ApplyOpeningBalanceCommand,
) -> Result<CashLedgerEntry, ProvisioningError> {
    command.validate()?;

    let request_hash = command.request_fingerprint();
    let mut transaction = pool.begin().await?;

    // Opening balances are cash credits, so they share the top-up idempotency scope.
    match idempotency::claim_topup(&mut transaction, &command.request_id, &request_hash).await? {
        IdempotencyClaim::Completed(record) => {
            let entry = record.deserialize_response::<CashLedgerEntry>()?;
            transaction.commit().await?;
            return Ok(entry);
        }
        IdempotencyClaim::Claimed(_) => {}
    }

    let entry = ledger::credit_opening_balance(
        &mut transaction,
        command.account_id,
        command.portfolio_id,
        command.amount,
        &command.request_id,
    )
    .await?;

    idempotency::complete_topup(&mut transaction, &command.request_id, 200, &entry).await?;
    transaction.commit().await?;
    Ok(entry)
}

pub async fn issue_initial_supply(
    pool: &PgPool,
    command: IssueInitialSupplyCommand,
) -> Result<IssueInitialSupplyResult, ProvisioningError> {
    command.validate()?;

    let request_hash = command.request_fingerprint();
    let mut transaction = pool.begin().await?;

    match idempotency::claim_admin_adjustment(&mut transaction, &command.request_id, &request_hash)
        .await?
    {
        IdempotencyClaim::Completed(record) => {
            let result = record.deserialize_response::<IssueInitialSupplyResult>()?;
            transaction.commit().await?;
            return Ok(result);
        }
        IdempotencyClaim::Claimed(_) => {}
    }

    let grouped = command.allocations_by_instrument();
    for (instrument_id, allocations) in &grouped {
        let instrument =
            instruments::lock_instrument_by_id(&mut transaction, *instrument_id).await?;
        if instruments::has_market_activity(&mut transaction, *instrument_id).await? {
            return Err(ProvisioningError::MarketActivityExists(*instrument_id));
        }

        let allocated: Decimal = allocations.iter().map(|item| item.quantity).sum();
        if allocated != instrument.shares_outstanding {
            return Err(ProvisioningError::SupplyMismatch {
                instrument_id: *instrument_id,
                allocated,
                shares_outstanding: instrument.shares_outstanding,
            });
        }

        for allocation in allocations {
            positions::increase_position(
                &mut transaction,
                allocation.portfolio_id,
                allocation.instrument_id,
                allocation.quantity,
            )
            .await?;
        }
    }

    let result = IssueInitialSupplyResult {
        request_id: command.request_id.clone(),
        instrument_count: grouped.len(),
        position_count: command.allocations.len(),
    };
    idempotency::complete_admin_adjustment(&mut transaction, &command.request_id, 200, &result)
        .await?;
    transaction.commit().await?;
    Ok(result)
}

pub async fn set_pre_market_price(
    pool: &PgPool,
    command: SetPreMarketPriceCommand,
) -> Result<PreMarketPriceResult, ProvisioningError> {
    command.validate()?;

    let request_hash = command.request_fingerprint();
    let mut transaction = pool.begin().await?;

    match idempotency::claim_admin_adjustment(&mut transaction, &command.request_id, &request_hash)
        .await?
    {
        IdempotencyClaim::Completed(record) => {
            let result = record.deserialize_response::<PreMarketPriceResult>()?;
            transaction.commit().await?;
            return Ok(result);
        }
        IdempotencyClaim::Claimed(_) => {}
    }

    let instrument =
        instruments::lock_instrument_by_id(&mut transaction, command.instrument_id).await?;
    if instruments::has_market_activity(&mut transaction, command.instrument_id).await? {
        return Err(ProvisioningError::MarketActivityExists(
            command.instrument_id,
        ));
    }

    instruments::reset_pre_market_price(&mut transaction, command.instrument_id, command.new_price)
        .await?;
    snapshots::record_price_snapshot(
        &mut transaction,
        command.instrument_id,
        instrument.current_price,
        command.new_price,
        PriceSnapshotReason::AdminAdjustment,
        None,
    )
    .await?;

    let result = PreMarketPriceResult {
        instrument_id: command.instrument_id,
        old_price: instrument.current_price,
        new_price: command.new_price,
    };
    idempotency::complete_admin_adjustment(&mut transaction, &command.request_id, 200, &result)
        .await?;
    transaction.commit().await?;
    Ok(result)
}

/// Re-anchors every player-share curve with a new calibration in one transaction. Prices are
/// untouched: each reference becomes the current price and net demand resets. Trades lock the
/// instrument rows they price, so none can interleave with the rebase.
pub async fn recalibrate_price_curves(
    pool: &PgPool,
    command: RecalibratePriceCurvesCommand,
) -> Result<RecalibratePriceCurvesResult, ProvisioningError> {
    command.validate()?;

    let mut transaction = pool.begin().await?;
    if !command.dry_run {
        let request_hash = command.request_fingerprint();
        match idempotency::claim_admin_adjustment(
            &mut transaction,
            &command.request_id,
            &request_hash,
        )
        .await?
        {
            IdempotencyClaim::Completed(record) => {
                let result = record.deserialize_response::<RecalibratePriceCurvesResult>()?;
                transaction.commit().await?;
                return Ok(result);
            }
            IdempotencyClaim::Claimed(_) => {}
        }
    }

    let curves =
        instruments::recalibrate_price_curves(&mut transaction, command.calibration).await?;
    let result = RecalibratePriceCurvesResult {
        request_id: command.request_id.clone(),
        dry_run: command.dry_run,
        calibration: command.calibration,
        instrument_count: curves.len(),
        reset_net_demand_count: curves
            .iter()
            .filter(|curve| !curve.old_net_shares_purchased.is_zero())
            .count(),
        max_reset_demand_ratio: curves
            .iter()
            .map(|curve| (curve.old_net_shares_purchased / curve.old_curve_depth_shares).abs())
            .max()
            .unwrap_or(Decimal::ZERO)
            .round_dp(6),
        previous_min_multiplier: curves
            .iter()
            .map(|curve| curve.old_full_supply_price_multiplier)
            .min(),
        previous_max_multiplier: curves
            .iter()
            .map(|curve| curve.old_full_supply_price_multiplier)
            .max(),
    };

    if command.dry_run {
        transaction.rollback().await?;
        return Ok(result);
    }
    idempotency::complete_admin_adjustment(&mut transaction, &command.request_id, 200, &result)
        .await?;
    transaction.commit().await?;
    Ok(result)
}
