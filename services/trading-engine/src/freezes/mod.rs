mod error;
mod repository;

pub use error::FreezeError;
pub use repository::{assert_not_frozen, freeze_instrument, unfreeze_instrument};
