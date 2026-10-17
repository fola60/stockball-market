//! Index fund rebalancing: moves a fund's basket to a new membership without changing what a unit
//! is worth, apart from the price impact of the trades it takes.
//!
//! Every member of the new basket holds the same number of shares per unit, sized so the new
//! basket is worth what the old one was. With units in issue, custody sells what leaves or
//! shrinks, then spends the proceeds and the fund's cash on what joins or grows. Price impact
//! makes the buys dearer than planned, so they are scaled down to the cash available and any
//! remainder stays as cash per unit. With no units in issue nothing trades: the basket is
//! rewritten at current prices.

use std::collections::{BTreeSet, HashMap};

use rust_decimal::{Decimal, RoundingStrategy};
use sqlx::{PgConnection, PgPool};
use uuid::Uuid;

use crate::{
    freezes,
    index_funds::{
        self, BasketChange, IndexConstituent, IndexFundError, RebalanceIndexFundCommand,
        RebalanceIndexFundResult, CUSTODY_ACCOUNT_ID, CUSTODY_PORTFOLIO_ID,
    },
    instruments::{self, Instrument, InstrumentStatus, InstrumentType},
    ledger,
    orders::OrderSide,
    price_impact::{self, PriceImpactDirection, PriceImpactError},
};

use super::{
    error::ExecutionError,
    index_fund::{execute_custody_trade, leg_quantity, BasketLeg},
    repository::{revalue_index_funds, TradeCause},
};

const SHARES_DECIMAL_PLACES: u32 = 6;
const CASH_DECIMAL_PLACES: u32 = 12;
/// Halvings of the buy scale: far finer than a share's sixth decimal place.
const BUY_SCALE_SEARCH_STEPS: usize = 40;

pub async fn rebalance_index_fund(
    pool: &PgPool,
    command: RebalanceIndexFundCommand,
) -> Result<RebalanceIndexFundResult, ExecutionError> {
    command.validate()?;
    let mut transaction = pool.begin().await?;
    if let Some(applied) =
        index_funds::find_rebalance(&mut transaction, &command.request_id).await?
    {
        if applied.instrument_id != command.instrument_id {
            return Err(IndexFundError::RequestMismatch(command.request_id).into());
        }
        transaction.commit().await?;
        return Ok(applied);
    }
    let result = rebalance_in_transaction(&mut transaction, &command).await?;
    transaction.commit().await?;
    Ok(result)
}

async fn rebalance_in_transaction(
    connection: &mut PgConnection,
    command: &RebalanceIndexFundCommand,
) -> Result<RebalanceIndexFundResult, ExecutionError> {
    let fund_id = command.instrument_id;
    if instruments::get_instrument_type(&mut *connection, fund_id).await?
        != InstrumentType::IndexFund
    {
        return Err(IndexFundError::NotAnIndexFund(fund_id).into());
    }
    let old_basket = index_funds::load_constituents(&mut *connection, fund_id).await?;
    let members: BTreeSet<Uuid> = command.members.iter().copied().collect();
    let touched: Vec<Uuid> = old_basket
        .iter()
        .map(|c| c.instrument_id)
        .chain(members.iter().copied())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();

    // Funds first, then players, each in id order: the order every trade flow locks in.
    let mut fund_ids = index_funds::index_ids_containing(&mut *connection, &touched).await?;
    fund_ids.push(fund_id);
    let funds = instruments::lock_index_fund_instruments(connection, &fund_ids).await?;
    let fund = funds
        .iter()
        .find(|fund| fund.id == fund_id)
        .ok_or(IndexFundError::NotAnIndexFund(fund_id))?;
    if fund.status == InstrumentStatus::Delisted {
        return Err(instruments::InstrumentError::NotTradable {
            instrument_id: fund_id,
            status: fund.status,
        }
        .into());
    }
    let players: HashMap<Uuid, Instrument> =
        instruments::lock_instruments_by_ids(connection, &touched)
            .await?
            .into_iter()
            .map(|player| (player.id, player))
            .collect();
    for member in &members {
        let player = &players[member];
        if player.status == InstrumentStatus::Delisted {
            return Err(IndexFundError::ConstituentNotListed {
                instrument_id: player.id,
                status: player.status,
            }
            .into());
        }
    }

    let units = index_funds::units_outstanding(&mut *connection, fund_id).await?;
    let cash_before = index_funds::cash_per_unit(&mut *connection, fund_id).await?;
    let price_of = |id: Uuid| players[&id].current_price;
    let unit_price_before = index_funds::basket_value(&old_basket, price_of) + cash_before;
    // A member that cannot trade, such as a player halted until their buyout, keeps its shares;
    // the rest of the value is spread evenly over the members that can.
    let old_shares: HashMap<Uuid, Decimal> = old_basket
        .iter()
        .map(|c| (c.instrument_id, c.shares_per_unit))
        .collect();
    let held: BTreeSet<Uuid> = if units.is_zero() {
        BTreeSet::new()
    } else {
        members
            .iter()
            .copied()
            .filter(|id| {
                players[id].status != InstrumentStatus::Active && old_shares.contains_key(id)
            })
            .collect()
    };
    let held_value: Decimal = held.iter().map(|id| old_shares[id] * price_of(*id)).sum();
    let members_value: Decimal = members
        .iter()
        .filter(|id| !held.contains(id))
        .map(|id| price_of(*id))
        .sum();
    let target_shares = if members_value.is_zero() {
        Decimal::ZERO
    } else {
        (unit_price_before - held_value) / members_value
    };

    let plan = if units.is_zero() {
        RebalancePlan::without_trades(&members, target_shares)
    } else {
        plan_trades(
            &old_shares,
            &members,
            &held,
            &players,
            units,
            cash_before,
            target_shares,
        )?
    };
    let new_prices: HashMap<Uuid, Decimal> = plan
        .sells
        .iter()
        .chain(&plan.buys)
        .map(|leg| (leg.instrument.id, leg.quote.new_price))
        .collect();
    let unit_price_after = index_funds::basket_value(&plan.new_basket, |id| {
        new_prices.get(&id).copied().unwrap_or_else(|| price_of(id))
    }) + plan.cash_per_unit;

    let change = BasketChange {
        index_instrument_id: fund_id,
        units_outstanding: units,
        unit_price_before,
        unit_price_after,
        cash_per_unit_after: plan.cash_per_unit,
        old_basket: &old_basket,
        new_basket: &plan.new_basket,
    };
    let rebalance_id = index_funds::record_rebalance(
        connection,
        &command.request_id,
        "REBALANCE",
        command.reason.trim(),
        &change,
    )
    .await?;
    let (added_instrument_ids, removed_instrument_ids) = (change.added(), change.removed());

    // Sales before purchases, so custody's cash never dips below what the units are owed.
    for (side, legs) in [(OrderSide::Sell, &plan.sells), (OrderSide::Buy, &plan.buys)] {
        for leg in legs {
            let request_id = format!("{}:{}", command.request_id, leg.instrument.id);
            let trade = execute_custody_trade(
                connection,
                request_id.clone(),
                side,
                leg,
                TradeCause::Rebalance(rebalance_id),
            )
            .await?;
            match side {
                OrderSide::Sell => {
                    ledger::credit_trade_cash(
                        connection,
                        CUSTODY_ACCOUNT_ID,
                        CUSTODY_PORTFOLIO_ID,
                        trade.id,
                        leg.quote.gross_amount,
                        &request_id,
                    )
                    .await?
                }
                OrderSide::Buy => {
                    ledger::debit_trade_cash(
                        connection,
                        CUSTODY_ACCOUNT_ID,
                        CUSTODY_PORTFOLIO_ID,
                        trade.id,
                        leg.quote.gross_amount,
                        &request_id,
                    )
                    .await?
                }
            };
        }
    }

    index_funds::replace_basket(connection, fund_id, &plan.new_basket, plan.cash_per_unit).await?;
    revalue_index_funds(connection, &funds, None, None).await?;

    Ok(RebalanceIndexFundResult {
        rebalance_id,
        instrument_id: fund_id,
        replayed: false,
        units_outstanding: units,
        unit_price_before,
        unit_price_after,
        cash_per_unit_after: plan.cash_per_unit,
        added_instrument_ids,
        removed_instrument_ids,
        constituents: plan.new_basket,
    })
}

struct RebalancePlan {
    sells: Vec<BasketLeg>,
    buys: Vec<BasketLeg>,
    new_basket: Vec<IndexConstituent>,
    cash_per_unit: Decimal,
}

impl RebalancePlan {
    fn without_trades(members: &BTreeSet<Uuid>, target_shares: Decimal) -> Self {
        let shares = round_shares_down(target_shares).max(Decimal::new(1, SHARES_DECIMAL_PLACES));
        Self {
            sells: Vec::new(),
            buys: Vec::new(),
            new_basket: members
                .iter()
                .map(|id| IndexConstituent {
                    instrument_id: *id,
                    shares_per_unit: shares,
                })
                .collect(),
            cash_per_unit: Decimal::ZERO,
        }
    }
}

fn plan_trades(
    old_shares: &HashMap<Uuid, Decimal>,
    members: &BTreeSet<Uuid>,
    kept: &BTreeSet<Uuid>,
    players: &HashMap<Uuid, Instrument>,
    units: Decimal,
    cash_before: Decimal,
    target_shares: Decimal,
) -> Result<RebalancePlan, ExecutionError> {
    let mut sells = Vec::new();
    let mut wanted_buys = Vec::new();
    let mut ids: Vec<&Uuid> = players.keys().collect();
    ids.sort();
    for id in ids {
        let player = &players[id];
        let held = units * old_shares.get(id).copied().unwrap_or_default();
        let target = if kept.contains(id) {
            held
        } else if members.contains(id) {
            units * target_shares
        } else {
            Decimal::ZERO
        };
        if target < held {
            let quantity = leg_quantity(held - target, PriceImpactDirection::Sell);
            if !quantity.is_zero() {
                sells.push(quote_leg(player, quantity, PriceImpactDirection::Sell)?);
            }
        } else if target > held {
            wanted_buys.push((player, target - held));
        }
    }

    let proceeds: Decimal = sells.iter().map(|leg| leg.quote.gross_amount).sum();
    let budget = units * cash_before + proceeds;
    let buys = fit_buys_to_budget(&wanted_buys, budget)?;
    let spent: Decimal = buys.iter().map(|leg| leg.quote.gross_amount).sum();

    let mut traded: HashMap<Uuid, Decimal> = HashMap::new();
    for leg in &sells {
        *traded.entry(leg.instrument.id).or_default() -= leg.quantity;
    }
    for leg in &buys {
        *traded.entry(leg.instrument.id).or_default() += leg.quantity;
    }
    // Each member's shares per unit are what custody now holds for the fund, rounded down so
    // custody always covers every unit; the fractions left over stay in custody.
    let new_basket = members
        .iter()
        .filter_map(|id| {
            let held = units * old_shares.get(id).copied().unwrap_or_default()
                + traded.get(id).copied().unwrap_or_default();
            let shares_per_unit = round_shares_down(held / units);
            (shares_per_unit > Decimal::ZERO).then_some(IndexConstituent {
                instrument_id: *id,
                shares_per_unit,
            })
        })
        .collect();

    Ok(RebalancePlan {
        sells,
        buys,
        new_basket,
        cash_per_unit: ((budget - spent) / units)
            .round_dp_with_strategy(CASH_DECIMAL_PLACES, RoundingStrategy::ToZero)
            .max(Decimal::ZERO),
    })
}

/// The purchases scaled to the largest fraction of what was wanted that the budget covers.
fn fit_buys_to_budget(
    wanted: &[(&Instrument, Decimal)],
    budget: Decimal,
) -> Result<Vec<BasketLeg>, ExecutionError> {
    let at_scale = |scale: Decimal| -> Result<Option<(Decimal, Vec<BasketLeg>)>, ExecutionError> {
        let mut legs = Vec::with_capacity(wanted.len());
        for (player, shares) in wanted {
            let quantity = leg_quantity(*shares * scale, PriceImpactDirection::Buy);
            if quantity.is_zero() {
                continue;
            }
            match quote_leg(player, quantity, PriceImpactDirection::Buy) {
                Ok(leg) => legs.push(leg),
                // Past the end of a player's curve counts as unaffordable at this scale.
                Err(ExecutionError::PriceImpact(PriceImpactError::BuyExceedsCurveLimit {
                    ..
                })) => return Ok(None),
                Err(error) => return Err(error),
            }
        }
        let cost = legs.iter().map(|leg| leg.quote.gross_amount).sum();
        Ok((cost <= budget).then_some((cost, legs)))
    };

    if let Some((_, legs)) = at_scale(Decimal::ONE)? {
        return Ok(legs);
    }
    let (mut affordable, mut unaffordable) = (Decimal::ZERO, Decimal::ONE);
    for _ in 0..BUY_SCALE_SEARCH_STEPS {
        let middle = (affordable + unaffordable) / Decimal::TWO;
        if at_scale(middle)?.is_some() {
            affordable = middle;
        } else {
            unaffordable = middle;
        }
    }
    Ok(at_scale(affordable)?
        .map(|(_, legs)| legs)
        .unwrap_or_default())
}

fn quote_leg(
    player: &Instrument,
    quantity: Decimal,
    direction: PriceImpactDirection,
) -> Result<BasketLeg, ExecutionError> {
    freezes::assert_not_frozen(player)?;
    instruments::assert_tradable(player)?;
    let quote = price_impact::quote_trade(
        player.reference_price,
        player.curve_depth_shares,
        player.net_shares_purchased,
        player.full_supply_price_multiplier,
        quantity,
        direction,
    )?;
    Ok(BasketLeg {
        instrument: player.clone(),
        quantity,
        quote,
    })
}

fn round_shares_down(shares: Decimal) -> Decimal {
    shares.round_dp_with_strategy(SHARES_DECIMAL_PLACES, RoundingStrategy::ToZero)
}
