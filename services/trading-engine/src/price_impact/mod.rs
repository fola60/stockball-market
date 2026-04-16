mod calculator;
mod error;
mod model;

pub use calculator::calculate_next_price;
pub use error::PriceImpactError;
pub use model::PriceImpactDirection;
