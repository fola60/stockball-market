use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use sqlx::{FromRow, PgExecutor};
use uuid::Uuid;

use super::{error::PortfolioError, model::Portfolio};

#[derive(Debug, FromRow)]
struct PortfolioRow {
    id: Uuid,
    account_id: Uuid,
    cash_balance: Decimal,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

pub async fn get_portfolio_by_id(
    executor: impl PgExecutor<'_>,
    portfolio_id: Uuid,
) -> Result<Option<Portfolio>, PortfolioError> {
    let row = sqlx::query_as::<_, PortfolioRow>(
        r#"
        SELECT
            id,
            account_id,
            cash_balance,
            created_at,
            updated_at
        FROM portfolios
        WHERE id = $1
        "#,
    )
    .bind(portfolio_id)
    .fetch_optional(executor)
    .await?;

    row.map(Portfolio::try_from).transpose()
}

pub async fn get_portfolio_for_account(
    executor: impl PgExecutor<'_>,
    account_id: Uuid,
) -> Result<Option<Portfolio>, PortfolioError> {
    let row = sqlx::query_as::<_, PortfolioRow>(
        r#"
        SELECT
            id,
            account_id,
            cash_balance,
            created_at,
            updated_at
        FROM portfolios
        WHERE account_id = $1
        "#,
    )
    .bind(account_id)
    .fetch_optional(executor)
    .await?;

    row.map(Portfolio::try_from).transpose()
}

pub fn assert_portfolio_belongs_to_account(
    portfolio: &Portfolio,
    account_id: Uuid,
) -> Result<(), PortfolioError> {
    if portfolio.account_id == account_id {
        return Ok(());
    }

    Err(PortfolioError::AccountMismatch {
        portfolio_id: portfolio.id,
        expected_account_id: account_id,
        actual_account_id: portfolio.account_id,
    })
}

pub async fn get_cash_balance(
    executor: impl PgExecutor<'_>,
    portfolio_id: Uuid,
) -> Result<Decimal, PortfolioError> {
    let cash_balance = sqlx::query_scalar::<_, Decimal>(
        r#"
        SELECT cash_balance
        FROM portfolios
        WHERE id = $1
        "#,
    )
    .bind(portfolio_id)
    .fetch_optional(executor)
    .await?
    .ok_or(PortfolioError::NotFound(portfolio_id))?;

    ensure_non_negative_cash_balance(portfolio_id, cash_balance)?;

    Ok(cash_balance)
}

pub fn assert_has_cash(
    portfolio: &Portfolio,
    required_amount: Decimal,
) -> Result<(), PortfolioError> {
    ensure_non_negative_cash_balance(portfolio.id, portfolio.cash_balance)?;

    if required_amount.is_sign_negative() {
        return Err(PortfolioError::NegativeRequiredCash {
            portfolio_id: portfolio.id,
            required: required_amount,
        });
    }

    if portfolio.cash_balance < required_amount {
        return Err(PortfolioError::InsufficientCash {
            portfolio_id: portfolio.id,
            available: portfolio.cash_balance,
            required: required_amount,
        });
    }

    Ok(())
}

fn ensure_non_negative_cash_balance(
    portfolio_id: Uuid,
    cash_balance: Decimal,
) -> Result<(), PortfolioError> {
    if cash_balance.is_sign_negative() {
        return Err(PortfolioError::NegativeCashBalance {
            portfolio_id,
            cash_balance,
        });
    }

    Ok(())
}

impl TryFrom<PortfolioRow> for Portfolio {
    type Error = PortfolioError;

    fn try_from(row: PortfolioRow) -> Result<Self, Self::Error> {
        ensure_non_negative_cash_balance(row.id, row.cash_balance)?;

        Ok(Self {
            id: row.id,
            account_id: row.account_id,
            cash_balance: row.cash_balance,
            created_at: row.created_at,
            updated_at: row.updated_at,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn portfolio_with_cash(cash_balance: Decimal) -> Portfolio {
        Portfolio {
            id: Uuid::new_v4(),
            account_id: Uuid::new_v4(),
            cash_balance,
            created_at: Utc::now(),
            updated_at: Utc::now(),
        }
    }

    #[test]
    fn assert_portfolio_belongs_to_account_accepts_matching_account() {
        let portfolio = portfolio_with_cash(Decimal::new(10_0000, 4));

        assert!(assert_portfolio_belongs_to_account(&portfolio, portfolio.account_id).is_ok());
    }

    #[test]
    fn assert_portfolio_belongs_to_account_rejects_mismatch() {
        let portfolio = portfolio_with_cash(Decimal::new(10_0000, 4));
        let expected_account_id = Uuid::new_v4();
        let error =
            assert_portfolio_belongs_to_account(&portfolio, expected_account_id).unwrap_err();

        assert!(matches!(
            error,
            PortfolioError::AccountMismatch {
                portfolio_id,
                expected_account_id: actual_expected_account_id,
                actual_account_id,
            } if portfolio_id == portfolio.id
                && actual_expected_account_id == expected_account_id
                && actual_account_id == portfolio.account_id
        ));
    }

    #[test]
    fn assert_has_cash_accepts_exact_required_amount() {
        let portfolio = portfolio_with_cash(Decimal::new(10_0000, 4));

        assert!(assert_has_cash(&portfolio, Decimal::new(10_0000, 4)).is_ok());
    }

    #[test]
    fn assert_has_cash_rejects_when_cash_is_lower_than_required_amount() {
        let portfolio = portfolio_with_cash(Decimal::new(9_9999, 4));
        let error = assert_has_cash(&portfolio, Decimal::new(10_0000, 4)).unwrap_err();

        assert!(matches!(
            error,
            PortfolioError::InsufficientCash {
                portfolio_id,
                available,
                required,
            } if portfolio_id == portfolio.id
                && available == Decimal::new(9_9999, 4)
                && required == Decimal::new(10_0000, 4)
        ));
    }

    #[test]
    fn assert_has_cash_rejects_negative_required_amount() {
        let portfolio = portfolio_with_cash(Decimal::new(10_0000, 4));
        let error = assert_has_cash(&portfolio, Decimal::new(-1, 0)).unwrap_err();

        assert!(matches!(
            error,
            PortfolioError::NegativeRequiredCash {
                portfolio_id,
                required,
            } if portfolio_id == portfolio.id && required == Decimal::new(-1, 0)
        ));
    }
}
