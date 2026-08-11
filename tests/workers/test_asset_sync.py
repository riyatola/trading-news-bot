"""Tests for app.workers.asset_sync.sync_assets."""
import pytest

from app.db.models import Asset
from app.exceptions import MEXCAPIError
from app.market.mexc import MEXCInstrument
from app.workers.asset_sync import sync_assets


class FakeMEXCClient:
    """Test double standing in for MEXCClient."""

    def __init__(self, instruments=None, raise_error=False):
        self._instruments = instruments or []
        self._raise_error = raise_error

    async def fetch_instruments(self):
        if self._raise_error:
            raise MEXCAPIError("simulated MEXC outage")
        return self._instruments

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return symbol.replace("_", "").replace("-", "").upper()


@pytest.fixture
def seeded_assets(db_session):
    assets = [
        Asset(
            id="AST-01", ticker="NVDA", company_name="NVIDIA Corporation",
            mexc_symbol="NVDAUSDT", exchange_ticker="NASDAQ:NVDA",
            sector="Technology", industry="Semiconductors", country="US",
            currency="USD", active=True,
        ),
        Asset(
            id="AST-02", ticker="AMD", company_name="Advanced Micro Devices, Inc.",
            mexc_symbol="AMDUSDT", exchange_ticker="NASDAQ:AMD",
            sector="Technology", industry="Semiconductors", country="US",
            currency="USD", active=False,  # currently inactive
        ),
    ]
    for a in assets:
        db_session.add(a)
    db_session.commit()
    return assets


@pytest.mark.asyncio
async def test_sync_deactivates_asset_no_longer_live(db_session, seeded_assets, monkeypatch):
    # Patch MEXCClient used inside asset_sync so it's not actually constructed.
    import app.workers.asset_sync as asset_sync_module
    monkeypatch.setattr(asset_sync_module, "MEXCClient", FakeMEXCClient)

    fake_client = FakeMEXCClient(instruments=[
        MEXCInstrument(symbol="AMD_USDT", display_name="AMD", state=0, is_active=True),
        # NVDA missing from live feed -> should be deactivated
    ])

    result = await sync_assets(db_session, client=fake_client)

    assert result.ok is True
    assert "NVDA" in result.deactivated
    assert "AMD" in result.reactivated

    nvda = db_session.query(Asset).filter_by(ticker="NVDA").first()
    amd = db_session.query(Asset).filter_by(ticker="AMD").first()
    assert nvda.active is False
    assert amd.active is True


@pytest.mark.asyncio
async def test_sync_leaves_db_unchanged_on_mexc_failure(db_session, seeded_assets):
    fake_client = FakeMEXCClient(raise_error=True)

    result = await sync_assets(db_session, client=fake_client)

    assert result.ok is False
    assert result.error is not None

    nvda = db_session.query(Asset).filter_by(ticker="NVDA").first()
    amd = db_session.query(Asset).filter_by(ticker="AMD").first()
    # Unchanged from seeded state
    assert nvda.active is True
    assert amd.active is False


@pytest.mark.asyncio
async def test_sync_flags_unmatched_live_symbols(db_session, seeded_assets):
    fake_client = FakeMEXCClient(instruments=[
        MEXCInstrument(symbol="NVDA_USDT", display_name="NVDA", state=0, is_active=True),
        MEXCInstrument(symbol="AMD_USDT", display_name="AMD", state=0, is_active=True),
        MEXCInstrument(symbol="NEWCO_USDT", display_name="NEWCO", state=0, is_active=True),
    ])

    result = await sync_assets(db_session, client=fake_client)

    assert "NEWCOUSDT" in result.unmatched_live_symbols
