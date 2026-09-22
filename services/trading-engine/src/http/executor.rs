use async_trait::async_trait;
use sqlx::PgPool;

use crate::{
    execution::{self, ExecuteOrderResult, ExecutionError, OrderQuote},
    instruments::{self, InstrumentError, SeedPlayerSharesResult},
    ledger::CashLedgerEntry,
    orders::ExecuteOrderCommand,
    topups::{self, ApplyTopupCommand, TopupError},
};

#[async_trait]
pub trait OrderExecutor: Clone + Send + Sync + 'static {
    async fn execute_order(
        &self,
        command: ExecuteOrderCommand,
    ) -> Result<ExecuteOrderResult, ExecutionError>;

    async fn quote_order(&self, command: ExecuteOrderCommand)
        -> Result<OrderQuote, ExecutionError>;

    async fn seed_player_shares(&self) -> Result<SeedPlayerSharesResult, InstrumentError>;

    async fn apply_topup(&self, command: ApplyTopupCommand) -> Result<CashLedgerEntry, TopupError>;
}

#[derive(Debug, Clone)]
pub struct SqlOrderExecutor {
    pool: PgPool,
}

impl SqlOrderExecutor {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

#[async_trait]
impl OrderExecutor for SqlOrderExecutor {
    async fn quote_order(
        &self,
        command: ExecuteOrderCommand,
    ) -> Result<OrderQuote, ExecutionError> {
        execution::quote_order(&self.pool, command).await
    }

    async fn execute_order(
        &self,
        command: ExecuteOrderCommand,
    ) -> Result<ExecuteOrderResult, ExecutionError> {
        execution::execute_order(&self.pool, command).await
    }

    async fn seed_player_shares(&self) -> Result<SeedPlayerSharesResult, InstrumentError> {
        instruments::seed_player_shares(&self.pool).await
    }

    async fn apply_topup(&self, command: ApplyTopupCommand) -> Result<CashLedgerEntry, TopupError> {
        topups::apply_topup(&self.pool, command).await
    }
}
