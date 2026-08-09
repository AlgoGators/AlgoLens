"""Application-layer exceptions."""


class ApplicationError(Exception):
    """Base application exception."""


class NotFoundError(ApplicationError):
    """Requested resource was not found."""


class ValidationError(ApplicationError):
    """Request data failed application validation."""
