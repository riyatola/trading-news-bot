"""Quiver Quantitative ingestion adapter package (Sprint 7).

Quiver Quantitative covers signals the rest of the source stack does not
touch: congressional stock trades, corporate insider transactions, WSB
sentiment aggregates, and Google Trends per ticker. It has a genuinely
free tier for the basic endpoints we use.

Each "signal type" maps to a different endpoint but they all normalize
into the same RawEvent shape via QuiverAdapter, preserving the signal
subtype (congress_trade / insider_trade / wsb_sentiment / google_trends)
in raw_metadata so the downstream event classifier can treat them
differently.

See: https://api.quiverquant.com/docs/
"""
