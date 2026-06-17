"""Plan verification and pipeline exceptions."""


class PlanRejectedError(Exception):
    """Raised when a lesson plan fails verification and must not be streamed."""

    def __init__(self, message: str, *, rejections: list[str] | None = None, attempts: int = 0):
        super().__init__(message)
        self.rejections = rejections or []
        self.attempts = attempts
