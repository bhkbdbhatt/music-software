"""Alembic environment.

Asynchronous on purpose: the application uses an async engine (asyncpg), and
running migrations on a separate sync URL is how people end up migrating one
database and serving another. ``alembic upgrade head`` therefore speaks the same
DSN as the app.

The URL comes from :mod:`app.core.config`, i.e. ``SAMPLEFORGE_DATABASE_URL`` or
``.env`` — never from ``alembic.ini``, which keeps a single source of truth.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from app.core.config import settings
from app.models.db import Base
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# The models import registers every table on Base.metadata, which is what
# autogenerate compares the live schema against. Importing Base alone is not
# enough if nothing imports app.models.db.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """The DSN to migrate.

    Returns:
        The URL from application settings. Alembic's own ``sqlalchemy.url`` is
        ignored on purpose; see the module docstring.
    """
    return settings.database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a database.

    For reviewing a migration: ``alembic upgrade head --sql``.
    """
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations on an open synchronous connection.

    Alembic's API is synchronous; async support means wrapping that call in the
    engine's own ``run_sync``, which is what lets one connection (and therefore
    one transaction) cover the whole run.

    Args:
        connection: An open connection, provided by ``run_sync``.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # Migrations own their transactions; Alembic should not also try to
        # commit per-statement on databases that support transactional DDL.
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Connect with the async engine and run the migrations through it."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        # No pooling: a migration process connects once and exits. NullPool also
        # avoids handing a pooled asyncpg connection back on interpreter
        # shutdown, which warns noisily.
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for an online migration run."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
