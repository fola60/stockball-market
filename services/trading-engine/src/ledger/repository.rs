use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use sqlx::{FromRow, PgConnection};
use uuid::Uuid;

use super::{
    error::LedgerError,
    model::{CashLedgerEntry, LedgerReason},
};

#[derive(Debug, FromRow)]
struct CashLedgerEntryRow {
    id: Uuid,
    account_id: Uuid,
    portfolio_id: Uuid,
    trade_id: Option<Uuid>,
    reason: String,
    amount_delta: Decimal,
    balance_after: Decimal,
    source_request_id: Option<String>,
    created_at: DateTime<Utc>,
}

#[derive(Debug, FromRow)]
struct PortfolioCashRow {
    account_id: Uuid,
    cash_balance: Decimal,
}

struct NewCashLedgerEntry<'a> {
    account_id: Uuid,
    portfolio_id: Uuid,
    trade_id: Option<Uuid>,
    reason: LedgerReason,
    amount_delta: Decimal,
    balance_after: Decimal,
    source_request_id: Option<&'a str>,
}

pub async fn debit_trade_cash(
    connection: &mut PgConnection,
    account_id: Uuid,
    portfolio_id: Uuid,
    trade_id: Uuid,
    amount: Decimal,
    source_request_id: &str,
) -> Result<CashLedgerEntry, LedgerError> {
    apply_cash_movement(
        connection,
        account_id,
        portfolio_id,
        Some(trade_id),
        LedgerReason::TradeBuyDebit,
        -ensure_positive_amount(amount)?,
        Some(source_request_id),
    )
    .await
}

pub async fn credit_trade_cash(
    connection: &mut PgConnection,
    account_id: Uuid,
    portfolio_id: Uuid,
    trade_id: Uuid,
    amount: Decimal,
    source_request_id: &str,
) -> Result<CashLedgerEntry, LedgerError> {
    apply_cash_movement(
        connection,
        account_id,
        portfolio_id,
        Some(trade_id),
        LedgerReason::TradeSellCredit,
        ensure_positive_amount(amount)?,
        Some(source_request_id),
    )
    .await
}

/// Credits a portfolio's one-time opening balance. A portfolio can receive at most one.
pub async fn credit_opening_balance(
    connection: &mut PgConnection,
    account_id: Uuid,
    portfolio_id: Uuid,
    amount: Decimal,
    source_request_id: &str,
) -> Result<CashLedgerEntry, LedgerError> {
    let already_credited = sqlx::query_scalar::<_, bool>(
        r#"
        SELECT EXISTS (
            SELECT 1
            FROM cash_ledger_entries
            WHERE portfolio_id = $1
              AND reason = 'OPENING_BALANCE'
        )
        "#,
    )
    .bind(portfolio_id)
    .fetch_one(&mut *connection)
    .await?;
    if already_credited {
        return Err(LedgerError::OpeningBalanceAlreadyApplied(portfolio_id));
    }

    apply_cash_movement(
        connection,
        account_id,
        portfolio_id,
        None,
        LedgerReason::OpeningBalance,
        ensure_positive_amount(amount)?,
        Some(source_request_id),
    )
    .await
}

pub async fn credit_weekly_topup(
    connection: &mut PgConnection,
    account_id: Uuid,
    portfolio_id: Uuid,
    amount: Decimal,
    source_request_id: &str,
) -> Result<CashLedgerEntry, LedgerError> {
    apply_cash_movement(
        connection,
        account_id,
        portfolio_id,
        None,
        LedgerReason::WeeklyTopup,
        ensure_positive_amount(amount)?,
        Some(source_request_id),
    )
    .await
}

pub async fn credit_monthly_topup(
    connection: &mut PgConnection,
    account_id: Uuid,
    portfolio_id: Uuid,
    amount: Decimal,
    source_request_id: &str,
) -> Result<CashLedgerEntry, LedgerError> {
    apply_cash_movement(
        connection,
        account_id,
        portfolio_id,
        None,
        LedgerReason::MonthlyTopup,
        ensure_positive_amount(amount)?,
        Some(source_request_id),
    )
    .await
}

async fn apply_cash_movement(
    connection: &mut PgConnection,
    account_id: Uuid,
    portfolio_id: Uuid,
    trade_id: Option<Uuid>,
    reason: LedgerReason,
    amount_delta: Decimal,
    source_request_id: Option<&str>,
) -> Result<CashLedgerEntry, LedgerError> {
    if amount_delta == Decimal::ZERO {
        return Err(LedgerError::NonPositiveAmount(amount_delta));
    }

    let balance_after =
        update_portfolio_cash_balance(&mut *connection, account_id, portfolio_id, amount_delta)
            .await?;

    insert_ledger_entry(
        &mut *connection,
        new_cash_ledger_entry(
            account_id,
            portfolio_id,
            trade_id,
            reason,
            amount_delta,
            balance_after,
            source_request_id,
        ),
    )
    .await
}

async fn update_portfolio_cash_balance(
    connection: &mut PgConnection,
    account_id: Uuid,
    portfolio_id: Uuid,
    amount_delta: Decimal,
) -> Result<Decimal, LedgerError> {
    let balance_after = sqlx::query_scalar::<_, Decimal>(
        r#"
        UPDATE portfolios
        SET
            cash_balance = cash_balance + $3,
            updated_at = now()
        WHERE id = $1
          AND account_id = $2
          AND cash_balance + $3 >= 0
        RETURNING cash_balance
        "#,
    )
    .bind(portfolio_id)
    .bind(account_id)
    .bind(amount_delta)
    .fetch_optional(&mut *connection)
    .await?;

    if let Some(balance_after) = balance_after {
        return Ok(balance_after);
    }

    let current = sqlx::query_as::<_, PortfolioCashRow>(
        r#"
        SELECT account_id, cash_balance
        FROM portfolios
        WHERE id = $1
        "#,
    )
    .bind(portfolio_id)
    .fetch_optional(&mut *connection)
    .await?
    .ok_or(LedgerError::PortfolioNotFound(portfolio_id))?;

    if current.account_id != account_id {
        return Err(LedgerError::PortfolioAccountMismatch {
            portfolio_id,
            expected_account_id: account_id,
            actual_account_id: current.account_id,
        });
    }

    if current.cash_balance.is_sign_negative() {
        return Err(LedgerError::NegativeCashBalance {
            portfolio_id,
            cash_balance: current.cash_balance,
        });
    }

    if amount_delta.is_sign_negative() {
        return Err(LedgerError::InsufficientCash {
            portfolio_id,
            available: current.cash_balance,
            required: -amount_delta,
        });
    }

    Err(LedgerError::CashUpdateRejected {
        portfolio_id,
        amount_delta,
    })
}

async fn insert_ledger_entry(
    connection: &mut PgConnection,
    entry: NewCashLedgerEntry<'_>,
) -> Result<CashLedgerEntry, LedgerError> {
    let row = sqlx::query_as::<_, CashLedgerEntryRow>(
        r#"
        INSERT INTO cash_ledger_entries (
            account_id,
            portfolio_id,
            trade_id,
            reason,
            amount_delta,
            balance_after,
            source_request_id
        ) VALUES (
            $1,
            $2,
            $3,
            $4,
            $5,
            $6,
            $7
        )
        RETURNING
            id,
            account_id,
            portfolio_id,
            trade_id,
            reason,
            amount_delta,
            balance_after,
            source_request_id,
            created_at
        "#,
    )
    .bind(entry.account_id)
    .bind(entry.portfolio_id)
    .bind(entry.trade_id)
    .bind(entry.reason.as_str())
    .bind(entry.amount_delta)
    .bind(entry.balance_after)
    .bind(entry.source_request_id)
    .fetch_one(&mut *connection)
    .await?;

    CashLedgerEntry::try_from(row)
}

fn new_cash_ledger_entry<'a>(
    account_id: Uuid,
    portfolio_id: Uuid,
    trade_id: Option<Uuid>,
    reason: LedgerReason,
    amount_delta: Decimal,
    balance_after: Decimal,
    source_request_id: Option<&'a str>,
) -> NewCashLedgerEntry<'a> {
    NewCashLedgerEntry {
        account_id,
        portfolio_id,
        trade_id,
        reason,
        amount_delta,
        balance_after,
        source_request_id,
    }
}

fn ensure_positive_amount(amount: Decimal) -> Result<Decimal, LedgerError> {
    if amount <= Decimal::ZERO {
        return Err(LedgerError::NonPositiveAmount(amount));
    }

    Ok(amount)
}

impl TryFrom<CashLedgerEntryRow> for CashLedgerEntry {
    type Error = LedgerError;

    fn try_from(row: CashLedgerEntryRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: row.id,
            account_id: row.account_id,
            portfolio_id: row.portfolio_id,
            trade_id: row.trade_id,
            reason: LedgerReason::try_from(row.reason)?,
            amount_delta: row.amount_delta,
            balance_after: row.balance_after,
            source_request_id: row.source_request_id,
            created_at: row.created_at,
        })
    }
}
