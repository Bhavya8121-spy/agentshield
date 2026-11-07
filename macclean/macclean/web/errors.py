from __future__ import annotations


class ApiError(Exception):
    """A failure the dashboard shows to the user, with the HTTP status to send."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
