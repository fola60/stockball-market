use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use sqlx::{FromRow, PgConnection, PgPool};
use uuid::Uuid;

use crate::{
    freezes, idempotency,
    idempotency::IdempotencyClaim,
    instruments, ledger, orders,
    orders::{ExecuteOrderCommand, Order, OrderSide},
    portfolios, positions, price_impact,
    price_impact::PriceImpactDirection,
    snapshots,
    snapshots::PriceSnapshotReason,
};

use super::{
    error::ExecutionError,
    model::{ExecuteOrderResult, Trade},
};

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
    executed_at: DateTime<Utc>,
    created_at: DateTime<Utc>,
}

pub async fn execute_order(
    pool: &PgPool,
    command: ExecuteOrderCommand,
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

    let instrument =
        instruments::lock_instrument_by_id(&mut transaction, command.instrument_id).await?;
    freezes::assert_not_frozen(&instrument)?;
    instruments::assert_tradable(&instrument)?;

    let portfolio =
        portfolios::lock_portfolio_by_id(&mut transaction, command.portfolio_id).await?;
    portfolios::assert_portfolio_belongs_to_account(&portfolio, command.account_id)?;

    let execution_price = instrument.current_price;
    let gross_amount = (command.quantity * execution_price).round_dp(4);

    if command.side == OrderSide::Buy {
        portfolios::assert_has_cash(&portfolio, gross_amount)?;
    } else {
        let current_position = positions::lock_position(
            &mut transaction,
            command.portfolio_id,
            command.instrument_id,
        )
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

    let order = orders::create_pending_order(&mut transaction, &command).await?;
    let trade = create_trade(&mut transaction, &order, execution_price, gross_amount).await?;

    let cash_ledger_entry = match command.side {
        OrderSide::Buy => {
            ledger::debit_trade_cash(
                &mut transaction,
                command.account_id,
                command.portfolio_id,
                trade.id,
                gross_amount,
                &command.request_id,
            )
            .await?
        }
        OrderSide::Sell => {
            ledger::credit_trade_cash(
                &mut transaction,
                command.account_id,
                command.portfolio_id,
                trade.id,
                gross_amount,
                &command.request_id,
            )
            .await?
        }
    };

    let position = match command.side {
        OrderSide::Buy => {
            positions::increase_position(
                &mut transaction,
                command.portfolio_id,
                command.instrument_id,
                command.quantity,
            )
            .await?
        }
        OrderSide::Sell => {
            positions::decrease_position(
                &mut transaction,
                command.portfolio_id,
                command.instrument_id,
                command.quantity,
            )
            .await?
        }
    };

    let new_price = price_impact::calculate_next_price(
        instrument.current_price,
        command.quantity,
        instrument.price_impact_unit,
        PriceImpactDirection::from(command.side),
    )?;
    instruments::update_current_price(&mut transaction, command.instrument_id, new_price).await?;

    snapshots::record_price_snapshot(
        &mut transaction,
        command.instrument_id,
        instrument.current_price,
        new_price,
        PriceSnapshotReason::from(command.side),
        Some(trade.id),
    )
    .await?;

    orders::mark_order_filled(&mut transaction, order.id).await?;

    let result = ExecuteOrderResult {
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
        cash_balance_after: cash_ledger_entry.balance_after,
        position_quantity_after: position.quantity,
        old_price: instrument.current_price,
        new_price,
        executed_at: trade.executed_at,
    };

    idempotency::complete_order_execution(&mut transaction, &command.request_id, 200, &result)
        .await?;

    transaction.commit().await?;

    Ok(result)
}

async fn create_trade(
    connection: &mut PgConnection,
    order: &Order,
    execution_price: Decimal,
    gross_amount: Decimal,
) -> Result<Trade, ExecutionError> {
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
            gross_amount
        ) VALUES (
            $1,
            $2,
            $3,
            $4,
            $5,
            $6,
            $7,
            $8
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
            executed_at: row.executed_at,
            created_at: row.created_at,
        })
    }
}
