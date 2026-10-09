class ModelValidationError(ValueError):
    """Raised when a model contains missing or invalid data."""


class DocumentNotFoundError(LookupError):
    """Raised when an operation requires a Firestore document that is missing."""
