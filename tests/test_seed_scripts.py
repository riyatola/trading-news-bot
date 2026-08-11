"""Tests for scripts/seed_assets.py and scripts/seed_relationships.py."""
import sys
from pathlib import Path

# Make the project root's scripts/ package importable in the test environment.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.seed_assets import SEED_ASSETS, seed_assets  # noqa: E402
from scripts.seed_relationships import SEED_RELATIONSHIPS, seed_relationships  # noqa: E402
from app.db.models import Asset, AssetRelationship  # noqa: E402


def test_seed_data_has_52_unique_assets():
    assert len(SEED_ASSETS) == 52
    tickers = [t[0] for t in SEED_ASSETS]
    assert len(tickers) == len(set(tickers)), "Duplicate tickers in seed data"


def test_seed_assets_creates_all_rows(db_session):
    created, updated = seed_assets(db=db_session)
    assert created == 52
    assert updated == 0
    assert db_session.query(Asset).count() == 52


def test_seed_assets_is_idempotent(db_session):
    seed_assets(db=db_session)
    created, updated = seed_assets(db=db_session)
    assert created == 0
    assert updated == 52
    assert db_session.query(Asset).count() == 52


def test_seed_relationships_reference_valid_tickers(db_session):
    seed_assets(db=db_session)
    valid_tickers = {t[0] for t in SEED_ASSETS}
    for source, target, *_ in SEED_RELATIONSHIPS:
        assert source in valid_tickers, f"Unknown source ticker in relationships seed: {source}"
        assert target in valid_tickers, f"Unknown target ticker in relationships seed: {target}"


def test_seed_relationships_creates_rows(db_session):
    seed_assets(db=db_session)
    created, updated, skipped = seed_relationships(db=db_session)
    assert created > 0
    assert skipped == 0
    assert db_session.query(AssetRelationship).count() == created
