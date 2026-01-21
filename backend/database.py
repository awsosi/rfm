"""
Database connection and session management for the Modular File Manager.

Provides async connection pooling, session management, and utility functions
for database operations. All operations use async/await for non-blocking I/O.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, QueuePool

from models import Base


class DatabaseManager:
    """
    Manages database connections and sessions.

    Singleton pattern ensures only one engine per application instance.
    Supports connection pooling with configurable parameters.
    """

    _engine: Optional[AsyncEngine] = None
    _session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    @classmethod
    def get_database_url(cls) -> str:
        """
        Get database URL from environment variables.

        Returns:
            PostgreSQL connection URL for asyncpg driver.

        Raises:
            ValueError: If DATABASE_URL is not set.
        """
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError(
                "DATABASE_URL environment variable not set. "
                "Example: postgresql+asyncpg://user:pass@host:5432/dbname"
            )

        # Ensure we're using the async driver
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )
        elif not database_url.startswith("postgresql+asyncpg://"):
            raise ValueError(
                f"Invalid database URL: {database_url}. "
                "Must use postgresql:// or postgresql+asyncpg://"
            )

        return database_url

    @classmethod
    def initialize(
        cls,
        pool_size: int = 20,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
        echo: bool = False,
    ) -> None:
        """
        Initialize database engine and session factory.

        Args:
            pool_size: Number of connections to maintain in pool.
            max_overflow: Max connections beyond pool_size.
            pool_timeout: Seconds to wait for connection from pool.
            pool_recycle: Seconds before recycling connections.
            echo: Whether to log all SQL statements.
        """
        if cls._engine is not None:
            return

        database_url = cls.get_database_url()

        # Create async engine with connection pooling
        cls._engine = create_async_engine(
            database_url,
            echo=echo,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            pool_pre_ping=True,  # Verify connections before using
        )

        # Create session factory
        cls._session_factory = async_sessionmaker(
            cls._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    @classmethod
    async def create_tables(cls) -> None:
        """
        Create all tables defined in models.

        WARNING: Only use for testing. In production, use Alembic migrations.
        """
        if cls._engine is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        async with cls._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @classmethod
    async def drop_tables(cls) -> None:
        """
        Drop all tables.

        WARNING: Destructive operation. Only use for testing.
        """
        if cls._engine is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        async with cls._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @classmethod
    async def close(cls) -> None:
        """Close database engine and release all connections."""
        if cls._engine is not None:
            await cls._engine.dispose()
            cls._engine = None
            cls._session_factory = None

    @classmethod
    def get_session_factory(cls) -> async_sessionmaker[AsyncSession]:
        """
        Get the session factory.

        Returns:
            Session factory for creating database sessions.

        Raises:
            RuntimeError: If database not initialized.
        """
        if cls._session_factory is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return cls._session_factory

    @classmethod
    @asynccontextmanager
    async def session(cls) -> AsyncGenerator[AsyncSession, None]:
        """
        Context manager for database sessions.

        Automatically commits on success and rolls back on exception.

        Usage:
            async with DatabaseManager.session() as session:
                user = await session.get(User, 1)
                session.add(user)

        Yields:
            AsyncSession for database operations.
        """
        session_factory = cls.get_session_factory()
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# Convenience alias for getting sessions
get_db_session = DatabaseManager.session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for getting database sessions.

    Usage:
        @app.get("/users/{user_id}")
        async def get_user(
            user_id: int,
            db: AsyncSession = Depends(get_db)
        ):
            user = await db.get(User, user_id)
            return user

    Yields:
        AsyncSession for database operations.
    """
    async with DatabaseManager.session() as session:
        yield session


async def init_database(
    pool_size: int = 20,
    max_overflow: int = 10,
    echo: bool = False,
) -> None:
    """
    Initialize database connection for application startup.

    Args:
        pool_size: Number of connections in pool.
        max_overflow: Max additional connections.
        echo: Whether to log SQL statements.
    """
    DatabaseManager.initialize(
        pool_size=pool_size,
        max_overflow=max_overflow,
        echo=echo,
    )


async def close_database() -> None:
    """Close database connections for application shutdown."""
    await DatabaseManager.close()


async def health_check() -> bool:
    """
    Check database connection health.

    Returns:
        True if database is reachable, False otherwise.
    """
    try:
        async with DatabaseManager.session() as session:
            await session.execute("SELECT 1")
        return True
    except Exception:
        return False
