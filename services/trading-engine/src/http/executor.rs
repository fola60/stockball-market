use async_trait::async_trait;
use sqlx::PgPool;

use crate::{
    execution::{self, ExecuteOrderResult, ExecutionError, OrderQuote},
    freezes::{
        self, ApplyFreezeCommand, ApplyFreezeResult, FreezeError, ReleaseFreezeCommand,
        ReleaseFreezeResult,
    },
    instruments::{self, InstrumentError, SeedPlayerSharesResult},
    ledger::CashLedgerEntry,
    orders::ExecuteOrderCommand,
    price_impact::CurveCalibration,
    provisioning::{
        self, ApplyOpeningBalanceCommand, IssueInitialSupplyCommand, IssueInitialSupplyResult,
        PreMarketPriceResult, ProvisioningError, RecalibratePriceCurvesCommand,
        RecalibratePriceCurvesResult, SetPreMarketPriceCommand,
    },
    topups::{self, ApplyTopupCommand, TopupError},
};

// async-trait generates must-use futures for these Result-returning methods. Rust 1.99's
// double_must_use lint sees both layers, even though the source methods have no such attribute.
#[allow(clippy::double_must_use)]
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

    async fn apply_opening_balance(
        &self,
        command: ApplyOpeningBalanceCommand,
    ) -> Result<CashLedgerEntry, ProvisioningError>;

    async fn issue_initial_supply(
        &self,
        command: IssueInitialSupplyCommand,
    ) -> Result<IssueInitialSupplyResult, ProvisioningError>;

    async fn set_pre_market_price(
        &self,
        command: SetPreMarketPriceCommand,
    ) -> Result<PreMarketPriceResult, ProvisioningError>;

    async fn recalibrate_price_curves(
        &self,
        command: RecalibratePriceCurvesCommand,
    ) -> Result<RecalibratePriceCurvesResult, ProvisioningError>;

    async fn apply_freeze(
        &self,
        command: ApplyFreezeCommand,
    ) -> Result<ApplyFreezeResult, FreezeError>;

    async fn release_freeze(
        &self,
        command: ReleaseFreezeCommand,
    ) -> Result<ReleaseFreezeResult, FreezeError>;
}

#[derive(Debug, Clone)]
pub struct SqlOrderExecutor {
    pool: PgPool,
    // The curve newly seeded players start on.
    seed_curve: CurveCalibration,
}

impl SqlOrderExecutor {
    pub fn new(pool: PgPool) -> Self {
        Self {
            pool,
            seed_curve: CurveCalibration::default(),
        }
    }

    pub fn with_seed_curve(mut self, seed_curve: CurveCalibration) -> Self {
        self.seed_curve = seed_curve;
        self
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
        instruments::seed_player_shares(&self.pool, self.seed_curve).await
    }

    async fn apply_topup(&self, command: ApplyTopupCommand) -> Result<CashLedgerEntry, TopupError> {
        topups::apply_topup(&self.pool, command).await
    }

    async fn apply_opening_balance(
        &self,
        command: ApplyOpeningBalanceCommand,
    ) -> Result<CashLedgerEntry, ProvisioningError> {
        provisioning::apply_opening_balance(&self.pool, command).await
    }

    async fn issue_initial_supply(
        &self,
        command: IssueInitialSupplyCommand,
    ) -> Result<IssueInitialSupplyResult, ProvisioningError> {
        provisioning::issue_initial_supply(&self.pool, command).await
    }

    async fn set_pre_market_price(
        &self,
        command: SetPreMarketPriceCommand,
    ) -> Result<PreMarketPriceResult, ProvisioningError> {
        provisioning::set_pre_market_price(&self.pool, command).await
    }

    async fn recalibrate_price_curves(
        &self,
        command: RecalibratePriceCurvesCommand,
    ) -> Result<RecalibratePriceCurvesResult, ProvisioningError> {
        provisioning::recalibrate_price_curves(&self.pool, command).await
    }

    async fn apply_freeze(
        &self,
        command: ApplyFreezeCommand,
    ) -> Result<ApplyFreezeResult, FreezeError> {
        freezes::apply_freeze(&self.pool, command).await
    }

    async fn release_freeze(
        &self,
        command: ReleaseFreezeCommand,
    ) -> Result<ReleaseFreezeResult, FreezeError> {
        freezes::release_freeze(&self.pool, command).await
    }
}
