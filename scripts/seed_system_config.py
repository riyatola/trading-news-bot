"""Seed `system_config` with Sprint 5's AI-cost-control defaults, making
them editable in the DB instead of only living as `Settings`/in-code
fallbacks (see app.config.system_config.DEFAULTS).

Idempotent: re-running does not overwrite a value an operator has already
tuned -- only rows that don't exist yet are created.

Usage:
    python -m scripts.seed_system_config
"""
from __future__ import annotations

import logging

from app.config.settings import get_settings
from app.config.system_config import DEFAULTS
from app.db.database import SessionLocal, engine
from app.db.models import Base, SystemConfig

logger = logging.getLogger(__name__)


def seed_system_config(db=None) -> int:
    """Insert any missing system_config rows from DEFAULTS. Returns the
    count created (existing rows are left untouched)."""
    owns_session = db is None
    db = db or SessionLocal()
    settings = get_settings()
    created = 0
    try:
        for key, (default, category, description) in DEFAULTS.items():
            existing = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            if existing:
                continue

            value = default
            if value is None:
                if key == "ai_daily_spend_cap_usd":
                    value = settings.ai_daily_spend_cap_usd
                elif key == "event_processing_batch_size":
                    value = settings.event_processing_batch_size

            db.add(SystemConfig(key=key, value=value, category=category, description=description))
            created += 1

        db.commit()
    finally:
        if owns_session:
            db.close()

    return created


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    Base.metadata.create_all(bind=engine)
    created = seed_system_config()
    logger.info("System config seed complete: %d created", created)
