mod error;
mod model;
mod repository;
mod seeding;

pub use error::InstrumentError;
pub use model::{IndexFundInstrument, Instrument, InstrumentStatus, InstrumentType};
pub use repository::{
    assert_tradable, get_active_instrument_by_id, get_current_price, get_instrument_by_id,
    get_instrument_type, RecalibratedCurve,
};
pub use seeding::{
    calculate_initial_price, fallback_price_for_position, seed_player_shares,
    SeedPlayerSharesResult,
};

pub(crate) use repository::{
    has_market_activity, insert_index_fund_instrument, lock_index_fund_instruments,
    lock_instrument_by_id, lock_instruments_by_ids, recalibrate_price_curves,
    reset_pre_market_price, update_index_fund_price, update_market_state,
};
