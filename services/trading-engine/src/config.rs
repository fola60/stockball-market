use std::{env, net::SocketAddr};

use sqlx::{postgres::PgPoolOptions, PgPool};

const DATABASE_URL_ENV: &str = "STOCKBALL_TRADING_ENGINE_DATABASE_URL";
const DATABASE_URL_FALLBACK_ENV: &str = "DATABASE_URL";
const BIND_ADDR_ENV: &str = "STOCKBALL_TRADING_ENGINE_BIND_ADDR";
const DEFAULT_BIND_ADDR: &str = "127.0.0.1:3000";

#[derive(Debug, Clone)]
pub struct ServerConfig {
    pub database_url: String,
    pub bind_addr: SocketAddr,
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

        Ok(Self {
            database_url,
            bind_addr,
        })
    }

    pub async fn connect_pool(&self) -> Result<PgPool, sqlx::Error> {
        PgPoolOptions::new()
            .max_connections(10)
            .connect(&self.database_url)
            .await
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("database url is required via {DATABASE_URL_ENV} or {DATABASE_URL_FALLBACK_ENV}")]
    MissingDatabaseUrl,

    #[error("invalid bind address: {0}")]
    InvalidBindAddress(std::net::AddrParseError),
}
