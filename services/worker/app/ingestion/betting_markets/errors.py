class Bet365IngestionError(Exception):
    """Raised when Bet365 website discovery cannot be completed or normalized."""


class Bet365SourceDisabledError(Bet365IngestionError):
    """Raised when required policy or browser settings are disabled."""
