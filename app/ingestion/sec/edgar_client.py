"""SEC EDGAR full-text search client (Sprint 4).

Uses EDGAR's full-text search API to find recent 8-K/10-K filings
mentioning a tracked company, rather than polling each company's
submissions feed by CIK -- that would require a ticker->CIK mapping table
we don't maintain yet. This is a reasonable v1 tradeoff (full-text search
covers the "material event" 8-K use case we care about most); switching
to per-CIK submissions polling for completeness is a natural follow-up.

SEC requires a descriptive User-Agent on every request (see
`settings.sec_user_agent`) -- unidentified requests are rate-limited or
blocked outright.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

from app.exceptions import SECEDGARError

logger = logging.getLogger(__name__)

EDGAR_FULL_TEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_FORMS = ["8-K", "10-K"]


@dataclass(frozen=True)
class EDGARFiling:
    company_name: str
    form_type: str
    filed_at: datetime
    accession_no: str
    url: str
    snippet: str


class SECEDGARClient:
    def __init__(
        self,
        user_agent: str,
        base_url: str = EDGAR_FULL_TEXT_SEARCH_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._user_agent = user_agent
        self._base_url = base_url
        self._timeout = timeout
        self._client = client  # injectable for testing

    async def search_filings(
        self,
        company_names: list[str],
        forms: Optional[list[str]] = None,
        since: Optional[datetime] = None,
    ) -> list[EDGARFiling]:
        """Search recent filings mentioning any of `company_names`.

        One request per company (EDGAR full-text search doesn't support a
        boolean-OR company query the way NewsAPI does), so this is
        comparatively expensive -- keep the polling interval reasonable
        (see `app.workers.scheduler`) and prefer this over ad-hoc calls.

        Raises:
            SECEDGARError: on network failure, non-200 response, or an
                unexpected response shape.
        """
        forms = forms or DEFAULT_FORMS
        headers = {"User-Agent": self._user_agent}
        filings: list[EDGARFiling] = []

        for name in company_names:
            params: dict = {
                "q": f'"{name}"',
                "forms": ",".join(forms),
            }
            if since is not None:
                params["dateRange"] = "custom"
                params["startdt"] = since.strftime("%Y-%m-%d")
                params["enddt"] = datetime.utcnow().strftime("%Y-%m-%d")

            try:
                if self._client is not None:
                    response = await self._client.get(
                        self._base_url, params=params, headers=headers, timeout=self._timeout
                    )
                else:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            self._base_url, params=params, headers=headers, timeout=self._timeout
                        )
            except httpx.HTTPError as exc:
                raise SECEDGARError(f"SEC EDGAR search failed for '{name}': {exc}") from exc

            if response.status_code != 200:
                raise SECEDGARError(
                    f"SEC EDGAR search returned status {response.status_code} for '{name}'"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise SECEDGARError(f"SEC EDGAR search returned invalid JSON for '{name}'") from exc

            hits = (payload.get("hits") or {}).get("hits") or []
            for hit in hits:
                source = hit.get("_source") or {}
                filed_raw = source.get("file_date")
                accession_no = hit.get("_id") or source.get("adsh")
                if not filed_raw or not accession_no:
                    continue
                try:
                    filed_at = datetime.strptime(filed_raw, "%Y-%m-%d")
                except ValueError:
                    logger.warning("Discarding EDGAR hit with unparseable file_date: %s", filed_raw)
                    continue

                cik = str(source.get("cik") or "").lstrip("0")
                accession_clean = str(accession_no).split(":")[0].replace("-", "")
                filing_url = (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}.txt"
                    if cik else ""
                )

                root_forms = source.get("root_forms")
                form_type = root_forms[0] if isinstance(root_forms, list) and root_forms else str(
                    source.get("form", "UNKNOWN")
                )

                filings.append(
                    EDGARFiling(
                        company_name=name,
                        form_type=form_type,
                        filed_at=filed_at,
                        accession_no=str(accession_no),
                        url=filing_url,
                        snippet=", ".join(source.get("display_names") or []) or name,
                    )
                )

        logger.info("Fetched %d SEC EDGAR filings across %d companies", len(filings), len(company_names))
        return filings
