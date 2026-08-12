"""Reddit ingestion adapter package (Sprint 7).

Covers retail sentiment via r/wallstreetbets, r/stocks, r/investing and
similar. Reddit's free OAuth tier is generous for read-only polling
(~60 req/min), and the 3 subreddits above produce the highest retail
signal/noise ratio for the kind of retail-driven moves the alert system
cares about.

Less structured than StockTwits (no built-in ticker tagging) so tickers
must be extracted from post title + selftext -- see RedditAdapter for
the $TICKER regex used.

See: https://www.reddit.com/prefs/apps  (register a "script" app)
"""
