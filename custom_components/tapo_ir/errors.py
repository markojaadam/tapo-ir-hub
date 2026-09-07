"""Integration-specific API errors."""


class TapoIrError(Exception):
    """Base error for the Tapo IR API."""


class TapoIrAuthError(TapoIrError):
    """Raised when the hub rejects supplied credentials."""


class TapoIrConnectionError(TapoIrError):
    """Raised when the hub cannot be reached or a request fails."""
