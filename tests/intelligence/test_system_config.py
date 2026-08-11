import pytest

from app.config.settings import get_settings
from app.config.system_config import get_config_value, set_config_value


def test_falls_back_to_settings_default_when_unset(db):
    value = get_config_value(db, "ai_daily_spend_cap_usd")
    assert value == get_settings().ai_daily_spend_cap_usd


def test_falls_back_to_in_code_default_when_unset(db):
    assert get_config_value(db, "prefilter_min_content_length") == 40


def test_set_then_get_returns_updated_value(db):
    set_config_value(db, "prefilter_min_content_length", 100)
    assert get_config_value(db, "prefilter_min_content_length") == 100


def test_unknown_key_raises(db):
    with pytest.raises(KeyError):
        get_config_value(db, "not_a_real_key")
