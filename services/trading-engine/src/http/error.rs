//! Stable HTTP error boundary.
//!
//! Domain-to-protocol mappings live under `error/` so handlers only depend on
//! the small public `ApiError` surface exposed here.

mod mapping;

pub use mapping::ApiError;
