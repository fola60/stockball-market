//! Index fund orders. One unit holds `shares_per_unit` of each constituent plus the fund's cash
//! per unit, so buying units buys every constituent on its own price curve and pays the cash into
//! custody, and selling units sells them back and pays the cash out. The custody account holds the
//! shares and cash; the trader holds fund units and pays or receives the basket's cost.

use std::collections::HashMap;

use rust_decimal::{Decimal, RoundingStrategy};
use sqlx::PgConnection;
use uuid::Uuid;

use crate::{
    fees::TradingFee,
    freezes,
    index_funds::{
        self, IndexConstituent, IndexFundError, CUSTODY_ACCOUNT_ID, CUSTODY_PORTFOLIO_ID,
    },
    instruments::{self, IndexFundInstrument, Instrument, InstrumentStatus, RowLock},
    ledger,
    orders::{self, ExecuteOrderCommand, OrderSide},
    portfolios, positions, price_impact,
    price_impact::{PriceImpactDirection, PriceImpactQuote},
    snapshots::{self, PriceSnapshotReason},
};

use super::{
    error::ExecutionError,
    model::{ExecuteOrderResult, Trade},
    repository::{create_trade, revalue_index_funds, settle_trade_cash, TradeCause},
};

const STORED_PRICE_DECIMAL_PLACES: u32 = 12;
const QUANTITY_DECIMAL_PLACES: u32 = 6;

pub(super) struct BasketLeg {
    pub instrument: Instrument,
    pub quantity: Decimal,
    pub quote: PriceImpactQuote,
}

/// Everything a fund order is priced from: the funds sharing its constituents, the
/// constituents' curves, and the fund's cash per unit. An order loads it with every row locked;
/// a quote reads it without locks.
pub(super) struct FundBook {
    /// Every fund holding any constituent, including the traded fund.
    pub funds: Vec<IndexFundInstrument>,
    constituents: Vec<IndexConstituent>,
    players: HashMap<Uuid, Instrument>,
    cash_per_unit: Decimal,
}

/// A fund order priced against its constituents' curves.
pub(super) struct PricedBasket {
    pub legs: Vec<BasketLeg>,
    /// The fund's cash behind the traded units, paid into or out of custody.
    pub cash_amount: Decimal,
    pub gross_amount: Decimal,
    pub execution_price: Decimal,
    pub unit_price_before: Decimal,
    pub unit_price_after: Decimal,
}

/// Loads a fund's book. With `RowLock::ForUpdate` it locks the funds sharing any of this fund's
/// constituents, then the constituents, each group in id order: player-share orders lock the
/// same way, funds first.
pub(super) async fn load_fund_book(
    connection: &mut PgConnection,
    fund_id: Uuid,
    lock: RowLock,
) -> Result<FundBook, ExecutionError> {
    let constituents = index_funds::load_constituents(&mut *connection, fund_id).await?;
    if constituents.is_empty() {
        return Err(IndexFundError::MissingBasket(fund_id).into());
    }
    let constituent_ids: Vec<Uuid> = constituents.iter().map(|c| c.instrument_id).collect();
    let mut fund_ids =
        index_funds::index_ids_containing(&mut *connection, &constituent_ids).await?;
    fund_ids.push(fund_id);
    let funds = instruments::select_index_fund_instruments(connection, &fund_ids, lock).await?;
    let fund = funds
        .iter()
        .find(|fund| fund.id == fund_id)
        .ok_or(instruments::InstrumentError::NotFound(fund_id))?;
    assert_fund_tradable(fund)?;

    let players = match lock {
        RowLock::ForUpdate => {
            instruments::lock_instruments_by_ids(connection, &constituent_ids).await?
        }
        RowLock::None => instruments::get_instruments_by_ids(connection, &constituent_ids).await?,
    };
    let cash_per_unit = index_funds::cash_per_unit(&mut *connection, fund_id).await?;

    Ok(FundBook {
        funds,
        constituents,
        players: players.into_iter().map(|p| (p.id, p)).collect(),
        cash_per_unit,
    })
}

impl FundBook {
    /// The fund's current unit price: its basket at current prices plus its cash.
    pub fn unit_price(&self) -> Decimal {
        index_funds::basket_value(&self.constituents, |id| {
            self.players
                .get(&id)
                .map(|player| player.current_price)
                .unwrap_or_default()
        }) + self.cash_per_unit
    }

    /// Quotes every leg of an order for `units`.
    pub fn price(
        &self,
        units: Decimal,
        direction: PriceImpactDirection,
    ) -> Result<PricedBasket, ExecutionError> {
        let legs = basket_legs(&self.constituents, &self.players, units, direction)?;
        let cash_amount = (self.cash_per_unit * units).round_dp(STORED_PRICE_DECIMAL_PLACES);
        let gross_amount = legs
            .iter()
            .map(|leg| leg.quote.gross_amount)
            .sum::<Decimal>()
            + cash_amount;
        let new_prices: HashMap<Uuid, Decimal> = legs
            .iter()
            .map(|leg| (leg.instrument.id, leg.quote.new_price))
            .collect();

        Ok(PricedBasket {
            legs,
            cash_amount,
            gross_amount,
            execution_price: (gross_amount / units).round_dp(STORED_PRICE_DECIMAL_PLACES),
            unit_price_before: self.unit_price(),
            unit_price_after: index_funds::basket_value(&self.constituents, |id| {
                new_prices.get(&id).copied().unwrap_or_else(|| {
                    self.players
                        .get(&id)
                        .map(|player| player.current_price)
                        .unwrap_or_default()
                })
            }) + self.cash_per_unit,
        })
    }
}

pub(super) fn assert_fund_tradable(fund: &IndexFundInstrument) -> Result<(), ExecutionError> {
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
///
/// Buys round each leg up and sales round it down, so custody always holds at least the shares
/// behind every unit in issue; the leftover fractions stay in custody.
fn basket_legs(
    constituents: &[IndexConstituent],
    players: &HashMap<Uuid, Instrument>,
    units: Decimal,
    direction: PriceImpactDirection,
) -> Result<Vec<BasketLeg>, ExecutionError> {
    constituents
        .iter()
        .map(|constituent| {
            let instrument = players.get(&constituent.instrument_id).cloned().ok_or(
                instruments::InstrumentError::NotFound(constituent.instrument_id),
            )?;
            freezes::assert_not_frozen(&instrument)?;
            instruments::assert_tradable(&instrument)?;
            let quantity = leg_quantity(constituent.shares_per_unit * units, direction);
            if quantity.is_zero() {
                return Ok(None);
            }
            let quote = price_impact::quote_trade(
                instrument.reference_price,
                instrument.curve_depth_shares,
                instrument.net_shares_purchased,
                instrument.full_supply_price_multiplier,
                quantity,
                direction,
            )?;
            Ok(Some(BasketLeg {
                instrument,
                quantity,
                quote,
            }))
        })
        .filter_map(Result::transpose)
        .collect()
}

/// Shares of one constituent traded for an order, rounded toward custody keeping a surplus.
pub(super) fn leg_quantity(shares: Decimal, direction: PriceImpactDirection) -> Decimal {
    let strategy = match direction {
        PriceImpactDirection::Buy => RoundingStrategy::AwayFromZero,
        PriceImpactDirection::Sell => RoundingStrategy::ToZero,
    };
    shares.round_dp_with_strategy(QUANTITY_DECIMAL_PLACES, strategy)
}

pub(super) async fn execute_index_fund_order(
    connection: &mut PgConnection,
    command: &ExecuteOrderCommand,
    fee: TradingFee,
) -> Result<ExecuteOrderResult, ExecutionError> {
    let book = load_fund_book(connection, command.instrument_id, RowLock::ForUpdate).await?;
    let basket = book.price(command.quantity, PriceImpactDirection::from(command.side))?;
    let portfolio = portfolios::lock_portfolio_by_id(connection, command.portfolio_id).await?;
    portfolios::assert_portfolio_belongs_to_account(&portfolio, command.account_id)?;
    if let Some(limits) = &command.execution_limits {
        limits.check(
            basket.unit_price_before,
            portfolio.cash_balance,
            basket.gross_amount,
        )?;
    }
    let fee_amount = fee.fee_for(basket.gross_amount);
    let cash_amount = fee.cash_amount(command.side, basket.gross_amount);
    command.check_cash_limit(cash_amount)?;

    if command.side == OrderSide::Buy {
        portfolios::assert_has_cash(&portfolio, cash_amount)?;
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
        fee_amount,
        TradeCause::Order,
    )
    .await?;

    let cash_balance_after = settle_trade_cash(
        connection,
        command,
        trade.id,
        basket.gross_amount,
        fee_amount,
    )
    .await?;
    let position = match command.side {
        OrderSide::Buy => {
            positions::increase_position(
                connection,
                command.portfolio_id,
                command.instrument_id,
                command.quantity,
                cash_amount,
            )
            .await?
        }
        OrderSide::Sell => {
            positions::decrease_position(
                connection,
                command.portfolio_id,
                command.instrument_id,
                command.quantity,
                cash_amount,
            )
            .await?
        }
    };

    if !basket.cash_amount.is_zero() {
        let delta = match command.side {
            OrderSide::Buy => basket.cash_amount,
            OrderSide::Sell => -basket.cash_amount,
        };
        ledger::move_index_fund_cash(
            connection,
            CUSTODY_ACCOUNT_ID,
            CUSTODY_PORTFOLIO_ID,
            trade.id,
            delta,
            &format!("{}:custody-cash", command.request_id),
        )
        .await?;
    }
    for leg in &basket.legs {
        execute_custody_trade(
            connection,
            format!("{}:{}", command.request_id, leg.instrument.id),
            command.side,
            leg,
            TradeCause::FundTrade(trade.id),
        )
        .await?;
    }

    let reason = PriceSnapshotReason::from(command.side);
    let unit_prices = revalue_index_funds(
        connection,
        &book.funds,
        Some(trade.id),
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
        fee_amount,
        cash_amount: Some(cash_amount),
        cash_balance_after,
        position_quantity_after: position.quantity,
        old_price: basket.unit_price_before,
        new_price: unit_prices
            .get(&command.instrument_id)
            .copied()
            .unwrap_or(basket.unit_price_after),
        executed_at: trade.executed_at,
    })
}

/// Records the custody account's trade in one constituent: order, trade, position change,
/// price move, and snapshot. Cash is the caller's: a unit trade moves it between the trader and
/// the market, a rebalance through custody's own ledger.
pub(super) async fn execute_custody_trade(
    connection: &mut PgConnection,
    request_id: String,
    side: OrderSide,
    leg: &BasketLeg,
    cause: TradeCause,
) -> Result<Trade, ExecutionError> {
    let leg_command = ExecuteOrderCommand {
        execution_limits: None,
        cash_limit: None,
        request_id,
        account_id: CUSTODY_ACCOUNT_ID,
        portfolio_id: CUSTODY_PORTFOLIO_ID,
        instrument_id: leg.instrument.id,
        side,
        quantity: leg.quantity,
    };
    let order = orders::create_pending_order(connection, &leg_command).await?;
    let trade = create_trade(
        connection,
        &order,
        leg.quote.execution_price,
        leg.quote.gross_amount,
        Decimal::ZERO,
        cause,
    )
    .await?;
    match side {
        OrderSide::Buy => {
            positions::increase_position(
                connection,
                CUSTODY_PORTFOLIO_ID,
                leg.instrument.id,
                leg.quantity,
                leg.quote.gross_amount,
            )
            .await?
        }
        OrderSide::Sell => {
            positions::decrease_position(
                connection,
                CUSTODY_PORTFOLIO_ID,
                leg.instrument.id,
                leg.quantity,
                leg.quote.gross_amount,
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
        PriceSnapshotReason::from(side),
        Some(trade.id),
    )
    .await?;
    orders::mark_order_filled(connection, order.id).await?;
    Ok(trade)
}
