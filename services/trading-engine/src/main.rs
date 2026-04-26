use stockball_trading_engine::{
    config::ServerConfig,
    http::{build_router, AppState, SqlOrderExecutor},
};
use tokio::net::TcpListener;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = ServerConfig::from_env()?;
    let pool = config.connect_pool().await?;
    let app = build_router(AppState::new(SqlOrderExecutor::new(pool)));
    let listener = TcpListener::bind(config.bind_addr).await?;

    println!("stockball-trading-engine listening on {}", config.bind_addr);

    axum::serve(listener, app).await?;

    Ok(())
}
