use async_trait::async_trait;
use sqlx::PgPool;

use crate::{
    execution::{self, ExecuteOrderResult, ExecutionError},
    orders::ExecuteOrderCommand,
};

#[async_trait]
pub trait OrderExecutor: Clone + Send + Sync + 'static {
    async fn execute_order(
        &self,
        command: ExecuteOrderCommand,
    ) -> Result<ExecuteOrderResult, ExecutionError>;
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
    async fn execute_order(
        &self,
        command: ExecuteOrderCommand,
    ) -> Result<ExecuteOrderResult, ExecutionError> {
        execution::execute_order(&self.pool, command).await
    }
}
