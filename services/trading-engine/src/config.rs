use std::{env, net::SocketAddr, str::FromStr};

use rust_decimal::Decimal;
use sqlx::{postgres::PgPoolOptions, PgPool};

use crate::price_impact::CurveCalibration;

const DATABASE_URL_ENV: &str = "STOCKBALL_TRADING_ENGINE_DATABASE_URL";
const DATABASE_URL_FALLBACK_ENV: &str = "DATABASE_URL";
const BIND_ADDR_ENV: &str = "STOCKBALL_TRADING_ENGINE_BIND_ADDR";
const DEFAULT_BIND_ADDR: &str = "127.0.0.1:3000";
const SEED_MULTIPLIER_ENV: &str = "STOCKBALL_DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER";
const SEED_DEPTH_DIVISOR_ENV: &str = "STOCKBALL_DEFAULT_CURVE_DEPTH_DIVISOR";

#[derive(Debug, Clone)]
pub struct ServerConfig {
    pub database_url: String,
    pub bind_addr: SocketAddr,
    /// The curve newly seeded players start on. Existing curves change only through a
    /// recalibration, which rebases them without moving prices.
    pub seed_curve: CurveCalibration,
}

impl ServerConfig {
    pub fn from_env() -> Result<Self, ConfigError> {
        let database_url = env::var(DATABASE_URL_ENV)
            .or_else(|_| env::var(DATABASE_URL_FALLBACK_ENV))
            .map_err(|_| ConfigError::MissingDatabaseUrl)?;

        let bind_addr = env::var(BIND_ADDR_ENV)
            .unwrap_or_else(|_| DEFAULT_BIND_ADDR.to_owned())
            .parse()
            .map_err(ConfigError::InvalidBindAddress)?;

        let seed_curve = CurveCalibration {
            full_supply_price_multiplier: decimal_env(
                SEED_MULTIPLIER_ENV,
                CurveCalibration::DEFAULT.full_supply_price_multiplier,
            )?,
            curve_depth_divisor: decimal_env(
                SEED_DEPTH_DIVISOR_ENV,
                CurveCalibration::DEFAULT.curve_depth_divisor,
            )?,
        };
        seed_curve
            .validate()
            .map_err(ConfigError::InvalidSeedCurve)?;

        Ok(Self {
            database_url,
            bind_addr,
            seed_curve,
        })
    }

    pub async fn connect_pool(&self) -> Result<PgPool, sqlx::Error> {
        PgPoolOptions::new()
            .max_connections(10)
            .connect(&self.database_url)
            .await
    }
}

fn decimal_env(name: &'static str, default: Decimal) -> Result<Decimal, ConfigError> {
    match env::var(name) {
        Ok(value) if !value.trim().is_empty() => {
            Decimal::from_str(value.trim()).map_err(|_| ConfigError::InvalidDecimal { name, value })
        }
        _ => Ok(default),
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("database url is required via {DATABASE_URL_ENV} or {DATABASE_URL_FALLBACK_ENV}")]
    MissingDatabaseUrl,

    #[error("invalid bind address: {0}")]
    InvalidBindAddress(std::net::AddrParseError),

    #[error("{name} must be a decimal number: {value}")]
    InvalidDecimal { name: &'static str, value: String },

    #[error("invalid seed price curve: {0}")]
    InvalidSeedCurve(String),
}
