//! Index fund orders. One unit holds `shares_per_unit` of each constituent, so buying units buys
//! every constituent on its own price curve and selling units sells them back. The custody
//! account holds the shares; the trader holds fund units and pays or receives the basket's cost.

use std::collections::HashMap;

use chrono::Utc;
use rust_decimal::Decimal;
use sqlx::PgConnection;
use uuid::Uuid;

use crate::{
    freezes,
    index_funds::{
        self, IndexConstituent, IndexFundError, CUSTODY_ACCOUNT_ID, CUSTODY_PORTFOLIO_ID,
    },
    instruments::{self, IndexFundInstrument, Instrument, InstrumentStatus},
    ledger,
    orders::{self, ExecuteOrderCommand, OrderSide},
    portfolios, positions, price_impact,
    price_impact::{PriceImpactDirection, PriceImpactQuote},
    snapshots::{self, PriceSnapshotReason},
};

use super::{
    error::ExecutionError,
    model::{ExecuteOrderResult, OrderQuote},
    repository::{create_trade, revalue_index_funds},
};

const STORED_PRICE_DECIMAL_PLACES: u32 = 12;

struct BasketLeg {
    instrument: Instrument,
    quantity: Decimal,
    quote: PriceImpactQuote,
}

/// A fund order priced against its constituents' curves, with every row it touches locked.
struct PricedBasket {
    /// Every fund holding any constituent, including the traded fund, all locked.
    funds: Vec<IndexFundInstrument>,
    legs: Vec<BasketLeg>,
    gross_amount: Decimal,
    execution_price: Decimal,
    unit_price_before: Decimal,
    unit_price_after: Decimal,
}

/// Locks the funds sharing any of this fund's constituents, then the constituents, each group
/// in id order, and quotes every leg. Player-share orders lock the same way, funds first.
async fn price_basket(
    connection: &mut PgConnection,
    command: &ExecuteOrderCommand,
) -> Result<PricedBasket, ExecutionError> {
    let constituents =
        index_funds::load_constituents(&mut *connection, command.instrument_id).await?;
    if constituents.is_empty() {
        return Err(IndexFundError::MissingBasket(command.instrument_id).into());
    }
    let constituent_ids: Vec<Uuid> = constituents.iter().map(|c| c.instrument_id).collect();
    let mut fund_ids =
        index_funds::index_ids_containing(&mut *connection, &constituent_ids).await?;
    fund_ids.push(command.instrument_id);
    let funds = instruments::lock_index_fund_instruments(connection, &fund_ids).await?;
    let fund = funds
        .iter()
        .find(|fund| fund.id == command.instrument_id)
        .ok_or(instruments::InstrumentError::NotFound(
            command.instrument_id,
        ))?;
    assert_fund_tradable(fund)?;

    let players = instruments::lock_instruments_by_ids(connection, &constituent_ids).await?;
    let direction = PriceImpactDirection::from(command.side);
    let legs = basket_legs(&constituents, players, command.quantity, direction)?;

    let gross_amount = legs
        .iter()
        .map(|leg| leg.quote.gross_amount)
        .sum::<Decimal>();
    let old_prices: HashMap<Uuid, Decimal> = legs
        .iter()
        .map(|leg| (leg.instrument.id, leg.instrument.current_price))
        .collect();
    let new_prices: HashMap<Uuid, Decimal> = legs
        .iter()
        .map(|leg| (leg.instrument.id, leg.quote.new_price))
        .collect();

    Ok(PricedBasket {
        funds,
        legs,
        gross_amount,
        execution_price: (gross_amount / command.quantity).round_dp(STORED_PRICE_DECIMAL_PLACES),
        unit_price_before: index_funds::basket_value(&constituents, |id| old_prices[&id]),
        unit_price_after: index_funds::basket_value(&constituents, |id| new_prices[&id]),
    })
}

fn assert_fund_tradable(fund: &IndexFundInstrument) -> Result<(), ExecutionError> {
    match fund.status {
        InstrumentStatus::Active => Ok(()),
        InstrumentStatus::Frozen => Err(freezes::FreezeError::Frozen {
            instrument_id: fund.id,
        }
        .into()),
        status => Err(instruments::InstrumentError::NotTradable {
            instrument_id: fund.id,
            status,
        }
        .into()),
    }
}

/// Quotes each constituent's share of the order. A fund trades only while every constituent
/// does, so a match-day freeze on one club's players pauses that club's fund.
fn basket_legs(
    constituents: &[IndexConstituent],
    players: Vec<Instrument>,
    units: Decimal,
    direction: PriceImpactDirection,
) -> Result<Vec<BasketLeg>, ExecutionError> {
    let mut players: HashMap<Uuid, Instrument> = players.into_iter().map(|p| (p.id, p)).collect();
    constituents
        .iter()
        .map(|constituent| {
            let instrument = players.remove(&constituent.instrument_id).ok_or(
                instruments::InstrumentError::NotFound(constituent.instrument_id),
            )?;
            freezes::assert_not_frozen(&instrument)?;
            instruments::assert_tradable(&instrument)?;
            let quantity = (constituent.shares_per_unit * units).round_dp(6);
            let quote = price_impact::quote_trade(
                instrument.reference_price,
                instrument.curve_depth_shares,
                instrument.net_shares_purchased,
                instrument.full_supply_price_multiplier,
                quantity,
                direction,
            )?;
            Ok(BasketLeg {
                instrument,
                quantity,
                quote,
            })
        })
        .collect()
}

pub(super) async fn quote_index_fund_order(
    connection: &mut PgConnection,
    command: &ExecuteOrderCommand,
) -> Result<OrderQuote, ExecutionError> {
    let basket = price_basket(connection, command).await?;
    let portfolio = portfolios::lock_portfolio_by_id(connection, command.portfolio_id).await?;
    portfolios::assert_portfolio_belongs_to_account(&portfolio, command.account_id)?;
    let current_position = positions::get_position(
        &mut *connection,
        command.portfolio_id,
        command.instrument_id,
    )
    .await?
    .map(|position| position.quantity)
    .unwrap_or(Decimal::ZERO);

    let (cash_balance_after, position_quantity_after) = match command.side {
        OrderSide::Buy => {
            portfolios::assert_has_cash(&portfolio, basket.gross_amount)?;
            (
                portfolio.cash_balance - basket.gross_amount,
                current_position + command.quantity,
            )
        }
        OrderSide::Sell => {
            positions::assert_has_quantity(
                command.portfolio_id,
                command.instrument_id,
                current_position,
                command.quantity,
            )?;
            (
                portfolio.cash_balance + basket.gross_amount,
                current_position - command.quantity,
            )
        }
    };

    Ok(OrderQuote {
        account_id: command.account_id,
        portfolio_id: command.portfolio_id,
        instrument_id: command.instrument_id,
        side: command.side,
        quantity: command.quantity,
        execution_price: basket.execution_price,
        gross_amount: basket.gross_amount,
        cash_balance_after,
        position_quantity_after,
        old_price: basket.unit_price_before,
        new_price: basket.unit_price_after,
        quoted_at: Utc::now(),
    })
}

pub(super) async fn execute_index_fund_order(
    connection: &mut PgConnection,
    command: &ExecuteOrderCommand,
) -> Result<ExecuteOrderResult, ExecutionError> {
    let basket = price_basket(connection, command).await?;
    let portfolio = portfolios::lock_portfolio_by_id(connection, command.portfolio_id).await?;
    portfolios::assert_portfolio_belongs_to_account(&portfolio, command.account_id)?;
    if let Some(limits) = &command.execution_limits {
        limits.check(
            basket.unit_price_before,
            portfolio.cash_balance,
            basket.gross_amount,
        )?;
    }

    if command.side == OrderSide::Buy {
        portfolios::assert_has_cash(&portfolio, basket.gross_amount)?;
    } else {
        let available =
            positions::lock_position(connection, command.portfolio_id, command.instrument_id)
                .await?
                .map(|position| position.quantity)
                .unwrap_or(Decimal::ZERO);
        positions::assert_has_quantity(
            command.portfolio_id,
            command.instrument_id,
            available,
            command.quantity,
        )?;
    }

    let order = orders::create_pending_order(connection, command).await?;
    let trade = create_trade(
        connection,
        &order,
        basket.execution_price,
        basket.gross_amount,
        None,
    )
    .await?;

    let cash_ledger_entry = match command.side {
        OrderSide::Buy => {
            ledger::debit_trade_cash(
                connection,
                command.account_id,
                command.portfolio_id,
                trade.id,
                basket.gross_amount,
                &command.request_id,
            )
            .await?
        }
        OrderSide::Sell => {
            ledger::credit_trade_cash(
                connection,
                command.account_id,
                command.portfolio_id,
                trade.id,
                basket.gross_amount,
                &command.request_id,
            )
            .await?
        }
    };
    let position = match command.side {
        OrderSide::Buy => {
            positions::increase_position(
                connection,
                command.portfolio_id,
                command.instrument_id,
                command.quantity,
            )
            .await?
        }
        OrderSide::Sell => {
            positions::decrease_position(
                connection,
                command.portfolio_id,
                command.instrument_id,
                command.quantity,
            )
            .await?
        }
    };

    for leg in &basket.legs {
        execute_custody_leg(connection, command, trade.id, leg).await?;
    }

    let reason = PriceSnapshotReason::from(command.side);
    let unit_prices = revalue_index_funds(
        connection,
        &basket.funds,
        trade.id,
        Some((command.instrument_id, reason)),
    )
    .await?;
    orders::mark_order_filled(connection, order.id).await?;

    Ok(ExecuteOrderResult {
        request_id: command.request_id.clone(),
        order_id: order.id,
        trade_id: trade.id,
        account_id: command.account_id,
        portfolio_id: command.portfolio_id,
        instrument_id: command.instrument_id,
        side: command.side,
        quantity: command.quantity,
        execution_price: basket.execution_price,
        gross_amount: basket.gross_amount,
        cash_balance_after: cash_ledger_entry.balance_after,
        position_quantity_after: position.quantity,
        old_price: basket.unit_price_before,
        new_price: unit_prices
            .get(&command.instrument_id)
            .copied()
            .unwrap_or(basket.unit_price_after),
        executed_at: trade.executed_at,
    })
}

/// Records the custody account's trade in one constituent. Cash moves only between the trader
/// and the market, so the leg has an order, trade, position change, and price move, but no
/// ledger entry of its own.
async fn execute_custody_leg(
    connection: &mut PgConnection,
    command: &ExecuteOrderCommand,
    fund_trade_id: Uuid,
    leg: &BasketLeg,
) -> Result<(), ExecutionError> {
    let leg_command = ExecuteOrderCommand {
        execution_limits: None,
        request_id: format!("{}:{}", command.request_id, leg.instrument.id),
        account_id: CUSTODY_ACCOUNT_ID,
        portfolio_id: CUSTODY_PORTFOLIO_ID,
        instrument_id: leg.instrument.id,
        side: command.side,
        quantity: leg.quantity,
    };
    let order = orders::create_pending_order(connection, &leg_command).await?;
    let trade = create_trade(
        connection,
        &order,
        leg.quote.execution_price,
        leg.quote.gross_amount,
        Some(fund_trade_id),
    )
    .await?;
    match command.side {
        OrderSide::Buy => {
            positions::increase_position(
                connection,
                CUSTODY_PORTFOLIO_ID,
                leg.instrument.id,
                leg.quantity,
            )
            .await?
        }
        OrderSide::Sell => {
            positions::decrease_position(
                connection,
                CUSTODY_PORTFOLIO_ID,
                leg.instrument.id,
                leg.quantity,
            )
            .await?
        }
    };
    instruments::update_market_state(
        connection,
        leg.instrument.id,
        leg.quote.new_price,
        leg.quote.net_shares_purchased_after,
    )
    .await?;
    snapshots::record_price_snapshot(
        connection,
        leg.instrument.id,
        leg.quote.old_price,
        leg.quote.new_price,
        PriceSnapshotReason::from(command.side),
        Some(trade.id),
    )
    .await?;
    orders::mark_order_filled(connection, order.id).await?;
    Ok(())
}
