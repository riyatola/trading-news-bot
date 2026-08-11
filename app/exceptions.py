"""Application exceptions."""


class EnvironmentNotConfigured(Exception):
    """Raised when required environment variables are not configured."""
    pass


class ExternalServiceError(Exception):
    """Base class for external service errors."""
    pass


class DatabaseError(Exception):
    """Raised when database operations fail."""
    pass


class RedisError(Exception):
    """Raised when Redis operations fail."""
    pass


class MEXCAPIError(ExternalServiceError):
    """Raised when MEXC API calls fail."""
    pass


class NewsAPIError(ExternalServiceError):
    """Raised when news API calls fail."""
    pass


class TelegramError(ExternalServiceError):
    """Raised when Telegram operations fail."""
    pass


class OpenAIError(ExternalServiceError):
    """Raised when OpenAI API calls fail."""
    pass


class EventProcessingError(Exception):
    """Raised when event processing fails."""
    pass


class DeduplicationError(Exception):
    """Raised when deduplication fails."""
    pass
