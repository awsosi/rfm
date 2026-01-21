#!/usr/bin/env python3
"""
Schema verification script for Modular File Manager database.

Checks that all tables, indexes, and default data are properly created
after running Alembic migrations.

Usage:
    python verify_schema.py

Requires:
    - DATABASE_URL environment variable set in .env
    - PostgreSQL database created
    - Alembic migrations run (alembic upgrade head)
"""

import asyncio
import sys
from typing import List, Tuple

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import DatabaseManager, get_db_session
from models import Config, User, UserRole


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def success(message: str) -> None:
    """Print success message in green."""
    print(f"{Colors.GREEN}✓{Colors.END} {message}")


def error(message: str) -> None:
    """Print error message in red."""
    print(f"{Colors.RED}✗{Colors.END} {message}")


def info(message: str) -> None:
    """Print info message in blue."""
    print(f"{Colors.BLUE}ℹ{Colors.END} {message}")


def header(message: str) -> None:
    """Print section header."""
    print(f"\n{Colors.BOLD}{message}{Colors.END}")


async def check_connection() -> bool:
    """
    Test database connection.

    Returns:
        True if connection successful, False otherwise.
    """
    try:
        DatabaseManager.initialize()
        async with get_db_session() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1
        success("Database connection successful")
        return True
    except Exception as e:
        error(f"Database connection failed: {e}")
        return False


async def check_tables() -> Tuple[bool, List[str]]:
    """
    Verify all required tables exist.

    Returns:
        Tuple of (success: bool, missing_tables: List[str])
    """
    required_tables = {
        'users',
        'sessions',
        'workers',
        'operations',
        'operation_workers',
        'audit_logs',
        'config',
    }

    try:
        async with DatabaseManager._engine.begin() as conn:
            inspector = inspect(conn.sync_connection)
            existing_tables = set(await asyncio.to_thread(inspector.get_table_names))

        missing = required_tables - existing_tables

        if missing:
            error(f"Missing tables: {', '.join(missing)}")
            return False, list(missing)
        else:
            success(f"All {len(required_tables)} required tables exist")
            return True, []

    except Exception as e:
        error(f"Failed to check tables: {e}")
        return False, []


async def check_admin_user() -> bool:
    """
    Verify default admin user exists.

    Returns:
        True if admin user exists with correct properties.
    """
    try:
        async with get_db_session() as session:
            admin = await session.get(User, 1)

            if not admin:
                error("Default admin user (id=1) not found")
                return False

            if admin.username != "admin":
                error(f"Admin username is '{admin.username}', expected 'admin'")
                return False

            if admin.role != UserRole.ADMIN:
                error(f"Admin role is '{admin.role}', expected 'admin'")
                return False

            if not admin.is_active:
                error("Admin user is not active")
                return False

            success(f"Default admin user exists (username: {admin.username}, role: {admin.role.value})")
            info(f"  ⚠️  Default password is 'admin123' - CHANGE IMMEDIATELY!")
            return True

    except Exception as e:
        error(f"Failed to check admin user: {e}")
        return False


async def check_config_entries() -> Tuple[bool, int]:
    """
    Verify default configuration entries.

    Returns:
        Tuple of (success: bool, config_count: int)
    """
    required_configs = {
        'max_concurrent_users',
        'session_lifetime_days',
        'global_path_a_prefix',
        'global_path_b_prefix',
        'enable_sybase_auth',
        'sybase_auth_url',
        'sybase_auth_timeout',
        'enable_syslog',
        'syslog_host',
        'syslog_port',
        'enable_remote_audit_api',
        'remote_audit_api_url',
        'log_retention_days',
        'worker_heartbeat_interval',
        'worker_heartbeat_timeout',
        'operation_timeout',
        'enable_auto_rollback',
        'max_file_listing_items',
    }

    try:
        async with get_db_session() as session:
            result = await session.execute(select(Config))
            configs = result.scalars().all()

            config_keys = {c.key for c in configs}
            missing = required_configs - config_keys

            if missing:
                error(f"Missing config entries: {', '.join(missing)}")
                return False, len(configs)
            else:
                success(f"All {len(required_configs)} default config entries exist")
                return True, len(configs)

    except Exception as e:
        error(f"Failed to check config entries: {e}")
        return False, 0


async def check_indexes() -> Tuple[bool, int]:
    """
    Verify critical indexes exist.

    Returns:
        Tuple of (success: bool, index_count: int)
    """
    critical_indexes = {
        'ix_users_username',
        'ix_sessions_token',
        'ix_sessions_expires_at',
        'ix_workers_name',
        'ix_workers_status',
        'ix_operations_user_id',
        'ix_operations_status',
        'ix_audit_logs_user_id',
        'ix_audit_logs_timestamp',
    }

    try:
        async with DatabaseManager._engine.begin() as conn:
            inspector = inspect(conn.sync_connection)
            all_indexes = set()

            # Get indexes from all tables
            for table in ['users', 'sessions', 'workers', 'operations', 'audit_logs']:
                table_indexes = await asyncio.to_thread(
                    inspector.get_indexes,
                    table
                )
                all_indexes.update(idx['name'] for idx in table_indexes)

            missing = critical_indexes - all_indexes

            if missing:
                error(f"Missing indexes: {', '.join(missing)}")
                return False, len(all_indexes)
            else:
                success(f"All {len(critical_indexes)} critical indexes exist")
                return True, len(all_indexes)

    except Exception as e:
        error(f"Failed to check indexes: {e}")
        return False, 0


async def check_enum_types() -> bool:
    """
    Verify PostgreSQL ENUM types are created.

    Returns:
        True if all ENUM types exist.
    """
    required_enums = {
        'userrole',
        'workerstatus',
        'operationtype',
        'operationstatus',
        'configtype',
    }

    try:
        async with get_db_session() as session:
            result = await session.execute(text("""
                SELECT typname FROM pg_type
                WHERE typtype = 'e'
            """))
            existing_enums = {row[0] for row in result.fetchall()}

            missing = required_enums - existing_enums

            if missing:
                error(f"Missing ENUM types: {', '.join(missing)}")
                return False
            else:
                success(f"All {len(required_enums)} ENUM types exist")
                return True

    except Exception as e:
        error(f"Failed to check ENUM types: {e}")
        return False


async def check_triggers() -> bool:
    """
    Verify database triggers are created.

    Returns:
        True if all triggers exist.
    """
    required_triggers = {
        'update_users_updated_at',
        'update_workers_updated_at',
        'update_config_updated_at',
    }

    try:
        async with get_db_session() as session:
            result = await session.execute(text("""
                SELECT tgname FROM pg_trigger
                WHERE tgname LIKE 'update_%_updated_at'
            """))
            existing_triggers = {row[0] for row in result.fetchall()}

            missing = required_triggers - existing_triggers

            if missing:
                error(f"Missing triggers: {', '.join(missing)}")
                return False
            else:
                success(f"All {len(required_triggers)} triggers exist")
                return True

    except Exception as e:
        error(f"Failed to check triggers: {e}")
        return False


async def run_verification() -> bool:
    """
    Run all verification checks.

    Returns:
        True if all checks pass, False otherwise.
    """
    header("🔍 Verifying Database Schema for Modular File Manager")

    all_passed = True

    # Check 1: Connection
    header("1. Database Connection")
    if not await check_connection():
        all_passed = False
        error("Cannot continue without database connection")
        return False

    # Check 2: Tables
    header("2. Tables")
    tables_ok, missing_tables = await check_tables()
    if not tables_ok:
        all_passed = False
        info("Run: alembic upgrade head")

    # Check 3: ENUM Types
    header("3. ENUM Types")
    if not await check_enum_types():
        all_passed = False

    # Check 4: Indexes
    header("4. Indexes")
    indexes_ok, index_count = await check_indexes()
    if not indexes_ok:
        all_passed = False

    # Check 5: Triggers
    header("5. Database Triggers")
    if not await check_triggers():
        all_passed = False

    # Check 6: Default Admin User
    header("6. Default Admin User")
    if not await check_admin_user():
        all_passed = False

    # Check 7: Configuration Entries
    header("7. Configuration Entries")
    config_ok, config_count = await check_config_entries()
    if not config_ok:
        all_passed = False

    # Summary
    header("📊 Verification Summary")
    if all_passed:
        success("All verification checks passed! ✅")
        print(f"\n{Colors.GREEN}Database schema is ready for use.{Colors.END}")
        print(f"\n{Colors.YELLOW}⚠️  IMPORTANT:{Colors.END}")
        print(f"  - Default admin credentials: admin / admin123")
        print(f"  - Change password immediately after first login")
        print(f"  - Configure .env with production settings")
        return True
    else:
        error("Some verification checks failed ❌")
        print(f"\n{Colors.RED}Database schema is incomplete.{Colors.END}")
        print(f"\n{Colors.YELLOW}Troubleshooting:{Colors.END}")
        print(f"  1. Ensure DATABASE_URL is set in .env")
        print(f"  2. Run: alembic upgrade head")
        print(f"  3. Check PostgreSQL logs for errors")
        return False


async def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        success = await run_verification()
        return 0 if success else 1
    except Exception as e:
        error(f"Verification failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        await DatabaseManager.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
