"""MEXC REST client for contract/instrument metadata.

Sprint 2 only needs the *contract detail* endpoint (list of tradable USDT-M
perpetual symbols) to reconcile our maintained 52-asset stock-perpetual
universe against what's actually live on MEXC. Real-time price/volume/OI
ingestion via WebSocket is Sprint 3 (see app/market/prices.py etc.).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.exceptions import MEXCAPIError

logger = logging.getLogger(__name__)

MEXC_CONTRACT_DETAIL_URL = "https://contract.mexc.com/api/v1/contract/detail"
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class MEXCInstrument:
    """A single tradable MEXC futures instrument, as relevant to asset sync."""

    symbol: str  # e.g. "NVDA_USDT" or "NVDAUSDT" depending on API version
    display_name: Optional[str]
    state: Optional[int]  # MEXC contract state code
    is_active: bool


class MEXCClient:
    """Thin async wrapper around the MEXC contract REST API.

    Any network or API-shape failure is raised as MEXCAPIError so callers
    (the asset-sync job, the opportunity engine's degraded-mode logic, etc.)
    can apply explicit fallback behavior instead of failing silently or
    crashing the whole pipeline.
    """

    def __init__(
        self,
        base_url: str = MEXC_CONTRACT_DETAIL_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._base_url = base_url
        self._timeout = timeout
        self._client = client  # injectable for testing

    async def fetch_instruments(self) -> list[MEXCInstrument]:
        """Fetch the full list of tradable MEXC futures instruments.

        Raises:
            MEXCAPIError: on network failure, non-200 response, or an
                unexpected response shape.
        """
        try:
            if self._client is not None:
                response = await self._client.get(self._base_url, timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.get(self._base_url, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise MEXCAPIError(f"MEXC contract detail request failed: {exc}") from exc

        if response.status_code != 200:
            raise MEXCAPIError(
                f"MEXC contract detail returned status {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise MEXCAPIError("MEXC contract detail returned invalid JSON") from exc

        if not isinstance(payload, dict) or "data" not in payload:
            raise MEXCAPIError("MEXC contract detail response missing 'data' field")

        raw_instruments = payload.get("data") or []
        instruments: list[MEXCInstrument] = []
        for item in raw_instruments:
            symbol = item.get("symbol")
            if not symbol:
                continue
            state = item.get("state")
            # MEXC uses state 0 == "enabled" for contract trading.
            is_active = state == 0
            instruments.append(
                MEXCInstrument(
                    symbol=symbol,
                    display_name=item.get("displayName") or item.get("displayNameEn"),
                    state=state,
                    is_active=is_active,
                )
            )

        logger.info("Fetched %d instruments from MEXC", len(instruments))
        return instruments

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """Normalize MEXC symbol formats (e.g. 'NVDA_USDT') to our stored
        'NVDAUSDT' convention so we can match against Asset.mexc_symbol."""
        return symbol.replace("_", "").replace("-", "").upper()
