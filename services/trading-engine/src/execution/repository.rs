use std::collections::HashMap;

use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use sqlx::{FromRow, PgConnection, PgPool};
use uuid::Uuid;

use crate::{
    fees::TradingFee,
    freezes, idempotency,
    idempotency::IdempotencyClaim,
    index_funds::{self, IndexFundError},
    instruments::{self, IndexFundInstrument, Instrument, InstrumentType, RowLock},
    ledger, orders,
    orders::{ExecuteOrderCommand, Order, OrderSide, QuoteOrderCommand, QuoteSize},
    portfolios, positions, price_impact,
    price_impact::PriceImpactDirection,
    snapshots,
    snapshots::PriceSnapshotReason,
};

use super::{
    error::ExecutionError,
    index_fund::{execute_index_fund_order, load_fund_book, FundBook},
    model::{ExecuteOrderResult, OrderQuote, Trade},
    sizing,
};

/// Quotes an order without placing it. Sized by `cash_amount`, it finds the share count that
/// amount buys, fee included, or the shares to sell to receive it after the fee.
///
/// A quote reads one consistent snapshot and takes no row locks, so quoting never holds up
/// trading. The order placed from it is priced again under locks, and its `cash_limit` refuses
/// the fill if the market moved too far in between.
pub async fn quote_order(
    pool: &PgPool,
    command: impl Into<QuoteOrderCommand>,
    fee: TradingFee,
) -> Result<OrderQuote, ExecutionError> {
    let command = command.into();
    let size = command.size()?;
    let mut transaction = pool.begin().await?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        .execute(&mut *transaction)
        .await?;

    let portfolio = portfolios::get_portfolio_by_id(&mut *transaction, command.portfolio_id)
        .await?
        .ok_or(portfolios::PortfolioError::NotFound(command.portfolio_id))?;
    portfolios::assert_portfolio_belongs_to_account(&portfolio, command.account_id)?;
    let current_position = positions::get_position(
        &mut *transaction,
        command.portfolio_id,
        command.instrument_id,
    )
    .await?
    .map(|position| position.quantity)
    .unwrap_or(Decimal::ZERO);

    let pricer = Pricer::load(&mut transaction, command.instrument_id).await?;
    let quantity = match size {
        QuoteSize::Quantity(quantity) => quantity,
        QuoteSize::CashAmount(cash_amount) => {
            let max_quantity = match command.side {
                OrderSide::Buy => pricer.max_buy_quantity(cash_amount),
                OrderSide::Sell => current_position,
            };
            sizing::quantity_for_cash(command.side, cash_amount, max_quantity, |quantity| {
                let priced = pricer.price(quantity, command.side)?;
                Ok(fee.cash_amount(command.side, priced.gross_amount))
            })?
        }
    };
    let priced = pricer.price(quantity, command.side)?;
    let fee_amount = fee.fee_for(priced.gross_amount);
    let cash_amount = fee.cash_amount(command.side, priced.gross_amount);

    let (cash_balance_after, position_quantity_after) = match command.side {
        OrderSide::Buy => {
            portfolios::assert_has_cash(&portfolio, cash_amount)?;
            (
                portfolio.cash_balance - cash_amount,
                current_position + quantity,
            )
        }
        OrderSide::Sell => {
            positions::assert_has_quantity(
                command.portfolio_id,
                command.instrument_id,
                current_position,
                quantity,
            )?;
            (
                portfolio.cash_balance + cash_amount,
                current_position - quantity,
            )
        }
    };

    transaction.rollback().await?;
    Ok(OrderQuote {
        account_id: command.account_id,
        portfolio_id: command.portfolio_id,
        instrument_id: command.instrument_id,
        side: command.side,
        quantity,
        execution_price: priced.execution_price,
        gross_amount: priced.gross_amount,
        fee_amount,
        cash_amount: Some(cash_amount),
        cash_balance_after,
        position_quantity_after,
        old_price: priced.old_price,
        new_price: priced.new_price,
        quoted_at: Utc::now(),
    })
}

/// What a quote prices against, read without locks.
enum Pricer {
    Player(Instrument),
    Fund(FundBook),
}

/// An order's price, before fees.
struct Priced {
    gross_amount: Decimal,
    execution_price: Decimal,
    old_price: Decimal,
    new_price: Decimal,
}

impl Pricer {
    async fn load(
        connection: &mut PgConnection,
        instrument_id: Uuid,
    ) -> Result<Self, ExecutionError> {
        if instruments::get_instrument_type(&mut *connection, instrument_id).await?
            == InstrumentType::IndexFund
        {
            let book = load_fund_book(connection, instrument_id, RowLock::None).await?;
            return Ok(Self::Fund(book));
        }
        let instrument = instruments::get_instrument_by_id(&mut *connection, instrument_id)
            .await?
            .ok_or(instruments::InstrumentError::NotFound(instrument_id))?;
        freezes::assert_not_frozen(&instrument)?;
        instruments::assert_tradable(&instrument)?;
        Ok(Self::Player(instrument))
    }

    fn price(&self, quantity: Decimal, side: OrderSide) -> Result<Priced, ExecutionError> {
        match self {
            Self::Player(instrument) => {
                let quote = price_impact::quote_trade(
                    instrument.reference_price,
                    instrument.curve_depth_shares,
                    instrument.net_shares_purchased,
                    instrument.full_supply_price_multiplier,
                    quantity,
                    PriceImpactDirection::from(side),
                )?;
                Ok(Priced {
                    gross_amount: quote.gross_amount,
                    execution_price: quote.execution_price,
                    old_price: quote.old_price,
                    new_price: quote.new_price,
                })
            }
            Self::Fund(book) => {
                let basket = book.price(quantity, PriceImpactDirection::from(side))?;
                Ok(Priced {
                    gross_amount: basket.gross_amount,
                    execution_price: basket.execution_price,
                    old_price: basket.unit_price_before,
                    new_price: basket.unit_price_after,
                })
            }
        }
    }

    /// No buy for `cash_amount` can exceed this: buying only raises the price, so the cash
    /// buys fewer shares than at today's price, and a curve ends at its depth.
    fn max_buy_quantity(&self, cash_amount: Decimal) -> Decimal {
        match self {
            Self::Player(instrument) => {
                let at_current_price = cash_amount / instrument.current_price;
                let curve_room = instrument.curve_depth_shares - instrument.net_shares_purchased;
                at_current_price.min(curve_room)
            }
            Self::Fund(book) => {
                let unit_price = book.unit_price();
                if unit_price <= Decimal::ZERO {
                    Decimal::ZERO
                } else {
                    cash_amount / unit_price
                }
            }
        }
    }
}

#[derive(Debug, FromRow)]
struct TradeRow {
    id: Uuid,
    order_id: Uuid,
    account_id: Uuid,
    portfolio_id: Uuid,
    instrument_id: Uuid,
    side: String,
    shares: Decimal,
    execution_price: Decimal,
    gross_amount: Decimal,
    fee_amount: Decimal,
    executed_at: DateTime<Utc>,
    created_at: DateTime<Utc>,
}

pub async fn execute_order(
    pool: &PgPool,
    command: ExecuteOrderCommand,
    fee: TradingFee,
) -> Result<ExecuteOrderResult, ExecutionError> {
    command.validate()?;

    let request_hash = command.request_fingerprint();
    let mut transaction = pool.begin().await?;

    match idempotency::claim_order_execution(&mut transaction, &command.request_id, &request_hash)
        .await?
    {
        IdempotencyClaim::Completed(record) => {
            let result = record.deserialize_response::<ExecuteOrderResult>()?;
            transaction.commit().await?;
            return Ok(result);
        }
        IdempotencyClaim::Claimed(_) => {}
    }

    let result =
        match instruments::get_instrument_type(&mut *transaction, command.instrument_id).await? {
            InstrumentType::PlayerShare => {
                execute_player_share_order(&mut transaction, &command, fee).await?
            }
            InstrumentType::IndexFund => {
                execute_index_fund_order(&mut transaction, &command, fee).await?
            }
        };

    idempotency::complete_order_execution(&mut transaction, &command.request_id, 200, &result)
        .await?;

    transaction.commit().await?;

    Ok(result)
}

async fn execute_player_share_order(
    transaction: &mut PgConnection,
    command: &ExecuteOrderCommand,
    fee: TradingFee,
) -> Result<ExecuteOrderResult, ExecutionError> {
    // Funds holding this player are repriced by the trade, so they are locked first, the
    // order every flow that touches both funds and players follows.
    let fund_ids =
        index_funds::index_ids_containing(&mut *transaction, &[command.instrument_id]).await?;
    let funds = instruments::lock_index_fund_instruments(transaction, &fund_ids).await?;
    let instrument = instruments::lock_instrument_by_id(transaction, command.instrument_id).await?;
    freezes::assert_not_frozen(&instrument)?;
    instruments::assert_tradable(&instrument)?;

    let portfolio = portfolios::lock_portfolio_by_id(transaction, command.portfolio_id).await?;
    portfolios::assert_portfolio_belongs_to_account(&portfolio, command.account_id)?;

    let quote = price_impact::quote_trade(
        instrument.reference_price,
        instrument.curve_depth_shares,
        instrument.net_shares_purchased,
        instrument.full_supply_price_multiplier,
        command.quantity,
        PriceImpactDirection::from(command.side),
    )?;
    if let Some(limits) = &command.execution_limits {
        limits.check(quote.old_price, portfolio.cash_balance, quote.gross_amount)?;
    }
    let execution_price = quote.execution_price;
    let gross_amount = quote.gross_amount;
    let fee_amount = fee.fee_for(gross_amount);
    let cash_amount = fee.cash_amount(command.side, gross_amount);
    command.check_cash_limit(cash_amount)?;

    if command.side == OrderSide::Buy {
        portfolios::assert_has_cash(&portfolio, cash_amount)?;
    } else {
        let current_position =
            positions::lock_position(transaction, command.portfolio_id, command.instrument_id)
                .await?;
        let available = current_position
            .as_ref()
            .map(|position| position.quantity)
            .unwrap_or(Decimal::ZERO);
        positions::assert_has_quantity(
            command.portfolio_id,
            command.instrument_id,
            available,
            command.quantity,
        )?;
    }

    let order = orders::create_pending_order(transaction, command).await?;
    let trade = create_trade(
        transaction,
        &order,
        execution_price,
        gross_amount,
        fee_amount,
        TradeCause::Order,
    )
    .await?;

    let cash_balance_after =
        settle_trade_cash(transaction, command, trade.id, gross_amount, fee_amount).await?;

    let position = match command.side {
        OrderSide::Buy => {
            positions::increase_position(
                transaction,
                command.portfolio_id,
                command.instrument_id,
                command.quantity,
                cash_amount,
            )
            .await?
        }
        OrderSide::Sell => {
            positions::decrease_position(
                transaction,
                command.portfolio_id,
                command.instrument_id,
                command.quantity,
                cash_amount,
            )
            .await?
        }
    };

    instruments::update_market_state(
        transaction,
        command.instrument_id,
        quote.new_price,
        quote.net_shares_purchased_after,
    )
    .await?;

    snapshots::record_price_snapshot(
        transaction,
        command.instrument_id,
        quote.old_price,
        quote.new_price,
        PriceSnapshotReason::from(command.side),
        Some(trade.id),
    )
    .await?;

    revalue_index_funds(transaction, &funds, Some(trade.id), None).await?;

    orders::mark_order_filled(transaction, order.id).await?;

    Ok(ExecuteOrderResult {
        request_id: command.request_id.clone(),
        order_id: order.id,
        trade_id: trade.id,
        account_id: command.account_id,
        portfolio_id: command.portfolio_id,
        instrument_id: command.instrument_id,
        side: command.side,
        quantity: command.quantity,
        execution_price,
        gross_amount,
        fee_amount,
        cash_amount: Some(cash_amount),
        cash_balance_after,
        position_quantity_after: position.quantity,
        old_price: quote.old_price,
        new_price: quote.new_price,
        executed_at: trade.executed_at,
    })
}

/// Moves an order's cash: the buy debit or sell credit at its gross amount, then the fee.
/// A sale is credited before its fee is taken, so a seller with no cash can still pay it.
/// Returns the cash balance after both.
pub(super) async fn settle_trade_cash(
    connection: &mut PgConnection,
    command: &ExecuteOrderCommand,
    trade_id: Uuid,
    gross_amount: Decimal,
    fee_amount: Decimal,
) -> Result<Decimal, ExecutionError> {
    let entry = match command.side {
        OrderSide::Buy => {
            ledger::debit_trade_cash(
                connection,
                command.account_id,
                command.portfolio_id,
                trade_id,
                gross_amount,
                &command.request_id,
            )
            .await?
        }
        OrderSide::Sell => {
            ledger::credit_trade_cash(
                connection,
                command.account_id,
                command.portfolio_id,
                trade_id,
                gross_amount,
                &command.request_id,
            )
            .await?
        }
    };
    let fee_entry = ledger::debit_trade_fee(
        connection,
        command.account_id,
        command.portfolio_id,
        trade_id,
        fee_amount,
        &format!("{}:fee", command.request_id),
    )
    .await?;
    Ok(fee_entry.unwrap_or(entry).balance_after)
}

/// Reprices locked funds to the current value of their baskets after a trade moved one or more
/// constituents. The traded fund itself, if any, records the trade's own snapshot reason.
pub(super) async fn revalue_index_funds(
    connection: &mut PgConnection,
    funds: &[IndexFundInstrument],
    trade_id: Option<Uuid>,
    traded_fund: Option<(Uuid, PriceSnapshotReason)>,
) -> Result<HashMap<Uuid, Decimal>, ExecutionError> {
    if funds.is_empty() {
        return Ok(HashMap::new());
    }
    let fund_ids: Vec<Uuid> = funds.iter().map(|fund| fund.id).collect();
    let unit_prices = index_funds::unit_prices(&mut *connection, &fund_ids).await?;
    for fund in funds {
        let unit_price = *unit_prices
            .get(&fund.id)
            .ok_or(IndexFundError::MissingBasket(fund.id))?;
        let reason = match traded_fund {
            Some((traded_id, reason)) if traded_id == fund.id => reason,
            _ if unit_price == fund.current_price => continue,
            _ => PriceSnapshotReason::IndexRevaluation,
        };
        instruments::update_index_fund_price(connection, fund.id, unit_price).await?;
        snapshots::record_price_snapshot(
            connection,
            fund.id,
            fund.current_price,
            unit_price,
            reason,
            trade_id,
        )
        .await?;
    }
    Ok(unit_prices)
}

/// What caused a custody trade: a fund unit trade or a rebalance.
#[derive(Debug, Clone, Copy)]
pub(super) enum TradeCause {
    Order,
    FundTrade(Uuid),
    Rebalance(Uuid),
}

/// Records a fill, linking a custody trade to the fund trade or rebalance that caused it.
pub(super) async fn create_trade(
    connection: &mut PgConnection,
    order: &Order,
    execution_price: Decimal,
    gross_amount: Decimal,
    fee_amount: Decimal,
    cause: TradeCause,
) -> Result<Trade, ExecutionError> {
    let (index_trade_id, index_rebalance_id) = match cause {
        TradeCause::Order => (None, None),
        TradeCause::FundTrade(id) => (Some(id), None),
        TradeCause::Rebalance(id) => (None, Some(id)),
    };
    let row = sqlx::query_as::<_, TradeRow>(
        r#"
        INSERT INTO trades (
            order_id,
            account_id,
            portfolio_id,
            instrument_id,
            side,
            shares,
            execution_price,
            gross_amount,
            index_trade_id,
            index_rebalance_id,
            fee_amount
        ) VALUES (
            $1,
            $2,
            $3,
            $4,
            $5,
            $6,
            $7,
            $8,
            $9,
            $10,
            $11
        )
        RETURNING
            id,
            order_id,
            account_id,
            portfolio_id,
            instrument_id,
            side,
            shares,
            execution_price,
            gross_amount,
            fee_amount,
            executed_at,
            created_at
        "#,
    )
    .bind(order.id)
    .bind(order.account_id)
    .bind(order.portfolio_id)
    .bind(order.instrument_id)
    .bind(order.side.as_str())
    .bind(order.quantity)
    .bind(execution_price)
    .bind(gross_amount)
    .bind(index_trade_id)
    .bind(index_rebalance_id)
    .bind(fee_amount)
    .fetch_one(&mut *connection)
    .await?;

    Trade::try_from(row)
}

impl From<OrderSide> for PriceImpactDirection {
    fn from(side: OrderSide) -> Self {
        match side {
            OrderSide::Buy => Self::Buy,
            OrderSide::Sell => Self::Sell,
        }
    }
}

impl From<OrderSide> for PriceSnapshotReason {
    fn from(side: OrderSide) -> Self {
        match side {
            OrderSide::Buy => Self::TradeBuy,
            OrderSide::Sell => Self::TradeSell,
        }
    }
}

impl TryFrom<TradeRow> for Trade {
    type Error = ExecutionError;

    fn try_from(row: TradeRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: row.id,
            order_id: row.order_id,
            account_id: row.account_id,
            portfolio_id: row.portfolio_id,
            instrument_id: row.instrument_id,
            side: OrderSide::try_from(row.side)?,
            quantity: row.shares,
            execution_price: row.execution_price,
            gross_amount: row.gross_amount,
            fee_amount: row.fee_amount,
            executed_at: row.executed_at,
            created_at: row.created_at,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn trade_storage_preserves_fractional_execution_precision() {
        let quote = price_impact::quote_trade(
            Decimal::from(100),
            Decimal::from(1_000_000),
            Decimal::ZERO,
            price_impact::DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER,
            Decimal::new(133_001, 3),
            PriceImpactDirection::Buy,
        )
        .unwrap();

        assert!(quote.execution_price.scale() > 4);
        assert!(quote.gross_amount.scale() > 4);
    }
}
