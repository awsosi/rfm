"""
Alembic environment configuration for async migrations.

This module configures Alembic to work with SQLAlchemy's async engine
and automatically loads DATABASE_URL from environment variables.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config, create_async_engine

# Load environment variables from .env file if present
from dotenv import load_dotenv
load_dotenv()

# Import models to register them with Base.metadata
from models import Base

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate support
target_metadata = Base.metadata

# Override sqlalchemy.url from environment variable
database_url = os.getenv("DATABASE_URL")
if database_url:
    # Ensure async driver
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    Calls to context.execute() emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    Run migrations with an active database connection.

    Args:
        connection: SQLAlchemy connection to use for migrations.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def create_default_admin() -> None:
    """Create default admin user from .env if it doesn't exist"""
    try:
        from argon2 import PasswordHasher
        
        username = os.getenv("INITIAL_ADMIN_USERNAME", "admin")
        password = os.getenv("INITIAL_ADMIN_PASSWORD", "admin123")
        
        ph = PasswordHasher()
        password_hash = ph.hash(password)
        
        # Użyj DATABASE_URL, zamiast config
        db_url = os.getenv("DATABASE_URL")
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        
        # Utwórz nowy async engine
        engine = create_async_engine(db_url)
        
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO users (username, password_hash, role, is_active)
                VALUES (:username, :password_hash, 'ADMIN', true)
                ON CONFLICT (username) DO NOTHING;
            """), {"username": username, "password_hash": password_hash})
        
        await engine.dispose()
        print(f"✓ Default admin user '{username}' created/verified")
        
    except Exception as e:
        print(f"✗ Admin creation failed: {e}")


async def run_async_migrations() -> None:
    """
    Run migrations in 'online' mode with async engine.

    Creates an async engine and runs migrations within an async context.
    """
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = config.get_main_option("sqlalchemy.url")

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()
    
    # Po migracji, stwórz domyślnego admina
    await create_default_admin()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    Uses asyncio to run async migrations.
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
