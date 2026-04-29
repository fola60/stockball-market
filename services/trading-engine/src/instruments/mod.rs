mod error;
mod model;
mod repository;
mod seeding;

pub use error::InstrumentError;
pub use model::{Instrument, InstrumentStatus, InstrumentType};
pub use repository::{
    assert_tradable, get_active_instrument_by_id, get_current_price, get_instrument_by_id,
    get_price_impact_unit,
};
pub use seeding::{
    calculate_initial_price, calculate_price_impact_unit, fallback_price_for_position,
    seed_player_shares, SeedPlayerSharesResult,
};

pub(crate) use repository::{lock_instrument_by_id, update_current_price};
