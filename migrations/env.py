"""Alembic migrations initialization."""
from alembic import context
from sqlalchemy import engine_from_config, pool
from logging.config import fileConfig
from app.db.models import Base
from app.config.settings import get_settings
import logging

# this is the Alembic Config object, which provides
# the values of the [alembic] section of the .ini file, which can be
# accessed via the `config` object parameter in various functions within
# the script files.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("sqlalchemy.track_modifications")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    # This configures the context with just a URL
    # without the need to create an Engine
    # and associate a connection with the context
    
    settings = get_settings()
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = settings.database_url

    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # this callback is used to prevent an auto-migration from being generated
    # when there are no changes to the schema
    # reference: http://alembic.sqlalchemy.org/en/latest/cookbook.html
    # ... below is the new approach ...

    settings = get_settings()
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = settings.database_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
