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


class SECEDGARError(ExternalServiceError):
    """Raised when SEC EDGAR full-text search requests fail."""
    pass


class RSSFeedError(ExternalServiceError):
    """Raised when a company IR RSS feed can't be fetched or parsed."""
    pass


class OpenAIError(ExternalServiceError):
    """Raised when OpenAI API calls fail."""
    pass


class XAPIError(ExternalServiceError):
    """Raised when X (Twitter) API calls fail (Sprint 7 -- deprecated; use StockTwits/Reddit/Quiver)."""
    pass


class StockTwitsAPIError(ExternalServiceError):
    """Raised when StockTwits API calls fail (Sprint 7: social sentiment, ticker-scoped streams)."""
    pass


class RedditAPIError(ExternalServiceError):
    """Raised when Reddit API calls fail (Sprint 7: retail sentiment, subreddit streams)."""
    pass


class QuiverQuantAPIError(ExternalServiceError):
    """Raised when Quiver Quantitative API calls fail (Sprint 7: congressional trades, insider, WSB, Google Trends)."""
    pass


class ApeWisdomAPIError(ExternalServiceError):
    """Raised when ApeWisdom API calls fail (Sprint 7: r/wallstreetbets + 4chan mention aggregator, no API key required)."""
    pass


class EventProcessingError(Exception):
    """Raised when event processing fails."""
    pass


class DeduplicationError(Exception):
    """Raised when deduplication fails."""
    pass
